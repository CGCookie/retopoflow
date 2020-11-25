'''
Copyright (C) 2014 Plasmasolutions
software@plasmasolutions.de

Created by Thomas Beck
Donated to CGCookie and the world

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

import bpy

from .blender import show_blender_popup, show_blender_text

from .globals import Globals

class Logger:
    _log_filename = 'Logger'
    _divider = '\n\n%s\n' % ('='*80)

    @staticmethod
    def set_log_filename(path):
        Logger._log_filename = path

    @staticmethod
    def get_log_filename():
        return Logger._log_filename

    @staticmethod
    def get_log(create=True):
        if Logger._log_filename not in bpy.data.texts:
            if not create: return None
            old = { t.name for t in bpy.data.texts }
            # create a log file for recording
            bpy.ops.text.new()
            for t in bpy.data.texts:
                if t.name in old: continue
                t.name = Logger._log_filename
                break
            else:
                assert False
        return bpy.data.texts[Logger._log_filename]

    @staticmethod
    def has_log():
        return Logger.get_log(create=False) is not None

    @staticmethod
    def add(line):
        log = Logger.get_log()
        log.write('%s%s' % (Logger._divider, str(line)))

    @staticmethod
    def open_log():
        if Logger.has_log():
            show_blender_text(Logger._log_filename)
        else:
            show_blender_popup('Log file (%s) not found' % Logger._log_filename)

logger = Logger()
Globals.set(logger)

