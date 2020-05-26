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
from bpy.app.handlers import persistent

from ...config.options import options, retopoflow_version

from ...addon_common.common.globals import Globals
from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.blender import matrix_vector_mult, get_preferences, set_object_selection, set_active_object
from ...addon_common.common.blender import toggle_screen_header, toggle_screen_toolbar, toggle_screen_properties, toggle_screen_lastop
from ...addon_common.common.maths import BBox
from ...addon_common.common.debug import dprint

from .rf_blender import RetopoFlow_Blender


@persistent
def handle_recover(*args, **kwargs):
    print('RetopoFlow: handling recover from auto save')

    # remove recover handler
    bpy.app.handlers.load_post.remove(handle_recover)

    ##################
    # restore
    
    # the rotate object should not exist, but just in case
    if options['rotate object'] in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[options['rotate object']], do_unlink=True)

    # grab previous blender state
    if options['blender state'] not in bpy.data.texts: return   # no blender state!?!?
    data = json.loads(bpy.data.texts[options['blender state']].as_string())

    # get target object and reset settings
    tar_object = bpy.data.objects[data['active object']]
    bpy.context.view_layer.objects.active = tar_object
    tar_object.hide_viewport = False
    tar_object.hide_render = False

    # restore window state (mostly tool, properties, header, etc.)
    RetopoFlow_Blender.restore_window_state(ignore_panels=False, ignore_mode=False)


class RetopoFlow_BlenderSave:
    '''
    backup / restore methods
    '''

    def check_auto_save_warnings(self):
        prefs = get_preferences(self.actions.context)
        use_auto_save = prefs.filepaths.use_auto_save_temporary_files
        save = self.actions.to_human_readable('blender save')
        path_blend = getattr(bpy.data, 'filepath', '')
        path_autosave = options.get_auto_save_filepath()

        good_auto_save = (not options['check auto save']) or use_auto_save
        good_unsaved = (not options['check unsaved']) or path_blend

        if good_auto_save and good_unsaved: return

        message = []

        if not good_auto_save:
            message += ['\n'.join([
                'The Auto Save option in Blender (Edit > Preferences > Save & Load > Auto Save) is currently disabled.',
                'Your changes will _NOT_ be saved automatically!',
                '',
                '''<input type="checkbox" value="options['check auto save']">Check Auto Save option when RetopoFlow starts</input>''',
            ])]

        if not good_unsaved:
            message += ['\n'.join([
                'You are currently working on an _UNSAVED_ Blender file.',
                'Your changes will be saved to `%s` when you press `%s`' % (path_autosave, save),
                '',
                '''<input type="checkbox" value="options['check unsaved']">Check for Unsaved when RetopoFlow starts</input>''',
            ])]
        else:
            message += ['Press `%s` any time to save your changes.' % (save)]

        self.alert_user(
            title='Blender auto save / save file checker',
            message='\n\n'.join(message),
            level='warning',
        )

    def handle_auto_save(self):
        prefs = get_preferences(self.actions.context)
        use_auto_save = prefs.filepaths.use_auto_save_temporary_files
        auto_save_time = prefs.filepaths.auto_save_time * 60

        if not use_auto_save: return    # Blender's auto save is disabled  :(

        if not hasattr(self, 'time_to_save'):
            # RF just started, so do not save yet
            self.last_change_count = None
            # record the next time to save
            self.time_to_save = time.time() + auto_save_time
        elif time.time() > self.time_to_save:
            # it is time to save, but only if changes were made!
            self.save_backup()
            # record the next time to save
            self.time_to_save = time.time() + auto_save_time

    @staticmethod
    def has_backup():
        filepath = options['last auto save path']
        return filepath and os.path.exists(filepath)

    @staticmethod
    def backup_recover():
        filepath = options['last auto save path']
        if not filepath or not os.path.exists(filepath): return

        bpy.app.handlers.load_post.append(handle_recover)

        print('backup recover:', filepath)
        bpy.ops.wm.open_mainfile(filepath=filepath)



    def save_backup(self):
        if hasattr(self, '_backup_broken'): return
        if self.last_change_count == self.change_count:
            dprint('skipping backup save')
            return
        filepath = options.get_auto_save_filepath()
        filepath1 = "%s1" % filepath
        dprint('saving backup to %s' % filepath)
        if os.path.exists(filepath1): os.remove(filepath1)
        if os.path.exists(filepath): os.rename(filepath, filepath1)
        try:
            bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=False, copy=True)
            options['last auto save path'] = filepath
            self.last_change_count = self.change_count
        except Exception as e:
            self._backup_broken = True
            self.alert_user(title='Could not save backup', message='Could not save backup file.  Temporarily preventing further backup attempts.  You might try saving file manually.\n\nFile path: %s\n\nError message: "%s"' % (filepath, str(e)))

    def save_normal(self):
        self.blender_ui_reset()
        try:
            bpy.ops.wm.save_mainfile()
        except Exception as e:
            # could not save for some reason; let the artist know!
            self.alert_user(
                title='Could not save',
                message='Could not save blend file.\n\n%s' % (str(e)),
                level='warning'
            )
        self.blender_ui_set()
        # note: filepath might not be set until after save
        filepath = os.path.abspath(bpy.data.filepath)
        dprint('saved to %s' % filepath)

