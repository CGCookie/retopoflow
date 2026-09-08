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

import bpy, bmesh
from bl_ui import space_toolsystem_common
from bpy.types import Context, Event, Mesh, Object
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from typing import Literal

from ..rfglobals import RFGlobals
from ..preferences import RF_Prefs
from .bmesh import get_bmesh_emesh
from .bmesh_maths import is_bmvert_hidden
from .raycast import ray_from_mouse, raycast_valid_sources, mouse_from_event
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_preferences import mouse_drag


DEBUG = False


def deselect_all_on_empty_click(context, bm, em, brush, mouse_down, mouse_up) -> bool:
    ''' Clear the selection when the artist clicks where the brush has no geometry to work on.
    Returns True when the selection actually changed. '''
    # The brush tools bind LMB on press, so their clicks never fall through to Blender's
    # view3d.select, which is what deselects on empty space in every other tool.
    if (Vector(mouse_up) - Vector(mouse_down)).length > mouse_drag():
        return False  # a stroke, not a click
    if brush.hit and brush.hit_p:
        M = context.edit_object.matrix_world
        center, radius_squared = Vector(brush.hit_p), brush.get_scaled_radius() ** 2
        if any(not bmv.hide and ((M @ bmv.co) - center).length_squared <= radius_squared for bmv in bm.verts):
            return False
    if not any(bmv.select for bmv in bm.verts):
        return False
    bmops.deselect_all(bm)
    bmops.flush_selection(bm, em)
    return True


def get_selected(
        context,
        objects: list[Object] = [],
        bm: Object = None
    ):
    selected = {} # {'object_name': {'verts': [], 'edges': [], 'faces': []} }

    if not objects:
        objects = [context.active_object]

    for obj in objects:
        obj_bm, owned = bm, False
        if obj_bm is None:
            if context.mode == 'EDIT_MESH':
                # This bmesh is Blender's, so don't free it
                obj_bm = bmesh.from_edit_mesh(obj.data)
            else:
                obj_bm = bmesh.new()
                obj_bm.from_mesh(obj.data)
                owned = True

        if obj.name not in selected.keys():
            selected[obj.name] = {'verts': [], 'edges': [], 'faces': []}

        obj_bm.verts.index_update()
        obj_bm.edges.index_update()
        obj_bm.faces.index_update()
        obj_bm.verts.ensure_lookup_table()
        obj_bm.edges.ensure_lookup_table()
        obj_bm.faces.ensure_lookup_table()

        {selected[obj.name]['verts'].append(x.index) for x in obj_bm.verts if x.select}
        {selected[obj.name]['edges'].append(x.index) for x in obj_bm.edges if x.select}
        {selected[obj.name]['faces'].append(x.index) for x in obj_bm.faces if x.select}

        if owned:
            if DEBUG: print('Retopoflow selection.py: freeing own bmesh')
            obj_bm.free()

    return selected


