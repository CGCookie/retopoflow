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

import math
import bpy
import bmesh
from bpy.props import IntProperty, FloatProperty, BoolProperty, EnumProperty, StringProperty

from mathutils import Vector

from ..rfglobals import RFGlobals
from ..common.operator import RFRegisterClass
from ..common.accel import SourceAccel
from ..common.bmesh import get_bmv_avg_edge_len, get_bmv_next_loop_vert
from ..common.bmesh_maths import is_bmvert_pinned
from ..common.maths import point_to_bvec3
from ..common.raycast import iter_all_valid_sources, nearest_point_valid_sources
from ..common.snapping import (
    SNAP_TO_ITEMS, build_island_bvh, build_snap_sources, draw_snap_to_props,
    seed_source_snap_props, source_snap_radius, source_tuple,
)
from ..rfpanels.rfpanel_snapping import draw_hard_surface_snapping
from ..rftool_relax.relax_logic import Relax_Logic, RelaxOptions


def has_space_edge_loops_evenly() -> bool:
    # mesh.space_edge_loops_evenly is new in Blender 5.2
    try:
        bpy.ops.mesh.space_edge_loops_evenly.get_rna_type()
        return True
    except KeyError:
        return False


def rf_is_running() -> bool:
    RFCore = RFGlobals.RFCore_None
    return bool(RFCore and RFCore.is_running)


def is_strip_end_corner(bmv) -> bool:
    return len(bmv.link_edges) == 2 and bool(bmv.link_faces)


