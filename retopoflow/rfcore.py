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
import bl_ui
import bmesh
from bpy.types import Context, Menu, Event, Depsgraph, Scene, Area, Region, Space, SpaceView3D, RegionView3D, Screen

import time
import traceback
from typing import Any
from collections.abc import Sequence

from . import rfglobals

from ..addon_common.common.blender import iter_all_view3d_areas, iter_all_view3d_spaces
from ..addon_common.common.debug import debugger
from ..addon_common.common.resetter import Resetter
from ..config.theme import Theme
from ..config.keymaps import alter_user_keymaps, restore_user_keymaps
from .common.bmesh import get_object_bmesh, get_bmesh_emesh, clear_object_bmesh
from .common.bpy_helper import bpy_ops_retopoflow
from .common.operator import RFOperator_Base, RFOperator, RFOperator_Execute, RFRegisterClass, RFAssetShelf
from .common.raycast import prep_raycast_valid_sources, iter_all_valid_sources
from .common.interface import show_message
from .common import icons as icons_module
from ..addon_common.common.drawing import free_shaders_and_batches
from ..addon_common.common.ui_draw import free_ui_draw_shaders_and_batches

from .rftool_base  import RFTool_Base
from .rfbrush_base import RFBrush_Base
from .rfoverlays.overlays import overlay_names
from .rftool_statusbar import draw_rftool_statusbar, StatusbarYield

# NOTE: import order determines tool order
from .rftool_polypen.polypen       import RFTool_PolyPen
# from .rftool_zipper.zipper         import RFTool_Zipper
from .rftool_polystrips.polystrips import RFTool_PolyStrips
from .rftool_strokes.strokes       import RFTool_Strokes
from .rftool_contours.contours     import RFTool_Contours
# from .rftool_patches.patches       import RFTool_Patches
from .rftool_tweak.tweak           import RFTool_Tweak
from .rftool_relax.relax           import RFTool_Relax

RFTools : dict[str, type[RFTool_Base]] = { rft.bl_idname: rft for rft in RFTool_Base.get_all_RFTools() }
# print(f'RFTools: {list(RFTools.keys())}')

from .rfpanels import (
    general_panel, help_panel, menu_mesh, mesh_cleanup_panel, masking_panel, mirror_panel,
    relax_algorithm_panel, tweaking_panel, tweak_snapping_panel, rfpanel_snapping, tools_pie,  # MUST IMPORT THIS _AFTER_ THE RFTOOLS ABOVE TO MAINTAIN ORDER!

)

from . import preferences
from .rfprops import rfprops_scene, rfprops_object

# Operator files need to be imported here in order to be registered, even if they are not used in this file
from .rfoperators import mesh_cleanup, mirror, pinning, reset_tool_settings, launch_browser, relax_selected, twist
from .rfoperators.apply_retopo_settings import RFOperator_ApplyRetopoSettings, RFOperator_RestoreRetopoSettings
from .rfoperators.newtarget import RFCore_NewTarget_Cursor, RFCore_NewTarget_Active

