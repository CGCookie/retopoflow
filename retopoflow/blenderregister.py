'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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
import re
import sys
import json
import time
import textwrap
import importlib
from pathlib import Path

import bpy

from bpy.types import Menu, Operator, Panel
from bpy.props import BoolProperty
from bpy_extras import object_utils
from bpy.app.handlers import persistent

from ..addon_common.hive.hive import Hive
from ..addon_common.common.decorators import add_cache
from ..addon_common.cookiecutter.cookiecutter import CookieCutter


import_succeeded = False

try:
    if "retopoflow" in locals():
        print('RetopoFlow: RELOADING!')
        # reloading RF modules
        importlib.reload(retopoflow)
        importlib.reload(image_preloader)
        importlib.reload(helpsystem)
        importlib.reload(updatersystem)
        importlib.reload(keymapsystem)
        importlib.reload(configoptions)
        importlib.reload(updater)
        importlib.reload(cookiecutter)
        importlib.reload(rftool)
    else:
        print('RetopoFlow: Initial load')
        from ..config import options as configoptions
        from . import retopoflow
        from . import helpsystem
        from . import updatersystem
        from . import keymapsystem
        from . import updater
        from . import rftool
        from ..addon_common.cookiecutter import cookiecutter
        from ..addon_common.common.maths import convert_numstr_num, has_inverse
        from ..addon_common.common.blender import get_active_object, BlenderIcon, get_path_from_addon_root, show_blender_popup, show_blender_text
        from ..addon_common.common.boundvar import BoundBool
        from ..addon_common.common.image_preloader import ImagePreloader
        from ..addon_common.terminal.deepdebug import DeepDebug
    options = configoptions.options
    rfurls = configoptions.retopoflow_urls
    import_succeeded = True
    RFTool = rftool.RFTool
except ModuleNotFoundError as e:
    print('RetopoFlow: ModuleNotFoundError caught when trying to enable add-on!')
    print(e)
except Exception as e:
    print('RetopoFlow: Unexpected Exception caught when trying to enable add-on!')
    print(e)
    from .addon_common.common.debug import Debugger
    message,h = Debugger.get_exception_info_and_hash()
    message = '\n'.join('- %s'%l for l in message.splitlines())
    print(message)


# the classes to register/unregister
RF_classes = []
def add_to_registry(cls_or_list):
    if isinstance(cls_or_list, list):
        RF_classes.extend(cls_or_list)
    else:
        # could be used as class decorator, so return class
        RF_classes.append(cls_or_list)
        return cls_or_list


if import_succeeded:
    # point BlenderIcon to correct icon path
    BlenderIcon.path_icons = get_path_from_addon_root('icons')

    if options['preload help images']:
        # start preloading images
        ImagePreloader.start([
            ('help'),
            ('icons'),
            ('addon_common', 'common', 'images'),
        ])


##################################################################################
# Blender Operator Factories

@add_cache('_cache', {})
def create_help_builtin_operator(label, filename):
    key = (label, filename)
    if key not in create_help_builtin_operator._cache:
        idname = label.replace(' ', '')
        class VIEW3D_OT_RetopoFlow_Help(helpsystem.RetopoFlow_OpenHelpSystem):
            """Open RetopoFlow Help System"""
            bl_idname = f'cgcookie.retopoflow_help_{idname.lower()}'
            bl_label = f'RF Help: {label}'
            bl_description = f'Open RetopoFlow Help System: {label}'
            bl_space_type = "VIEW_3D"
            bl_region_type = "TOOLS"
            bl_options = set()
            rf_startdoc = f'{filename}.md'
        VIEW3D_OT_RetopoFlow_Help.__name__ = f'VIEW3D_OT_RetopoFlow_Help_{idname}'
        add_to_registry(VIEW3D_OT_RetopoFlow_Help)
        create_help_builtin_operator._cache[key] = VIEW3D_OT_RetopoFlow_Help
    return create_help_builtin_operator._cache[key]

@add_cache('_cache', {})
def create_help_online_operator(label, filename):
    key = (label, filename)
    if key not in create_help_online_operator._cache:
        idname = label.replace(' ', '')
        class VIEW3D_OT_RetopoFlow_Online(Operator):
            """Open RetopoFlow Help Online"""
            bl_idname = f'cgcookie.retopoflow_online_{idname.lower()}'
            bl_label = f'RF Online: {label}'
            bl_description = f'Open RetopoFlow Help Online: {label}'
            bl_space_type = "VIEW_3D"
            bl_region_type = "TOOLS"
            bl_options = set()
            def invoke(self, context, event):
                return self.execute(context)
            def execute(self, context):
                bpy.ops.wm.url_open(url=rfurls['help doc'](filename))
                return {'FINISHED'}
        VIEW3D_OT_RetopoFlow_Online.__name__ = f'VIEW3D_OT_RetopoFlow_Online_{idname}'
        add_to_registry(VIEW3D_OT_RetopoFlow_Online)
        create_help_online_operator._cache[key] = VIEW3D_OT_RetopoFlow_Online
    return create_help_online_operator._cache[key]

@add_cache('_cache', {})
def create_webpage_operator(name, label, description, url):
    key = (name, label, description, url)
    if key not in create_webpage_operator._cache:
        idname = name.lower()
        class VIEW3D_OT_RetopoFlow_Web(Operator):
            bl_idname = f'cgcookie.retopoflow_web_{idname}'
            bl_label = f'{label}'
            bl_description = f'Open {description} in the default browser'
            bl_space_type = 'VIEW_3D'
            bl_region_type = 'TOOLS'
            bl_options = set()
            def invoke(self, context, event):
                return self.execute(context)
            def execute(self, context):
                bpy.ops.wm.url_open(url=url)
                return {'FINISHED'}
        VIEW3D_OT_RetopoFlow_Web.__name__ = f'VIEW3D_OT_RetopoFlow_Web_{name}'
        add_to_registry(VIEW3D_OT_RetopoFlow_Web)
        create_webpage_operator._cache[key] = VIEW3D_OT_RetopoFlow_Web
    return create_webpage_operator._cache[key]

