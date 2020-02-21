'''
Copyright (C) 2020 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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
import bpy
import json
import time
from datetime import datetime
from mathutils import Matrix, Vector
from bpy_extras.object_utils import object_data_add

from ...config.options import options, retopoflow_version

from ...addon_common.common.globals import Globals
from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.blender import matrix_vector_mult, get_preferences, set_object_selection, set_active_object
from ...addon_common.common.blender import toggle_screen_header, toggle_screen_toolbar, toggle_screen_properties, toggle_screen_lastop
from ...addon_common.common.maths import BBox
from ...addon_common.common.debug import dprint

class RetopoFlow_BlenderSave:
    '''
    backup / restore methods
    '''

    def check_auto_save(self):
        use_auto_save_temporary_files = get_preferences(self.actions.context).filepaths.use_auto_save_temporary_files
        if not use_auto_save_temporary_files: return
        if hasattr(self, 'time_to_save'):
            if time.time() < self.time_to_save: return
            self.save_backup()
        auto_save_time = get_preferences(self.actions.context).filepaths.auto_save_time * 60
        self.time_to_save = time.time() + auto_save_time

    @staticmethod
    def has_backup():
        filepath = options.temp_filepath('blend')
        return os.path.exists(filepath)

    @staticmethod
    def backup_recover():
        filepath = options.temp_filepath('blend')
        if not os.path.exists(filepath): return
        print('backup recover:', filepath)
        bpy.ops.wm.open_mainfile(filepath=filepath)

    def save_backup(self):
        if hasattr(self, '_backup_broken'): return
        filepath = options.temp_filepath('blend')
        filepath1 = "%s1" % filepath
        dprint('saving backup to %s' % filepath)
        if os.path.exists(filepath1): os.remove(filepath1)
        if os.path.exists(filepath): os.rename(filepath, filepath1)
        self.blender_ui_reset()
        try:
            assert False
            bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=False, copy=True)
        except Exception as e:
            self._backup_broken = True
            self.alert_user(title='Could not save backup', message='Could not save backup file.  Temporarily preventing further backup attempts.  You might try saving file manually.\n\nFile path: %s\n\nError message: "%s"' % (filepath, str(e)))
        self.blender_ui_set()

    def save_normal(self):
        self.blender_ui_reset()
        try:
            bpy.ops.wm.save_mainfile()
        except Exception as e:
            # could not save for some reason; let the artist know!
            self.alert_user(title='Could not save', message='Could not save blend file. Error message: %s' % (str(e)))
        self.blender_ui_set()
        # self.overwrite_window_state()
        # note: filepath might not be set until after save
        filepath = os.path.abspath(bpy.data.filepath)
        dprint('saved to %s' % filepath)

