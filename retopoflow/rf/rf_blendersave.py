'''
Copyright (C) 2021 CG Cookie
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
from ...addon_common.common.blender import (
    matrix_vector_mult,
    get_preferences,
    set_object_selection,
    set_active_object,
    toggle_screen_header,
    toggle_screen_toolbar,
    toggle_screen_properties,
    toggle_screen_lastop,
    show_error_message,
)
from ...addon_common.common.maths import BBox
from ...addon_common.common.debug import dprint

from .rf_blender import RetopoFlow_Blender



@persistent
def revert_auto_save_after_load(*_, **__):
    # remove recover handler
    bpy.app.handlers.load_post.remove(revert_auto_save_after_load)
    RetopoFlow_BlenderSave.recovery_revert()


class RetopoFlow_BlenderSave:
    '''
    backup / restore methods
    '''

    @staticmethod
    def can_recover():
        if options['rotate object'] in bpy.data.objects: return True
        if options['blender state'] in bpy.data.texts: return True
        return False

    @staticmethod
    def recovery_revert():
        print('RetopoFlow: recovering from auto save')

        # the rotate object should not exist, but just in case
        if options['rotate object'] in bpy.data.objects:
            bpy.data.objects.remove(
                bpy.data.objects[options['rotate object']],
                do_unlink=True,
            )

        # grab previous blender state
        if options['blender state'] not in bpy.data.texts: return   # no blender state!?!?
        data = json.loads(bpy.data.texts[options['blender state']].as_string())

        # get target object and reset settings
        tar_object = bpy.data.objects[data['active object']]
        tar_object.hide_viewport = False
        tar_object.hide_render = False
        bpy.context.view_layer.objects.active = tar_object
        tar_object.select_set(True)

        # restore window state (mostly tool, properties, header, etc.)
        RetopoFlow_Blender.restore_window_state(
            ignore_panels=False,
            ignore_mode=False,
        )

        factor = data['unit scaling factor']
        RetopoFlow_Blender.scale_sources_target(factor)

        bpy.data.texts.remove(
            bpy.data.texts[options['blender state']],
            do_unlink=True,
        )


    @staticmethod
    def get_auto_save_settings(context):
        prefs = get_preferences(context)
        use_auto_save = prefs.filepaths.use_auto_save_temporary_files
        path_blend = getattr(bpy.data, 'filepath', '')
        path_autosave = options.get_auto_save_filepath()
        good_auto_save = (not options['check auto save']) or use_auto_save
        good_unsaved = (not options['check unsaved']) or path_blend
        return {
            'auto save': good_auto_save,
            'auto save path': path_autosave,
            'saved': good_unsaved,
        }

    def check_auto_save_warnings(self):
        settings = RetopoFlow_BlenderSave.get_auto_save_settings(self.actions.context)
        save = self.actions.to_human_readable('blender save')
        good_auto_save = settings['auto save']
        path_autosave = settings['auto save path']
        good_unsaved = settings['saved']

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
                f'Your changes will be saved to `{path_autosave}` when you press `{save}`',
                '',
                '''<input type="checkbox" value="options['check unsaved']">Run check for unsaved .blend file when RetopoFlow starts</input>''',
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
    def has_auto_save():
        filepath = options['last auto save path']
        return filepath and os.path.exists(filepath)

    @staticmethod
    def recover_auto_save():
        filepath = options['last auto save path']
        print(f'backup recover: {filepath}')
        if not filepath or not os.path.exists(filepath):
            print(f'  DOES NOT EXIST!')
            return

        bpy.app.handlers.load_post.append(revert_auto_save_after_load)

        bpy.ops.wm.open_mainfile(filepath=filepath)

    def save_emergency(self):
        try:
            filepath = options.get_auto_save_filepath(suffix='EMERGENCY')
            bpy.ops.wm.save_as_mainfile(
                filepath=filepath,
                compress=True,          # write compressed file
                check_existing=False,   # do not warn if file already exists
                copy=True,              # does not make saved file active
            )
        except:
            self.done(emergency_bail=True)
            show_error_message(
                "RetopoFlow crashed unexpectedly.  Be sure to save your work, and report what happened so that we can try fixing it.",
                "Unexpected Crash!",
            )

    def save_backup(self):
        if hasattr(self, '_backup_broken'): return
        if self.last_change_count == self.change_count:
            print('skipping backup save')
            return

        filepath = options.get_auto_save_filepath()
        filepath1 = f'{filepath}1'

        print(f'saving backup: {filepath}')
        errors = {}

        if os.path.exists(filepath):
            if os.path.exists(filepath1):
                try:
                    print(f'  deleting old backup: {filepath1}')
                    os.remove(filepath1)
                except Exception as e:
                    print(f'    caught exception: {e}')
                    errors['delete old'] = e

            try:
                print(f'  renaming prev backup: {filepath1}')
                os.rename(filepath, filepath1)
            except Exception as e:
                print(f'    caught exception: {e}')
                errors['rename prev'] = e

        if 'rename prev' not in errors:
            try:
                print(f'  saving...')
                bpy.ops.wm.save_as_mainfile(
                    filepath=filepath,
                    compress=True,          # write compressed file
                    check_existing=False,   # do not warn if file already exists
                    copy=True,              # does not make saved file active
                )
                options['last auto save path'] = filepath
                self.last_change_count = self.change_count
            except Exception as e:
                print(f'   caught exception: {e}')
                errors['saving'] = e
        else:
            '''
            skipping normal save, because we might lose data!
            '''
            errors['skipped save'] = 'error while trying to rename prev'

        if errors:
            self._backup_broken = True
            self.alert_user(
                title='Could not save backup',
                level='assert',
                message=(
                    f'Could not save backup file.  '
                    f'Temporarily preventing further backup attempts.  '
                    f'You might try saving file manually.\n\n'
                    f'File paths: `{filepath}`, `{filepath1}`\n\n'
                    f'Errors: {errors}\n\n'
                ),
            )

    def save_normal(self):
        self.blender_ui_reset()
        try:
            bpy.ops.wm.save_mainfile()
        except Exception as e:
            # could not save for some reason; let the artist know!
            self.alert_user(
                title='Could not save',
                message=f'Could not save blend file.\n\nError message: "{e}"',
                level='warning',
            )
        self.blender_ui_set()
        # note: filepath might not be set until after save
        filepath = os.path.abspath(bpy.data.filepath)
        print(f'saved: {filepath}')