from ..addon_common.autosave.autosave import AutoSave



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
    is_running     : bool = False  # RFCore modal operator is running
    is_controlling : bool = False  # RFCore is top modal operator
    is_paused      : bool = False  # Allows for switching modes and tools in operators without restarting RF
    event_mouse    : tuple[int, int] | None = None   # keeps track of last mouse update, hack used to determine if RFCore is top modal operator
    depsgraph_version : int = 0

    default_RFTool         = RFTool_PolyPen     # TODO: should be stored and sticky across sessions
    selected_RFTool_idname : str | None = None               # currently selected RFTool, but might not be active
    running_in_areas       = []                 # areas that RFCore operator is currently running in
    resetter               = Resetter('RFCore')  # helper for resetting bpy settings to original settings
    reset_attempts         = 0
    last_reset_attempt     = 0
    km_context             = None   # context for the active tool keymap (used by the statusbar drawing to filter out keymaps that does not match the current tool context)
    km_status_override : str | Sequence[str] | None = None   # override for the statusbar text (used to display additional information about the current tool)

    _last_rf_mesh_update_time: float = 0.0
    _original_bmesh_update_edit_mesh = None   # used to know when to pause statusbar drawing to let Blender info be displayed

    _is_registered        = False   # True if RF is registered with Blender
    _unwrap_activate_tool = None    # fn to unwrap space_toolsystem_common.activate_by_id
    _handle_draw_cursor   = None    # handle to callback for WindowManager's draw cursor
    _handle_preview       = None    # handle to callback for PRE_VIEW draw handler
    _handle_postview      = None    # handle to callback for POST_VIEW draw handler
    _handle_postpixel     = None    # handle to callback for POST_PIXEL draw handler

    @staticmethod
    def register():
        print(f'RFCore.register')
        if RFCore._is_registered:
            # print(f'  ALREADY REGISTERED!!')
            return

        # register RF operator and RF tools
        icons_module.register()
        preferences.register()
        rfprops_scene.register()
        rfprops_object.register()
        RFTool_Base.register_all()
        RFOperator_Base.register_all()
        RFRegisterClass.register_all()
        RFAssetShelf.register_all()
        mesh_cleanup_panel.register()
        tweaking_panel.register()
        masking_panel.register()
        general_panel.register()
        help_panel.register()
        mirror_panel.register()
        pinning.register()
        relax_algorithm_panel.register()
        tweak_snapping_panel.register()
        rfpanel_snapping.register()
        launch_browser.register()
        tools_pie.register()

        AutoSave.register()
        AutoSave.exclude_modal_operator('RetopoFlow Core')
        AutoSave.exclude_modal_operators(overlay_names)

        # wrap tool change function so we know when the artist switches tool
        from bl_ui import space_toolsystem_common
        from ..addon_common.common.functools import wrap_function
        RFCore._unwrap_activate_tool = wrap_function(space_toolsystem_common.activate_by_id, fn_pre=RFCore.tool_changed)

        bpy.types.VIEW3D_MT_mesh_add.append(RFCore.draw_menu_items)
        bpy.types.VIEW3D_MT_edit_mesh_vertices.append(menu_mesh.draw_vertex_menu_items)
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(menu_mesh.draw_vertex_menu_items)
        bpy.app.handlers.load_post.append(RFCore.handle_load_post)

        # track when RF modifies the mesh vs built-in Blender operator
        update_em_original = bmesh.update_edit_mesh
        RFCore._original_bmesh_update_edit_mesh = update_em_original
        def _rf_tracked_update_edit_mesh(*args, **kwargs):
            if RFCore.is_running:
                # Only record the time. Suppression is cancelled in modal() for direct user interactions.
                # Timer-driven mesh changes also call update_edit_mesh and must not clear the yield window.
                RFCore._last_rf_mesh_update_time = time.monotonic()
            return update_em_original(*args, **kwargs)
        bmesh.update_edit_mesh = _rf_tracked_update_edit_mesh

        RFCore._is_registered = True

    @staticmethod
    def unregister():
        print(f'RFCore.unregister')
        if not RFCore._is_registered:
            print(f'  ALREADY UNREGISTERED!!')
            return
        RFCore._is_registered = False

        # Restore bmesh.update_edit_mesh to its original (unpatched) version
        # Must happen before the workspace early-return so the patch is never left in place on addon reload
        if RFCore._original_bmesh_update_edit_mesh is not None:
            import bmesh as _bmesh_mod
            _bmesh_mod.update_edit_mesh = RFCore._original_bmesh_update_edit_mesh
            RFCore._original_bmesh_update_edit_mesh = None

        # unwrap tool change function, also before the early-return so activate_by_id is always removed
        if RFCore._unwrap_activate_tool is not None:
            RFCore._unwrap_activate_tool()
            RFCore._unwrap_activate_tool = None

        if not bpy.context.workspace:
            # no workspace?  blender might be closing, which unregisters add-ons (DON'T KNOW WHY)
            return

        if RFCore.selected_RFTool_idname:
            # RFTool is active, so switch away first!
            bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.move')
            bpy.context.workspace.status_text_set(None)

        try:
            RFCore.stop()
        except ReferenceError as e:
            print(f'Caught ReferenceError while trying to unregister')
            debugger.print_exception()

        # Clean up bmesh cache.
        clear_object_bmesh()

        bpy.types.VIEW3D_MT_mesh_add.remove(RFCore.draw_menu_items)
        bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(menu_mesh.draw_vertex_menu_items)
        bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(menu_mesh.draw_vertex_menu_items)
        bpy.app.handlers.load_post.remove(RFCore.handle_load_post)

        AutoSave.unregister()

        # unregister RF operator and RF tools
        RFAssetShelf.unregister_all()
        RFRegisterClass.unregister_all()
        RFOperator_Base.unregister_all()
        RFTool_Base.unregister_all()
        mesh_cleanup_panel.unregister()
        tweaking_panel.unregister()
        masking_panel.unregister()
        general_panel.unregister()
        help_panel.unregister()
        mirror_panel.unregister()
        relax_algorithm_panel.unregister()
        tweak_snapping_panel.unregister()
        rfpanel_snapping.unregister()
        tools_pie.unregister()
        rfprops_scene.unregister()
        rfprops_object.unregister()
        pinning.unregister()
        launch_browser.unregister()
        preferences.unregister()
        icons_module.unregister()

        free_shaders_and_batches()
        free_ui_draw_shaders_and_batches()

    @staticmethod
    def draw_menu_items(menu : Menu, context : Context):
        if context.mode != 'OBJECT': return
        if not menu.layout: return
        menu.layout.separator()
        RFCore_NewTarget_Cursor.draw_menu_item(menu, context)
        RFCore_NewTarget_Active.draw_menu_item(menu, context)

    @staticmethod
    def iter_spaces():
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                screen = win.screen
                for area in screen.areas:
                    if area.type != 'VIEW_3D': continue
                    for space in area.spaces:
                        if space.type != 'VIEW_3D': continue
                        for rgn in area.regions:
                            if rgn.type != 'WINDOW': continue
                            yield {'window':win, 'screen':screen, 'area':area, 'region':rgn, 'space':space}

    @staticmethod
    def switch_to_tool(bl_idname : str):
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                screen = win.screen
                for area in screen.areas:
                    if area.type != 'VIEW_3D': continue
                    for space in area.spaces:
                        if space.type != 'VIEW_3D': continue
                        for rgn in area.regions:
                            if rgn.type != 'WINDOW': continue
                            with bpy.context.temp_override(window=win, screen=screen, area=area, region=rgn, space=space):
                                _ = bpy.ops.wm.tool_set_by_id(name=bl_idname)

    @staticmethod
    def quick_switch_to_reset(bl_idname):
        if not bl_idname: return
        delta = time.time() - RFCore.last_reset_attempt
        print(f'{delta=} {RFCore.reset_attempts=}')
        if delta < 2:
            RFCore.reset_attempts += 1
        else:
            RFCore.reset_attempts = 0
        RFCore.last_reset_attempt = time.time()
        if RFCore.reset_attempts > 4:
            print('ATTEMPTED TOO MANY TIMES TO RESET!')
            RFCore.switch_to_tool('builtin.move')
        else:
            RFCore.quick_switch_with_call(None, bl_idname)

    @staticmethod
    def quick_switch_with_call(*args : Any, delay:float=0.25):
        def switch(*args):
            print(f'SWITCH: {args}')
            if not args: return
            if args[0] is None:
                pass
            elif type(args[0]) is str:
                RFCore.switch_to_tool(args[0])
            else:
                try: args[0]()
                except Exception as e: print(f'CAUGHT EXCEPTION {e=}')
            args = args[1:]
            bpy.app.timers.register(lambda: switch(*args), first_interval=delay)
        RFCore.stop()
        switch('builtin.move', *args)
        # bpy.app.timers.register(lambda: switch('builtin.move', *args), first_interval=delay)

    @staticmethod
    def _update_statusbar(context: bpy.types.Context):
        # print(f'RFOperator._update_statusbar {RFCore.selected_RFTool_idname}')
        # get the statusbar text from the active/selected RFTool.
        if tool_idname := RFCore.selected_RFTool_idname:
            if StatusbarYield.is_active():
                return  # Currently showing native status bar for external op report: don't re-register yet
            RFCore.km_context = 'init'
            RFCore.km_status_override = None
            context.workspace.status_text_set(
                lambda statusbar, context: draw_rftool_statusbar(
                    statusbar,
                    context,
                    tool=RFTools[tool_idname]
                )
            )
        else:
            RFCore.km_context = None
            RFCore.km_status_override = None
            context.workspace.status_text_set(None)

    @staticmethod
    def tool_changed(context, space_type, idname, **kwargs):
        # print(f'tool_changed(context, {space_type=}, {idname=}, {kwargs=})')
        if RFCore.is_paused: return

        prev_selected_RFTool_idname = RFCore.selected_RFTool_idname
        RFCore.selected_RFTool_idname = idname if idname in RFTools else None

        if prev_selected_RFTool_idname and not RFCore.selected_RFTool_idname:
            RFCore.stop()
            return

        if not prev_selected_RFTool_idname and RFCore.selected_RFTool_idname:
            # need to start RFCore in the correct context
            if not context.area:
                RFCore.quick_switch_to_reset(RFCore.selected_RFTool_idname)
                return

            if context.area.type == 'VIEW_3D': RFCore.start(context)
            else:
                started = False
                for wm in bpy.data.window_managers:
                    for win in wm.windows:
                        for area in win.screen.areas:
                            if area.type != 'VIEW_3D': continue
                            for space in area.spaces:
                                if space.type != 'VIEW_3D': continue
                                for rgn in area.regions:
                                    if started: break
                                    if rgn.type != 'WINDOW': continue
                                    with bpy.context.temp_override(window=win, area=area, region=rgn, space=space):
                                        RFCore.start(bpy.context)
                                    started = True
                assert started, f'Could not start after tool changed!?'

        # XXX: resizing the Blender window will cause tool change to change to current tool???
        if prev_selected_RFTool_idname != RFCore.selected_RFTool_idname:
            if prev_selected_RFTool_idname:
                RFTools[prev_selected_RFTool_idname].deactivate(context)
            if RFCore.selected_RFTool_idname:
                rftool = RFTools[RFCore.selected_RFTool_idname]
                rftool.activate(context)
                if rftool.rf_overlay:
                    if not context.region:
                        print(f'')
                        print(f'')
                        print(f'>>>>>>>> NO context.region <<<<<<<<<<')
                        print(f'tool_changed')
                        print(f'  {context=} {context.area=} {context.region=}')
                        print(f'  {bpy.context=} {bpy.context.area=} {bpy.context.region=}')
                        # this can happen if RF tool is selected when .blend file is saved
                        # try switching to different tool then switch back later?
                        RFCore.quick_switch_to_reset(rftool.rf_idname) # bpy.context.scene.retopoflow.saved_tool)
                    else:
                        try:
                            print(f'Activating {rftool.rf_overlay}')
                            print(bpy.context.area, bpy.context.region)
                            rftool.rf_overlay.activate()
                        except Exception as e:
                            print(f'Caught exception while trying to activate overlay {e}')
                            RFCore.restart()

        StatusbarYield.cancel()
        RFCore._update_statusbar(context)

    @staticmethod
    def start(context):
        if RFCore.is_running: return
        RFCore.is_running = True
        RFCore.event_mouse = None
        RFCore.is_controlling = True
        RFCore._last_rf_mesh_update_time = time.monotonic() # Reset timestamp so a startup geometry event never triggers a suppression window

        wm, space = bpy.types.WindowManager, bpy.types.SpaceView3D
        RFCore._handle_draw_cursor = wm.draw_cursor_add(RFCore.handle_draw_cursor,   (context, context.area), 'VIEW_3D', 'WINDOW')
        RFCore._handle_preview     = space.draw_handler_add(RFCore.handle_preview,   (context, context.area), 'WINDOW', 'PRE_VIEW')
        RFCore._handle_postview    = space.draw_handler_add(RFCore.handle_postview,  (context, context.area), 'WINDOW', 'POST_VIEW')
        RFCore._handle_postpixel   = space.draw_handler_add(RFCore.handle_postpixel, (context, context.area), 'WINDOW', 'POST_PIXEL')
        # tag_redraw_all('CC ui_start', only_tag=False)

        # bpy.app.handlers.depsgraph_update_post.append(RFCore.handle_depsgraph_update)
        bpy.app.handlers.redo_post.append(RFCore.handle_redo_post)
        bpy.app.handlers.undo_post.append(RFCore.handle_undo_post)
        bpy.app.handlers.load_pre.append(RFCore.handle_load_pre)
        bpy.app.handlers.depsgraph_update_post.append(RFCore.handle_depsgraph_update)
        bpy.app.handlers.save_pre.append(RFCore.handle_save_pre)
        if bpy.app.version >= (5,1,0):
            bpy.app.handlers.exit_pre.append(RFCore.handle_exit_pre)

        # Apply setup_snapping preference to projection before touching any snap settings
        prefs = preferences.RF_Prefs.get_prefs(context)
        snapping = context.scene.retopoflow.snapping
        if not prefs.setup_snapping:
            snapping.projection = 'FOLLOW_BLENDER'

        # Setup tool settings
        if snapping.projection != 'FOLLOW_BLENDER':
            RFCore.resetter['context.scene.tool_settings.use_snap'] = True
            RFCore.resetter['context.scene.tool_settings.snap_target'] = 'CLOSEST'
            RFCore.resetter['context.scene.tool_settings.use_snap_self'] = True
            RFCore.resetter['context.scene.tool_settings.use_snap_edit'] = True
            RFCore.resetter['context.scene.tool_settings.use_snap_nonedit'] = True
            RFCore.resetter['context.scene.tool_settings.use_snap_translate'] = True
            RFCore.resetter['context.scene.tool_settings.use_snap_rotate'] = True
            RFCore.resetter['context.scene.tool_settings.use_snap_scale'] = True
            RFCore.resetter.store('context.tool_settings.snap_elements_base')
            snap_elem = 'FACE_PROJECT' if snapping.projection == 'SCREEN_SPACE' else 'FACE_NEAREST'
            RFCore.resetter['context.tool_settings.snap_elements_individual'] = {snap_elem}
            if context.scene.tool_settings.snap_face_nearest_steps < 6:
                RFCore.resetter['context.scene.tool_settings.snap_face_nearest_steps'] = 6

        if prefs.setup_selection_mode:
            RFCore.resetter['context.tool_settings.mesh_select_mode'] = [True, True, False]

        if prefs.setup_automerge:
            RFCore.resetter['context.tool_settings.use_mesh_automerge'] = True

        # Setup viewport settings
        if prefs.setup_object_wires:
            RFCore.resetter['context.active_object.show_wire'] = True
            RFCore.resetter['context.active_object.show_all_edges'] = True

        if prefs.setup_fade_inactive:
            def show_fade_inactive(space):
                RFCore.resetter['space.overlay.show_fade_inactive'] = True
            for s in iter_all_view3d_spaces():
                show_fade_inactive(s)

        if prefs.setup_component_size:
            RFCore.resetter['context.preferences.themes[0].view_3d.vertex_size'] = prefs.vertex_size
            RFCore.resetter['context.preferences.themes[0].view_3d.edge_width'] = prefs.edge_width

        Theme.store_default(context)
        if prefs.theme != 'none':
            settings = Theme.common | getattr(Theme, prefs.theme)
            for pref in settings.keys():
                prop_path = 'context.preferences.themes[0].view_3d.' + pref
                RFCore.resetter[prop_path] = settings[pref]

        # Set up retopology overlay
        offset = context.space_data.overlay.retopology_offset
        props = context.scene.retopoflow
        if bpy.app.version < (4, 5, 0) and props.override_default_offset and offset > 0.2 and offset <0.20001:
            # Fixing Blender's bad default
            context.space_data.overlay.retopology_offset = 0.01
            print("Switching from Blender's default overlay distance to a smaller value")
        props.override_default_offset = False # Should only happen on initial load
        props.retopo_offset = context.space_data.overlay.retopology_offset
        if prefs.setup_retopo_overlay:
            def show_retopology(space):
                RFCore.resetter[(space, 'overlay.show_retopology')] = True
            for s in iter_all_view3d_spaces():
                show_retopology(s)

        mirror.setup_mirror(context)
        if prefs.setup_selection_adjustments:
            alter_user_keymaps(context)

        pinning.setup_pinning(context)

        try:
            bpy_ops_retopoflow('core')
        except Exception as e:
            print('Caught Exception when calling bpy.ops.retopoflow.core() while trying to start')
            print(f'  Exception: {e}')


    @staticmethod
    def restart():
        print(f'RFCore.restart()')
        def rerun():
            screen : Screen = bpy.context.screen
            area : Area | None = next(iter_all_view3d_areas(screen=screen), None)
            if not area: return
            region : Region | None = next((rgn for rgn in area.regions if rgn.type == 'WINDOW'), None)
            if not region: return
            space : Space | None = area.spaces.active
            if not isinstance(space, SpaceView3D): return
            r3d : RegionView3D | None = space.region_3d
            if not r3d: return
            with bpy.context.temp_override(area=area, region=region, space=space, region_3d=r3d):
                try:
                    bpy_ops_retopoflow('core')
                except Exception as e:
                    print('Caught Exception when calling bpy.ops.retopoflow.core() while trying to restart')
                    print(f'  Exception: {e}')
        bpy.app.timers.register(rerun, first_interval=0.01)

    @staticmethod
    def tag_redraw_areas():
        for a in RFCore.running_in_areas:
            a.tag_redraw()

    @staticmethod
    def pause():
        RFCore.is_paused = True

    @staticmethod
    def resume():
        RFCore.is_paused = False


    @staticmethod
    def stop():
        if not RFCore.is_running: return
        print(f'Stopping RFCore')
        RFCore.is_running = False
        RFCore.event_mouse = None
        RFCore.is_controlling = False

        StatusbarYield.cancel() # Cancel any pending status bar suppression timers

        for rfop in RFOperator.active_operators:
            try:
                rfop.stop()
            except ReferenceError as e:
                # ReferenceError likely means that Blender is shutting down
                # we will gracefully "handle" this by ignoring it
                pass
            except Exception as e:
                print(f'Caught unexpected Exception while trying to stop active RetopoFlow operators')
                print(f'  {e}')
                debugger.print_exception()

        bpy.app.handlers.save_pre.remove(RFCore.handle_save_pre) # pyright: ignore[reportArgumentType]
        bpy.app.handlers.load_pre.remove(RFCore.handle_load_pre) # pyright: ignore[reportArgumentType]
        bpy.app.handlers.redo_post.remove(RFCore.handle_redo_post)
        bpy.app.handlers.undo_post.remove(RFCore.handle_undo_post)
        bpy.app.handlers.depsgraph_update_post.remove(RFCore.handle_depsgraph_update)
        if bpy.app.version >= (5,1,0):
            bpy.app.handlers.exit_pre.remove(RFCore.handle_exit_pre) # pyright: ignore[reportArgumentType]

        RFCore.remove_handlers()

        RFCore.running_in_areas.clear()

        if not getattr(RFCore, 'is_saving', False):
            bpy.context.scene.retopoflow.saved_tool = ''

        pinning.restore_pinning(bpy.context)
        mirror.cleanup_mirror(bpy.context)
        restore_user_keymaps(bpy.context)

        RFCore.resetter.reset()

    @staticmethod
    def remove_handlers():
        print(f'RFCore.remove_handlers')
        wm, space = bpy.types.WindowManager, bpy.types.SpaceView3D
        if RFCore._handle_preview:
            space.draw_handler_remove(RFCore._handle_preview,   'WINDOW')
            RFCore._handle_preview = None
        if RFCore._handle_postview:
            space.draw_handler_remove(RFCore._handle_postview,  'WINDOW')
            RFCore._handle_postview = None
        if RFCore._handle_postpixel:
            space.draw_handler_remove(RFCore._handle_postpixel, 'WINDOW')
            RFCore._handle_postpixel = None
        if RFCore._handle_draw_cursor:
            wm.draw_cursor_remove(RFCore._handle_draw_cursor)
            RFCore._handle_draw_cursor = None

    @staticmethod
    def handle_update(context : Context, event : Event):
        if not RFCore.selected_RFTool_idname: return

        selected_RFTool = RFTools[RFCore.selected_RFTool_idname]
        brush = selected_RFTool.rf_brush
        if brush: brush.update(context, event)

    @staticmethod
    def is_current_area(context : Context):
        return context.area == RFCore.running_in_areas[0] if RFCore.running_in_areas else False

    @staticmethod
    def is_top_modal(context : Context):
        op_name = 'RetopoFlow Core'
        ops = context.window.modal_operators
        if not ops: return False
        if ops[0].name == op_name: return True
        if len(ops) >= 2 and ops[0].name == 'Screencast Keys' and ops[1].name == op_name: return True
        return False

    @staticmethod
    def handle_draw_cursor(context : Context, area : Area, mouse : tuple[int, int]):
        if len(area.spaces) == 0:
            RFCore.remove_handlers()
            return
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
            bpy_ops_retopoflow('core')
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
    def cursor_warp(context : Context, point : Sequence[int]):
        x,y = map(int, point)
        context.window.cursor_warp(x, y)
        RFCore.event_mouse = (x, y)

    @staticmethod
    def handle_exit_pre(_is_not_background_process : bool):
        bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.move')

    @staticmethod
    def handle_save_pre(_path_blend : str):
        if AutoSave.actively_saving:
            # RF AutoSave is doing the work, so let's skip the switch
            return
        RFCore.is_saving = True
        bpy.context.scene.retopoflow.saved_tool = RFCore.selected_RFTool_idname
        bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.move')
        bpy.app.handlers.save_post.append(RFCore.handle_save_post)

    @staticmethod
    def handle_save_post(_path_blend : str):
        bpy.app.handlers.save_post.remove(RFCore.handle_save_post)
        # if bpy.context.scene.retopoflow.saved_tool: RFCore.quick_switch_to_reset(bpy.context.scene.retopoflow.saved_tool)
        if bpy.context.scene.retopoflow.saved_tool:
            bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', bpy.context.scene.retopoflow.saved_tool)
        bpy.context.scene.retopoflow.saved_tool = ''
        if hasattr(RFCore, 'is_saving'):
            del RFCore.is_saving

    @staticmethod
    def handle_load_pre(_path_blend : str):
        # switch away from RF
        print(f'LOAD PRE!!')
        # # find 3D view area
        # for area in bpy.context.screen.areas:
        #     if area.type != 'VIEW_3D': continue
        #     for rgn in area.regions:
        #         if rgn.type != 'WINDOW': continue
        #         with bpy.context.temp_override(area=area, region=rgn):
        #             print(f'switching tool')
        #             bpy.ops.wm.tool_set_by_id(name='builtin.move')
        if getattr(bpy.context.workspace, 'tools', None):
            bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.move')
        RFCore.stop()

    @staticmethod
    @bpy.app.handlers.persistent
    def handle_load_post(path_blend):
        if not hasattr(bpy.context.scene, 'retopoflow'): return
        if not getattr(bpy.context.scene.retopoflow, 'saved_tool', ''): return
        RFCore.quick_switch_to_reset(bpy.context.scene.retopoflow.saved_tool)
        # bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', bpy.context.scene.retopoflow.saved_tool)

    @staticmethod
    def handle_preview(context : Context, area : Area):
        if not area or len(area.spaces) == 0:
            RFCore.remove_handlers()
            return
        if not RFCore.is_controlling: return
        if not RFCore.is_running: return
        op = RFOperator.active_operator()
        if op:
            try:
                op.draw_preview(context)
            except Exception as e:
                print('Caught exception while trying to draw preview')
                print(f'  {e}')
                debugger.print_exception()
                RFCore.restart()

    @staticmethod
    def handle_postview(context : Context, area : Area):
        if len(area.spaces) == 0:
            RFCore.remove_handlers()
            return
        if context.mode != 'EDIT_MESH': return
        # print(f'handle_postview {len(area.spaces)}')

        # import gpu
        # from .common.nearestcpp.test import batch, shader
        # gpu.state.depth_test_set('LESS_EQUAL')
        # gpu.state.depth_mask_set(True)
        # batch.draw(shader)

        if not RFCore.is_controlling: return
        if not RFCore.is_running: return

        op = RFOperator.active_operator()
        if op:
            try:
                op.draw_postview(context)
            except ReferenceError as e:
                print('Caught ReferenceError while trying to draw tool postview')
                print(f'  {e}')
                debugger.print_exception()
                RFCore.stop()
            except Exception as e:
                print('Caught exception while trying to draw tool postview')
                print(f'  {e}')
                debugger.print_exception()
                RFCore.quick_switch_to_reset(RFCore.selected_RFTool_idname)
                # RFCore.restart()

        selected_RFTool_idname = RFCore.selected_RFTool_idname
        if not selected_RFTool_idname: return
        selected_RFTool = RFTools[selected_RFTool_idname]
        if not selected_RFTool: return
        brush = selected_RFTool.rf_brush
        if not brush: return

        try:
            brush.draw_postview(context)
        except ReferenceError as re:
            print('Caught ReferenceError while trying to draw brush postview')
            print(f'  {re}')
            traceback.print_exc()
            RFCore.restart()

    @staticmethod
    def handle_postpixel(context : Context, area : Area):
        if len(area.spaces) == 0:
            RFCore.remove_handlers()
            return
        if not RFCore.is_controlling: return
        if not RFCore.is_running: return
        op = RFOperator.active_operator()
        if op:
            try:
                op.draw_postpixel(context)
            except Exception as e:
                print('Caught exception while trying to draw tool postpixel')
                traceback.print_exc()
                RFCore.restart()

        selected_RFTool_idname = RFCore.selected_RFTool_idname
        if not selected_RFTool_idname: return
        selected_RFTool = RFTools[selected_RFTool_idname]
        if not selected_RFTool: return
        brush = selected_RFTool.rf_brush
        if not brush: return

        try:
            brush.draw_postpixel(context)
        except ReferenceError as re:
            print('Caught ReferenceError while trying to draw brush postpixel')
            print(f'  {re}')
            traceback.print_exc()
            RFCore.restart()

    @staticmethod
    def handle_depsgraph_update(_scene : Scene, depsgraph : Depsgraph):
        if not RFCore.is_running:
            # can happen between stop() setting is_running=False and the handler being removed from the list
            return
        if not RFCore.selected_RFTool_idname:
            # this can happen when Blender is closing
            return

        RFCore.depsgraph_version += 1
        # print(f"{bpy.data.window_managers[0].windows[0].screen.show_fullscreen=}")
        # print(f'handle_depsgraph_update({scene}, {depsgraph})')
        # for up in depsgraph.updates:
        #     print(f'  {up.id=} {up.is_updated_geometry=} {up.is_updated_shading=} {up.is_updated_transform=}')

        # Detect Blender geometry ops to display their info in statusbar.
        try:
            # Intercept bmesh.update_edit_mesh to record the last time RF's own Python code pushed a mesh change.
            # Built-in C operators never call Python's bmesh.update_edit_mesh.
            _yield_active  = StatusbarYield.is_active()
            _elapsed       = time.monotonic() - RFCore._last_rf_mesh_update_time
            _has_geom      = any(u.is_updated_geometry for u in depsgraph.updates)
            # print(f'RF depsgraph: {_yield_active=} elapsed={_elapsed:.3f} {_has_geom=}')
            if not _yield_active and _elapsed > 0.2 and _has_geom:
                StatusbarYield.begin(3.0)
        except Exception as e:
            print(f'RF: external op detection error: {e}')

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
        op = RFOperator.active_operator()
        if op: op.reset()

    @staticmethod
    def handle_undo_post(*args, **kwargs):
        if not RFOperator.active_operator(): return
        if not RFCore.is_controlling: return
        # print(f'handle_undo_post({args}, {kwargs})')
        op = RFOperator.active_operator()
        if op: op.reset()

    @staticmethod
    def resetter_clear_all():
        RFCore.resetter.clear()
        for rftool in RFTools.values():
            resetter = getattr(rftool, 'resetter', None)
            if not resetter: continue
            resetter.clear()

    @staticmethod
    def resetter_restore_all():
        RFCore.resetter.restore()
        for rftool in RFTools.values():
            resetter = getattr(rftool, 'resetter', None)
            if not resetter: continue
            resetter.restore()