def create_toggle_operator(name, label, description, boundbool):
    idname = label.replace(' ', '')
    class VIEW3D_OT_RetopoFlow_Toggle(Operator):
        bl_idname = f'cgcookie.retopoflow_toggle_{idname.lower()}'
        bl_label = f'RF Toggle: {label}'
        bl_description = f'Toggle RetopoFlow value: {label}'
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        def invoke(self, context, event):
            return self.execute(context)
        def execute(self, context):
            boundbool.checked = not boundbool.checked
            return {'FINISHED'}
    VIEW3D_OT_RetopoFlow_Toggle.__name__ = f'VIEW3D_OT_RetopoFlow_Toggle_{name}'
    add_to_registry(VIEW3D_OT_RetopoFlow_Toggle)
    return VIEW3D_OT_RetopoFlow_Toggle

##################################################################################

create_webpage_operator(
    'BlenderMarket',
    'Visit Blender Market',
    'Blender Market RetopoFlow',
    rfurls['blender market'],
)

create_webpage_operator(
    'GitHub_NewIssue',
    'Create a new issue on GitHub',
    'RetopoFlow GitHub New Issue Page',
    rfurls['new github issue'],
)

create_webpage_operator(
    'Online_Main',
    'Online documentation',
    'RetopoFlow Online Documentation',
    rfurls['help docs'],
)

@add_to_registry
class VIEW3D_OT_RetopoFlow_EnableDebugging(Operator):
    bl_idname = "cgcookie.retopoflow_enabledebugging"
    bl_label = "RetopoFlow: Enable Debugging"
    bl_description = "Enables deep debugging (requires restarting Blender)"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()
    @classmethod
    def poll(cls, context):
        return DeepDebug.can_be_enabled() and not DeepDebug.is_enabled()
    def invoke(self, context, event):
        return self.execute(context)
    def execute(self, context):
        DeepDebug.enable()
        show_blender_popup('You must restart Blender to finish enabling deep debugging', title='Restart Blender')
        return {'FINISHED'}
@add_to_registry
class VIEW3D_OT_RetopoFlow_DisableDebugging(Operator):
    bl_idname = "cgcookie.retopoflow_disabledebugging"
    bl_label = "RetopoFlow: Disable Debugging"
    bl_description = "Disables deep debugging (requires restarting Blender)"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()
    @classmethod
    def poll(cls, context):
        return DeepDebug.is_enabled()
    def invoke(self, context, event):
        return self.execute(context)
    def execute(self, context):
        DeepDebug.disable()
        show_blender_popup('You must restart Blender to finish disabling deep debugging', title='Restart Blender')
        return {'FINISHED'}

@add_to_registry
class VIEW3D_OT_RetopoFlow_OpenDebugging(Operator):
    bl_idname = "cgcookie.retopoflow_opendebugging"
    bl_label = "RetopoFlow: Open Debugging Info"
    bl_description = "Opens deep debugging info in a text editor"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()
    @classmethod
    def poll(cls, context):
        path = next((str(p) for p in [DeepDebug.path_debug(), DeepDebug.path_debug_backup()] if p.exists()), None)
        return path is not None
        # return DeepDebug.is_enabled()
    def invoke(self, context, event):
        return self.execute(context)
    def execute(self, context):
        path = next((str(p) for p in [DeepDebug.path_debug(), DeepDebug.path_debug_backup()] if p.exists()), None)
        if not path: return {'CANCELLED'}
        def get_debug_textblock():
            return next((t for t in bpy.data.texts if t.filepath == path), None)
        sys.stdout.flush()
        sys.stderr.flush()
        t = get_debug_textblock()
        if t: bpy.data.texts.remove(t)
        bpy.ops.text.open(filepath=path)
        t = get_debug_textblock()
        show_blender_text(t.name)
        return {'FINISHED'}

@add_to_registry
class VIEW3D_OT_RetopoFlow_ClearDebugging(Operator):
    bl_idname = "cgcookie.retopoflow_cleardebugging"
    bl_label = "RetopoFlow: Clear Debugging Info"
    bl_description = "Deletes any deep debugging info"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()
    @classmethod
    def poll(cls, context):
        path = next((str(p) for p in [DeepDebug.path_debug(), DeepDebug.path_debug_backup()] if p.exists()), None)
        return path is not None
        # return DeepDebug.is_enabled()
    def invoke(self, context, event):
        return self.execute(context)
    def execute(self, context):
        for path in [DeepDebug.path_debug(), DeepDebug.path_debug_backup()]:
            if path.exists(): path.unlink()
        return {'FINISHED'}



if import_succeeded:
    # create operators for viewing RetopoFlow help documents
    for (label, filename) in [
        ('Quick Start Guide', 'quick_start'),
        ('Welcome Message',   'welcome'),
        ('Table of Contents', 'table_of_contents'),
        ('FAQ',               'faq'),
        ('Keymap Editor',     'keymap_editor'),
        ('Updater System',    'addon_updater'),
        ('Warning Details',   'warnings'),
        ('Debugging',         'debugging')
    ]:
        create_help_builtin_operator(label, filename),
        create_help_online_operator(label, filename),

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_UpdaterSystem(updatersystem.RetopoFlow_OpenUpdaterSystem):
        """Open RetopoFlow Updater System"""
        bl_idname = "cgcookie.retopoflow_updater"
        bl_label = "Updater"
        bl_description = "Open RetopoFlow Updater"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_KeymapEditor(keymapsystem.RetopoFlow_OpenKeymapSystem):
        """Open RetopoFlow Keymap Editor"""
        bl_idname = "cgcookie.retopoflow_keymapeditor"
        bl_label = "Keymap Editor"
        bl_description = "Open RetopoFlow Keymap Editor"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()




