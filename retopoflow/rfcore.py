'''
Copyright (C) 2024 CG Cookie
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
import bmesh
import bl_ui

from ..addon_common.hive.hive import Hive
from ..addon_common.common.blender import iter_all_view3d_areas, iter_all_view3d_spaces
from ..addon_common.common.reseter import Reseter
from .common.operator import RFOperator, RFRegisterClass
from .common.raycast import prep_raycast_valid_sources

from .rftool_base import RFTool_Base

from .rfoperators.newtarget import RFCore_NewTarget_Cursor, RFCore_NewTarget_Active

# import order determines tool order
# from .rftool_contours.contours import RFTool_Contours
from .rftool_polypen.polypen   import RFTool_PolyPen
from .rftool_relax.relax       import RFTool_Relax

RFTools = { rft.bl_idname: rft for rft in RFTool_Base.get_all_RFTools() }
# print(f'RFTools: {list(RFTools.keys())}')


'''
TODO:
- does not handle multiple spaces correctly
    - each space has its own overlay.show_retopology, but we're approaching this globally
    - this is potentially complicated when full-screening area
- does not handle multiple windows correctly
    - how to stop operator running in window if that window is closed?
'''

class RFCore:
    default_RFTool = RFTool_PolyPen  # should be stored and sticky across sessions
    active_RFTool = None
    is_running = False
    event_mouse = None
    is_controlling = False

    running_in_windows = []

    reseter = Reseter()

    _is_registered = False
    _unwrap_activate_tool = None
    _handle_draw_cursor = None
    _handle_preview = None
    _handle_postview = None
    _handle_postpixel = None

    @staticmethod
    def register():
        # print(f'REGISTER')
        if RFCore._is_registered:
            # print(f'  ALREADY REGISTERED!!')
            return

        # register RF operator and RF tools
        RFTool_Base.register_all()
        RFOperator.register_all()
        RFRegisterClass.register_all()

        # wrap toll change function
        from bl_ui import space_toolsystem_common
        from ..addon_common.common.functools import wrap_function
        RFCore._unwrap_activate_tool = wrap_function(space_toolsystem_common.activate_by_id, fn_pre=RFCore.tool_changed)

        # bpy.types.VIEW3D_MT_editor_menus.append(RFCORE_PT_Panel.draw_popover)
        bpy.types.VIEW3D_MT_add.append(RFCore.draw_menu_items)

        RFCore._is_registered = True

    @staticmethod
    def unregister():
        # print(f'UNREGISTER')
        if not RFCore._is_registered:
            # print(f'  ALREADY UNREGISTERED!!')
            return

        if not bpy.context.workspace:
            # no workspace?  blender might be closing, which unregisters add-ons (DON'T KNOW WHY)
            return

        if RFCore.active_RFTool:
            # RFTool is active, so switch away first!
            bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.select_box')

        RFCore.stop()

        bpy.types.VIEW3D_MT_add.remove(RFCore.draw_menu_items)
        # bpy.types.VIEW3D_MT_editor_menus.remove(RFCORE_PT_Panel.draw_popover)

        # unwrap tool change function
        RFCore._unwrap_activate_tool()
        RFCore._unwrap_activate_tool = None

        # unregister RF operator and RF tools
        RFRegisterClass.unregister_all()
        RFOperator.unregister_all()
        RFTool_Base.unregister_all()

        RFCore._is_registered = False

    @staticmethod
    def draw_menu_items(self, context):
        if context.mode != 'OBJECT': return
        self.layout.separator()
        # self.layout.label(text=f'{Hive.get("name")}')
        RFCore_NewTarget_Cursor.draw_menu_item(self, context)
        RFCore_NewTarget_Active.draw_menu_item(self, context)

    @staticmethod
    def tool_changed(context, space_type, idname, **kwargs):
        prev_active = RFCore.active_RFTool
        RFCore.active_RFTool = idname if idname in RFTools else None
        # print(f'{prev_active} -> {idname}')

        if not prev_active and RFCore.active_RFTool:
            RFCore.start(context)

        # XXX: resizing the Blender window will cause tool change to change to current tool???
        if prev_active != RFCore.active_RFTool:
            if prev_active:
                RFTools[prev_active].deactivate(context)
            if RFCore.active_RFTool:
                RFTools[RFCore.active_RFTool].activate(context)

        if prev_active and not RFCore.active_RFTool:
            RFCore.stop()

    @staticmethod
    def start(context):
        if RFCore.is_running: return
        RFCore.is_running = True
        RFCore.event_mouse = None
        RFCore.is_controlling = True

        wm = bpy.types.WindowManager
        RFCore._handle_draw_cursor = wm.draw_cursor_add(RFCore.handle_draw_cursor, (context,), 'VIEW_3D', 'WINDOW')

        space = bpy.types.SpaceView3D
        RFCore._handle_preview   = space.draw_handler_add(RFCore.handle_preview,   (context,), 'WINDOW', 'PRE_VIEW')
        RFCore._handle_postview  = space.draw_handler_add(RFCore.handle_postview,  (context,), 'WINDOW', 'POST_VIEW')
        RFCore._handle_postpixel = space.draw_handler_add(RFCore.handle_postpixel, (context,), 'WINDOW', 'POST_PIXEL')
        # tag_redraw_all('CC ui_start', only_tag=False)

        # bpy.app.handlers.depsgraph_update_post.append(RFCore.handle_depsgraph_update)
        # bpy.app.handlers.redo_post.append(RFCore.handle_redo_post)
        # bpy.app.handlers.undo_post.append(RFCore.handle_undo_post)

        for s in iter_all_view3d_spaces():
            RFCore.reseter['s.overlay.show_retopology'] = True
            RFCore.reseter['s.overlay.show_object_origins'] = False
        RFCore.reseter['context.scene.tool_settings.use_snap'] = True
        RFCore.reseter['context.scene.tool_settings.snap_target'] = 'CLOSEST'
        RFCore.reseter['context.scene.tool_settings.use_snap_self'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_edit'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_nonedit'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_selectable'] = True

        bpy.ops.retopoflow.core()

    @staticmethod
    def restart():
        def rerun():
            area = next(iter_all_view3d_areas(screen=bpy.context.screen), None)
            with bpy.context.temp_override(area=area):
                bpy.ops.retopoflow.core()
        bpy.app.timers.register(rerun, first_interval=0.01)

    @staticmethod
    def stop():
        if not RFCore.is_running: return
        RFCore.is_running = False
        RFCore.event_mouse = None
        RFCore.is_controlling = False

        # bpy.app.handlers.depsgraph_update_post.remove(RFCore.handle_depsgraph_update)
        # bpy.app.handlers.redo_post.remove(RFCore.handle_redo_post)
        # bpy.app.handlers.undo_post.remove(RFCore.handle_undo_post)

        space = bpy.types.SpaceView3D
        space.draw_handler_remove(RFCore._handle_preview,   'WINDOW')
        space.draw_handler_remove(RFCore._handle_postview,  'WINDOW')
        space.draw_handler_remove(RFCore._handle_postpixel, 'WINDOW')

        wm = bpy.types.WindowManager
        wm.draw_cursor_remove(RFCore._handle_draw_cursor)

        RFCore.reseter.reset()

    @staticmethod
    def handle_draw_cursor(context, mouse):
        if not RFCore.is_running:
            # print('NOT RUNNING ANYMORE')
            return

        # print(f'handle_draw_cursor({mouse})  {bpy.context.window in RFCore.running_in_windows}')
        if bpy.context.window not in RFCore.running_in_windows:
            # print(f'LAUNCHING IN NEW WINDOW')
            bpy.ops.retopoflow.core()

        # print(list(context.window_manager.operators))
        if mouse != RFCore.event_mouse:
            if RFCore.event_mouse:
                # print(f'LOST CONTROL!')
                context.area.tag_redraw()
                RFCore.is_controlling = False
            RFCore.event_mouse = None

    @staticmethod
    def cursor_warp(context, point):
        x,y = map(int, point)
        context.window.cursor_warp(x, y)
        RFCore.event_mouse = (x,y)


    @staticmethod
    def handle_preview(context):
        if not RFOperator.active_operator(): return
        if not RFCore.is_controlling: return
        RFOperator.active_operator().draw_preview(context)
    @staticmethod
    def handle_postview(context):
        if not RFOperator.active_operator(): return
        if not RFCore.is_controlling: return
        RFOperator.active_operator().draw_postview(context)
    @staticmethod
    def handle_postpixel(context):
        if not RFOperator.active_operator(): return
        if not RFCore.is_controlling: return
        RFOperator.active_operator().draw_postpixel(context)

    @staticmethod
    def handle_depsgraph_update(scene, depsgraph):
        # print(f'handle_depsgraph_update({scene}, {depsgraph})')
        # for up in depsgraph.updates:
        #     print(f'  {up.id=} {up.is_updated_geometry=} {up.is_updated_shading=} {up.is_updated_transform=}')
        pass
    @staticmethod
    def handle_redo_post(*args, **kwargs):
        # print(f'handle_redo_post({args}, {kwargs})')
        pass
    @staticmethod
    def handle_undo_post(*args, **kwargs):
        # print(f'handle_undo_post({args}, {kwargs})')
        pass

RFOperator.RFCore = RFCore
RFCore_NewTarget_Active.RFCore = RFCore
RFCore_NewTarget_Cursor.RFCore = RFCore


class RFCore_Operator(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.core"
    bl_label = "RetopoFlow Core"

    @classmethod
    def poll(cls, context):
        # only start if an RFTool is active
        return RFCore.active_RFTool

    def execute(self, context):
        prep_raycast_valid_sources(context)
        context.window_manager.modal_handler_add(self)
        RFCore.running_in_windows.append(context.window)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # print(f'MODAL {event.type} {event.value}')

        if not context.area:
            # THIS HAPPENS WHEN THE UI LAYOUT IS CHANGED WHILE RUNNING
            # WORKAROUND: restart modal operator with correct context
            # print(f'RESTARTING!')
            RFCore.restart()
            return {'FINISHED'}

        if not RFCore.is_running:
            # print(f'EXITING!')
            RFCore.running_in_windows.remove(context.window)
            return {'FINISHED'}

        if not RFCore.event_mouse:
            # print(f'IN CONTROL!')
            RFCore.is_controlling = True
        RFCore.event_mouse = (event.mouse_x, event.mouse_y)

        return {'PASS_THROUGH'}



class RFCORE_PT_Panel(RFRegisterClass, bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = 'Start RetopoFlow'

    @classmethod
    def poll(cls, context):
        return False

    @staticmethod
    def draw_popover(self, context):
        if context.mode == 'OBJECT':
            layout = self.layout
            layout.separator()
            row = layout.row(align=True)
            row.label(text=f'{Hive.get("short name")}')
            row.operator('retopoflow.newtarget_cursor', text="", icon='CURSOR')
            row.operator('retopoflow.newtarget_active', text="", icon='MOD_MESHDEFORM')

    def draw(self, context): pass

    # def draw(self, context):
    #     layout = self.layout

    #     row = layout.row(align=True)
    #     row.label(text='Continue')
    #     row.operator('retopoflow.newtarget_cursor', text='Edit Active', icon='MOD_DATA_TRANSFER') # icon='EDITMODE_HLT')

    #     # row = layout.row(align=True)
    #     # row.label(text='New')
    #     # row.operator('cgcookie.retopoflow_newtarget_cursor', text='Cursor', icon='ADD')
    #     # row.operator('cgcookie.retopoflow_newtarget_active', text='Active', icon='ADD')


# class RFCORE_MT_PIE_PieMenu(bpy.types.Menu):
#     bl_idname = 'retopoflow.piemenu'
#     bl_label = 'RetopoFlow Tool Switch'

#     def draw(self, context):
#         if context.mode != 'EDIT_MESH': return

#         layout = self.layout
#         pie = layout.menu_pie()
#         # 4 - LEFT
#         pie.operator(RFTool_Contours.bl_idname, text=RFTool_Contours.bl_label, icon="OBJECT_DATAMODE")
#         # 6 - RIGHT
#         # pie.operator(RFTool_PolyPen.bl_idname, text=RFTool_PolyPen.bl_label, icon="OBJECT_DATAMODE")
#         pie.separator()
#         # 2 - BOTTOM
#         # pie.operator(RFTool_Relax.bl_idname, text=RFTool_Relax.bl_label, icon="OBJECT_DATAMODE")
#         pie.separator()
#         # 8 - TOP
#         pie.separator()
#         # 7 - TOP - LEFT
#         pie.separator()
#         # 9 - TOP - RIGHT
#         pie.separator()
#         # 1 - BOTTOM - LEFT
#         pie.separator()
#         # 3 - BOTTOM - RIGHT
#         pie.separator()
