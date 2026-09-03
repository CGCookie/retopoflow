'''
Copyright (C) 2025 CG Cookie
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

import math
import time
from collections.abc import Iterable

import bmesh
import bpy
from bmesh.types import BMVert, BMEdge, BMFace
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..common.bmesh import (
    bme_other_bmv, bmes_shared_bmv,
    bmvs_shared_bme,
    bmf_midpoint,
    get_bmesh_emesh,
)
from ..common.drawing import (
    Drawing,
    CC_2D_LINES,
)
from ..common.maths import Point
from ..common.operator import RFOperator_Invoke, RFKeyMaps, rf_is_running, hotkey_owns_context
from ..common.raycast import nearest_point_valid_sources, vec_right
from ..common.snapping import SNAP_TO_ITEMS, build_island_bvh, build_snap_sources, draw_snap_to_props

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.maths import Frame
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.colors import Color4


def is_perimeter(bme, bmfaces):
    bmfs = list(bme.link_faces)
    if len(bmfs) == 1: return True
    if len([bmf for bmf in bmfs if bmf in bmfaces]) == 1: return True
    return False

def compute_average_normal(bmverts : list[BMVert]) -> Vector:
    normal : Vector = sum(( bmv.normal for bmv in bmverts ), Vector((0,0,0)))
    return normal.normalized()

def compute_perimeter_normal(bmverts : list[BMVert]) -> Vector:
    center = Vector(Point.average(bmv.co for bmv in bmverts))
    normal : Vector = sum(
        (
            (center - bmv0.co).cross(bmv1.co - bmv0.co).normalized() * (bmv1.co - bmv0.co).length
            for (bmv0, bmv1) in iter_pairs(bmverts, True)
        ),
        Vector((0,0,0))
    )
    return normal.normalized()

# poll() walks the perimeter on every menu redraw, so the diagnostic below is off by default
DEBUG_PERIMETER = False

def get_perimeter_bmedges(bmfaces : Iterable[BMFace]) -> list[BMEdge]:
    bmedges = { bme for bmf in bmfaces for bme in bmf.edges }
    perimeter_bmedges = { bme for bme in bmedges if is_perimeter(bme, bmfaces) }

    perimeter = [ next(iter(perimeter_bmedges)) ]
    bmv = perimeter[-1].verts[0]
    perimeter_bmverts = [bmv]

    while True:
        potentials = {
            bme
            for bme in bmv.link_edges
            if bme in perimeter_bmedges and bme != perimeter[-1]
        }
        if len(potentials) != 1:
            if DEBUG_PERIMETER: print(f'{potentials=} but len not 1')
            return []
        bme = next(iter(potentials))
        bmv = bme_other_bmv(bme, bmv)
        if bme == perimeter[0]:
            break
        perimeter.append(bme)
        perimeter_bmverts.append(bmv)

    if len(perimeter) != len(perimeter_bmedges): return []

    n0 = compute_average_normal(perimeter_bmverts)
    n1 = compute_perimeter_normal(perimeter_bmverts)
    if n0.dot(n1) < 0:
        perimeter.reverse()

    return perimeter

def same_bmedges(bme0, bme1):
    THRESHOLD = 0.000001
    bmv00, bmv01 = bme0.verts
    bmv10, bmv11 = bme1.verts
    co00, co01 = bmv00.co, bmv01.co
    co10, co11 = bmv10.co, bmv11.co
    if (co00 - co10).length < THRESHOLD and (co01 - co11).length < THRESHOLD: return True
    if (co00 - co11).length < THRESHOLD and (co01 - co10).length < THRESHOLD: return True
    return False

# TODO: turn into propert Operator with redo params!
def rip_rotate_zip(context, ITERATIONS, SPRING_K, SPRING_C, OFFSET, *, undo=False):
    TIMESTEP = 0.02
    MASS = 0.1

    if undo:
        bpy.ops.ed.undo_push(message=f'Rip Rotate Zip commit {time.time()}')

def find_duplicate(bmv0, other_bmvs, *, threshold=0.000001) -> BMVert | None:
    if not other_bmvs: return None
    bmv1 = min(other_bmvs, key=lambda bmv1:(bmv0.co - bmv1.co).length)
    return bmv1 if (bmv0.co - bmv1.co).length <= threshold else None


class RFOperator_TopoRotate(RFOperator_Invoke):
    bl_idname = 'retopoflow.toporotate'
    bl_label = 'Rotate Topology (Retopoflow)'
    bl_description = 'Topologically rotates the selected patch'
    bl_space_type = 'VIEW_3d'
    bl_region_type = 'TOOLS'
    bl_options = { 'REGISTER', 'UNDO' }

    rf_keymaps : RFKeyMaps = [
        (bl_idname, {'type': 'R', 'value': 'PRESS', 'alt': True}, None),
    ]
    # Inert: nothing reads rf_status unless the operator calls set_statusbar_override itself.
    # The modal header (see header_modal_text) carries this instead, in and out of RF.
    rf_status = ['LMB: Commit', 'MMB: (nothing)', 'RMB: Cancel']

    # set on the standalone Mesh-keymap item only, so hotkey_owns_context governs the key
    # and not the tool keymap above or the right-click menu entry
    hotkey: bpy.props.BoolProperty(
        name='From Hotkey',
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    _is_running = False  # only one drag at a time; a second rip would tear an already-ripped patch


    offset: bpy.props.IntProperty(
        name='Offset',
        description='Number of edges to offset (positive: clockwise, negative: counter-clockwise)',
        default=0,
    )

    iterations: bpy.props.IntProperty(
        name='Iterations',
        description='Iterations of mass-spring simulation',
        default=100,
        min=0,
        max=10000,
    )
    spring_k: bpy.props.FloatProperty(
        name='Spring K',
        description='Spring force',
        default=5.0,
        min=0.0,
        max=1000.0,
    )
    spring_c: bpy.props.FloatProperty(
        name='Spring C',
        description='Spring damping constant (0.0 no damping, 1.0 full damping)',
        default=0.95,
        min=0.0,
        max=1.0,
    )

    # Only used while RF is not running.  RF supplies its own sources otherwise.
    snap_to: bpy.props.EnumProperty(
        name='Snap To',
        description='Surface to project the patch onto while it rotates',
        items=SNAP_TO_ITEMS,
        default='ORIGINAL_MESH',
    )
    snap_object: bpy.props.StringProperty(
        name='Object',
        description='Name of the object to snap vertices to',
        default='',
    )
    snap_collection: bpy.props.StringProperty(
        name='Collection',
        description='Name of the collection to snap vertices to',
        default='',
    )

    bm = None
    draw_handle = None

    perimeter0: list[BMEdge]
    perimeter0_bmverts: list[BMVert]
    perimeter1: list[BMEdge]
    perimeter1_bmverts: list[BMVert]
    frame: Frame
    mouse: Vector
    mouse_down: Vector
    patch_center: Vector

    @classmethod
    def poll(cls, context):
        # RFOperator_Invoke.poll is the plain edit-mesh check, with no dependence on RFCore
        if not super().poll(context): return False
        if cls._is_running: return False
        # the drag angle is measured on screen, so this only means anything in a 3D view.
        # space_data rather than region_data: menus draw in their own region, which has none.
        if not context.space_data or context.space_data.type != 'VIEW_3D': return False
        bm, em = get_bmesh_emesh(context, ensure_lookup_tables=False)
        bmfaces = bmops.get_all_selected_bmfaces(bm)
        if len(bmfaces) <= 1: return False
        perimeter = get_perimeter_bmedges(bmfaces)
        return bool(perimeter)


    def rip(self, context):
        ''' Split the selected patch away from the mesh and cache everything the rotation
        needs.  Returns False when the selection has no single clean perimeter. '''
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        self.M = context.edit_object.matrix_world
        self.Mi = self.M.inverted_safe()
        self.bmfaces : set[BMFace] = bmops.get_all_selected_bmfaces(self.bm)

        # RF supplies the sources when it is running.  Outside RF the operator picks its own,
        # and 'ORIGINAL_MESH' needs its BVH built from the patch before the rip below moves anything.
        self.rf_running = rf_is_running()
        self.snap_sources = []
        self.snap_bvh = None
        if not self.rf_running:
            self.snap_sources = build_snap_sources(
                context, self.snap_to,
                snap_object=self.snap_object, snap_collection=self.snap_collection,
            )
            if self.snap_to == 'ORIGINAL_MESH':
                self.snap_bvh = build_island_bvh(
                    self.M, { bmv for bmf in self.bmfaces for bmv in bmf.verts },
                )

        perimeter = get_perimeter_bmedges(self.bmfaces)
        if not perimeter: return False
        self.count : int = len(perimeter)
        is_boundary = [bme.is_boundary for bme in perimeter]

        # rip the patch away!
        res = bmesh.ops.split_edges(self.bm, edges=perimeter)
        all_bmedges = set(res['edges'])

        bmesh.update_edit_mesh(self.em)
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, self.bmfaces)
        bmops.flush_selection(self.bm, self.em)

        # grab inner perimeter and outer perimiter of ripped faces again, because there are new edges
        self.perimeter0 = get_perimeter_bmedges(self.bmfaces)
        self.perimeter0_bmverts = [ bmes_shared_bmv(bme0, bme1) for (bme0, bme1) in iter_pairs(self.perimeter0, True) ]
        perimeter1 = all_bmedges - set(self.perimeter0)
        perimeter1_bmverts = { bmv for bme in perimeter1 for bmv in bme.verts }
        perimeter1_bmverts = [
            find_duplicate(bmv0, perimeter1_bmverts)
            for bmv0 in self.perimeter0_bmverts
        ]
        self.perimeter1_bmverts = [
            bmv1 if bmv1 is not None else self.bm.verts.new(bmv0.co)
            for (bmv0, bmv1) in zip(self.perimeter0_bmverts, perimeter1_bmverts)
        ]
        self.perimeter1 = []
        for (i0, bmv0) in enumerate(self.perimeter1_bmverts):
            i1 = (i0 + 1) % self.count
            bmv1 = self.perimeter1_bmverts[i1]
            bme = next(iter(set(bmv0.link_edges) & set(bmv1.link_edges)), None)
            if not bme: bme = self.bm.edges.new((bmv0, bmv1))
            self.perimeter1.append(bme)
        self.perimeter1 = self.perimeter1[1:] + self.perimeter1[:1]

        self.all_bmverts = { bmv for bmf in self.bmfaces for bmv in bmf.verts }
        self.perimeter_bmverts = set(self.perimeter0_bmverts)
        self.inner_bmverts = self.all_bmverts - self.perimeter_bmverts
        self.outer_bmverts = { bmv for bme in self.perimeter1 for bmv in bme.verts }

        self.all_bmedges = { bme for bmf in self.bmfaces for bme in bmf.edges }
        self.perimeter_bmedges = set(self.perimeter0)
        self.inner_bmedges = self.all_bmedges - self.perimeter_bmedges

        o = Point.average(bmv.co for bmv in self.perimeter0_bmverts)
        z = compute_average_normal(self.perimeter0_bmverts)
        self.frame = Frame(o, z=z)
        self.original_positions = {
            bmv: Vector(bmv.co)
            for bmv in self.all_bmverts
        }
        self.original_positions_local = {
            bmv: self.frame.w2l_point(bmv.co)
            for bmv in self.all_bmverts
        }
        return True

    def invoke(self, context, event):
        if self.hotkey and not hotkey_owns_context(context, 'toporotate_tool_context'):
            return {'PASS_THROUGH'}
        if not context.region_data:
            self.report({'ERROR'}, 'Topo Rotate: needs a 3D viewport')
            return {'CANCELLED'}
        if not self.rip(context):
            self.report({'ERROR'}, 'Topo Rotate: selection has no single closed perimeter')
            return {'CANCELLED'}

        pts = [
            pt
            for bmv in self.all_bmverts
            if (pt := location_3d_to_region_2d(context.region, context.region_data, self.M @ bmv.co)) is not None
        ]
        if not pts:
            # rip() already tore the patch, so put it back before bailing out
            self.abort(context, 'Topo Rotate: the selected patch is not on screen')
            return {'CANCELLED'}
        self.patch_center = sum(pts, Vector((0,0))) / len(pts)
        self.mouse_start = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_angle = math.atan2(self.mouse_start.y - self.patch_center.y, self.mouse_start.x - self.patch_center.x)

        type(self)._is_running = True
        self.draw_handle = bpy.types.SpaceView3D.draw_handler_add(
            self.draw_rotation_line, (context,), 'WINDOW', 'POST_PIXEL'
        )
        self.set_header_text(context)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def header_modal_text(self):
        return f'Topo Rotate: {self.offset:+d}   |   LMB/Enter: Confirm   RMB/Esc: Cancel'

    def set_header_text(self, context):
        if context.area: context.area.header_text_set(self.header_modal_text())

    def clear_header_text(self, context):
        if context.area: context.area.header_text_set(None)

    def abort(self, context, message):
        ''' Zip the ripped patch back exactly where it was, then let go of it. '''
        self.report({'ERROR'}, message)
        self.revert_to_original()
        self.zip_patch(context)
        self.release(context)

    def release(self, context):
        ''' Drop the draw handler and every BMesh reference while the bmesh is still alive. '''
        type(self)._is_running = False
        self.clear_header_text(context)
        if handle := self.draw_handle:
            bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            self.draw_handle = None
        self.bm, self.em = None, None
        self.bmfaces = set()
        self.all_bmverts = set()
        self.all_bmedges = set()
        self.inner_bmverts = set()
        self.inner_bmedges = set()
        self.outer_bmverts = set()
        self.perimeter0 = []
        self.perimeter1 = []
        self.perimeter0_bmverts = []
        self.perimeter1_bmverts = []
        self.perimeter_bmverts = set()
        self.perimeter_bmedges = set()
        self.original_positions = {}
        self.original_positions_local = {}
        self.merging = {}

    def snap_co(self, context, co_world):
        ''' Nearest point on whichever surface this run is snapping to, or None. '''
        if self.rf_running:
            return nearest_point_valid_sources(context, co_world, respect_clip_planes=True)
        if self.snap_sources:
            return nearest_point_valid_sources(context, co_world, sources=self.snap_sources, respect_clip_planes=True)
        if self.snap_bvh:
            hit_co, _normal, _idx, _dist = self.snap_bvh.find_nearest(co_world)
            return Vector(hit_co) if hit_co else None
        return None

    def revert_to_original(self):
        # undo everything
        self.merging = {
            bmv0: bmv1
            for (bmv0, bmv1) in zip(self.perimeter0_bmverts, self.perimeter1_bmverts)
        }
        for bmv in self.all_bmverts:
            bmv.co = self.original_positions[bmv]

    def zip_patch(self, context):
        ''' Weld the ripped perimeter back into the mesh along the current offset. '''
        bmesh.ops.weld_verts(self.bm, targetmap=self.merging)

        bmesh.update_edit_mesh(self.em)
        bmops.deselect_all(self.bm)
        bmops.select_iter(self.bm, self.bmfaces)
        bmops.flush_selection(self.bm, self.em)

    def execute(self, context):
        ''' Non-modal path, used by the redo panel and by scripts. '''
        if not self.rip(context):
            self.report({'ERROR'}, 'Topo Rotate: selection has no single closed perimeter')
            return {'CANCELLED'}
        # delta_angle straight from offset: in a redo there is no mouse to measure against
        self.apply_offset(context, self.offset, self.offset * 2.0 * math.pi / self.count)
        self.zip_patch(context)
        self.release(context)
        return {'FINISHED'}

    def cancel(self, context):
        ''' Blender calls this when it ends the modal operator itself (ex: the area closes). '''
        # not called when modal() returns CANCELLED, so the patch may already be zipped and released
        if not self.bm: return
        self.revert_to_original()
        self.zip_patch(context)
        self.release(context)

    def modal(self, context, event):
        if context.mode != 'EDIT_MESH':
            # can happen when an undo drops back to OBJECT mode; the bmesh is gone with it
            self.release(context)
            return {'CANCELLED'}

        cancelled = event.type in {'ESC', 'RIGHTMOUSE'}
        committed = event.type in {'ENTER', 'LEFTMOUSE'}
        if cancelled or committed:
            if cancelled: self.revert_to_original()
            self.zip_patch(context)
            self.release(context)
            context.area.tag_redraw()
            return {'FINISHED'} if committed else {'CANCELLED'}

        if event.type != 'MOUSEMOVE': return {'RUNNING_MODAL'}

        context.area.tag_redraw()
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        angle = math.atan2(self.mouse.y - self.patch_center.y, self.mouse.x - self.patch_center.x)
        delta_angle = self.mouse_angle - angle
        offset = round(delta_angle / (2.0 * math.pi) * self.count)
        # if offset == self.offset:
        #     return {'RUNNING_MODAL'}

        self.offset = offset
        self.set_header_text(context)
        self.apply_offset(context, offset, delta_angle)
        return {'RUNNING_MODAL'}


    def apply_offset(self, context, offset, delta_angle):
        ''' Rotate the ripped patch by `delta_angle`, pin its perimeter to the verts `offset`
        steps around the hole, and relax the interior back towards its original spacing. '''
        iterations = self.iterations
        spring_k = self.spring_k
        spring_c = self.spring_c
        TIMESTEP = 0.02

        self.merging = {
            bmv0: self.perimeter1_bmverts[(i + offset) % self.count]
            for (i, bmv0) in enumerate(self.perimeter0_bmverts)
        }

        # set up mass-spring sim based on distances from perimeter (push verts towards original size)
        springs = [
            (bmv, bmv1, (self.original_positions[bmv] - self.original_positions[bmv0]).length)
            for bmv in self.inner_bmverts
            for (bmv0, bmv1) in self.merging.items()
        ]


        # initially rotate points roughly to where they go
        frame = self.frame.clone()
        frame.rotate_about_z(delta_angle)
        for (bmv, co) in self.original_positions_local.items():
            bmv.co = frame.l2w_point(co)

        # move perimiter bmverts to the final position
        for bmv0, bmv1 in self.merging.items():
            bmv0.co = bmv1.co

        # now run the mass-spring simulation
        vels = {
            bmv: Vector((0, 0, 0)) for bmv in self.inner_bmverts
        }
        for _ in range(iterations):
            forces = {
                bmv: Vector((0,0,0)) for bmv in self.inner_bmverts
            }
            for (bmv0, bmo1, length) in springs:
                p0 = bmv0.co
                p1 = bmo1.co if type(bmo1) is BMVert else bmf_midpoint(bmo1)
                vdiff = p1 - p0
                l = vdiff.length
                if l == 0: continue
                ddiff = vdiff / l
                f = ddiff * (length - l)
                if bmv0 in self.inner_bmverts:
                    forces[bmv0] -= spring_k * f
                if bmo1 in self.inner_bmverts:
                    forces[bmo1] += spring_k * f
            for (bmv, f) in forces.items():
                p = bmv.co + TIMESTEP * vels[bmv]
                snapped = self.snap_co(context, self.M @ p)
                # Without the fallback the simulation is inert whenever nothing is being
                # snapped to, because the integrated position is never written back.
                bmv.co = self.Mi @ snapped if snapped else p
                vels[bmv] = TIMESTEP * forces[bmv] + (1 - spring_c) * vels[bmv]

        bmesh.update_edit_mesh(self.em)

    def draw_rotation_line(self, context):
        ''' Own draw handler: RFCore only dispatches draw callbacks for RFOperators. '''
        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.color(Color4((1,1,1,1)))
            draw.line_width(1)
            draw.stipple(pattern=[5,5], offset=0, color=Color4((1,1,1,0)))
            draw.vertex(self.patch_center).vertex(self.mouse)

    def draw_warning(self, layout):
        row = layout.split(factor=0.4)
        row.alert = True
        row.separator()
        row.label(text='No valid source found', icon='ERROR')

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, 'offset')

        if not rf_is_running():
            # RF picks the sources itself when it is running, so this only applies outside it
            draw_snap_to_props(self, context, layout, self.draw_warning)


# Global hotkey outside the tool-scoped one every RF tool already carries in its own bl_keymap
keymaps = []

def register():
    keyconfigs = bpy.context.window_manager.keyconfigs.addon
    if not keyconfigs: return
    km = keyconfigs.keymaps.new(name='Mesh')
    kmi = km.keymap_items.new(RFOperator_TopoRotate.bl_idname, 'R', 'PRESS', ctrl=False, shift=False, alt=True)
    kmi.properties.hotkey = True
    keymaps.append((km, kmi))

def unregister():
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()