if import_succeeded:
    '''
    create operators to start RetopoFlow
    '''

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_NewTarget_Cursor(Operator):
        """Create new target object+mesh at the 3D Cursor and start RetopoFlow"""
        bl_idname = "cgcookie.retopoflow_newtarget_cursor"
        bl_label = "RF: New target at Cursor"
        bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nCreate new target mesh based on the cursor and start RetopoFlow"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

        @classmethod
        def poll(cls, context):
            if not context.region or context.region.type != 'WINDOW': return False
            if not context.space_data or context.space_data.type != 'VIEW_3D': return False
            # check we are not in mesh editmode
            if context.mode == 'EDIT_MESH': return False
            # make sure we have source meshes
            if not retopoflow.RetopoFlow.get_sources(): return False
            # all seems good!
            return True

        def invoke(self, context, event):
            retopoflow.RetopoFlow.create_new_target(context)
            return bpy.ops.cgcookie.retopoflow('INVOKE_DEFAULT')

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_NewTarget_Active(Operator):
        """Create new target object+mesh at the active source and start RetopoFlow"""
        bl_idname = "cgcookie.retopoflow_newtarget_active"
        bl_label = "RF: New target at Active"
        bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nCreate new target mesh based on the active source and start RetopoFlow"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

        @classmethod
        def poll(cls, context):
            if not context.region or context.region.type != 'WINDOW': return False
            if not context.space_data or context.space_data.type != 'VIEW_3D': return False
            # check we are not in mesh editmode
            if context.mode == 'EDIT_MESH': return False
            # make sure we have source meshes
            if not retopoflow.RetopoFlow.get_sources(): return False
            o = get_active_object()
            if not o: return False
            if not retopoflow.RetopoFlow.is_valid_source(o, test_poly_count=False): return False
            # all seems good!
            return True

        def invoke(self, context, event):
            o = get_active_object()
            retopoflow.RetopoFlow.create_new_target(context, matrix_world=o.matrix_world)
            return bpy.ops.cgcookie.retopoflow('INVOKE_DEFAULT')

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_Continue_Active(Operator):
        """Continue with active target object+mesh and start RetopoFlow"""
        bl_idname = "cgcookie.retopoflow_continue_active"
        bl_label = "RF: Continue with Active Target"
        bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nContinue editing with active target"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

        @classmethod
        def poll(cls, context):
            if not context.region or context.region.type != 'WINDOW': return False
            if not context.space_data or context.space_data.type != 'VIEW_3D': return False
            # check we are not in mesh editmode
            if context.mode != 'OBJECT': return False
            # make sure we have source meshes
            if not retopoflow.RetopoFlow.get_sources(ignore_active=True): return False
            o = get_active_object()
            if not o: return False
            if not retopoflow.RetopoFlow.is_valid_target(o, ignore_edit_mode=True): return False
            # all seems good!
            return True

        def invoke(self, context, event):
            bpy.ops.object.mode_set(mode='EDIT')
            # o = get_active_object()
            # retopoflow.RetopoFlow.create_new_target(context, matrix_world=o.matrix_world)
            return bpy.ops.cgcookie.retopoflow('INVOKE_DEFAULT')

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_LastTool(retopoflow.RetopoFlow):
        """Start RetopoFlow"""
        bl_idname = "cgcookie.retopoflow"
        bl_label = "Start RetopoFlow"
        bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nStart with last used tool"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_Warnings(retopoflow.RetopoFlow):
        """Start RetopoFlow"""
        bl_idname = "cgcookie.retopoflow_warnings"
        bl_label = "Start RetopoFlow (with warnings)"
        bl_description = "\nWARNINGS were detected!\n\nA suite of retopology tools for Blender through a unified retopology mode.\nStart with last used tool"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    def VIEW3D_OT_RetopoFlow_Tool_Factory(rftool):
        name = rftool.name
        description = rftool.description
        class VIEW3D_OT_RetopoFlow_Tool(retopoflow.RetopoFlow):
            """Start RetopoFlow with a specific tool"""
            bl_idname = f'cgcookie.retopoflow_{name.lower()}'
            bl_label = f'RF: {name}'
            bl_description = f'A suite of retopology tools for Blender through a unified retopology mode.\nStart with {name}: {description}'
            bl_space_type = "VIEW_3D"
            bl_region_type = "TOOLS"
            bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}
            rf_starting_tool = name
            icon_id = rftool.icon_id
        # just in case: remove spaces, so that class name is proper
        VIEW3D_OT_RetopoFlow_Tool.__name__ = f'VIEW3D_OT_RetopoFlow_{name.replace(" ", "")}'
        return VIEW3D_OT_RetopoFlow_Tool
    RF_tool_classes = [
        VIEW3D_OT_RetopoFlow_Tool_Factory(rftool)
        for rftool in RFTool.registry
    ]
    add_to_registry(RF_tool_classes)


