# -*- python -*-
# ex: set syntax=python:

# We define our own build classes, for working with the quirky LSB build
# system.  The idea is that we set (or don't) certain environment variables
# depending on whether the branch or revision has been overriden, to add
# the date-based versions when they haven't.  Also, for those projects
# built out of packaging, handle them too.

import re

from twisted.python import log
from twisted.application import internet

from buildbot import buildset
from buildbot.steps.shell import ShellCommand
from buildbot.steps.master import MasterShellCommand
from buildbot.scheduler import BaseUpstreamScheduler, Triggerable
from buildbot.sourcestamp import SourceStamp

# List of supported architectures.  Used for MultiScheduler.

lsb_archs = ["x86_64", "x86", "ia64", "ppc32", "ppc64", "s390", "s390x"]

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
    def __init__(self, name, builderNames, useSourceStamp=False):
        Triggerable.__init__(self, name, builderNames)
        self.useSourceStamp = useSourceStamp

    def trigger(self, ss, set_props=None):
        if not self.useSourceStamp:
            return Triggerable.trigger(self, 
                                       SourceStamp(None, None, None, None), 
                                       set_props)
        else:
            return Triggerable.trigger(self, ss, set_props)

# Job file parser for MultiScheduler.  It turns a job file into a number
# of BuildRequest objects.

class JobParseError(Exception):
    pass

class MultiJobFile:
    def __init__(self, path, properties={}):
        self.tag = None
        self.projects = []
        self.branch_name = None
        self.build_type = "normal"
        self.properties = properties
        self.path = path

        try:
            self.f = open(self.path)
        except:
            raise JobParseError("could not open job file " + self.path)

        try:
            self.parse()
        finally:
            self.f.close()

        self.properties["build_type"] = self.build_type

        if not self.branch_name or not self.projects:
            raise JobParseError("missing information in job file")
        if self.build_type not in ("normal", "production", "beta"):
            raise JobParseError("invalid build type: " + self.build_type)

    def __iter__(self):
        if self.tag:
            revision = "tag:" + self.tag
        else:
            revision = None

        for prj in self.projects:
            for arch in lsb_archs:
                builderNames = ["%s-%s" % (prj, arch)]
                branch = "lsb/%s/%s" % (self.branch_name, prj)
                ss = SourceStamp(branch, revision, None, None)
                yield buildset.BuildSet(builderNames, ss, 
                                        reason="MultiScheduler job",
                                        properties=self.properties)

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
            else:
                raise JobParseError("invalid key: " + name)

# Scheduler which can start a number of builds at once.  These are
# grouped by project; they are started across all supported architectures.

class MultiScheduler(BaseUpstreamScheduler):
    compare_attrs = ('name', 'jobdir', 'properties')

    def __init__(self, name, builderNames, jobdir, properties={}):
        BaseUpstreamScheduler.__init__(self, name, properties)
        self.builderNames = builderNames
        self.jobdir = jobdir
        self.properties = properties
        self.poller = internet.TimerService(10, self.poll)
        self.poller.setServiceParent(self)

    def listBuilderNames(self):
        return self.builderNames

    def getPendingBuildTimes(self):
        return []

    def poll(self):
        for f in os.listdir(self.jobdir):
            f_full = os.path.join(self.jobdir, f)
            try:
                try:
                    jobfile = MultiJobFile(f_full, self.properties)
                    for bs in jobfile:
                        self.submitBuildSet(bs)
                finally:
                    os.unlink(f_full)
            except JobParseError, e:
                log.msg("bad job file %s: %s" % (f, str(e)))
                continue

class PropMasterShellCommand(MasterShellCommand):
    def start(self):
        properties = self.build.getProperties()
        self.command = properties.render(self.command)
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

        if self.getProperty("build_type") in ("beta", "production") \
                or found_lsb_version:
            args.append("OFFICIAL_RELEASE=%s" % self.build.source.revision)

        if self.getProperty("build_type") == "beta":
            args.append("SKIP_DEVEL_VERSIONS=no")

        return args

    def _set_branch_name(self):
        "Set the branch_name property to a safe branch name."

        self.setProperty("branch_name", 
                         extract_branch_name(self.getProperty("branch")))

    def _calc_build_type(self):
        "Figure out whether we're being called for a beta build."

        if "beta:" in self.build.reason:
            return "beta"
        elif "production:" in self.build.reason:
            return "production"
        else:
            return "normal"

    def _set_build_type(self):
        "Propagate the build type into the build's properties if needed."

        try:
            self.getProperty("build_type")
        except KeyError:
            self.setProperty("build_type", self._calc_build_type())

    def start(self):
        self._set_branch_name()
        self._set_build_type()

        if self.do_make_args:
            self.setCommand(self.command + " " + " ".join(self._get_make_args()))

        ShellCommand.start(self)

class LSBBuildPackage(LSBBuildCommand):
    def __init__(self, makeargs=False, **kwargs):
        if "command" not in kwargs:
            kwargs["command"] = "cd package && make BUILD_NO_DEB=1"
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

# Reload the SDK.  This class figures out what SDK we need (devel, stable,
# or beta) and installs it.

class LSBReloadSDK(LSBBuildCommand):
    command = ["placeholder"]

    def _is_devel(self):
        "Figure out whether we're being called on a devel tree."

        return self.getProperty("branch_name") == "devel"

    def _is_beta(self):
        "Figure out whether we're being called for a beta build."

        return self.getProperty("build_type") == "beta"

    def start(self):
        m = re.search(r'-([^\-]+)$', self.getProperty("buildername"))
        arch = m.group(1)

        self._set_branch_name()
        self._set_build_type()
        if self._is_beta():
            self.setCommand(['reset-sdk', '--beta'])
        elif self._is_devel():
            self.setCommand(['update-sdk',
                             '../../build-sdk-%s/sdk-results' % arch])
        else:
            self.setCommand(['reset-sdk'])
        ShellCommand.start(self)
