'''
Copyright (C) 2021 CG Cookie
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
import time
import textwrap
import importlib
from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl
from bpy.types import Menu, Operator, Panel
from bpy_extras import object_utils
from bpy.app.handlers import persistent

# a hack to check if we're under git version control
is_git = os.path.exists(os.path.join(os.path.dirname(__file__), '.git'))
bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of retopology tools for Blender through a unified retopology mode",
    "author":      "Jonathan Denning, Jonathan Lampel, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (3, 2, 1),
    "blender":     (2, 83, 0),
    "location":    "View 3D > Header",
    "warning":     "Alpha",                   # used for warning icon and text in addons panel
    # "warning":     "Beta",
    # "warning":     "Release Candidate 1",
    # "warning":     "Release Candidate 2",
    "doc_url":     "https://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View",
}

import_succeeded = False

if bpy.app.background:
    print(f'RetopoFlow: Blender is running in background; skipping any RF initializations')
else:
    try:
        if "retopoflow" in locals():
            print('RetopoFlow: RELOADING!')
            # reloading RF modules
            importlib.reload(retopoflow)
            importlib.reload(helpsystem)
            importlib.reload(updatersystem)
            importlib.reload(keymapsystem)
            importlib.reload(configoptions)
            importlib.reload(updater)
            importlib.reload(rftool)
        else:
            print('RetopoFlow: Initial load')
            from .retopoflow import retopoflow
            from .retopoflow import helpsystem
            from .retopoflow import updatersystem
            from .retopoflow import keymapsystem
            from .config import options as configoptions
            from .retopoflow import updater
            from .addon_common.common.maths import convert_numstr_num
            from .addon_common.common.blender import get_active_object
            from .retopoflow import rftool
        options = configoptions.options
        retopoflow_version = configoptions.retopoflow_version
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


if import_succeeded:
    '''
    create operators for viewing RetopoFlow help documents
    '''

    class VIEW3D_OT_RetopoFlow_Help_QuickStart(helpsystem.RetopoFlow_OpenHelpSystem):
        """Open RetopoFlow Quick Start Guide"""
        bl_idname = "cgcookie.retopoflow_help_quickstart"
        bl_label = "Quick Start Guide"
        bl_description = "Open RetopoFlow Quick Start Guide"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        rf_startdoc = 'quick_start.md'
    RF_classes += [VIEW3D_OT_RetopoFlow_Help_QuickStart]

    class VIEW3D_OT_RetopoFlow_Help_Welcome(helpsystem.RetopoFlow_OpenHelpSystem):
        """Open RetopoFlow Welcome"""
        bl_idname = "cgcookie.retopoflow_help_welcome"
        bl_label = "Welcome Message"
        bl_description = "Open RetopoFlow Welcome Message"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        rf_startdoc = 'welcome.md'
    RF_classes += [VIEW3D_OT_RetopoFlow_Help_Welcome]

    class VIEW3D_OT_RetopoFlow_Help_TableOfContents(helpsystem.RetopoFlow_OpenHelpSystem):
        """Open RetopoFlow Table of Contents"""
        bl_idname = "cgcookie.retopoflow_help_tableofcontents"
        bl_label = "Table of Contents"
        bl_description = "Open RetopoFlow Table of Contents"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        rf_startdoc = 'table_of_contents.md'
    RF_classes += [VIEW3D_OT_RetopoFlow_Help_TableOfContents]

    class VIEW3D_OT_RetopoFlow_Help_FAQ(helpsystem.RetopoFlow_OpenHelpSystem):
        """Open RetopoFlow Table of Contents"""
        bl_idname = "cgcookie.retopoflow_help_faq"
        bl_label = "RetopoFlow FAQ"
        bl_description = "Open RetopoFlow Frequently Asked Questions"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        rf_startdoc = 'faq.md'
    RF_classes += [VIEW3D_OT_RetopoFlow_Help_FAQ]

    class VIEW3D_OT_RetopoFlow_Help_Warnings(helpsystem.RetopoFlow_OpenHelpSystem):
        """Open RetopoFlow Warnings Document"""
        bl_idname = "cgcookie.retopoflow_help_warnings"
        bl_label = "See details on these warnings"
        bl_description = "See details on the RetopoFlow warnings"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        rf_startdoc = 'warnings.md'
    RF_classes += [VIEW3D_OT_RetopoFlow_Help_Warnings]

    class VIEW3D_OT_RetopoFlow_UpdaterSystem(updatersystem.RetopoFlow_OpenUpdaterSystem):
        """Open RetopoFlow Updater System"""
        bl_idname = "cgcookie.retopoflow_updater"
        bl_label = "Updater"
        bl_description = "Open RetopoFlow Updater"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
    RF_classes += [VIEW3D_OT_RetopoFlow_UpdaterSystem]

    class VIEW3D_OT_RetopoFlow_KeymapSystem(keymapsystem.RetopoFlow_OpenKeymapSystem):
        """Open RetopoFlow Keymap Editor"""
        bl_idname = "cgcookie.retopoflow_keymap"
        bl_label = "Keymap Editor"
        bl_description = "Open RetopoFlow Keymap Editor"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
    RF_classes += [VIEW3D_OT_RetopoFlow_KeymapSystem]

    class VIEW3D_OT_RetopoFlow_Help_Updater(helpsystem.RetopoFlow_OpenHelpSystem):
        """Open RetopoFlow Updater Help"""
        bl_idname = "cgcookie.retopoflow_help_updater"
        bl_label = "Updater Help"
        bl_description = "Open RetopoFlow Updater Help"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        rf_startdoc = 'addon_updater.md'
    RF_classes += [VIEW3D_OT_RetopoFlow_Help_Updater]

    class VIEW3D_OT_RetopoFlow_Help_Keymap(helpsystem.RetopoFlow_OpenHelpSystem):
        """Open RetopoFlow Keymap Editor Help"""
        bl_idname = "cgcookie.retopoflow_help_keymap"
        bl_label = "Keymap Editor Help"
        bl_description = "Open RetopoFlow Keymap Editor Help"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()
        rf_startdoc = 'keymap_editor.md'
    RF_classes += [VIEW3D_OT_RetopoFlow_Help_Keymap]

    if options['preload help images']: retopoflow.preload_help_images()



class VIEW3D_OT_RetopoFlow_BlenderMarket(Operator):
    bl_idname = 'cgcookie.retopoflow_blendermarket'
    bl_label = 'Visit Blender Market'
    bl_description = 'Open the Blender Market RetopoFlow page'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    def invoke(self, context, event):
        bpy.ops.wm.url_open(url='https://blendermarket.com/products/retopoflow')
        return {'FINISHED'}
RF_classes += [VIEW3D_OT_RetopoFlow_BlenderMarket]

class VIEW3D_OT_RetopoFlow_Help_Online(Operator):
    bl_idname = 'cgcookie.retopoflow_help_online'
    bl_label = 'Online Documentation'
    bl_description = 'Open RetopoFlow Online Documentation'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_options = set()

    def invoke(self, context, event):
        bpy.ops.wm.url_open(url='https://docs.retopoflow.com')
        return {'FINISHED'}
RF_classes += [VIEW3D_OT_RetopoFlow_Help_Online]



if import_succeeded:
    '''
    create operators to start RetopoFlow
    '''

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
            auto_edit_mode = bpy.context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
            bpy.context.preferences.edit.use_enter_edit_mode = False
            for o in bpy.data.objects: o.select_set(False)
            mesh = bpy.data.meshes.new('RetopoFlow')
            obj = object_utils.object_data_add(context, mesh, name='RetopoFlow')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode
            return bpy.ops.cgcookie.retopoflow('INVOKE_DEFAULT')
    RF_classes += [VIEW3D_OT_RetopoFlow_NewTarget_Cursor]

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
            active = get_active_object()
            auto_edit_mode = bpy.context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
            bpy.context.preferences.edit.use_enter_edit_mode = False
            for o in bpy.data.objects: o.select_set(False)
            mesh = bpy.data.meshes.new('RetopoFlow')
            obj = object_utils.object_data_add(context, mesh, name='RetopoFlow')
            obj.select_set(True)
            context.view_layer.objects.active = obj
            obj.matrix_world = active.matrix_world
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode
            return bpy.ops.cgcookie.retopoflow('INVOKE_DEFAULT')
    RF_classes += [VIEW3D_OT_RetopoFlow_NewTarget_Active]

    class VIEW3D_OT_RetopoFlow_LastTool(retopoflow.RetopoFlow):
        """Start RetopoFlow"""
        bl_idname = "cgcookie.retopoflow"
        bl_label = "Start RetopoFlow"
        bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nStart with last used tool"
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}
    RF_classes += [VIEW3D_OT_RetopoFlow_LastTool]

    def VIEW3D_OT_RetopoFlow_Tool_Factory(rftool):
        name = rftool.name
        description = rftool.description
        class VIEW3D_OT_RetopoFlow_Tool(retopoflow.RetopoFlow):
            """Start RetopoFlow with a specific tool"""
            bl_idname = "cgcookie.retopoflow_%s" % name.lower()
            bl_label = "RF: %s" % name
            bl_description = "A suite of retopology tools for Blender through a unified retopology mode.\nStart with %s: %s" % (name, description)
            bl_space_type = "VIEW_3D"
            bl_region_type = "TOOLS"
            bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}
            rf_starting_tool = name
        # just in case: remove spaces, so that class name is proper
        VIEW3D_OT_RetopoFlow_Tool.__name__ = 'VIEW3D_OT_RetopoFlow_%s' % name.replace(' ', '')
        return VIEW3D_OT_RetopoFlow_Tool
    RF_tool_classes = [
        VIEW3D_OT_RetopoFlow_Tool_Factory(rftool)
        for rftool in RFTool.registry
    ]
    RF_classes += RF_tool_classes


if import_succeeded:
    '''
    create operator for recovering auto save
    '''

    class VIEW3D_OT_RetopoFlow_Recover(Operator):
        bl_idname = 'cgcookie.retopoflow_recover'
        bl_label = 'Recover Auto Save'
        bl_description = 'Recover from RetopoFlow auto save'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'TOOLS'
        bl_options = set()
        rf_icon = 'rf_recover_icon'

        @classmethod
        def poll(cls, context):
            return retopoflow.RetopoFlow.has_backup()

        def invoke(self, context, event):
            global perform_backup_recovery
            retopoflow.RetopoFlow.backup_recover()
            return {'FINISHED'}
    RF_classes += [VIEW3D_OT_RetopoFlow_Recover]


if import_succeeded:
    '''
    create panel for showing tools in Blender
    '''

    class VIEW3D_PT_RetopoFlow(Panel):
        """RetopoFlow Blender Menu"""
        bl_label = f'RetopoFlow {retopoflow_version}{" (git)" if configoptions.retopoflow_version_git else " (self)" if not configoptions.retopoflow_cgcookie_built else ""}'
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'

        @staticmethod
        def has_sources(context):
            return retopoflow.RetopoFlow.has_valid_source()

        @staticmethod
        def is_editing_target(context):
            obj = context.active_object
            mode_string = context.mode
            edit_object = context.edit_object
            gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}
            return not gp_edit and edit_object and mode_string == 'EDIT_MESH'

        @staticmethod
        def are_sources_too_big(context):
            # take a look at https://github.com/CoDEmanX/blend_stats/blob/master/blend_stats.py#L98
            total = 0
            for src in retopoflow.RetopoFlow.get_sources():
                total += len(src.data.polygons)
            m = convert_numstr_num(options['warning max sources'])
            return total > m

        @staticmethod
        def is_target_too_big(context):
            # take a look at https://github.com/CoDEmanX/blend_stats/blob/master/blend_stats.py#L98
            tar = retopoflow.RetopoFlow.get_target()
            if not tar: return False
            m = convert_numstr_num(options['warning max target'])
            return len(tar.data.polygons) > m

        @staticmethod
        def multiple_3dviews(context):
            views = [area for area in context.window.screen.areas if area.type == 'VIEW_3D']
            return len(views) > 1

        @staticmethod
        def in_quadview(context):
            for area in context.window.screen.areas:
                if area.type != 'VIEW_3D': continue
                for space in area.spaces:
                    if space.type != 'VIEW_3D': continue
                    if len(space.region_quadviews) > 0: return True
            return False

        def draw(self, context):
            layout = self.layout

            warningbox = None
            warningsubboxes = {}
            def add_warning():
                nonlocal warningbox, layout
                if not warningbox:
                    warningbox = layout.box()
                    warningbox.label(text='Warnings', icon='ERROR')
                return warningbox.box()
            def add_warning_subbox(label):
                nonlocal warningsubboxes
                if label not in warningsubboxes:
                    box = add_warning().column()
                    box.label(text=label)
                    warningsubboxes[label] = box
                return warningsubboxes[label]

            # SETUP CHECKS
            if not retopoflow.RetopoFlow.get_sources():
                box = add_warning_subbox('Setup Issue')
                box.label(text=f'No sources detected', icon='DOT')
            if VIEW3D_PT_RetopoFlow.is_editing_target(context) and not retopoflow.RetopoFlow.get_target():
                box = add_warning_subbox('Setup Issue')
                box.label(text=f'No target detected', icon='DOT')

            # PERFORMANCE CHECKS
            if VIEW3D_PT_RetopoFlow.is_target_too_big(context):
                box = add_warning_subbox('Performance Issue')
                box.label(text=f'Target is too large (>{options["warning max target"]})', icon='DOT')
            if VIEW3D_PT_RetopoFlow.are_sources_too_big(context):
                box = add_warning_subbox('Performance Issue')
                box.label(text=f'Sources are too large (>{options["warning max sources"]})', icon='DOT')

            # LAYOUT
            if VIEW3D_PT_RetopoFlow.multiple_3dviews(context):
                box = add_warning_subbox('Layout Issue')
                box.label(text='Multiple 3D Views', icon='DOT')
            if VIEW3D_PT_RetopoFlow.in_quadview(context):
                box = add_warning_subbox('Layout Issue')
                box.label(text='Quad View will be disabled', icon='DOT')
            lock_cursor = any(
                space.lock_cursor
                for space in context.area.spaces
                if space.type == 'VIEW_3D'
            )
            if lock_cursor:
                box = add_warning_subbox('Layout Issue')
                box.label(text='View is locked to cursor', icon='DOT')
            lock_object = any(
                space.lock_object
                for space in context.area.spaces
                if space.type == 'VIEW_3D'
            )
            if lock_object:
                box = add_warning_subbox('Layout Issue')
                box.label(text='View is locked to object', icon='DOT')

            # AUTO SAVE / UNSAVED
            if not retopoflow.RetopoFlow.get_auto_save_settings(context)['auto save']:
                box = add_warning_subbox('Auto Save / Save')
                box.label(text='Auto Save is disabled', icon='DOT')
            if not retopoflow.RetopoFlow.get_auto_save_settings(context)['saved']:
                box = add_warning_subbox('Auto Save / Save')
                box.label(text='Unsaved Blender file', icon='DOT')

            # show button for more warning details
            if warningbox:
                warningbox.operator('cgcookie.retopoflow_help_warnings', icon='HELP')

            box = layout.box()
            if VIEW3D_PT_RetopoFlow.is_editing_target(context):
                # currently editing target, so show RF tools
                box.label(text='Start RetopoFlow with Edit Mesh')
                col = box.column()
                for c in RF_tool_classes:
                    col.operator(c.bl_idname)
            else:
                box.label(text='Create New RetopoFlow Target')
                col = box.column()
                # currently not editing target, so show operator to create new target
                col.operator('cgcookie.retopoflow_newtarget_cursor', icon='ADD') #'ORIENTATION_CURSOR')
                col.operator('cgcookie.retopoflow_newtarget_active', icon='ADD') #'OBJECT_ORIGIN')

            box = layout.box()
            box.label(text='Help and Support') # , icon='QUESTION')
            col = box.column()
            col.operator('cgcookie.retopoflow_help_quickstart', icon='HELP')
            col.operator('cgcookie.retopoflow_help_welcome', icon='HELP')
            col.operator('cgcookie.retopoflow_help_tableofcontents', icon='HELP')
            col.operator('cgcookie.retopoflow_help_faq', icon='HELP')

            col = box.column()
            col.operator('cgcookie.retopoflow_help_online', icon='HELP')

            col = box.column()
            col.operator('cgcookie.retopoflow_blendermarket', icon='URL')

            box = layout.box()
            box.label(text='Config')
            box.operator('cgcookie.retopoflow_keymap', icon='PREFERENCES')

            box = layout.box()
            box.label(text='Auto Save') # , icon='FILE_TICK')
            box.operator('cgcookie.retopoflow_recover', icon='RECOVER_LAST')
            # if retopoflow.RetopoFlow.has_backup():
            #     box.label(text=options['last auto save path'])

            box = layout.box()
            box.label(text='RetopoFlow Updater')
            col = box.column()
            if configoptions.retopoflow_version_git:
                col.label(text='RetopoFlow under Git control', icon='DOT')
                col.label(text='Use Git to Pull latest updates', icon='DOT')
                # col.operator('cgcookie.retopoflow_updater', text='Updater System', icon='SETTINGS')
            else:
                col.operator('cgcookie.retopoflow_updater_check_now', text='Check for updates', icon='FILE_REFRESH')
                col.operator('cgcookie.retopoflow_updater_update_now', text='Update now', icon="IMPORT")
                col.operator('cgcookie.retopoflow_updater', text='Updater System', icon='SETTINGS')
                # col.operator('cgcookie.retopoflow_help_updater', text='Updater System Help', icon='HELP')

        #############################################################################
        # the following two methods add/remove RF to/from the main 3D View menu
        # NOTE: this is a total hack: hijacked the draw function!
        @staticmethod
        def menu_add():
            # for more icon options, see:
            #     https://docs.blender.org/api/current/bpy.types.UILayout.html#bpy.types.UILayout.operator
            VIEW3D_PT_RetopoFlow.menu_remove()
            VIEW3D_PT_RetopoFlow._menu_original = bpy.types.VIEW3D_MT_editor_menus.draw_collapsible

            def hijacked(context, layout):
                obj = context.active_object
                mode_string = context.mode
                edit_object = context.edit_object
                gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}

                VIEW3D_PT_RetopoFlow._menu_original(context, layout)

                if context.mode in {'EDIT_MESH', 'OBJECT'}:
                    row = layout.row(align=True)
                    # row.menu("VIEW3D_PT_RetopoFlow", text="RetopoFlow")
                    if VIEW3D_PT_RetopoFlow.is_editing_target(context):
                        row.operator('cgcookie.retopoflow', text="", icon='MOD_DATA_TRANSFER')
                    row.popover(panel="VIEW3D_PT_RetopoFlow", text=VIEW3D_PT_RetopoFlow.bl_label)

            bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = hijacked

        @staticmethod
        def menu_remove():
            if not hasattr(VIEW3D_PT_RetopoFlow, '_menu_original'): return
            bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = VIEW3D_PT_RetopoFlow._menu_original
            del VIEW3D_PT_RetopoFlow._menu_original
    RF_classes += [VIEW3D_PT_RetopoFlow]


if not import_succeeded:
    '''
    importing failed.  show this to the user!
    '''

    class VIEW3D_PT_RetopoFlow(Panel):
        """RetopoFlow Blender Menu"""
        bl_label = "RetopoFlow (broken)"
        bl_space_type = 'VIEW_3D'
        bl_region_type = 'HEADER'

        def draw(self, context):
            layout = self.layout

            box = layout.box()
            box.label(text='RetopoFlow cannot start.', icon='ERROR')

            box = layout.box()
            tw = textwrap.TextWrapper(width=35)
            report_lines = [
                'This is likely due to an incorrect installation of the add-on.',
                'Please try restarting Blender.'
                'If that does not work, please download the latest version from the Blender Market.',
                'If you continue to see this error, contact us through the Blender Market Indox, and we will work to get it fixed!',
            ]
            for report_line in report_lines:
                col = box.column()
                for l in tw.wrap(text=report_line):
                    col.label(text=l)

            box = layout.box()
            box.operator('cgcookie.retopoflow_blendermarket', icon='URL')

        #############################################################################
        # the following two methods add/remove RF to/from the main 3D View menu
        # NOTE: this is a total hack: hijacked the draw function!
        @staticmethod
        def menu_add():
            # for more icon options, see:
            #     https://docs.blender.org/api/current/bpy.types.UILayout.html#bpy.types.UILayout.operator
            VIEW3D_PT_RetopoFlow.menu_remove()
            VIEW3D_PT_RetopoFlow._menu_original = bpy.types.VIEW3D_MT_editor_menus.draw_collapsible

            def hijacked(context, layout):
                obj = context.active_object
                mode_string = context.mode
                edit_object = context.edit_object
                gp_edit = obj and obj.mode in {'EDIT_GPENCIL', 'PAINT_GPENCIL', 'SCULPT_GPENCIL', 'WEIGHT_GPENCIL'}

                VIEW3D_PT_RetopoFlow._menu_original(context, layout)

                if context.mode in {'EDIT_MESH', 'OBJECT'} and retopoflow.RetopoFlow.get_sources(): # context.object and context.object.mode in {'EDIT', 'OBJECT'}:
                    row = layout.row(align=True)
                    # row.menu("VIEW3D_PT_RetopoFlow", text="RetopoFlow")
                    row.popover(panel="VIEW3D_PT_RetopoFlow", text="RetopoFlow (broken)")

            bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = hijacked

        @staticmethod
        def menu_remove():
            if not hasattr(VIEW3D_PT_RetopoFlow, '_menu_original'): return
            bpy.types.VIEW3D_MT_editor_menus.draw_collapsible = VIEW3D_PT_RetopoFlow._menu_original
            del VIEW3D_PT_RetopoFlow._menu_original
    RF_classes += [VIEW3D_PT_RetopoFlow]



def register():
    for cls in RF_classes: bpy.utils.register_class(cls)
    if import_succeeded: updater.register(bl_info)
    VIEW3D_PT_RetopoFlow.menu_add()

def unregister():
    if import_succeeded: retopoflow.preload_help_images.quit = True
    VIEW3D_PT_RetopoFlow.menu_remove()
    if import_succeeded: updater.unregister()
    for cls in reversed(RF_classes): bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