if import_succeeded:
    '''
    create operator for recovering auto save
    '''

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_RecoverOpen(Operator):
        bl_idname = 'cgcookie.retopoflow_recover_open'
        bl_label = 'Recover: Open Last Auto Save'
        bl_description = 'Recover by opening last file automatically saved by RetopoFlow'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'TOOLS'
        bl_options = set()
        rf_icon = 'rf_recover_icon'

        @classmethod
        def poll(cls, context):
            return retopoflow.RetopoFlow.has_auto_save()
        def invoke(self, context, event):
            return self.execute(context)
        def execute(self, context):
            retopoflow.RetopoFlow.recover_auto_save()
            return {'FINISHED'}

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_RecoverFolder(Operator):
        bl_idname = 'cgcookie.retopoflow_recover_folder'
        bl_label = 'Recover: Open Folder With Last Auto Save'
        bl_description = 'Open folder containing last file automatically saved by RetopoFlow'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'TOOLS'
        bl_options = set()
        rf_icon = 'rf_recover_icon'
        # FILE_FOLDER

        @classmethod
        def poll(cls, context):
            return retopoflow.RetopoFlow.has_auto_save()
        def invoke(self, context, event):
            return self.execute(context)
        def execute(self, context):
            filename = retopoflow.RetopoFlow.get_auto_save_filename()
            bpy.ops.wm.path_open(filepath=os.path.dirname(filename))
            return {'FINISHED'}

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_RecoverDelete(Operator):
        bl_idname = 'cgcookie.retopoflow_recover_delete'
        bl_label = 'Permanently Delete Last Auto Save'
        bl_description = 'Delete last file automatically saved by RetopoFlow'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'TOOLS'
        bl_options = set()
        rf_icon = 'rf_recover_icon'

        @classmethod
        def poll(cls, context):
            return retopoflow.RetopoFlow.has_auto_save()
        def invoke(self, context, event):
            return context.window_manager.invoke_confirm(self, event)
            # return self.execute(context)
        def execute(self, context):
            retopoflow.RetopoFlow.delete_auto_save()
            return {'FINISHED'}

    @add_to_registry
    class VIEW3D_OT_RetopoFlow_RecoverRevert(Operator):
        bl_idname = 'cgcookie.retopoflow_recover_finish'
        bl_label = 'Recover: Finish Auto Save Recovery'
        bl_description = 'Finish recovering open file'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'TOOLS'
        bl_options = set()
        rf_icon = 'rf_recover_icon'

        @classmethod
        def poll(cls, context):
            return retopoflow.RetopoFlow.can_recover()
        def invoke(self, context, event):
            return self.execute(context)
        def execute(self, context):
            retopoflow.RetopoFlow.recovery_revert()
            return {'FINISHED'}


