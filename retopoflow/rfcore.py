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

from ..addon_common.common.blender import iter_all_view3d_areas, iter_all_view3d_spaces
from ..addon_common.common.reseter import Reseter

from .rftool_base import get_all_RFTools
from .rftool_base import register as register_ops
from .rftool_base import unregister as unregister_ops

# import order determines tool order
from .rftool_contours.contours import RFTool_Contours
from .rftool_polypen.polypen   import RFTool_PolyPen

RFTools = { rft.bl_idname: rft for rft in get_all_RFTools() }
print(f'RFTools: {list(RFTools.keys())}')


'''
TODO:
- does not handle multiple spaces correctly
    - each space has its own overlay.show_retopology, but we're approaching this globally
    - this is potentially complicated when full-screening area
- does not handle multiple windows correctly
    - how to stop operator running in window if that window is closed?
'''

class RFCore:
    active_RFTool = None
    is_running = False
    event_mouse = None

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
        print(f'REGISTER')
        if RFCore._is_registered:
            print(f'  ALREADY REGISTERED!!')
            return

        # register RF operator and RF tools
        bpy.utils.register_class(RFCore_Operator)
        for i, rft in enumerate(get_all_RFTools()):
            bpy.utils.register_tool(rft, separator=(i==0))
            rft.register()
        register_ops()

        # wrap toll change function
        from bl_ui import space_toolsystem_common
        from ..addon_common.common.functools import wrap_function
        RFCore._unwrap_activate_tool = wrap_function(space_toolsystem_common.activate_by_id, fn_pre=RFCore.tool_changed)

        RFCore._is_registered = True

    @staticmethod
    def unregister():
        print(f'UNREGISTER')
        if not RFCore._is_registered:
            print(f'  ALREADY UNREGISTERED!!')
            return

        if not bpy.context.workspace:
            # no workspace?  blender might be closing, which unregisters add-ons (DON'T KNOW WHY)
            return

        if RFCore.active_RFTool:
            # RFTool is active, so switch away first!
            import bl_ui
            bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.select_box')

        RFCore.stop()

        # unwrap tool change function
        RFCore._unwrap_activate_tool()
        RFCore._unwrap_activate_tool = None

        # unregister RF operator and RF tools
        unregister_ops()
        for rft in reversed(get_all_RFTools()):
            rft.unregister()
            bpy.utils.unregister_tool(rft)
        bpy.utils.unregister_class(RFCore_Operator)

        RFCore._is_registered = False

    @staticmethod
    def tool_changed(context, space_type, idname, **kwargs):
        prev_active = RFCore.active_RFTool
        RFCore.active_RFTool = idname if idname in RFTools else None
        print(f'{prev_active} -> {idname}')

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

        wm = bpy.types.WindowManager
        RFCore._handle_draw_cursor = wm.draw_cursor_add(RFCore.handle_draw_cursor, tuple(), 'VIEW_3D', 'WINDOW')

        space = bpy.types.SpaceView3D
        RFCore._handle_preview   = space.draw_handler_add(RFCore.handle_preview,   tuple(), 'WINDOW', 'PRE_VIEW')
        RFCore._handle_postview  = space.draw_handler_add(RFCore.handle_postview,  tuple(), 'WINDOW', 'POST_VIEW')
        RFCore._handle_postpixel = space.draw_handler_add(RFCore.handle_postpixel, tuple(), 'WINDOW', 'POST_PIXEL')
        # tag_redraw_all('CC ui_start', only_tag=False)

        bpy.app.handlers.depsgraph_update_post.append(RFCore.handle_depsgraph_update)
        bpy.app.handlers.redo_post.append(RFCore.handle_redo_post)
        bpy.app.handlers.undo_post.append(RFCore.handle_undo_post)

        for s in iter_all_view3d_spaces():
            RFCore.reseter['s.overlay.show_retopology'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap'] = True
        RFCore.reseter['context.scene.tool_settings.snap_target'] = 'CLOSEST'
        RFCore.reseter['context.scene.tool_settings.use_snap_self'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_edit'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_nonedit'] = True
        RFCore.reseter['context.scene.tool_settings.use_snap_selectable'] = True

        emesh = context.active_object.data
        bm = bmesh.from_edit_mesh(emesh)
        if 'rf: select after move' not in bm.verts.layers.int:
            bm.verts.layers.int.new('rf: select after move')
        if 'rf: select after move' not in bm.edges.layers.int:
            bm.edges.layers.int.new('rf: select after move')
        if 'rf: select after move' not in bm.faces.layers.int:
            bm.faces.layers.int.new('rf: select after move')

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

        bpy.app.handlers.depsgraph_update_post.remove(RFCore.handle_depsgraph_update)
        bpy.app.handlers.redo_post.remove(RFCore.handle_redo_post)
        bpy.app.handlers.undo_post.remove(RFCore.handle_undo_post)

        space = bpy.types.SpaceView3D
        space.draw_handler_remove(RFCore._handle_preview,   'WINDOW')
        space.draw_handler_remove(RFCore._handle_postview,  'WINDOW')
        space.draw_handler_remove(RFCore._handle_postpixel, 'WINDOW')

        wm = bpy.types.WindowManager
        wm.draw_cursor_remove(RFCore._handle_draw_cursor)

        RFCore.reseter.reset()

    @staticmethod
    def handle_draw_cursor(mouse):
        if not RFCore.is_running:
            print('NOT RUNNING ANYMORE')
            return

        # print(f'handle_draw_cursor({mouse})  {bpy.context.window in RFCore.running_in_windows}')
        if bpy.context.window not in RFCore.running_in_windows:
            print(f'LAUNCHING IN NEW WINDOW')
            bpy.ops.retopoflow.core()

        if mouse != RFCore.event_mouse:
            if RFCore.event_mouse: print(f'LOST CONTROL!')
            RFCore.event_mouse = None

    @staticmethod
    def handle_preview():
        # print(f'handle_preview()')
        pass
    @staticmethod
    def handle_postview():
        # print(f'handle_postview()')
        pass
    @staticmethod
    def handle_postpixel():
        # print(f'handle_postpixel()')
        pass

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



class RFCore_Operator(bpy.types.Operator):
    bl_idname = "retopoflow.core"
    bl_label = "RetopoFlow Core"

    @classmethod
    def poll(cls, context):
        # only start if an RFTool is active
        return RFCore.active_RFTool

    def execute(self, context):
        context.window_manager.modal_handler_add(self)
        RFCore.running_in_windows.append(context.window)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # print(f'MODAL {event.type} {event.value}')

        if not context.area:
            # THIS HAPPENS WHEN THE UI LAYOUT IS CHANGED WHILE RUNNING
            # WORKAROUND: restart modal operator with correct context
            print(f'RESTARTING!')
            RFCore.restart()
            return {'FINISHED'}

        if not RFCore.is_running:
            print(f'EXITING!')
            RFCore.running_in_windows.remove(context.window)
            return {'FINISHED'}

        if not RFCore.event_mouse: print(f'IN CONTROL!')
        RFCore.event_mouse = (event.mouse_x, event.mouse_y)

        return {'PASS_THROUGH'}