rfglobals.set_RFCore(RFCore)


class InvalidationManager:
    watching = {
        'depsgraph_update_pre': [],
        'depsgraph_update_post': [],
    }
    preventing = 0
    # run_next = 0
    # bm = None
    # em = None
    # changed = True

    @classmethod
    def run_test(cls, _context : Context):
        return
        # if cls.preventing: return

        # if not cls.bm or not cls.bm.is_valid:
        #     invalid = cls.bm and not cls.bm.is_valid
        #     if invalid: print(f'DETECTED INVALIDATION!')
        #     cls.bm, cls.em = get_bmesh_emesh(context)
        #     cls.run_next = time.time() + 1 if invalid else 0

        # cls.changed = False
        # for callback_name in cls.watching:
        #     fns = {
        #         fn
        #         for fn in getattr(bpy.app.handlers, callback_name)
        #         if not fn.__module__.endswith('retopoflow.rfcore')
        #     }
        #     if fns == cls.watching[callback_name]: continue
        #     cls.watching[callback_name] = fns
        #     cls.changed = True

        # if cls.changed or cls.run_next < time.time():
        #     print(f'{cls.changed=}')
        #     bmesh.update_edit_mesh(cls.em)
        #     cls.run_next = time.time() + 1

    @classmethod
    def prevent_invalidation(cls):
        cls.preventing += 1
        # print(f'>>> PREVENTING {cls.preventing}')
        for callback_name in cls.watching:
            callbacks = getattr(bpy.app.handlers, callback_name)
            fns = [
                fn for fn in callbacks
                if not fn.__module__.endswith('retopoflow.rfcore')
            ]
            cls.watching[callback_name] += fns
            for fn in fns:
                callbacks.remove(fn)

    @classmethod
    def resume_invalidation(cls):
        cls.preventing -= 1
        # print(f'>>> RESUMING {cls.preventing}')
        if cls.preventing > 0: return
        for callback_name in cls.watching:
            callbacks = getattr(bpy.app.handlers, callback_name)
            for fn in cls.watching[callback_name]:
                callbacks.append(fn)
            cls.watching[callback_name].clear()