def restore_selected(
        context,
        selection: dict[str, dict[Literal['verts', 'edges', 'faces'], list]],
        objects: list[Object] = [],
        bm: Object = None,
        skip: dict[str, dict[Literal['verts', 'edges', 'faces'], list]] | None = None
    ):

    if not objects:
        objects = [context.active_object]

    for obj in objects:
        if (
            not selection[obj.name]['verts'] and
            not selection[obj.name]['edges'] and
            not selection[obj.name]['faces']
        ):
            # Saves a bmesh conversion if not needed
            continue

        obj_bm, owned = bm, False
        if obj_bm is None:
            if context.mode == 'EDIT_MESH':
                # This bmesh is Blender's, so don't free it
                obj_bm = bmesh.from_edit_mesh(obj.data)
            else:
                obj_bm = bmesh.new()
                obj_bm.from_mesh(obj.data)
                owned = True

        obj_skip = (skip or {}).get(obj.name) or {'verts': [], 'edges': [], 'faces': []}

        {v.select_set(False) for v in obj_bm.verts}
        {e.select_set(False) for e in obj_bm.edges}
        {f.select_set(False) for f in obj_bm.faces}

        # NOTE: do NOT call index_update() on this bmesh between removing a component and here
        if selection[obj.name]['verts']:
            wanted, skipped = set(selection[obj.name]['verts']), set(obj_skip['verts'])
            for v in obj_bm.verts:
                if v.index in wanted and v.index not in skipped:
                    v.select_set(True)
        if selection[obj.name]['edges']:
            wanted, skipped = set(selection[obj.name]['edges']), set(obj_skip['edges'])
            for e in obj_bm.edges:
                if e.index in wanted and e.index not in skipped:
                    e.select_set(True)
        if selection[obj.name]['faces']:
            wanted, skipped = set(selection[obj.name]['faces']), set(obj_skip['faces'])
            for f in obj_bm.faces:
                if f.index in wanted and f.index not in skipped:
                    f.select_set(True)

        if obj_bm is bm:
            continue  # caller supplied the bmesh, so pushing it back is the caller's business
        if context.mode == 'EDIT_MESH':
            bmesh.update_edit_mesh(obj.data)
        else:
            obj_bm.to_mesh(obj.data)
            if DEBUG: print('Retopoflow selection.py: freeing own bmesh')
            obj_bm.free()


def hovered_bmelem(context : Context, event : Event, distance2d, nearest_bmv, nearest_bme, nearest_bmf):
    ''' Nearest unhidden element the select mode allows, and the source point it was measured
    from. Both None when the cursor is off the source. Dragging and clicking both pick through
    here so they measure the same boundary. '''
    hit = raycast_valid_sources(context, mouse_from_event(event), respect_clip_planes=True)
    if not hit: return (None, None)
    co = hit['co_local']
    nearest_bmv.update(context, co, distance2d=distance2d, filter_fn=lambda bmv: not is_bmvert_hidden(context, bmv))
    nearest_bme.update(context, co, distance2d=distance2d, filter_fn=lambda bme: not any(is_bmvert_hidden(context, bmv) for bmv in bme.verts))
    nearest_bmf.update(context, co, distance2d=distance2d, filter_fn=lambda bmf: not any(is_bmvert_hidden(context, bmv) for bmv in bmf.verts))
    mode = context.tool_settings.mesh_select_mode
    for allowed, bmelem in zip(mode, (nearest_bmv.bmv, nearest_bme.bme, nearest_bmf.bmf)):
        if allowed and bmelem is not None: return (bmelem, co)
    return (None, co)


# Blender's fallback selection tools and the gesture each runs. Tweak has no gesture, so it gets Box.
FALLBACK_SELECT_OPS : dict[str, str] = {
    'builtin.select':        'select_box',
    'builtin.select_box':    'select_box',
    'builtin.select_circle': 'select_circle',
    'builtin.select_lasso':  'select_lasso',
}


def fallback_select_tool_item(context : Context):
    ''' The tool in the toolbar's fallback (selection) slot, or None. '''
    helper = space_toolsystem_common.ToolSelectPanelHelper._tool_class_from_space_type('VIEW_3D')
    if helper is None: return None
    item, _index, _group = helper._tool_get_by_id_active_with_group(context, helper.tool_fallback_id)
    return item


def fallback_select_icon_and_label(context : Context) -> tuple[int, str]:
    ''' The toolbar's own icon and name for that tool, for layout.operator(). '''
    item = fallback_select_tool_item(context)
    if not item: return (0, 'Select Tool')
    icon_value = space_toolsystem_common.ToolSelectPanelHelper._icon_value_from_icon_handle(item.icon)
    return (icon_value, item.label)


# The gesture is invoked and left to run, so a timer polls for it and cleans up once it ends.
# Everything below is scoped to the gesture we launched; ones started through Blender's own keys
# are left alone.
_watching : str | None = None                          # op name of the gesture we launched
_restore_select_mode : tuple[bool, ...] | None = None  # mesh_select_mode borrowed for circle select
_circle_radius : int | None = None                     # radius the last circle select ended at


