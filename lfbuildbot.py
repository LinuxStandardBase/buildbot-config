# -*- python -*-
# ex: set syntax=python:

# We define our own build classes, for working with the quirky LSB build
# system.  The idea is that we set (or don't) certain environment variables
# depending on whether the branch or revision has been overriden, to add
# the date-based versions when they haven't.  Also, for those projects
# built out of packaging, handle them too.

import re

from buildbot.steps.shell import ShellCommand
from buildbot.steps.master import MasterShellCommand
from buildbot.scheduler import Triggerable
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

        if "production:" in self.build.reason or found_lsb_version:
            args.append("OFFICIAL_RELEASE=%s" % self.build.source.revision)

        return args

    def _set_branch_name(self):
        "Set the branch_name property to a safe branch name."

        self.setProperty("branch_name", 
                         extract_branch_name(self.getProperty("branch")))

    def start(self):
        self._set_branch_name()

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

class LSBReloadSDK(ShellCommand):
    command = ["placeholder"]

    def _set_branch_name(self):
        "Set the branch_name property to a safe branch name."

        self.setProperty("branch_name", 
                         extract_branch_name(self.getProperty("branch")))

    def _is_devel(self):
        "Figure out whether we're being called on a devel tree."

        return self.getProperty("branch_name") == "devel"

    def start(self):
        m = re.search(r'-([^\-]+)$', self.getProperty("buildername"))
        arch = m.group(1)

        self._set_branch_name()
        if self._is_devel():
            self.setCommand(['update-sdk',
                             '../../build-sdk-%s/sdk-results' % arch])
        else:
            self.setCommand(['reset-sdk'])
        ShellCommand.start(self)