rfglobals.set_InvalidationManager(InvalidationManager)


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
            #bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.move')
            #return False
            # def switch(state=0):
            #     if state == 0:
            #         bpy.app.timers.register(lambda: switch(1), first_interval=0.01)
            #     elif state == 1:
            #         bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', 'builtin.move')
            #         bpy.app.timers.register(lambda: switch(2), first_interval=0.01)
            #     else:
            #         bl_ui.space_toolsystem_common.activate_by_id(bpy.context, 'VIEW_3D', RFCore.default_RFTool.bl_idname)
            # switch()
            # return False
        # only start if an RFTool is active
        return bool(RFCore.selected_RFTool_idname)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        print(f'RFCore_Operator.__init__')
        self.running_in_area = None
        RFCore_Operator.running_operators += 1
        self.is_running = True

    def __del__(self):
        print(f'RFCore_Operator.__del__!!!')
        try:
            print(f'    {self=}')
            print(f'    {getattr(self, "is_running", None)=}')
            if hasattr(self, 'running_in_area') and self.running_in_area in RFCore.running_in_areas:
                RFCore.running_in_areas.remove(self.running_in_area)
            self.is_running = False
        except ReferenceError:
            # Blender struct has been removed, can't access or set properties
            print(f'    <struct removed>')
        finally:
            RFCore_Operator.running_operators -= 1
        print(f'  done')

    def execute(self, context : Context) -> set[str]:
        prep_raycast_valid_sources(context)
        context.window_manager.modal_handler_add(self)
        self.running_in_area = context.area
        self.is_running = True
        RFCore.running_in_areas.append(context.area)

        # Display an alert message if no sources are detected.
        prefs = preferences.RF_Prefs.get_prefs(context)
        source_count = len(list(iter_all_valid_sources(context)))
        if source_count == 0 and prefs.warn_no_sources:
            selected = context.scene.retopoflow.snapping.snap_only_selected
            selectable = context.scene.tool_settings.use_snap_selectable
            obj = context.scene.retopoflow.snapping.snap_object
            collection = context.scene.retopoflow.snapping.snap_collection
            message = (
                f"No sources detected.\n"
                f"Retopoflow tools need a visible object that is not being edited to snap the retopology mesh to."
            )
            if selected: message = message + "\nOnly use selected objects as sources is ON."
            if selectable: message = message + "\nOnly use selectable objects as sources is ON."
            if obj: message = message + f"\nThe object {obj.name} is set to be the only possible source."
            if not obj and collection: message = message + f"\nOnly objects in the collection {collection.name} are set as possible sources."
            if any([selectable, selected, obj, collection]): message = message + "\nYou can change the source settings in the General panel."
            show_message(message=message, title="Retopoflow", icon="ERROR")
            self.report({'ERROR'}, message)

        print(f'RFCore_Operator executing')
        return {'RUNNING_MODAL'}

    def modal(self, context : Context, event : Event) -> set[str]:
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
            print(f'RFCore_Operator restarting due to no context.area')
            RFCore.quick_switch_to_reset(RFCore.selected_RFTool_idname)
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

        InvalidationManager.run_test(context)

        if not RFCore.event_mouse:
            # print(f'IN CONTROL!')
            RFCore.is_controlling = True
            context.area.tag_redraw()
        RFCore.event_mouse = (event.mouse_x, event.mouse_y)
        # Cancel native status bar display on user interaction.
        if (StatusbarYield.is_active()
            # Check PRESS not RELEASE or else the click on the menu that calls the op interferes
            and not event.type.startswith('TIMER')
            and event.type not in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'NOTHING', 'WINRESIZE'}
            and event.value == 'PRESS'
        ):
            StatusbarYield.cancel()
            RFCore._update_statusbar(context)

        if RFCore.is_controlling:
            # RFCore.handle_update(context, event)
            try:
                RFCore.handle_update(context, event)
            except ReferenceError as referr:
                print(f'RFCore_Operator threw an unexpected ReferenceError')
                print(referr)
                print(f'Attempting to fix by restarting')
                RFCore.quick_switch_to_reset(RFCore.selected_RFTool_idname)
                return {'FINISHED'}

        return {'PASS_THROUGH'}