def _running_gesture():
    if not _watching: return None
    idname = f'VIEW3D_OT_{_watching}'
    return next((
        op
        for window in bpy.context.window_manager.windows
        for op in window.modal_operators
        if op.bl_idname == idname
    ), None)


def _watch_gesture_timer() -> float | None:
    global _watching, _restore_select_mode, _circle_radius
    op = _running_gesture()
    if op:
        # Python invocations don't get last-used properties back, so keep the radius ourselves
        if _watching == 'select_circle' and 'radius' in op.properties:
            _circle_radius = op.properties['radius']
        return 0.05
    _watching = None
    if _restore_select_mode is not None and bpy.context.scene:
        bpy.context.scene.tool_settings.mesh_select_mode = _restore_select_mode
        _restore_select_mode = None
    if RFCore := RFGlobals.RFCore_None:
        RFCore._update_statusbar(bpy.context)
    return None


def _start_gesture(context : Context, event : Event) -> bool:
    ''' Start the toolbar's fallback selection gesture from the drag in progress. '''
    global _watching, _restore_select_mode
    item = fallback_select_tool_item(context)
    op_name = FALLBACK_SELECT_OPS.get(item.idname) if item else None
    if DEBUG: print(f'fallback select: {item.idname if item else None} -> {op_name}')
    if not op_name: return False
    op = getattr(bpy.ops.view3d, op_name)
    if not op.poll(): return False

    # add to the selection rather than replace it, so reaching for the gesture never costs what was selected
    mode = 'AND' if (event.shift and event.ctrl) else 'SUB' if event.ctrl else 'ADD'
    if op_name == 'select_circle' and mode == 'AND': mode = 'ADD'  # circle has no AND
    props = {'mode': mode}
    # box and circle wait for a click when invoked from Python, but the drag already is the click
    if 'wait_for_input' in op.get_rna_type().properties: props['wait_for_input'] = False
    if op_name == 'select_circle':
        # in vert+edge mode the circle grabs edges that merely cross it, so run it vert-only
        ts = context.scene.tool_settings
        select_mode = tuple(ts.mesh_select_mode)
        if select_mode[0] and select_mode[1]:
            _restore_select_mode = select_mode
            ts.mesh_select_mode = (True, False, False)
        if _circle_radius is not None: props['radius'] = _circle_radius

    _watching = op_name
    context.workspace.status_text_set(None)  # show Blender's gesture hints instead of RF's hotkeys
    if not bpy.app.timers.is_registered(_watch_gesture_timer):
        bpy.app.timers.register(_watch_gesture_timer, first_interval=0.05)
    op('INVOKE_DEFAULT', **props)
    return True


def selected_under_mouse(context : Context, event : Event) -> bool:
    ''' Whether the target face under the cursor carries any selection, ignoring the select mode.
    Raycasts the target itself, so it also answers where the target overhangs the source. '''
    if not context.edit_object: return False
    o, d = ray_from_mouse(context, event)
    if o is None: return False
    bm, _em = get_bmesh_emesh(context, ensure_lookup_tables=True)
    Mi = context.edit_object.matrix_world.inverted_safe()
    _co, _no, index, _dist = BVHTree.FromBMesh(bm).ray_cast((Mi @ o).xyz, (Mi @ d).xyz)
    if index is None: return False
    bmf = bm.faces[index]
    return bmf.select or any(bmv.select for bmv in bmf.verts)


def try_drag_select(context : Context, event : Event, *, hovering_selected : bool = False) -> bool:
    ''' Hand a drag that started away from geometry to the fallback selection gesture. Returns
    True when the gesture took the drag, so the caller should drop what it was about to do. '''
    if not RF_Prefs.get_prefs(context).tweaking_drag_select: return False
    if hovering_selected or selected_under_mouse(context, event): return False
    return _start_gesture(context, event)
