# Copyright (c) 2014-present PlatformIO <contact@platformio.org>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import

import sys
from os.path import isdir, isfile, join

from SCons.Script import COMMAND_LINE_TARGETS

from platformio import exception, util
from platformio.managers.platform import PlatformFactory


@util.memoized
def initPioPlatform(name):
    return PlatformFactory.newPlatform(name)


def PioPlatform(env):
    variables = {}
    for name in env['PIOVARIABLES']:
        if name in env:
            variables[name.lower()] = env[name]
    p = initPioPlatform(env['PLATFORM_MANIFEST'])
    p.configure_default_packages(variables, COMMAND_LINE_TARGETS)
    return p


def BoardConfig(env, board=None):
    p = initPioPlatform(env['PLATFORM_MANIFEST'])
    try:
        board = board or env.get("BOARD")
        assert board, "BoardConfig: Board is not defined"
        config = p.board_config(board)
    except (AssertionError, exception.UnknownBoard) as e:
        sys.stderr.write("Error: %s\n" % str(e))
        env.Exit(1)
    return config


def GetFrameworkScript(env, framework):
    p = env.PioPlatform()
    assert p.frameworks and framework in p.frameworks
    script_path = env.subst(p.frameworks[framework]['script'])
    if not isfile(script_path):
        script_path = join(p.get_dir(), script_path)
    return script_path


def LoadPioPlatform(env, variables):
    p = env.PioPlatform()
    installed_packages = p.get_installed_packages()

    # Ensure real platform name
    env['PIOPLATFORM'] = p.name

    # Add toolchains and uploaders to $PATH
    for name in installed_packages:
        type_ = p.get_package_type(name)
        if type_ not in ("toolchain", "uploader"):
            continue
        path = p.get_package_dir(name)
        if isdir(join(path, "bin")):
            path = join(path, "bin")
        env.PrependENVPath("PATH", path)

    # Platform specific LD Scripts
    if isdir(join(p.get_dir(), "ldscripts")):
        env.Prepend(LIBPATH=[join(p.get_dir(), "ldscripts")])

    if "BOARD" not in env:
        return

    board_config = env.BoardConfig()
    for k in variables.keys():
        if k in env or \
                not any([k.startswith("BOARD_"), k.startswith("UPLOAD_")]):
            continue
        _opt, _val = k.lower().split("_", 1)
        if _opt == "board":
            _opt = "build"
        if _val in board_config.get(_opt):
            env.Replace(**{k: board_config.get("%s.%s" % (_opt, _val))})

    if "build.ldscript" in board_config:
        env.Replace(LDSCRIPT_PATH=board_config.get("build.ldscript"))


def PrintSystemInfo(env):
    data = []
    debug_tools = None
    mcu = env.subst("$BOARD_MCU")
    f_cpu = env.subst("$BOARD_F_CPU")
    if mcu:
        data.append(mcu.upper())
    if f_cpu:
        f_cpu = int("".join([c for c in str(f_cpu) if c.isdigit()]))
        data.append("%dMHz" % (f_cpu / 1000000))

    if "BOARD" in env:
        board_config = env.BoardConfig()
        debug_tools = board_config.get("debug", {}).get("tools")
        ram = board_config.get("upload", {}).get("maximum_ram_size")
        flash = board_config.get("upload", {}).get("maximum_size")
        for (key, value) in (("RAM", ram), ("Flash", flash)):
            if not value:
                continue
            data.append("%s/%s" % (key, util.format_filesize(value)))

    if data:
        print "System: %s" % " ".join(data)

    # Debugging
    if not debug_tools:
        return

    data = []
    onboard = []
    external = []
    for key, value in debug_tools.items():
        if value.get("onboard"):
            onboard.append(key)
        else:
            external.append(key)
    if onboard:
        data.append("ON-BORD/%s" % ", ".join(sorted(onboard)))
    if external:
        data.append("EXTERNAL/%s" % ", ".join(sorted(external)))

    print "Debug: %s" % " ".join(data)


def exists(_):
    return True


def generate(env):
    env.AddMethod(PioPlatform)
    env.AddMethod(BoardConfig)
    env.AddMethod(GetFrameworkScript)
    env.AddMethod(LoadPioPlatform)
    env.AddMethod(PrintSystemInfo)
    return env
