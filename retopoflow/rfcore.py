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

import random

from ..addon_common.hive.hive import Hive
from ..addon_common.common.blender import iter_all_view3d_areas, iter_all_view3d_spaces
from ..addon_common.common.reseter import Reseter
from .common.bmesh import get_object_bmesh
from .common.operator import RFOperator, RFOperator_Execute, RFRegisterClass
from .common.raycast import prep_raycast_valid_sources

from .rftool_base  import RFTool_Base
from .rfbrush_base import RFBrush_Base

from .rfoperators.newtarget import RFCore_NewTarget_Cursor, RFCore_NewTarget_Active

# NOTE: import order determines tool order
from .rftool_contours.contours import RFTool_Contours
from .rftool_polypen.polypen   import RFTool_PolyPen
from .rftool_strokes.strokes   import RFTool_Strokes
from .rftool_tweak.tweak       import RFTool_Tweak
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
    # is_running and is_controlling indicate current state of RetopoFlow's core.
    # under normal circumstances, RFCore is in control whenever it is running.  however, RF will
    # lose "control" any time another modal operator gains control (ex: orbit view, box select, etc.).
    is_running     = False  # RFCore modal operator is running
    is_controlling = False  # RFCore is top modal operator
    event_mouse    = None   # keeps track of last mouse update, hack used to determine if RFCore is top modal operator
    depsgraph_version = 0

    default_RFTool         = RFTool_PolyPen     # TODO: should be stored and sticky across sessions
    selected_RFTool_idname = None               # currently selected RFTool, but might not be active
    running_in_areas       = []                 # areas that RFCore operator is currently running in
    reseter                = Reseter('RFCore')  # helper for resetting bpy settings to original settings

    _is_registered        = False   # True if RF is registered with Blender
    _unwrap_activate_tool = None    # fn to unwrap space_toolsystem_common.activate_by_id
    _handle_draw_cursor   = None    # handle to callback for WindowManager's draw cursor
    _handle_preview       = None    # handle to callback for PRE_VIEW draw handler
    _handle_postview      = None    # handle to callback for POST_VIEW draw handler
    _handle_postpixel     = None    # handle to callback for POST_PIXEL draw handler

    @staticmethod
    def register():
        # print(f'REGISTER')
        if RFCore._is_registered:
            # print(f'  ALREADY REGISTERED!!')
            return

        # register RF operator and RF tools
        RFTool_Base.register_all()
        RFOperator.register_all()
        RFOperator_Execute.register_all()
        RFRegisterClass.register_all()

        # wrap tool change function so we know when the artist switches tool
        from bl_ui import space_toolsystem_common
        from ..addon_common.common.functools import wrap_function
        RFCore._unwrap_activate_tool = wrap_function(space_toolsystem_common.activate_by_id, fn_pre=RFCore.tool_changed)

        # bpy.types.VIEW3D_MT_editor_menus.append(RFCORE_PT_Panel.draw_popover)
        bpy.types.VIEW3D_MT_mesh_add.append(RFCore.draw_menu_items)

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

        if RFCore.selected_RFTool_idname:
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
        RFOperator_Execute.unregister_all()
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
        prev_selected_RFTool_idname = RFCore.selected_RFTool_idname
        RFCore.selected_RFTool_idname = idname if idname in RFTools else None

        if not prev_selected_RFTool_idname and RFCore.selected_RFTool_idname:
            RFCore.start(context)

        # XXX: resizing the Blender window will cause tool change to change to current tool???
        if prev_selected_RFTool_idname != RFCore.selected_RFTool_idname:
            if prev_selected_RFTool_idname:
                RFTools[prev_selected_RFTool_idname].deactivate(context)
            if RFCore.selected_RFTool_idname:
                rftool = RFTools[RFCore.selected_RFTool_idname]
                rftool.activate(context)
                if rftool.rf_overlay:
                    rftool.rf_overlay.activate()

        if prev_selected_RFTool_idname and not RFCore.selected_RFTool_idname:
            RFCore.stop()

    @staticmethod
    def start(context):
        if RFCore.is_running: return
        RFCore.is_running = True
        RFCore.event_mouse = None
        RFCore.is_controlling = True

        wm, space = bpy.types.WindowManager, bpy.types.SpaceView3D
        RFCore._handle_draw_cursor = wm.draw_cursor_add(RFCore.handle_draw_cursor,   (context,), 'VIEW_3D', 'WINDOW')
        RFCore._handle_preview     = space.draw_handler_add(RFCore.handle_preview,   (context,), 'WINDOW', 'PRE_VIEW')
        RFCore._handle_postview    = space.draw_handler_add(RFCore.handle_postview,  (context,), 'WINDOW', 'POST_VIEW')
        RFCore._handle_postpixel   = space.draw_handler_add(RFCore.handle_postpixel, (context,), 'WINDOW', 'POST_PIXEL')
        # tag_redraw_all('CC ui_start', only_tag=False)

        # bpy.app.handlers.depsgraph_update_post.append(RFCore.handle_depsgraph_update)
        bpy.app.handlers.redo_post.append(RFCore.handle_redo_post)
        bpy.app.handlers.undo_post.append(RFCore.handle_undo_post)
        bpy.app.handlers.depsgraph_update_post.append(RFCore.handle_depsgraph_update)

        for s in iter_all_view3d_spaces():
            RFCore.reseter['s.overlay.show_retopology'] = True
            RFCore.reseter['s.overlay.show_object_origins'] = False
        RFCore.reseter['context.scene.tool_settings.use_snap'] = True
        RFCore.reseter['context.scene.tool_settings.snap_target'] = 'CLOSEST'
        RFCore.reseter['context.scene.tool_settings.use_snap_self'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_edit'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_nonedit'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_selectable'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_translate'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_rotate'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_scale'] = True

        try:
            bpy.ops.retopoflow.core()
        except:
            pass

    @staticmethod
    def restart():
        print(f'RFCore.restart()')
        def rerun():
            area = next(iter_all_view3d_areas(screen=bpy.context.screen), None)
            if not area: return
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            space = area.spaces.active
            r3d = space.region_3d
            with bpy.context.temp_override(area=area, region=region, space=space, region_3d=r3d):
                bpy.ops.retopoflow.core()
        bpy.app.timers.register(rerun, first_interval=0.01)

    @staticmethod
    def tag_redraw_areas():
        for a in RFCore.running_in_areas:
            a.tag_redraw()

    @staticmethod
    def stop():
        if not RFCore.is_running: return
        RFCore.is_running = False
        RFCore.event_mouse = None
        RFCore.is_controlling = False

        # clean up cache, otherwise old bmesh objects may become invalid even if
        # blender does not recognize them as invalid (bm.is_valid still True)
        get_object_bmesh.cache.clear()

        bpy.app.handlers.depsgraph_update_post.remove(RFCore.handle_depsgraph_update)
        bpy.app.handlers.redo_post.remove(RFCore.handle_redo_post)
        bpy.app.handlers.undo_post.remove(RFCore.handle_undo_post)

        space = bpy.types.SpaceView3D
        space.draw_handler_remove(RFCore._handle_preview,   'WINDOW')
        space.draw_handler_remove(RFCore._handle_postview,  'WINDOW')
        space.draw_handler_remove(RFCore._handle_postpixel, 'WINDOW')

        wm = bpy.types.WindowManager
        wm.draw_cursor_remove(RFCore._handle_draw_cursor)

        RFCore.running_in_areas.clear()

        RFCore.reseter.reset()

    @staticmethod
    def handle_update(context, event):
        if not RFCore.selected_RFTool_idname: return

        selected_RFTool = RFTools[RFCore.selected_RFTool_idname]
        brush = selected_RFTool.rf_brush
        if brush: brush.update(context, event)

    @staticmethod
    def is_current_area(context):
        return context.area == RFCore.running_in_areas[0] if RFCore.running_in_areas else False

    @staticmethod
    def handle_draw_cursor(context, mouse):
        if not RFCore.is_running:
            # print('NOT RUNNING ANYMORE')
            return

        def idx(items, item):
            return next((idx for (idx,i) in enumerate(items) if i == item), None)
        # print(f'handle_draw_cursor area={idx(context.window.screen.areas, context.area)}')
        # print(f'handle_draw_cursor({mouse})  {RFCore.selected_RFTool_idname=}  {RFOperator.active_operator()=}  {bpy.context.window in RFCore.running_in_areas=}')
        # print(f'{RFTools[RFCore.selected_RFTool_idname]}')
        if context.area not in RFCore.running_in_areas:
            print(f'LAUNCHING IN NEW AREA {context.area.x},{context.area.y}')
            bpy.ops.retopoflow.core()
        else:
            # print(f'handle_draw_cursor: context.area: {context.area.x},{context.area.y}')
            if not RFCore.is_current_area(context):
                # reorder RFCore.running_in_areas so first is current area
                RFCore.running_in_areas = [context.area] + [a for a in RFCore.running_in_areas if a != context.area]

        # print(list(context.window_manager.operators))
        if mouse != RFCore.event_mouse:
            if RFCore.event_mouse:
                # print(f'LOST CONTROL!')
                context.area.tag_redraw()
                RFCore.is_controlling = False
            RFCore.event_mouse = None

        # if RFCore.is_controlling:
        #     selected_RFTool = RFTools[RFCore.selected_RFTool_idname]
        #     brush = selected_RFTool.rf_brush
        #     if brush:
        #         print(f'updating brush {brush}')
        #         pass

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
        if not RFCore.is_controlling: return
        if RFOperator.active_operator():
            RFOperator.active_operator().draw_postview(context)

        selected_RFTool = RFTools[RFCore.selected_RFTool_idname]
        brush = selected_RFTool.rf_brush
        if brush:
            brush.draw_postview(context)

    @staticmethod
    def handle_postpixel(context):
        if not RFCore.is_controlling: return
        if RFOperator.active_operator():
            RFOperator.active_operator().draw_postpixel(context)

        selected_RFTool = RFTools[RFCore.selected_RFTool_idname]
        brush = selected_RFTool.rf_brush
        if brush:
            brush.draw_postpixel(context)

    @staticmethod
    def handle_depsgraph_update(scene, depsgraph):
        RFCore.depsgraph_version += 1
        # print(f'handle_depsgraph_update({scene}, {depsgraph})')
        # for up in depsgraph.updates:
        #     print(f'  {up.id=} {up.is_updated_geometry=} {up.is_updated_shading=} {up.is_updated_transform=}')

        selected_RFTool = RFTools[RFCore.selected_RFTool_idname]
        selected_RFTool.depsgraph_update()
        brush = selected_RFTool.rf_brush
        if brush: brush.depsgraph_update()
        RFOperator.tickle(bpy.context)


    @staticmethod
    def handle_redo_post(*args, **kwargs):
        if not RFOperator.active_operator(): return
        if not RFCore.is_controlling: return
        # print(f'handle_redo_post({args}, {kwargs})')
        RFOperator.active_operator().reset()

    @staticmethod
    def handle_undo_post(*args, **kwargs):
        if not RFOperator.active_operator(): return
        if not RFCore.is_controlling: return
        # print(f'handle_undo_post({args}, {kwargs})')
        RFOperator.active_operator().reset()

