'''
Copyright (C) 2026 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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
from bpy.types import bpy_struct
from bpy.app.handlers import persistent

import os
import re
import tempfile
from collections.abc import Iterable

from ..common.blender import show_blender_popup


class AutoSave:
    SECOND_TIMER_WAIT     : float = 0.25
    MAX_AUTOSAVE_FAILURES : int   = 5
    USE_DEBUG_TIMING      : bool  = False

    enabled           : bool     = True
    edit_mode         : bool     = False
    autosave_failures : int      = 0
    actively_saving   : bool     = False
    exclude_modal_ops : set[str] = set()

    @staticmethod
    def property_update_enabled(v : bool):
        AutoSave.enabled = v

    @staticmethod
    def is_enabled() -> bool:
        return all([
            AutoSave.enabled,
            bool(bpy.context.preferences.filepaths.use_auto_save_temporary_files),
        ])

    @staticmethod
    def autosave_minutes() -> int:
        if AutoSave.USE_DEBUG_TIMING: return 5
        return 60 * int(bpy.context.preferences.filepaths.auto_save_time)

    @staticmethod
    def random_identifier() -> int:
        # not really random, but this is what blender's source does!  see wm_autosave_location
        return os.getpid()

    @staticmethod
    def can_write(path : str) -> bool:
        if os.path.exists(path):
            return os.access(path, os.W_OK)
        try:    open(path, 'w').close()
        except: return False
        try:    os.remove(path)
        except: return False
        return True

    @staticmethod
    def path_autosave() -> str | None:
        if bpy.data.filepath:
            path_blend = str(bpy.data.filepath)
            path_blendfile = os.path.basename(path_blend)
            filename, ext = os.path.splitext(path_blendfile)
            filename = re.sub(r'_\d+_autosave$', '', filename)  # strip trailing `_####_autosave` in filename so it does not "double up"
            filename_autosave = f'{filename}_{AutoSave.random_identifier()}_autosave{ext}'
        else:
            filename_autosave = f'{AutoSave.random_identifier()}_autosave.blend'

        path_tmp = str(bpy.context.preferences.filepaths.temporary_directory) or tempfile.gettempdir()
        path = os.path.join(path_tmp, filename_autosave)
        if AutoSave.can_write(path): return path

        path_tmp = tempfile.gettempdir()
        path = os.path.join(path_tmp, filename_autosave)
        if AutoSave.can_write(path): return path

        message = '\n'.join([
            f'Cannot write to auto save file: "{path}".',
            f'Check Edit > Prefs > File Paths > Data > Temp Files points to a valid folder with which you have write permissions.',
            f'Check terminal/console for a more detailed report.',
        ])
        detailed_message = '\n'.join([
            f'Cannot write to autosave file',
            f'  autosave:     {path=}',
            f'  filename:     {filename_autosave}',
            f'  blend path:   {bpy.data.filepath}',
            f'  random id:    {AutoSave.random_identifier()}',
            f'  blender temp: {bpy.context.preferences.filepaths.temporary_directory}',
            f'  system temp:  {tempfile.gettempdir()}',
        ])
        show_blender_popup(message, title='Auto-Save Error', icon="ERROR") # wrap=80
        print(detailed_message)
        return None

    @staticmethod
    @persistent
    def handle_depsgraph_change(*args, **kwargs):
        # print(f'AutoSave: depsgraph changed {args=} {kwargs=}')
        if AutoSave.actively_saving: return         # currently saving so ignore!

        in_edit_mode = bool(bpy.context.mode == 'EDIT_MESH')
        was_edit_mode = AutoSave.edit_mode
        AutoSave.edit_mode = in_edit_mode
        # print(f'          {was_edit_mode=} {in_edit_mode=}')

        if in_edit_mode != was_edit_mode:
            AutoSave.unregister_first_timer()       # change into/out of edit mode
            if in_edit_mode:
                AutoSave.register_first_timer()     # in edit mode, so start first timer

        # might not need the following line since we check the modal operators before saving...
        AutoSave.register_second_timer(True)        # change detected, so restart second timer if going

    @staticmethod
    @persistent
    def handle_post_save(*args, **kwargs):
        # print(f'AutoSave: saved')
        # manual saving should reset first timer so we do not auto-save right afterwards
        if not bpy.app.timers.is_registered(AutoSave.first_timer):
            return

        AutoSave.unregister_first_timer()
        AutoSave.register_first_timer()

    @staticmethod
    @persistent
    def handle_pre_load(*args, **kwargs):
        # print(f'AutoSave: loading')
        # reset state of everything!
        AutoSave.unregister_first_timer()
        AutoSave.unregister_second_timer()
        AutoSave.edit_mode = False
        AutoSave.autosave_failures = 0
        AutoSave.actively_saving = False

    @staticmethod
    @persistent
    def handle_post_load(*args, **kwargs):
        print(f'AutoSave: loaded')
        if AutoSave.handle_depsgraph_change not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(AutoSave.handle_depsgraph_change)
        AutoSave.register()

    @staticmethod
    def register_first_timer():
        AutoSave.unregister_first_timer()
        bpy.app.timers.register(
            AutoSave.first_timer,
            first_interval=AutoSave.autosave_minutes() - AutoSave.SECOND_TIMER_WAIT,
        )

    @staticmethod
    def unregister_first_timer():
        if bpy.app.timers.is_registered(AutoSave.first_timer):
            bpy.app.timers.unregister(AutoSave.first_timer)

    @staticmethod
    def register_second_timer(only_if_registered : bool):
        if only_if_registered and not bpy.app.timers.is_registered(AutoSave.second_timer):
            return
        AutoSave.unregister_second_timer()
        bpy.app.timers.register(
            AutoSave.second_timer,
            first_interval=AutoSave.SECOND_TIMER_WAIT,
        )

    @staticmethod
    def unregister_second_timer():
        if bpy.app.timers.is_registered(AutoSave.second_timer):
            bpy.app.timers.unregister(AutoSave.second_timer)

    @staticmethod
    def first_timer():
        # print(f'AutoSave: first timer')
        if not AutoSave.is_enabled():
            # autosave is disabled, so simply reset first timer (artist might enable it again)
            AutoSave.register_first_timer()
        else:
            AutoSave.register_second_timer(False)

    @staticmethod
    def second_timer():
        # print(f'AutoSave: second timer')
        modal_operators = set(op.name for op in bpy.context.window.modal_operators) - AutoSave.exclude_modal_ops
        if modal_operators:
            # artist is using modal operator, so we should wait...
            # print(f'          waiting for {modal_operators} to finish')
            return AutoSave.SECOND_TIMER_WAIT

        filepath = AutoSave.path_autosave()
        if not filepath:
            # something failed with getting an autosave path!
            return

        try:
            AutoSave.actively_saving = True
            # NOTE: this will create .blend1, .blend2, etc. files
            #       not deleting previous versions
            _ = bpy.ops.wm.save_as_mainfile(
                filepath=filepath,
                check_existing=False,
                compress=True,
                copy=True,
            )
            AutoSave.register_first_timer()
            # print(f'          SUCCESS!')
        except Exception as e:
            print(f'Auto-Save: Caught exception while attempting to auto-save {e}')

            AutoSave.autosave_failures += 1
            if AutoSave.autosave_failures <= AutoSave.MAX_AUTOSAVE_FAILURES:
                # attempt again!
                return AutoSave.SECOND_TIMER_WAIT

            message = '\n'.join([
                'Something unexpected happened while trying to perform auto save.',
                'Disabling Auto-Save feature for now.',
                'Be sure to save often!',
                'Check terminal / console for more details.',
            ])
            show_blender_popup(message, title='Auto-Save Error', icon="ERROR")
            print(f'Auto-Save: Hit maximum failed attempts ({AutoSave.MAX_AUTOSAVE_FAILURES})!  disabling auto save for now')
            AutoSave.enabled = False   # this is only temporary; does not update the preferences
        finally:
            AutoSave.actively_saving = False

    @staticmethod
    def exclude_modal_operator(label : str):
        AutoSave.exclude_modal_ops.add(label)
    @staticmethod
    def exclude_modal_operators(labels : Iterable[str]):
        for label in labels:
            AutoSave.exclude_modal_ops.add(label)

    @staticmethod
    def register():
        # print(f'AutoSave: Registering!!!')
        if AutoSave.handle_depsgraph_change not in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.append(AutoSave.handle_depsgraph_change)
        if AutoSave.handle_pre_load not in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.append(AutoSave.handle_pre_load)
        if AutoSave.handle_post_load not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(AutoSave.handle_post_load)
        if AutoSave.handle_post_save not in bpy.app.handlers.save_post:
            bpy.app.handlers.save_post.append(AutoSave.handle_post_save)

        AutoSave.edit_mode = False
        AutoSave.autosave_failures = 0
        AutoSave.actively_saving = False

    @staticmethod
    def unregister():
        # print(f'AutoSave: Unregistering)

        AutoSave.unregister_first_timer()
        AutoSave.unregister_second_timer()
        AutoSave.edit_mode = False
        AutoSave.autosave_failures = 0
        AutoSave.actively_saving = False

        if AutoSave.handle_depsgraph_change in bpy.app.handlers.depsgraph_update_post:
            bpy.app.handlers.depsgraph_update_post.remove(AutoSave.handle_depsgraph_change)
        if AutoSave.handle_pre_load in bpy.app.handlers.load_pre:
            bpy.app.handlers.load_pre.remove(AutoSave.handle_pre_load)
        if AutoSave.handle_post_load in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(AutoSave.handle_post_load)
        if AutoSave.handle_post_save in bpy.app.handlers.save_post:
            bpy.app.handlers.save_post.remove(AutoSave.handle_post_save)