if import_succeeded:
    '''
    create panel for showing tools in Blender
    '''

    # some common checker fns
    def has_sources(context):
        return retopoflow.RetopoFlow.has_valid_source()
    def is_editing_target(context):
        obj = context.active_object
        mode_string = context.mode
        edit_object = context.edit_object
        gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}
        return not gp_edit and edit_object and mode_string == 'EDIT_MESH'
    def are_sources_too_big(context):
        # take a look at https://github.com/CoDEmanX/blend_stats/blob/master/blend_stats.py#L98
        total = 0
        for src in retopoflow.RetopoFlow.get_sources():
            total += len(src.data.polygons)
        m = convert_numstr_num(options['warning max sources'])
        return total > m
    def is_target_too_big(context):
        # take a look at https://github.com/CoDEmanX/blend_stats/blob/master/blend_stats.py#L98
        tar = retopoflow.RetopoFlow.get_target()
        if not tar: return False
        m = convert_numstr_num(options['warning max target'])
        return len(tar.data.polygons) > m
    def multiple_3dviews(context):
        views = [area for area in context.window.screen.areas if area.type == 'VIEW_3D']
        return len(views) > 1
    def is_local_view(context):
        return context.space_data.local_view is not None
    def in_quadview(context):
        for area in context.window.screen.areas:
            if area.type != 'VIEW_3D': continue
            for space in area.spaces:
                if space.type != 'VIEW_3D': continue
                if bool(space.region_quadviews): return True
        return False
    def is_addon_folder_valid(context):
        # remove .retopoflow
        if __package__.startswith('bl_ext'): return True
        path = re.sub(r'\.retopoflow$', '', __package__)
        bad_chars = set(re.sub(r'[a-zA-Z0-9_]', '', path))
        if not bad_chars: return True
        # print(f'Bad characters found in add-on: {bad_chars}')
        return False


    rf_label_extra = " (?)"
    if       configoptions.retopoflow_product['git version']:     rf_label_extra = " (git)"
    elif not configoptions.retopoflow_product['cgcookie built']:  rf_label_extra = " (self)"
    elif     configoptions.retopoflow_product['github']:          rf_label_extra = " (github)"
    elif     configoptions.retopoflow_product['blender market']:  rf_label_extra = ""


    expand_help_op = create_toggle_operator(
        'expand_help',
        'Expand Help and Support',
        'Expand Help and Support Panel',
        BoundBool('''options['expand help panel']'''),
    )
    expand_advanced_op = create_toggle_operator(
        'expand_advanced',
        'Expand Advanced',
        'Expand Advanced RetopoFlow Panel',
        BoundBool('''options['expand advanced panel']'''),
    )

    @add_to_registry
    class VIEW3D_PT_RetopoFlow(Panel):
        """RetopoFlow Blender Menu"""
        bl_label = 'RetopoFlow'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        # bl_ui_units_x = 12

        @staticmethod
        def draw_popover(self, context):
            if retopoflow.RetopoFlow.instance: return
            if CookieCutter.is_running: return
            if context.mode == 'EDIT_MESH' or context.mode == 'OBJECT':
                self.layout.separator()
                if is_editing_target(context):
                    if VIEW3D_PT_RetopoFlow_Warnings.has_warnings(context):
                        # self.layout.operator('cgcookie.retopoflow_warnings', text="", icon='ERROR')
                        pass
                    else:
                        self.layout.operator('cgcookie.retopoflow', text="", icon='MOD_DATA_TRANSFER')
                if cookiecutter.is_broken:
                    self.layout.popover('VIEW3D_PT_RetopoFlow', text='RetopoFlow BROKEN')
                else:
                    self.layout.popover('VIEW3D_PT_RetopoFlow')

        def draw_rf_version(self, context, layout):
            row = layout.row()
            row.label(text=f'RetopoFlow {configoptions.retopoflow_product["version"]}{rf_label_extra}')
            if cookiecutter.is_broken:
                row.label(text=f'BROKEN')

        def draw_start_edit(self, context, layout):
            if is_editing_target(context):
                if False:
                    # currently editing target, so show RF tools
                    for c in RF_tool_classes:
                        layout.operator(c.bl_idname, text=c.rf_starting_tool, icon_value=c.icon_id)
                else:
                    col = layout.column(align=True)
                    col.operator('cgcookie.retopoflow')

                    buttons = col.grid_flow(
                        row_major=True,
                        columns=int(len(RF_tool_classes) / 2),
                        even_columns=True, even_rows=True,
                        align=True,
                    )
                    for c in RF_tool_classes:
                        buttons.operator(c.bl_idname, text='', icon_value=c.icon_id)

        def draw_start_object(self, context, layout):
            if not is_editing_target(context):
                row = layout.row(align=True)
                col = row.column()
                col.label(text='Start New')
                col = row.column()
                col.operator('cgcookie.retopoflow_newtarget_cursor', text='From Cursor', icon='PIVOT_CURSOR')
                col.operator('cgcookie.retopoflow_newtarget_active', text='From Active', icon='OBJECT_DATA')

                row = layout.row(align=True)
                col = row.column()
                col.label(text='Continue')
                col = row.column()
                col.operator('cgcookie.retopoflow_continue_active', text='Edit Active', icon='MESH_DATA') # icon='EDITMODE_HLT' or 'MOD_DATA_TRANSFER'

        def draw_help(self, context, layout):
            row = layout.row(align=True)
            row.label(text='Help and Support')
            icon = 'TRIA_UP' if options['expand help panel'] else 'TRIA_DOWN'
            row.operator(expand_help_op.bl_idname, text='', icon=icon, emboss=False, depress=options['expand help panel'])

            if not options['expand help panel']: return
            
            box = layout.box()

            col = box.column(align=True)

            row = col.row(align=True)
            row.label(text='Quick Start Guide')
            row.operator('cgcookie.retopoflow_help_quickstartguide', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_quickstartguide', text='', icon='URL')

            row = col.row(align=True)
            row.label(text='Welcome Message')
            row.operator('cgcookie.retopoflow_help_welcomemessage', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_welcomemessage', text='', icon='URL')

            row = col.row(align=True)
            row.label(text='Table of Contents')
            row.operator('cgcookie.retopoflow_help_tableofcontents', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_tableofcontents', text='', icon='URL')

            row = col.row(align=True)
            row.label(text='FAQ')
            row.operator('cgcookie.retopoflow_help_faq', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_faq', text='', icon='URL')

            # col.separator()
            # col.operator('cgcookie.retopoflow_web_online_main', icon='HELP')

            col.separator()
            col.operator('cgcookie.retopoflow_web_blendermarket', icon_value=BlenderIcon.icon_id('blendermarket.png')) # icon='URL'

        def draw_advanced(self, context, layout):
            row = layout.row(align=True)
            row.label(text='Advanced')
            icon = 'TRIA_UP' if options['expand advanced panel'] else 'TRIA_DOWN'
            row.operator(expand_advanced_op.bl_idname, text='', icon=icon, emboss=False, depress=options['expand advanced panel'])

            if not options['expand advanced panel']: return
            box = layout.box()

            # KEYMAP EDITOR
            row = box.row(align=True)
            row.label(text='Keymap Editor')
            row.operator('cgcookie.retopoflow_keymapeditor',        text='', icon='PREFERENCES')
            row.operator('cgcookie.retopoflow_help_keymapeditor',   text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_keymapeditor', text='', icon='URL')

            # DEEP DEBUGGER
            if DeepDebug.can_be_enabled():
                col = box.column()
                row = col.row(align=True)
                row.label(text='Deep Debugging')
                if DeepDebug.is_enabled():
                    row.operator('cgcookie.retopoflow_disabledebugging', text='', icon='CHECKBOX_HLT') #'X')
                else:
                    row.operator('cgcookie.retopoflow_enabledebugging', text='', icon='CHECKBOX_DEHLT') #'X')
                row.operator('cgcookie.retopoflow_help_debugging',      text='', icon='HELP')
                row.operator('cgcookie.retopoflow_online_debugging',    text='', icon='URL')
                if DeepDebug.needs_restart():
                    col.label(text='Restart Blender to finish', icon='BLENDER')
                elif DeepDebug.is_enabled():
                    row = col.row(align=True)
                    row.label(text='', icon='DOT')
                    row.operator('cgcookie.retopoflow_opendebugging',    text='Open', icon='TEXT')
                elif DeepDebug.path_debug_backup().exists():
                    row = col.row(align=True)
                    row.label(text='', icon='DOT')
                    row.operator('cgcookie.retopoflow_opendebugging',    text='Open', icon='TEXT')
                    row.operator('cgcookie.retopoflow_cleardebugging',   text='Clear', icon='X')

            # ADDON UPDATER
            col = box.column(align=True)
            row = col.row(align=True)
            row.label(text='Updater')
            if configoptions.retopoflow_product['git version']:
                col.label(text='Use Git to Pull latest updates', icon='DOT')
            else:
                row.operator('cgcookie.retopoflow_updater_check_now',    text='', icon='FILE_REFRESH')
                row.operator('cgcookie.retopoflow_updater_update_now',   text='', icon="IMPORT")
                row.operator('cgcookie.retopoflow_updater',              text='', icon='SETTINGS')
                row.operator('cgcookie.retopoflow_help_updatersystem',   text='', icon='HELP')
                row.operator('cgcookie.retopoflow_online_updatersystem', text='', icon='URL')


        def draw(self, context):
            layout = self.layout

            self.draw_rf_version(context, layout)
            layout.separator()
            self.draw_start_edit(context, layout)
            self.draw_start_object(context, layout)
            layout.separator()
            self.draw_help(context, layout)
            layout.separator()
            self.draw_advanced(context, layout)

 
    @add_to_registry
    class VIEW3D_PT_RetopoFlow_Warnings(Panel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        bl_parent_id = 'VIEW3D_PT_RetopoFlow'
        bl_label = 'Warnings'

        debug_all_warnings = False

        @classmethod
        def has_warnings(cls, context):
            return any(v for v in cls.get_warnings(context).values())

        @classmethod
        def get_warnings(cls, context):
            minv, maxv = Hive.get_version('blender minimum version'), Hive.get_version('blender maximum version')
            sources = retopoflow.RetopoFlow.get_sources()
            target = retopoflow.RetopoFlow.get_target()

            warnings = {
                # install checks
                'install: invalid add-on folder':             not is_addon_folder_valid(context),
                'install: unexpected runtime error occurred': cookiecutter.is_broken,
                'install: invalid version':                   bpy.app.version < minv or (maxv and bpy.app.version > maxv),

                # setup checks
                'setup: local view':                       is_local_view(context),
                'setup: no sources':                       not sources,
                'setup: source has non-invertible matrix': not all(has_inverse(source.matrix_local) for source in sources),
                'setup: source has armature':              any(mod.type == 'ARMATURE' and mod.object and mod.show_viewport for source in sources for mod in source.modifiers),
                'setup: no target':                        is_editing_target(context) and not target,
                'setup: target has non-invertible matrix': target and not has_inverse(target.matrix_local),

                # performance checks
                'performance: target too big': is_target_too_big(context),
                'performance: source too big': are_sources_too_big(context),

                # layout checks
                'layout: multiple 3d views':        multiple_3dviews(context),
                'layout: in quad view':             in_quadview(context),
                'layout: view is locked to cursor': any(space.lock_cursor for space in context.area.spaces if space.type == 'VIEW_3D'),
                'layout: view is locked to object': any(space.lock_object for space in context.area.spaces if space.type == 'VIEW_3D'),

                # auto save / unsaved checks
                'save: auto save is disabled': not retopoflow.RetopoFlow.get_auto_save_settings(context)['auto save'],
                'save: unsaved blender file':  not retopoflow.RetopoFlow.get_auto_save_settings(context)['saved'],
                'save: can recover auto save': retopoflow.RetopoFlow.can_recover(),                                         # user directly opened an auto save file
                'save: has auto save':         retopoflow.RetopoFlow.has_auto_save(),                                       # auto save file detected
            }

            return warnings if not cls.debug_all_warnings else { k: True for k in warnings }

        @classmethod
        def poll(cls, context):
            return cls.has_warnings(context)

        def draw(self, context):
            layout = self.layout

            class WarningSection:
                _boxes = {}
                ''' creates exactly one warning subbox per label _only_ when needed '''
                def __init__(self, label):
                    self._label = label
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc_val, exc_tb):
                    pass
                def subbox(self):
                    if self._label not in WarningSection._boxes:
                        box = layout.box().column(align=True)
                        box.label(text=self._label, icon='ERROR')
                        WarningSection._boxes[self._label] = box
                    return WarningSection._boxes[self._label]
                def label(self, *args, **kwargs):
                    box = self.subbox()
                    box.label(*args, **kwargs)
                    return box

            warnings = self.get_warnings(context)

            with WarningSection('Installation') as section:
                if warnings['install: invalid add-on folder']:
                    section.label(text=f'Invalid add-on folder name', icon='DOT')
                if warnings['install: unexpected runtime error occurred']:
                    section.label(text=f'Unexpected runtime error', icon='DOT')
                if warnings['install: invalid version']:
                    box = section.subbox()
                    def neatver(v): return f'{v[0]}.{v[1]}'
                    box.label(text=f'Incorrect versions', icon='DOT')
                    tab = box.row(align=True)
                    tab.label(icon='BLANK1')
                    minv, maxv = Hive.get_version('blender minimum version'), Hive.get_version('blender maximum version')
                    if not maxv:
                        tab.label(text=f'Require Blender {neatver(minv)}+', icon='BLENDER')
                    else:
                        tab.label(text=f'Require Blender {neatver(minv)}--{neatver(maxv)}', icon='BLENDER')

            with WarningSection('Setup Issue') as section:
                if warnings['setup: local view']:
                    section.label(text=f'Currently in local view', icon='DOT')
                if warnings['setup: no sources']:
                    section.label(text=f'No sources detected', icon='DOT')
                if warnings['setup: source has non-invertible matrix']:
                    section.label(text=f'A source has non-invertible matrix', icon='DOT')
                if warnings['setup: source has armature']:
                    section.label(text=f'A source has an armature', icon='DOT')
                if warnings['setup: no target']:
                    section.label(text=f'No target detected', icon='DOT')
                if warnings['setup: target has non-invertible matrix']:
                    section.label(text=f'Target has non-invertible matrix', icon='DOT')

            with WarningSection('Performance Issue') as section:
                if warnings['performance: target too big']:
                    section.label(text=f'Target is too large (>{options["warning max target"]})', icon='DOT')
                if warnings['performance: source too big']:
                    section.label(text=f'Sources are too large (>{options["warning max sources"]})', icon='DOT')

            with WarningSection('Layout Issue') as section:
                if warnings['layout: multiple 3d views']:
                    section.label(text='Multiple 3D Views', icon='DOT')
                if warnings['layout: in quad view']:
                    section.label(text='Quad View will be disabled', icon='DOT')
                if warnings['layout: view is locked to cursor']:
                    section.label(text='View is locked to cursor', icon='DOT')
                if warnings['layout: view is locked to object']:
                    section.label(text='View is locked to object', icon='DOT')

            with WarningSection('Auto Save / Save') as section:
                if warnings['save: auto save is disabled']:
                    section.label(text='Auto Save is disabled', icon='DOT')
                if warnings['save: unsaved blender file']:
                    section.label(text='Unsaved Blender file', icon='DOT')
                if warnings['save: can recover auto save']:
                    box = section.subbox()
                    box.label(text=f'Auto Save file opened', icon='DOT')
                    tab = box.row(align=True)
                    tab.label(icon='BLANK1')
                    tab.operator('cgcookie.retopoflow_recover_finish', text='Finish Auto Save Recovery', icon='RECOVER_LAST')
                if warnings['save: has auto save']:
                    box = section.subbox()
                    box.label(text=f'Found RetopoFlow auto save', icon='DOT')

                    tab = box.row(align=True)
                    tab.label(icon='BLANK1')
                    tab.label(text=bpy.path.basename(retopoflow.RetopoFlow.get_auto_save_filename()))

                    tab = box.row(align=True)
                    tab.label(icon='BLANK1')
                    col = tab.column(align=True)
                    col.operator('cgcookie.retopoflow_recover_open',   text='Open',        icon='RECOVER_LAST')
                    col.operator('cgcookie.retopoflow_recover_folder', text='Open Folder', icon='FILE_FOLDER')
                    col.operator('cgcookie.retopoflow_recover_delete', text='Delete',      icon='X')

            # show button for more warning details
            row = layout.row(align=True)
            row.label(text='See warning details')
            row.operator('cgcookie.retopoflow_help_warningdetails', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_warningdetails', text='', icon='URL')
   

    """
    @add_to_registry
    class VIEW3D_PT_RetopoFlow_EditMesh(Panel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        bl_parent_id = 'VIEW3D_PT_RetopoFlow'
        bl_label = 'Continue Editing Target'

        @classmethod
        def poll(cls, context):
            return is_editing_target(context)

        def draw(self, context):
            layout = self.layout

            if False:
                # currently editing target, so show RF tools
                for c in RF_tool_classes:
                    layout.operator(c.bl_idname, text=c.rf_starting_tool, icon_value=c.icon_id)
            else:
                col = layout.column(align=True)
                col.operator('cgcookie.retopoflow')

                buttons = col.grid_flow(
                    row_major=True,
                    columns=int(len(RF_tool_classes) / 2),
                    even_columns=True, even_rows=True,
                    align=True,
                )
                for c in RF_tool_classes:
                    buttons.operator(c.bl_idname, text='', icon_value=c.icon_id)

    """
    
    """
    @add_to_registry
    class VIEW3D_PT_ReteopoFlow_ObjectMode(Panel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        bl_parent_id = 'VIEW3D_PT_RetopoFlow'
        bl_label = 'Start RetopoFlow'

        @classmethod
        def poll(cls, context):
            return not is_editing_target(context)

        def draw(self, context):
            layout = self.layout


            row = layout.row(align=True)
            row.label(text='Continue')
            row.operator('cgcookie.retopoflow_continue_active', text='Edit Active', icon='MOD_DATA_TRANSFER') # icon='EDITMODE_HLT')

            row = layout.row(align=True)
            row.label(text='New')
            row.operator('cgcookie.retopoflow_newtarget_cursor', text='Cursor', icon='ADD')
            row.operator('cgcookie.retopoflow_newtarget_active', text='Active', icon='ADD')
    """

    """
    @add_to_registry
    class VIEW3D_PT_RetopoFlow_HelpAndSupport(Panel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        bl_parent_id = 'VIEW3D_PT_RetopoFlow'
        bl_label = ''

        def draw(self, context):
            layout = self.layout

            row = layout.row(align=True)
            row.label(text='Help and Support')
            icon = 'TRIA_UP' if options['expand help panel'] else 'TRIA_DOWN'
            row.operator(expand_help_op.bl_idname, text='', icon=icon, emboss=False, depress=options['expand help panel'])

            if not options['expand help panel']: return
            
            box = layout.box()

            col = box.column(align=True)

            row = col.row(align=True)
            row.label(text='Quick Start Guide')
            row.operator('cgcookie.retopoflow_help_quickstartguide', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_quickstartguide', text='', icon='URL')

            row = col.row(align=True)
            row.label(text='Welcome Message')
            row.operator('cgcookie.retopoflow_help_welcomemessage', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_welcomemessage', text='', icon='URL')

            row = col.row(align=True)
            row.label(text='Table of Contents')
            row.operator('cgcookie.retopoflow_help_tableofcontents', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_tableofcontents', text='', icon='URL')

            row = col.row(align=True)
            row.label(text='FAQ')
            row.operator('cgcookie.retopoflow_help_faq', text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_faq', text='', icon='URL')

            # col.separator()
            # col.operator('cgcookie.retopoflow_web_online_main', icon='HELP')

            col.separator()
            col.operator('cgcookie.retopoflow_web_blendermarket', icon_value=BlenderIcon.icon_id('blendermarket.png')) # icon='URL'
    """

    """
    @add_to_registry
    class VIEW3D_PT_RetopoFlow_Advanced(Panel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        bl_parent_id = 'VIEW3D_PT_RetopoFlow'
        bl_label = ''

        def draw(self, context):
            layout = self.layout

            row = layout.row(align=True)
            row.label(text='Advanced')
            icon = 'TRIA_UP' if options['expand advanced panel'] else 'TRIA_DOWN'
            row.operator(expand_advanced_op.bl_idname, text='', icon=icon, emboss=False, depress=options['expand advanced panel'])

            if not options['expand advanced panel']: return
            box = layout.box()

            # KEYMAP EDITOR
            row = box.row(align=True)
            row.label(text='Keymap Editor')
            row.operator('cgcookie.retopoflow_keymapeditor',        text='', icon='PREFERENCES')
            row.operator('cgcookie.retopoflow_help_keymapeditor',   text='', icon='HELP')
            row.operator('cgcookie.retopoflow_online_keymapeditor', text='', icon='URL')

            # DEEP DEBUGGER
            if DeepDebug.can_be_enabled():
                col = box.column()
                row = col.row(align=True)
                row.label(text='Deep Debugging')
                if DeepDebug.is_enabled():
                    row.operator('cgcookie.retopoflow_disabledebugging', text='', icon='CHECKBOX_HLT') #'X')
                else:
                    row.operator('cgcookie.retopoflow_enabledebugging', text='', icon='CHECKBOX_DEHLT') #'X')
                row.operator('cgcookie.retopoflow_help_debugging',      text='', icon='HELP')
                row.operator('cgcookie.retopoflow_online_debugging',    text='', icon='URL')
                if DeepDebug.needs_restart():
                    col.label(text='Restart Blender to finish', icon='BLENDER')
                elif DeepDebug.is_enabled():
                    row = col.row(align=True)
                    row.label(text='', icon='DOT')
                    row.operator('cgcookie.retopoflow_opendebugging',    text='Open', icon='TEXT')
                elif DeepDebug.path_debug_backup().exists():
                    row = col.row(align=True)
                    row.label(text='', icon='DOT')
                    row.operator('cgcookie.retopoflow_opendebugging',    text='Open', icon='TEXT')
                    row.operator('cgcookie.retopoflow_cleardebugging',   text='Clear', icon='X')

            # ADDON UPDATER
            col = box.column(align=True)
            row = col.row(align=True)
            row.label(text='Updater')
            if configoptions.retopoflow_product['git version']:
                col.label(text='Use Git to Pull latest updates', icon='DOT')
            else:
                row.operator('cgcookie.retopoflow_updater_check_now',    text='', icon='FILE_REFRESH')
                row.operator('cgcookie.retopoflow_updater_update_now',   text='', icon="IMPORT")
                row.operator('cgcookie.retopoflow_updater',              text='', icon='SETTINGS')
                row.operator('cgcookie.retopoflow_help_updatersystem',   text='', icon='HELP')
                row.operator('cgcookie.retopoflow_online_updatersystem', text='', icon='URL')
    """

    """
    @add_to_registry
    class VIEW3D_PT_RetopoFlow_AutoSave(Panel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        bl_parent_id = 'VIEW3D_PT_RetopoFlow'
        bl_label = 'Auto Save
        def draw(self, context):
            layout = self.layout
            layout.operator(
                'cgcookie.retopoflow_recover_open',
                text='Open Last Auto Save',
                icon='RECOVER_LAST',
            )
            # if retopoflow.RetopoFlow.has_backup():
            #     box.label(text=options['last auto save path'])
    """
    
    """
    @add_to_registry
    class VIEW3D_PT_RetopoFlow_Updater(Panel):
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'
        bl_parent_id = 'VIEW3D_PT_RetopoFlow'
        bl_label = 'Updater
        def draw(self, context):
            layout = self.layout
            if configoptions.retopoflow_product['git version']:
                box = layout.box().column(align=True)
                box.label(text='RetopoFlow under Git control') #, icon='DOT')
                box.label(text='Use Git to Pull latest updates') #, icon='DOT')
                # col.operator('cgcookie.retopoflow_updater', text='Updater System', icon='SETTINGS')
            else:
                col = layout.column(align=True)
                col.operator('cgcookie.retopoflow_updater_check_now', text='Check for updates', icon='FILE_REFRESH')
                col.operator('cgcookie.retopoflow_updater_update_now', text='Update now', icon="IMPORT"
                col.separator()
                row = col.row(align=True)
                row.operator('cgcookie.retopoflow_updater', text='Updater System', icon='SETTINGS')
                row.operator('cgcookie.retopoflow_help_updatersystem', text='', icon='HELP')
                row.operator('cgcookie.retopoflow_online_updatersystem', text='', icon='URL')
    """


if not import_succeeded:
    '''
    importing failed.  show this to the user!
    '''

    from .addon_common.common.utils import normalize_triplequote

    @add_to_registry
    class VIEW3D_PT_RetopoFlow(Panel):
        """RetopoFlow Blender Menu"""
        bl_label = "RetopoFlow (broken)"
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'

        @staticmethod
        def draw_popover(self, context):
            self.layout.popover('VIEW3D_PT_RetopoFlow')

        def draw(self, context):
            layout = self.layout

            box = layout.box()
            box.label(text='RetopoFlow cannot start.', icon='ERROR')

            box = layout.box()
            tw_p = textwrap.TextWrapper(width=36)
            tw_ul = textwrap.TextWrapper(width=30)
            report_lines = normalize_triplequote('''
                This is likely due to an incorrect installation of the add-on.

                Please try restarting Blender.

                If that does not work, please try:

                - remove RetopoFlow from Blender,
                - restart Blender,
                - download the latest version from the Blender Market, then
                - install RetopoFlow in Blender.

                If you continue to see this error, contact us through the Blender Market Inbox, and we will work to get it fixed!
            ''')
            for paragraph in report_lines.split('\n\n'):
                lines = paragraph.split('\n')
                icons = ('NONE', 'NONE')
                tw = tw_p
                if lines[0].startswith('- '):
                    nlines = []
                    for line in lines:
                        line = line.strip()
                        if not line.startswith('- '):
                            nlines[-1] += f' {line}'
                        else:
                            nlines += [line[2:].strip()]
                    lines = nlines
                    icons = ('DOT', 'BLANK1')
                    tw = tw_ul
                col = box.column(align=True)
                for line in lines:
                    for i, l in enumerate(tw.wrap(text=line)):
                        col.label(text=l, icon=icons[0 if i==0 else 1])

            box = layout.box()
            box.operator('cgcookie.retopoflow_web_blendermarket', icon='URL')


def register():
    for cls in RF_classes: bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_editor_menus.append(VIEW3D_PT_RetopoFlow.draw_popover)

def unregister():
    if import_succeeded: ImagePreloader.quit()
    bpy.types.VIEW3D_MT_editor_menus.remove(VIEW3D_PT_RetopoFlow.draw_popover)
    for cls in reversed(RF_classes): bpy.utils.unregister_class(cls)