class RFOperator_SpaceEvenly(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.space_evenly"
    bl_label = "Even (Retopoflow)"
    bl_description = (
        "For loops, space the vertices of each selected edge loop evenly. \n"
        "For non-loop edges, average their lengths. \n"
        "For faces, optionally average their areas and face angles."
    )
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    rf_label = "Space Selection Evenly"

    factor: FloatProperty(
        name='Factor',
        description='How far vertices move toward their evenly spaced positions',
        subtype='FACTOR',
        min=0.0, max=1.0, default=1.0,
    )
    smooth_loops: BoolProperty(
        name='Smooth Loops',
        description='Space edge loop vertices along a smooth spline fit through the loop instead of '
                    'sliding them along the existing edges',
        default=False,
    )
    face_angles: BoolProperty(
        name='Equalize Faces',
        description='Push face corners toward even angles and average face sizes.',
        default=True,
    )
    preserve_sharp: BoolProperty(
        name='Preserve Sharp Angles',
        description='Keep sharp angles in place.',
        default=True,
    )
    sharp_threshold: FloatProperty(
        name='Threshold',
        description='Corners and edges whose angle deviates from straight or flat by more than this are treated as sharp',
        subtype='ANGLE',
        min=0.0, max=math.radians(180),
        default=math.radians(45),
    )
    iterations: IntProperty(
        name='Iterations',
        description='Number of times to run the relax simulation on face and non-loop edge areas',
        min=1, max=100, default=25,
    )

    # -------------------------------------------------------------------------
    # Source feature snapping, seeded from the Retopoflow snapping settings in invoke
    # -------------------------------------------------------------------------
    snap_to: EnumProperty(
        name='Snap To',
        description='Surface to project vertices onto after each step',
        items=SNAP_TO_ITEMS,
        default='NONE',
    )
    snap_object: StringProperty(
        name='Object',
        description='Name of the object to snap vertices to',
        default='',
    )
    snap_collection: StringProperty(
        name='Collection',
        description='Name of the collection to snap vertices to',
        default='',
    )
    source_edge_sharps: BoolProperty(
        name='Snap to Source Sharps',
        description='Snap vertices to the sharp edges of the source mesh',
        default=False,
    )
    source_edge_seams: BoolProperty(
        name='Snap to Source Seams',
        description='Snap vertices to the seams of the source mesh',
        default=False,
    )
    source_edge_creases: BoolProperty(
        name='Snap to Source Creases',
        description='Snap vertices to the creases of the source mesh',
        default=False,
    )
    source_edge_angle: FloatProperty(
        name='Angle',
        description='Snap to edges above this angle threshold on the source object',
        subtype='ANGLE',
        min=math.radians(1),
        max=math.radians(180),
        default=math.radians(45),
    )
    source_edge_angle_enabled: BoolProperty(
        name='Use Angle Threshold',
        description='Detect sharp edges on the source mesh based on face angle',
        default=False,
    )
    source_edge_proximity: FloatProperty(
        name='Proximity',
        description='How close to feature edges vertices must be to snap, as a fraction of the average edge length',
        subtype='FACTOR',
        min=0, max=1, default=0.25,
    )
    source_edge_use_fixed_distance: BoolProperty(
        name='Fixed Distance',
        description='Snap within a fixed world space distance instead of scaling the snap distance by the local edge length',
        default=False,
    )
    source_edge_fixed_distance: FloatProperty(
        name='Distance',
        description='World space distance within which vertices snap to source feature edges and corners',
        subtype='DISTANCE',
        min=0.0, soft_max=1.0, default=0.05,
    )
    source_edge_stickiness: FloatProperty(
        name='Stickiness',
        description='How difficult it is for vertices to escape feature edges',
        min=0, max=1, default=0.5,
    )
    source_edge_guide_loops: FloatProperty(
        name='Guide Loops',
        description='How strongly elected loops are pulled toward the source edge',
        subtype='FACTOR',
        min=0, max=1, default=1.0,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        if rf_is_running():
            # Start from the tool's own snapping settings rather than this operator's defaults.
            # Redo keeps any tweaks and the next fresh run re-seeds.
            seed_source_snap_props(context, self)
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        # The show_ flags are stashed by execute; before it runs (or after the
        # factor=0 early-out) they are missing and every option stays visible
        layout.prop(self, 'factor', slider=True)

        if getattr(self, 'show_iterations', True):
            layout.prop(self, 'iterations', slider=True)

        split = layout.split(factor=0.4)
        split.use_property_split = False
        label = split.row()
        label.alignment = 'RIGHT'
        label.label(text='Preserve Sharp')
        row = split.row(align=True)
        row.prop(self, 'preserve_sharp', text='')
        sub = row.row()
        sub.enabled = self.preserve_sharp
        sub.prop(self, 'sharp_threshold', text='')

        if getattr(self, 'show_smooth_loops', True):
            row = layout.row()
            row.enabled = has_space_edge_loops_evenly()
            row.row(heading='Smooth Loops').prop(self, 'smooth_loops', text='')

        if getattr(self, 'show_face_angles', True):
            layout.row(heading='Equalize Faces').prop(self, 'face_angles', text='')

        # Every path that moves a vert snaps it, loop runs included
        if getattr(self, 'show_snapping', True):
            running = rf_is_running()
            snap_header, snap_panel = layout.panel('space_evenly_snap', default_closed=True)
            snap_header.label(text='Snapping')
            if snap_panel:
                # Retopoflow supplies the sources itself, so Snap To is only for standalone use
                if not running:
                    draw_snap_to_props(self, context, snap_panel, self.draw_warning)
                if running or self.snap_to not in ('NONE', 'ORIGINAL_MESH'):
                    draw_hard_surface_snapping(snap_panel, context, self, guide_loops=True)

    def draw_warning(self, layout):
        row = layout.split(factor=0.4)
        row.alert = True
        row.separator()
        row.label(text='No valid source found', icon='ERROR')

    def execute(self, context):
        if self.factor <= 0.0:
            return {'FINISHED'}
        me = context.edit_object.data
        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        runs, face_vert_idxs, other_vert_idxs = self.classify_selection(bm)

        if not runs and not face_vert_idxs and not other_vert_idxs:
            self.report({'WARNING'}, 'Space Evenly: nothing selected')
            return {'CANCELLED'}

        if runs and not has_space_edge_loops_evenly():
            # Blender < 5.2 has no mesh.space_edge_loops_evenly, so loop runs
            # fall back to the same averaging the non-loop edges get
            for vert_chain, edge_chain, is_cycle in runs:
                other_vert_idxs.extend(vert_chain)
            runs = []

        self.show_smooth_loops = bool(runs)
        self.show_face_angles = bool(face_vert_idxs)
        self.show_iterations = bool(face_vert_idxs or other_vert_idxs)
        # Every path snaps the verts it moves, so snapping applies to loop runs too
        self.show_snapping = bool(runs or face_vert_idxs or other_vert_idxs)

        if runs:
            # Pinned verts and sharp corners cut runs into sections, and the operator
            # pins each section's endpoints so those verts stay put. Single-edge
            # sections have no interior vert to move and are skipped.
            edge_lists = [
                section
                for run in runs
                for section in self.split_run_at_anchors(bm, run)
                if len(section) >= 2
            ]
            # Both must be captured before spacing: the operator invalidates bm, and an
            # Original Mesh BVH has to describe the shape from before the move
            snap_idxs = set().union(*(self.run_snap_indices(bm, run) for run in runs))
            snap_bvh = (
                build_island_bvh(context.edit_object.matrix_world, [bm.verts[i] for i in snap_idxs])
                if snap_idxs and self.snap_to == 'ORIGINAL_MESH' and not rf_is_running() else None
            )
            if edge_lists:
                self.space_runs(context, me, edge_lists)
            self.snap_spaced_verts(context, me, snap_idxs, snap_bvh)

        if face_vert_idxs or other_vert_idxs:
            self.relax_areas(context, face_vert_idxs, other_vert_idxs)

        return {'FINISHED'}

    # ------------------------------------------------------------------
    # Selection classification
    # ------------------------------------------------------------------

    @classmethod
    def classify_selection(cls, bm):
        ''' Split the selection into connected components and bucket each one:
        edge loop runs (as ordered (vert index chain, edge index chain, is_cycle)
        tuples) for Blender's space-evenly operator, areas with faces (vert indices)
        for Relax's equalize faces, and everything else (vert indices) for Relax's
        average edge lengths. '''
        sel_verts = [bmv for bmv in bm.verts if bmv.select and not bmv.hide]
        sel_edges = [bme for bme in bm.edges if bme.select and not bme.hide]
        sel_faces = [bmf for bmf in bm.faces if bmf.select and not bmf.hide]

        parent = {bmv: bmv for bmv in sel_verts}
        def find(bmv):
            root = bmv
            while parent[root] is not root:
                root = parent[root]
            while parent[bmv] is not root:  # path compression
                parent[bmv], bmv = root, parent[bmv]
            return root
        for bme in sel_edges:
            v0, v1 = bme.verts
            if v0 not in parent or v1 not in parent:
                continue
            r0, r1 = find(v0), find(v1)
            if r0 is not r1:
                parent[r0] = r1

        comp_verts: dict = {}
        for bmv in sel_verts:
            comp_verts.setdefault(find(bmv), []).append(bmv)
        comp_edges: dict = {}
        for bme in sel_edges:
            if bme.verts[0] in parent:
                comp_edges.setdefault(find(bme.verts[0]), []).append(bme)
        face_roots = {
            find(bmf.verts[0]) for bmf in sel_faces
            if bmf.verts[0] in parent
        }

        runs, face_vert_idxs, other_vert_idxs = [], [], []
        for root, verts in comp_verts.items():
            edges = comp_edges.get(root, [])
            if root in face_roots:
                face_vert_idxs.extend(bmv.index for bmv in verts)
                continue
            chain = cls.walk_loop_run(verts, edges) if edges else None
            if chain is not None:
                chain_verts, is_cycle = chain
                edge_lookup = {frozenset(bme.verts): bme.index for bme in edges}
                pair_count = len(chain_verts) if is_cycle else len(chain_verts) - 1
                edge_chain = [
                    edge_lookup[frozenset((chain_verts[i], chain_verts[(i + 1) % len(chain_verts)]))]
                    for i in range(pair_count)
                ]
                runs.append(([bmv.index for bmv in chain_verts], edge_chain, is_cycle))
            else:
                other_vert_idxs.extend(bmv.index for bmv in verts)
        return runs, face_vert_idxs, other_vert_idxs

    @staticmethod
    def walk_loop_run(verts, edges):
        ''' When the component is a single chain or cycle of edges that follows a mesh edge loop,
        returns the ordered vert chain and whether it is a cycle. Returns None for everything else. '''
        adj: dict = {bmv: [] for bmv in verts}
        for bme in edges:
            v0, v1 = bme.verts
            adj[v0].append(v1)
            adj[v1].append(v0)
        if any(len(others) > 2 for others in adj.values()):
            return None  # pole inside the selection

        ends = [bmv for bmv, others in adj.items() if len(others) == 1]
        is_cycle = not ends
        start = ends[0] if ends else verts[0]

        chain = [start]
        prev, cur = None, start
        while True:
            nxt = next((other for other in adj[cur] if other is not prev), None)
            if nxt is None or (is_cycle and nxt is start):
                break
            chain.append(nxt)
            prev, cur = cur, nxt
        if len(chain) != len(verts):
            return None

        n = len(chain)
        if is_cycle:
            triples = ((chain[i-1], chain[i], chain[(i+1) % n]) for i in range(n))
        else:
            triples = zip(chain, chain[1:], chain[2:])
        if not all(get_bmv_next_loop_vert(a, b) is c for a, b, c in triples):
            return None
        return chain, is_cycle

    def run_anchor_positions(self, bm, run) -> set:
        ''' Positions along a run's vert chain that must hold their exact location: verts
        pinned in Retopoflow, and, when Preserve Sharp is on, verts where the path bends
        more than the threshold.'''
        vert_chain, edge_chain, is_cycle = run
        cos = [bm.verts[i].co for i in vert_chain]
        n = len(cos)

        def bends_sharply(i):
            if not is_cycle and i in (0, n - 1):
                return False  # an open end has no bend to measure
            d_in = cos[i] - cos[i - 1]
            d_out = cos[(i + 1) % n] - cos[i]
            if d_in.length < 1e-12 or d_out.length < 1e-12:
                return False
            return d_in.angle(d_out, 0.0) > self.sharp_threshold

        def is_anchor(i):
            bmv = bm.verts[vert_chain[i]]
            # A pin is explicit intent, so it holds even at a strip end
            if is_bmvert_pinned(bm, bmv, ensure_lookup_table=False):
                return True
            return self.preserve_sharp and not is_strip_end_corner(bmv) and bends_sharply(i)

        return {i for i in range(n) if is_anchor(i)}

    def run_snap_indices(self, bm, run) -> set:
        ''' Vert indices in a run that the snapping pass may move, i.e. everything except the anchors. '''
        vert_chain, edge_chain, is_cycle = run
        anchor_positions = self.run_anchor_positions(bm, run)
        return {idx for i, idx in enumerate(vert_chain) if i not in anchor_positions}

    def split_run_at_anchors(self, bm, run):
        ''' Cut a run into sections of consecutive edges at every anchor, so the spacing
        operator's endpoint pinning holds those verts in place. A cycle with a single
        anchor cannot be split by selection alone (its edges still form a closed ring),
        so one edge next to the anchor is left out of the section to hold it. '''
        vert_chain, edge_chain, is_cycle = run
        n = len(vert_chain)
        anchor_positions = self.run_anchor_positions(bm, run)

        if is_cycle:
            anchors = sorted(anchor_positions)
            if not anchors:
                return [edge_chain]
            if len(anchors) == 1:
                start = anchors[0]
                return [(edge_chain[start:] + edge_chain[:start])[:-1]]
            return [
                edge_chain[a:b] if a < b else edge_chain[a:] + edge_chain[:b]
                for a, b in zip(anchors, anchors[1:] + anchors[:1])
            ]

        # An open run's ends already bound the chain, so only interior anchors split it
        anchors = sorted(i for i in anchor_positions if 0 < i < n - 1)
        bounds = [0] + anchors + [n - 1]
        return [edge_chain[a:b] for a, b in zip(bounds, bounds[1:])]

    # ------------------------------------------------------------------
    # Edge loop runs: Blender's Space Edge Loops Evenly, one section at a time
    # ------------------------------------------------------------------

    def space_runs(self, context, me, runs):
        bm = bmesh.from_edit_mesh(me)
        orig_verts = [bmv.index for bmv in bm.verts if bmv.select]
        orig_edges = [bme.index for bme in bm.edges if bme.select]
        orig_faces = [bmf.index for bmf in bm.faces if bmf.select]

        for edge_indices in runs:
            bm = bmesh.from_edit_mesh(me)
            bm.edges.ensure_lookup_table()
            for bmv in bm.verts:
                bmv.select = False
            for i in edge_indices:
                bm.edges[i].select = True
            bm.select_flush_mode()
            bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)
            try:
                bpy.ops.mesh.space_edge_loops_evenly(
                    factor=self.factor,
                    interpolation='CUBIC' if self.smooth_loops else 'LINEAR',
                )
            except RuntimeError as e:
                self.report({'WARNING'}, f'Space Evenly: {e}')

        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()
        for bmv in bm.verts:
            bmv.select = False
        for i in orig_verts:
            bm.verts[i].select = True
        for i in orig_edges:
            bm.edges[i].select = True
        for i in orig_faces:
            bm.faces[i].select = True
        bm.select_flush_mode()
        bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)

    def snap_spaced_verts(self, context, me, vert_idxs, snap_bvh=None):
        ''' Put the spaced loop verts back on the source. '''
        sources = self.snap_sources(context)
        if not vert_idxs or (not sources and not snap_bvh):
            return

        accel = SourceAccel.build_from_tool(context, self, sources)
        M  = context.edit_object.matrix_world
        Mi = M.inverted_safe()
        scale_avg = sum(M.to_scale()) / 3
        corner_factor = RelaxOptions.algorithm_source_corner_proximity

        bm = bmesh.from_edit_mesh(me)
        bm.verts.ensure_lookup_table()
        for i in vert_idxs:
            bmv = bm.verts[i]
            co_world = point_to_bvec3((M @ Vector((*bmv.co, 1.0))).xyz)
            if sources:
                snapped = nearest_point_valid_sources(
                    context, co_world, world=True, sources=sources, respect_clip_planes=True,
                )
                if snapped:
                    co_world = snapped
            elif snap_bvh:
                hit_loc, _, _, _ = snap_bvh.find_nearest(co_world)
                if hit_loc:
                    co_world = point_to_bvec3(hit_loc)

            if accel:
                # Same radius relax uses
                co_vec = Vector(co_world)
                radius = source_snap_radius(
                    get_bmv_avg_edge_len(bmv) * scale_avg,
                    use_fixed=self.source_edge_use_fixed_distance,
                    fixed_distance=self.source_edge_fixed_distance,
                    avg_edge_factor=self.source_edge_proximity,
                )
                corner = accel.find_corner(co_vec)
                if corner and corner[2] <= radius * corner_factor:
                    co_world = corner[0]
                elif (closest := accel.closest_point(co_vec)) and (Vector(closest) - co_vec).length <= radius:
                    co_world = closest

            bmv.co = Mi @ Vector(co_world)
        bmesh.update_edit_mesh(me)

    def snap_sources(self, context) -> list:
        ''' [(obj, M, Mi, Mi_3x3), ...] Retopoflow supplies these itself; standalone they
        come from Snap To. Matches what Relax_Logic.initial_setup builds. '''
        if rf_is_running():
            return [source_tuple(obj) for obj in iter_all_valid_sources(context)]
        return build_snap_sources(
            context, self.snap_to,
            snap_object=self.snap_object, snap_collection=self.snap_collection,
        )

    # ------------------------------------------------------------------
    # Face areas and non-loop edges: Relax forces
    # ------------------------------------------------------------------

    def relax_areas(self, context, face_vert_idxs, other_vert_idxs):
        running = rf_is_running()

        if not self.face_angles:
            other_vert_idxs = other_vert_idxs + face_vert_idxs
            face_vert_idxs = []

        # Reuses the Relax Sharp Angles masking: EXCLUDE pins verts sitting on edges
        # whose face angle exceeds the threshold, so creases hold their exact shape.
        # mask_opt() reads these off rf_options, which is this operator below, so
        # they must be set before the logic is built.
        self.mask_angle = 'EXCLUDE' if self.preserve_sharp else 'INCLUDE'
        self.mask_angle_threshold = self.sharp_threshold
        # Verts pinned in Retopoflow are never relaxed. Outside Retopoflow the pin
        # layer is absent, so this filters nothing.
        self.include_pinned = False

        options = RelaxOptions(
            algorithm_method='STEPS',
            algorithm_iterations=self.iterations,
            algorithm_laplacian=False,
            algorithm_straighten_edges=False,
            algorithm_average_edge_lengths=False,
            algorithm_equalize_faces=False,
            algorithm_slide_edges=True,
            source_edge_angle=self.source_edge_angle if self.source_edge_angle_enabled else math.pi,
            source_edge_seams=self.source_edge_seams,
            source_edge_creases=self.source_edge_creases,
            source_edge_sharps=self.source_edge_sharps,
            source_edge_proximity=self.source_edge_proximity,
            source_edge_use_fixed_distance=self.source_edge_use_fixed_distance,
            source_edge_fixed_distance=self.source_edge_fixed_distance,
            source_edge_stickiness=self.source_edge_stickiness,
            source_edge_guide_loops=self.source_edge_guide_loops,
        )
        logic = Relax_Logic.for_options(context, options, rf_options=self)
        logic.bm.verts.ensure_lookup_table()

        # Snap To defaults to None standalone, so nothing snaps unless the user opts in
        logic.sources = self.snap_sources(context)
        # Same as Relax Selected: the accel is built against whatever sources are in
        # play, but controlled by this operator's own props
        logic.source_edge_accel = SourceAccel.build_from_tool(context, options, logic.sources)
        logic.source_sharp_proximity = options.source_edge_proximity
        logic.source_use_fixed = options.source_edge_use_fixed_distance
        logic.source_fixed_distance = options.source_edge_fixed_distance
        logic.stickiness = options.source_edge_stickiness if logic.source_edge_accel else 0.0
        snap_unforced = bool(logic.sources) if running else (self.snap_to != 'NONE')

        for vert_idxs, algorithm in (
            (face_vert_idxs,  'algorithm_equalize_faces'),
            (other_vert_idxs, 'algorithm_average_edge_lengths'),
        ):
            if not vert_idxs:
                continue
            verts = logic.filter_verts({logic.bm.verts[i] for i in vert_idxs})
            if self.preserve_sharp:
                # Pinned verts are simply left out of the relaxed set, so they act as
                # fixed anchors for their neighbors, same as unselected verts
                verts -= self.sharp_path_verts(verts)
            if not verts:
                continue
            # Built per bucket so each projects onto the shape around its own verts
            snap_bvh = (
                build_island_bvh(logic.matrix_world, verts)
                if not running and self.snap_to == 'ORIGINAL_MESH' else None
            )
            setattr(options, algorithm, True)
            vert_strength = {bmv: self.factor for bmv in verts}
            logic.relax_verts(
                context, verts, vert_strength,
                iterations=self.iterations,
                snap_bvh=snap_bvh,
                snap_unforced_verts=snap_unforced,
            )
            setattr(options, algorithm, False)

    def sharp_path_verts(self, verts):
        ''' Verts that sit on a sharp corner. Either the mesh boundary turns sharply
        through the vert, which catches flat, in-plane corners that the face-angle
        mask cannot see, or even the straightest continuation of the selected edge
        path turns sharply, so a pole with a straight-through pair stays free. '''
        def direction(bme, bmv):
            d = bme.other_vert(bmv).co - bmv.co
            return d.normalized() if d.length > 1e-12 else None

        sharp = set()
        for bmv in verts:
            if is_strip_end_corner(bmv):
                continue
            boundary_dirs = [
                d for bme in bmv.link_edges
                if bme.is_boundary and (d := direction(bme, bmv)) is not None
            ]
            if len(boundary_dirs) == 2 and (-boundary_dirs[0]).angle(boundary_dirs[1], 0.0) > self.sharp_threshold:
                sharp.add(bmv)
                continue
            dirs = [
                d for bme in bmv.link_edges
                if bme.select and (d := direction(bme, bmv)) is not None
            ]
            if len(dirs) < 2:
                continue
            straightest = min(
                (-dirs[i]).angle(dirs[j], 0.0)
                for i in range(len(dirs))
                for j in range(i + 1, len(dirs))
            )
            if straightest > self.sharp_threshold:
                sharp.add(bmv)
        return sharp
