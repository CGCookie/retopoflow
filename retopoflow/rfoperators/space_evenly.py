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
from bpy.props import IntProperty, FloatProperty, BoolProperty

from ..rfglobals import RFGlobals
from ..common.operator import RFRegisterClass
from ..common.bmesh import get_bmv_next_loop_vert
from ..common.bmesh_maths import is_bmvert_pinned
from ..rftool_relax.relax_logic import Relax_Logic, RelaxOptions


def has_space_edge_loops_evenly() -> bool:
    # mesh.space_edge_loops_evenly is new in Blender 5.2
    try:
        bpy.ops.mesh.space_edge_loops_evenly.get_rna_type()
        return True
    except KeyError:
        return False


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

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

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
            if edge_lists:
                self.space_runs(context, me, edge_lists)

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

    def split_run_at_anchors(self, bm, run):
        ''' Cut a run into sections of consecutive edges at every vert that must hold
        its position: verts pinned in Retopoflow, and, when Preserve Sharp is on, verts
        where the path bends more than the threshold. A cycle with a single anchor
        cannot be split by selection alone (its edges still form a closed ring), so one
        edge next to the anchor is left out of the section to hold it in place. '''
        vert_chain, edge_chain, is_cycle = run
        cos = [bm.verts[i].co for i in vert_chain]
        n = len(cos)

        def bends_sharply(i):
            d_in = cos[i] - cos[i - 1]
            d_out = cos[(i + 1) % n] - cos[i]
            if d_in.length < 1e-12 or d_out.length < 1e-12:
                return False
            return d_in.angle(d_out, 0.0) > self.sharp_threshold

        def is_anchor(i):
            if is_bmvert_pinned(bm, bm.verts[vert_chain[i]], ensure_lookup_table=False):
                return True
            return self.preserve_sharp and bends_sharply(i)

        if is_cycle:
            anchors = [i for i in range(n) if is_anchor(i)]
            if not anchors:
                return [edge_chain]
            if len(anchors) == 1:
                start = anchors[0]
                return [(edge_chain[start:] + edge_chain[:start])[:-1]]
            return [
                edge_chain[a:b] if a < b else edge_chain[a:] + edge_chain[:b]
                for a, b in zip(anchors, anchors[1:] + anchors[:1])
            ]

        anchors = [i for i in range(1, n - 1) if is_anchor(i)]
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

    # ------------------------------------------------------------------
    # Face areas and non-loop edges: Relax forces
    # ------------------------------------------------------------------

    def relax_areas(self, context, face_vert_idxs, other_vert_idxs):
        RFCore = RFGlobals.RFCore_None
        rf_is_running = bool(RFCore and RFCore.is_running)

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
        )
        logic = Relax_Logic.for_options(context, options, rf_options=self)
        logic.bm.verts.ensure_lookup_table()

        # Outside Retopoflow there is no snapping, matching Relax Selected's default
        if not rf_is_running:
            logic.sources = []
            logic.source_edge_accel = None
            logic.stickiness = 0.0
        snap_unforced = bool(logic.sources)

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
            setattr(options, algorithm, True)
            vert_strength = {bmv: self.factor for bmv in verts}
            logic.relax_verts(
                context, verts, vert_strength,
                iterations=self.iterations,
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
