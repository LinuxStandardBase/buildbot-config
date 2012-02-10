# -*- python -*-
# ex: set syntax=python:

# We define our own build classes, for working with the quirky LSB build
# system.  The idea is that we set (or don't) certain environment variables
# depending on whether the branch or revision has been overriden, to add
# the date-based versions when they haven't.  Also, for those projects
# built out of packaging, handle them too.

import os
import re

from twisted.python import log
from twisted.application import internet
from twisted.internet import reactor

from buildbot.process.properties import Properties
from buildbot.steps.shell import ShellCommand
from buildbot.steps.master import MasterShellCommand
from buildbot.schedulers.base import BaseScheduler
from buildbot.schedulers.triggerable import Triggerable
from buildbot.sourcestamp import SourceStamp

# Helper function.  This takes a branch as passed into buildbot, and
# pulls out just the LSB version part.  If it can't figure out the
# LSB version, it creates a normalized branch name based off the
# branch path.

def extract_branch_name(branch):
    if branch is None:
        branch_name = "devel"
    elif branch[:4] == "lsb/":
        branch_name = branch[4:]
        branch_name = branch_name[:branch_name.index("/")]
    else:
        branch_name = branch.replace("/", "-")

    return branch_name

# Special Triggerable scheduler which can ignore the trigger's SourceStamp
# entirely.  This allows a build to trigger another build that doesn't use
# the same version control repository.

class IndepTriggerable(Triggerable):
    def __init__(self, name, builderNames, defaultProject,
                 properties={}, useSourceStamp=False, alwaysDevel=False):
        Triggerable.__init__(self, name, builderNames, properties)
        self.defaultProject = defaultProject
        self.useSourceStamp = useSourceStamp
        self.alwaysDevel = alwaysDevel

    def trigger(self, ss, set_props=None):
        if not self.useSourceStamp:
            # This comes from Triggerable.  We need the current set
            # of properties, including those set by the trigger.  It
            # gets repeated inside Triggerable, but oh well; there's
            # no way to pass these calculated properties into the base.
            props = Properties()
            props.updateFromProperties(self.properties)
            if set_props: props.updateFromProperties(set_props)

            # Now, override whatever SourceStamp was provided with
            # one determined by the branch_name property (however
            # we got it).
            if self.alwaysDevel:
                branch_name = "devel"
            else:
                branch_name = props.getProperty("branch_name", default="devel")
            branch = "lsb/%s/%s" % (branch_name, self.defaultProject)
            ss = SourceStamp(branch, None, None, None)

        return Triggerable.trigger(self, ss, set_props)

# Job file parser for MultiScheduler.  It turns a job file into a number
# of BuildRequest objects.

class JobParseError(Exception):
    pass

class MultiJobFile:
    def __init__(self, path, repos, archs, indep_prj, indep_arch, prop):
        self.tag = None
        self.projects = []
        self.branch_name = None
        self.build_type = "normal"
        self.properties = prop
        self.path = path
        self.repos = repos
        self.archs = archs
        self.indep_prj = indep_prj
        self.indep_arch = indep_arch

        try:
            self.f = open(self.path)
        except:
            raise JobParseError("could not open job file " + self.path)

        try:
            self.parse()
        finally:
            self.f.close()

        self.properties.setProperty("build_type", self.build_type, "Scheduler")
        if self.build_type == "beta":
            self.properties.setProperty("result_tag", "-beta", "Scheduler")

        if not self.branch_name or not self.projects:
            raise JobParseError("missing information in job file")
        if self.build_type not in ("normal", "production", "devel", "beta"):
            raise JobParseError("invalid build type: " + self.build_type)

    def __iter__(self):
        if self.tag:
            revision = "tag:" + self.tag
        else:
            revision = "-1"

        for prj in self.projects:
            if prj in self.repos and self.repos[prj]:
                repo = self.repos[prj]
            else:
                repo = prj

            if prj in self.indep_prj:
                archs = [self.indep_arch]
            else:
                archs = self.archs

            for arch in archs:
                builderNames = ["%s-%s" % (prj, arch)]
                branch = "lsb/%s/%s" % (self.branch_name, repo)
                ss = SourceStamp(branch, revision, None, None)
                yield (ss, builderNames, self.properties,
                       "MultiScheduler job")

    def parse(self):
        for line in self.f:
            (name, value) = [x.strip() for x in line.strip().split("=")]
            if name == "branch_name":
                self.branch_name = value
            elif name == "tag":
                self.tag = value
            elif name == "projects":
                for prj in value.split(","):
                    self.projects.append(prj.strip())
            elif name == "build_type":
                self.build_type = value
            elif name == "architectures":
                new_archs = []
                for arch in value.split(","):
                    if arch in self.archs:
                        new_archs.append(arch)
                self.archs = new_archs
            else:
                raise JobParseError("invalid key: " + name)

