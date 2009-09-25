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
    def setupEnvironment(self, cmd):
        if self.build.source.changes is None:
            if self.build.source.revision is None:
                buildrev = "-1"
            else:
                buildrev = self.build.source.revision
            if cmd.args['env'] is None:
                cmd.args
            self.build.slaveEnvironment['OFFICIAL_RELEASE'] = buildrev

        ShellCommand.setupEnvironment(self, cmd)

class LSBBuildPackage(LSBBuildCommand):
    def __init__(self, **kwargs):
        if "command" not in kwargs:
            kwargs["command"] = "cd package && make rpm_package"
        ShellCommand.__init__(self, **kwargs)

# Automate some of the packaging build.  When using this, be sure to check
# out a copy of "packaging" (via ShellCommand, as buildbot's source stuff
# can't currently handle multi-repo builds), that your source checkout
# uses a named build dir that's the same as the project, and that BZRTREES
# is set to "..".

class LSBBuildFromPackaging(LSBBuildCommand):
    def __init__(self, **kwargs):
        if "subdir" in kwargs:
            kwargs["command"] = "cd ../packaging/%s && make rpm_package" % kwargs["subdir"]
            del kwargs["subdir"]
        ShellCommand.__init__(self, **kwargs)
