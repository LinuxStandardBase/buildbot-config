# -*- python -*-
# ex: set syntax=python:

# We define our own build classes, for working with the quirky LSB build
# system.  The idea is that we set (or don't) certain environment variables
# depending on whether the branch or revision has been overriden, to add
# the date-based versions when they haven't.  Also, for those projects
# built out of packaging, handle them too.

from buildbot.steps.shell import ShellCommand
from buildbot.steps.master import MasterShellCommand

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
        if "production:" in self.build.reason:
            args.append("OFFICIAL_RELEASE=%s" % self.build.source.revision)
        return args

    def start(self):
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
