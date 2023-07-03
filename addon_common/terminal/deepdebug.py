'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import os
import sys
from pathlib import Path

from . import term_printer


# DEEP DEBUGGING: if debug.txt file exists in addon root folder, redirect **ALL** stdout and stderr to that file!
class DeepDebug:
    _fn_debug = 'debug.txt'
    _path_debug = None
    _needs_restart = False

    @staticmethod
    def path_debug():
        if DeepDebug._path_debug is None:
            DeepDebug._path_debug = Path(__file__).parent.parent.parent / DeepDebug._fn_debug
        return DeepDebug._path_debug

    @staticmethod
    def is_enabled():
        return DeepDebug.path_debug().exists()

    @staticmethod
    def needs_restart():
        return DeepDebug._needs_restart

    @staticmethod
    def enable():
        if DeepDebug.is_enabled(): return
        DeepDebug.path_debug().touch()
        DeepDebug._needs_restart = True

    @staticmethod
    def disable():
        if not DeepDebug.is_enabled(): return
        DeepDebug.path_debug().unlink()
        DeepDebug._needs_restart = True

    @staticmethod
    def init(*, fn_debug=None, clear=True):
        assert DeepDebug._path_debug is None, f'Addon Common: DeepDebug should be initialized only once'

        if fn_debug:
            DeepDebug._fn_debug = fn_debug

        # assuming this file is two folders under the addon root folder
        if not DeepDebug.is_enabled(): return

        path_debug = DeepDebug.path_debug()

        term_printer.boxed(
            f'Redirecting ALL STDOUT and STDERR',
            f'path: {path_debug}',
            title='Deep Debugging', margin=' ', sides='double', color='black', highlight='blue',
         )
        sys.stdout.flush()
        if clear: path_debug.unlink()  # delete it to reset session recording

        # https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/11632982#11632982
        # in C++, see https://stackoverflow.com/a/13888242 and https://cplusplus.com/reference/cstdio/freopen/
        os.close(1)
        os.open(path_debug, os.O_WRONLY | os.O_CREAT)

    @staticmethod
    def read():
        if not DeepDebug.is_enabled(): return None
        return DeepDebug.path_debug().read_text()