# Scheduler which can start a number of builds at once.  These are
# grouped by project; they are started across all supported architectures.

class MultiScheduler(BaseScheduler):
    compare_attrs = ('name', 'builderNames', 'jobdir', 'repos', 'archs', 
                     'indep_prj', 'properties')

    def __init__(self, name, builderNames, jobdir, repos, archs, indep_prj, 
                 indep_arch, prop_dict={}):
        BaseScheduler.__init__(self, name, builderNames, prop_dict)
        self.builderNames = builderNames
        self.jobdir = jobdir
        self.repos = repos
        self.archs = archs
        self.indep_prj = indep_prj
        self.indep_arch = indep_arch
        self.poller = None

    def listBuilderNames(self):
        return self.builderNames

    def getPendingBuildTimes(self):
        return []

    def startService(self):
        BaseScheduler.startService(self)
        self.poller = reactor.callLater(10, self.poll)

    def stopService(self):
        BaseScheduler.stopService(self)
        self.poller.cancel()
        self.poller = None

    def poll(self):
        for f in os.listdir(self.jobdir):
            f_full = os.path.join(self.jobdir, f)
            try:
                try:
                    jobfile = MultiJobFile(f_full, self.repos, self.archs,
                                           self.indep_prj, self.indep_arch, 
                                           self.properties)
                    for (ss, builderNames, properties, reason) in jobfile:
                        d = ss.getSourceStampId(self.master)
                        d.addCallback(self.buildset_cb,
                                      builderNames=builderNames,
                                      properties=properties,
                                      reason=reason)
                finally:
                    os.unlink(f_full)
            except JobParseError, e:
                log.msg("bad job file %s: %s" % (f, str(e)))
                continue

        self.poller = reactor.callLater(10, self.poll)

    def buildset_cb(ssid, builderNames, properties, reason):
        self.addBuildsetForSourceStamp(self, ssid, reason=reason,
                                       builderNames=builderNames,
                                       properties=properties)

class PropMasterShellCommand(MasterShellCommand):
    def start(self):
        prop = self.build.getProperties()
        self.command = prop.render(self.command)
        MasterShellCommand.start(self)

class LSBBuildCommand(ShellCommand):
    def __init__(self, makeargs=False, **kwargs):
        self.do_make_args = makeargs
        ShellCommand.__init__(self, **kwargs)
        self.addFactoryArguments(makeargs=makeargs)

    def _get_make_args(self):
        "Get any special make arguments needed."

        args = []

        branch_name = self.getProperty("branch_name")
        found_lsb_version = re.match(r'^\d+\.\d+$', branch_name)
        if found_lsb_version:
            args.append("LSBCC_LSBVERSION=%s" % branch_name)
            args.append("PKG_CONFIG_DIR=/opt/lsb/lib-%s/pkgconfig" 
                        % branch_name)
        else:
            args.append("PKG_CONFIG_DIR=/opt/lsb/lib/pkgconfig")

        if self.getProperty("build_type") in ("beta", "production") \
                or found_lsb_version:
            if isinstance(self.build.source.revision, str) and \
               self.build.source.revision[:4] == "tag:":
                args.append("OFFICIAL_RELEASE=%s" % self.build.source.revision)
            else:
                args.append("OFFICIAL_RELEASE=-1")

        if self.getProperty("build_type") == "beta":
            args.append("SKIP_DEVEL_VERSIONS=no")

        return args

    def _calc_build_type(self):
        "Figure out whether we're being called for a beta build."

        if "beta:" in self.build.reason:
            return "beta"
        elif "production:" in self.build.reason:
            return "production"
        elif "devel:" in self.build.reason:
            return "devel"
        else:
            return "normal"

    def _set_build_props(self):
        "Set build-time properties."

        current_branch = self.getProperty("branch")
        calc_branch_name = extract_branch_name(current_branch)

        set_branch_name = self.getProperty("branch_name", None)
        if set_branch_name is None:
            self.setProperty("branch_name", calc_branch_name)

        try:
            self.getProperty("build_type")
        except KeyError:
            self.setProperty("build_type", self._calc_build_type())

        # Under certain circumstances, branch_name and branch can conflict.
        # Detect these situations and override the branch as needed.

        if set_branch_name and calc_branch_name != set_branch_name:
            new_branch = current_branch.replace(calc_branch_name,
                                                set_branch_name)
            self.setProperty("branch", new_branch)

    def start(self):
        self._set_build_props()

        if self.do_make_args:
            self.setCommand(self.command + " " + " ".join(self._get_make_args()))

        ShellCommand.start(self)