RFOperator.RFCore = RFCore
RFCore_NewTarget_Active.RFCore = RFCore
RFCore_NewTarget_Cursor.RFCore = RFCore
RFBrush_Base.RFCore = RFCore


class RFCore_Operator(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.core"
    bl_label = "RetopoFlow Core"
    running_operators = 0

    @classmethod
    def poll(cls, context):
        if not context.region:
            # TODO: fix this!!
            print('RF was started without context being set up correctly.')
            print('This can happen when blender starts RF without the artist switching to it.')
            print('For example: if startup blend chooses RF tool')
            RFCore.restart()
            return False
            #RFCore.selected_RFTool_idname = None
            #bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.select_box')
            #return False
            # def switch(state=0):
            #     if state == 0:
            #         bpy.app.timers.register(lambda: switch(1), first_interval=0.01)
            #     elif state == 1:
            #         bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.select_box')
            #         bpy.app.timers.register(lambda: switch(2), first_interval=0.01)
            #     else:
            #         bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', RFCore.default_RFTool.bl_idname)
            # switch()
            # return False
        # only start if an RFTool is active
        return bool(RFCore.selected_RFTool_idname)

    def __init__(self):
        print(f'RFCore_Operator.__init__')
        self.running_in_area = None
        RFCore_Operator.running_operators += 1
        self.is_running = True
    def __del__(self):
        print(f'RFCore_Operator.__del__!!! {getattr(self, "is_running", None)}')
        if hasattr(self, 'running_in_area') and self.running_in_area in RFCore.running_in_areas:
            RFCore.running_in_areas.remove(self.running_in_area)
        RFCore_Operator.running_operators -= 1
        self.is_running = False

    def execute(self, context):
        prep_raycast_valid_sources(context)
        context.window_manager.modal_handler_add(self)
        self.running_in_area = context.area
        self.is_running = True
        RFCore.running_in_areas.append(context.area)
        print(f'RFCore_Operator executing')
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # print(f'MODAL {event.type} {event.value}')
        # print(f'RFCore_Operator:')
        # print(dir(context))
        # print(f' {context.area=}')
        # print(f' {context.space_data=}')
        # print(f' {context.space_data.region_3d=}')
        # print(event.type, [op for op in context.window.modal_operators], random.random())

        if RFOperator.tickled:
            RFOperator.tickled()

        if not context.area:
            # THIS HAPPENS WHEN THE UI LAYOUT IS CHANGED WHILE RUNNING
            # WORKAROUND: restart modal operator with correct context
            print(f'no context.area, exiting')
            # RFCore.restart()
            print(f'RFCore_Operator exiting')
            return {'FINISHED'}
        if context.area.type != 'VIEW_3D':
            print(f'area type changed, exiting')
            return {'FINISHED'}

        if not context.region or not context.region_data:
            # THIS HAPPENS WHEN BLENDER STARTED RETOPOFLOW WITHOUT THE
            # ARTIST SWITCHING TO IT (EX: RF TOOL IS DEFAULT).
            # I THINK THE CONTEXT IS NOT QUITE SET UP CORRECTLY.
            # NEED TO SWITCH TO DIFFERENT TOOL, THEN SWITCH BACK??
            print(f'no {context.region=} or {context.region_data=}, RESTARTING!')
            RFCore.restart()
            print(f'RFCore_Operator exiting')
            return {'FINISHED'}

        # print(f' {len(context.area.spaces)=}')
        #' {context.region=} {context.region_data=}')

        if not RFCore.is_running:
            # print(f'EXITING!')
            print(f'RFCore_Operator exiting')
            return {'FINISHED'}

        if not RFCore.event_mouse:
            # print(f'IN CONTROL!')
            RFCore.is_controlling = True
            context.area.tag_redraw()
        RFCore.event_mouse = (event.mouse_x, event.mouse_y)

        if RFCore.is_controlling:
            RFCore.handle_update(context, event)

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