class LSBBuildPackage(LSBBuildCommand):
    def __init__(self, makeargs=False, **kwargs):
        if "command" not in kwargs:
            kwargs["command"] = "cd package && make BUILD_NO_DEB=1 BZRTREES=$(dirname $PWD)/.."
            makeargs = True
        LSBBuildCommand.__init__(self, makeargs=makeargs, **kwargs)

# Automate some of the packaging build.  When using this, be sure to check
# out a copy of "packaging" (via ShellCommand, as buildbot's source stuff
# can't currently handle multi-repo builds), that your source checkout
# uses a named build dir that's the same as the project, and that BZRTREES
# is set to "..".

class LSBBuildFromPackaging(LSBBuildCommand):
    def __init__(self, makeargs=False, **kwargs):
        if "subdir" in kwargs:
            kwargs["command"] = "cd ../packaging/%s && make rpm_package" % kwargs["subdir"]
            del kwargs["subdir"]
            makeargs = True
        LSBBuildCommand.__init__(self, makeargs=makeargs, **kwargs)

# Building stuff from appbat is "special".  We need makeargs processing,
# but the make command changes for different steps.  So, force the command
# to be a shell command, and default to always adding the make args.

class LSBBuildAppbat(LSBBuildCommand):
    def __init__(self, makeargs=True, **kwargs):
        if "command" not in kwargs:
            raise KeyError, "command argument required for appbat builds"
        if kwargs["command"] is list:
            kwargs["command"] = " ".join(kwargs["command"])
        LSBBuildCommand.__init__(self, makeargs=makeargs, **kwargs)

# The appbat build is so special, we need a configure script runner for it.
# This class sets the environment-like make args (FOO=bar) in the
# slave's environment, because we can't rely on make to do that.

class LSBConfigureAppbat(LSBBuildCommand):
    def __init__(self, **kwargs):
        kwargs["makeargs"] = False
        LSBBuildCommand.__init__(self, **kwargs)

    def start(self):
        self._set_build_props()

        for env_item in self._get_make_args():
            if "=" in env_item:
                (name, value) = env_item.split("=")
                self.build.slaveEnvironment[name] = value

        LSBBuildCommand.start(self)

# Reload the SDK.  This class figures out what SDK we need (devel, stable,
# or beta) and installs it.

class LSBReloadSDK(LSBBuildCommand):
    command = ["placeholder"]

    def _is_devel(self):
        "Figure out whether we're being called on a devel tree."

        build_type = self.getProperty("build_type")
        return build_type == "devel" or \
            (build_type == "normal" and 
             self.getProperty("branch_name") == "devel")

    def _is_beta(self):
        "Figure out whether we're being called for a beta build."

        return self.getProperty("build_type") == "beta"

    def start(self):
        self._set_build_props()

        m = re.search(r'-([^\-]+)$', self.getProperty("buildername"))
        arch = m.group(1)

        if self._is_beta():
            self.setCommand(['reset-sdk', '--beta'])
        elif self._is_devel():
            self.setCommand(['update-sdk',
                             '../../build-sdk-%s/sdk-results' % arch])
        else:
            self.setCommand(['reset-sdk'])
        LSBBuildCommand.start(self)
