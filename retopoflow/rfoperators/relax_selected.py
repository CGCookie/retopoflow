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

# A plain Blender operator that drives the extracted relax core (Relax_Logic.relax_verts)
# on the current vertex selection.  Primarily a test harness for the core now that it is
# decoupled from the brush, and a reference for how Tweak will call it after a grab.

import math
import bpy
import bmesh
from bpy.props import IntProperty, BoolProperty, EnumProperty, FloatProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..common.operator import RFRegisterClass
from ..common.interface import draw_expandable_enum
from ..rftool_relax.relax_logic import Relax_Logic, RelaxOptions


def _vertex_menu_draw(self, context):
    self.layout.separator()
    self.layout.operator("retopoflow.relax_selected", icon='MOD_SMOOTH')


class RFOperator_RelaxSelected(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.relax_selected"
    bl_label = "Relax Vertices (Retopoflow)"
    bl_description = "Relax the selected vertices using the Retopoflow relax algorithm"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    rf_label = "Relax Selected Vertices"
    RFCore = None

    @classmethod
    def register(cls):
        bpy.types.VIEW3D_MT_edit_mesh_vertices.append(_vertex_menu_draw)

    @classmethod
    def unregister(cls):
        bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(_vertex_menu_draw)

    # -------------------------------------------------------------------------
    # Algorithm settings
    # -------------------------------------------------------------------------
    iterations: IntProperty(
        name='Iterations',
        description='Number of relax integration steps to apply',
        min=1, max=100, default=50,
    )
    strength: FloatProperty(
        name='Strength',
        description='How far vertices move per iteration — equivalent to brush strength',
        subtype='FACTOR',
        min=0.01, max=1.0, default=0.5,
    )
    smooth_vertices: BoolProperty(
        name='Smooth Vertices',
        description='Average vertex locations (Laplacian smooth)',
        default=True,
    )
    straighten_edges: BoolProperty(
        name='Straighten Edges',
        description='Move each vertex toward making its connected edges straighter',
        default=False,
    )
    average_edge_lengths: BoolProperty(
        name='Average Edge Lengths',
        description='Squash / stretch each edge toward the average edge length',
        default=False,
    )
    equalize_faces: BoolProperty(
        name='Equalize Faces',
        description='Even out face size and spread (slower)',
        default=False,
    )
    preserve_volume: BoolProperty(
        name='Preserve Volume',
        description=(
            'Scale the relaxed vertices so the mesh stays the same size as before. '
            'Uses the standard cube-root-of-volume-ratio method: computes the mesh '
            'volume before and after relaxation and scales by (V_before/V_after)^(1/3). '
            'Works on both closed and open meshes'
        ),
        default=True,
    )
    reproject_shape: BoolProperty(
        name='Reproject onto Shape',
        description=(
            'Project each vertex back onto the original mesh surface after every relax step, '
            'preserving the overall shape while improving topology. '
            'Uses the full mesh island connected to the selection as the projection surface. '
            'Ignored when a source object is present (the source is used instead)'
        ),
        default=False,
    )

    # -------------------------------------------------------------------------
    # Masking settings
    # -------------------------------------------------------------------------
    mask_selected: EnumProperty(
        name='Selected',
        description='Which vertices to relax based on selection state',
        items=[
            ('ALL',     'All',     'Relax all vertices regardless of selection',  'SELECT_EXTEND',     2),
            ('ONLY',    'Only',    'Relax only selected vertices',                'SELECT_INTERSECT',  1),
            ('EXCLUDE', 'Exclude', 'Relax only unselected vertices',              'SELECT_DIFFERENCE', 0),
        ],
        default='ONLY',
    )
    mask_boundary: EnumProperty(
        name='Boundary',
        description='How to handle boundary geometry',
        items=[
            ('INCLUDE', 'Include', 'Relax vertices regardless of being along boundary',              'SELECT_EXTEND',     2),
            ('SLIDE',   'Slide',   'Relax vertices along boundary, sliding along boundary edges',    'SNAP_MIDPOINT',     1),
            ('EXCLUDE', 'Exclude', 'Do not relax vertices along boundary',                           'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_seams: EnumProperty(
        name='Seams',
        description='How to handle seam edges',
        items=[
            ('INCLUDE', 'Include', 'Relax vertices regardless of being along a seam',  'SELECT_EXTEND',     2),
            ('SLIDE',   'Slide',   'Relax vertices along seams by sliding along them', 'SNAP_MIDPOINT',     1),
            ('EXCLUDE', 'Exclude', 'Do not relax vertices along seams',                'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_sharps: EnumProperty(
        name='Sharps',
        description='How to handle sharp edges',
        items=[
            ('INCLUDE', 'Include', 'Relax vertices regardless of being along a sharp edge',  'SELECT_EXTEND',     2),
            ('SLIDE',   'Slide',   'Relax vertices along sharp edges by sliding along them', 'SNAP_MIDPOINT',     1),
            ('EXCLUDE', 'Exclude', 'Do not relax vertices along sharp edges',                'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_creases: EnumProperty(
        name='Creases',
        description='How to handle creased edges',
        items=[
            ('INCLUDE', 'Include', 'Relax vertices regardless of being along a crease',  'SELECT_EXTEND',     2),
            ('SLIDE',   'Slide',   'Relax vertices along creases by sliding along them', 'SNAP_MIDPOINT',     1),
            ('EXCLUDE', 'Exclude', 'Do not relax vertices along creases',                'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_angle: EnumProperty(
        name='Sharp Angles',
        description='How to handle vertices on edges whose adjacent faces exceed the angle threshold',
        items=[
            ('INCLUDE', 'Include', 'Relax vertices regardless of edge angle',                                   'SELECT_EXTEND',     2),
            ('SLIDE',   'Slide',   'Relax vertices along high-angle edges by sliding along them',               'SNAP_MIDPOINT',     1),
            ('EXCLUDE', 'Exclude', 'Do not relax vertices that lie on edges exceeding the angle threshold',     'SELECT_DIFFERENCE', 0),
        ],
        default='INCLUDE',
    )
    mask_angle_threshold: FloatProperty(
        name='Threshold',
        description='Edges whose adjacent face dihedral angle exceeds this value are treated as high-angle',
        subtype='ANGLE',
        min=math.radians(0),
        max=math.radians(180),
        default=math.radians(45),
    )
    include_corners: BoolProperty(
        name='Corners',
        description='Include corners (vertices with exactly two edges)',
        default=True,
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'strength', slider=True)
        layout.prop(self, 'iterations', slider=True)
        layout.prop(self, 'preserve_volume')
        layout.prop(self, 'reproject_shape', text='Reproject')
        layout.separator()
        col = layout.column(heading='Algorithm')
        col.prop(self, 'smooth_vertices',      text='Smooth Vertices')
        col.prop(self, 'straighten_edges',     text='Straighten Edges')
        col.prop(self, 'average_edge_lengths', text='Average Edge Lengths')
        col.prop(self, 'equalize_faces',       text='Equalize Faces')
        layout.separator()
        layout.row(heading='Include').prop(self, 'include_corners', text='Corners')
        layout.prop( self, 'mask_boundary',  text='Boundary',    )
        layout.prop( self, 'mask_angle',     text='Sharp Angles',)
        row = layout.row()
        row.enabled = self.mask_angle != 'INCLUDE'
        row.prop(self, 'mask_angle_threshold', text='Threshold')
        layout.prop( self, 'mask_seams',     text='Seams',       )
        layout.prop( self, 'mask_sharps',    text='Sharps',      )
        layout.prop( self, 'mask_creases',   text='Creases',     )

    def execute(self, context):
        # Build a plain options object and a brush-less engine, then drive the shared core.
        # Pass self as rf_options so the engine uses this operator's own mask_*/include_*
        # props rather than context.scene.retopoflow.
        options = RelaxOptions(
            algorithm_method='STEPS',
            algorithm_iterations=self.iterations,
            algorithm_laplacian=self.smooth_vertices,
            algorithm_straighten_edges=self.straighten_edges,
            algorithm_average_edge_lengths=self.average_edge_lengths,
            algorithm_equalize_faces=self.equalize_faces,
        )
        logic = Relax_Logic.for_options(context, options, rf_options=self)

        raw_verts = { bmv for bmv in logic.bm.verts if     bmv.select and not bmv.hide }

        # Further filter by boundary, seams, sharps, creases, angle, pins, corners.
        verts = logic.filter_verts(raw_verts)
        if not verts:
            self.report({'WARNING'}, 'Relax: no vertices remain after applying mask settings')
            return {'CANCELLED'}

        # Build an island BVH from the original mesh shape if requested and there is no
        # source object to project onto. Capture positions NOW, before any relaxation.
        snap_bvh = None
        if self.reproject_shape and not logic.sources:
            snap_bvh = self._build_island_bvh(logic, verts)

        # Capture volume before relaxation (cube-root-of-volume-ratio algorithm).
        vol_before = abs(logic.bm.calc_volume()) if self.preserve_volume else 0.0

        # Scale vert_strength by the user's strength setting rather than using pressure.
        # pressure is a final multiplier applied after integration, so pressure > 2 causes
        # straighten_edges (0.5× step fraction) to overshoot and diverge.  Scaling
        # vert_strength instead keeps every algorithm within its stability bounds: the worst
        # case (straighten at strength=1.0) is 0.5 × 1.0 = 0.5 < 1.0, always convergent.
        vert_strength = { bmv: self.strength for bmv in verts }
        logic.relax_verts(context, verts, vert_strength, iterations=self.iterations, snap_bvh=snap_bvh)

        # Volume preservation: scale selected verts around their centroid so the overall
        # mesh volume matches what it was before relaxation.
        if self.preserve_volume and vol_before > 1e-6:
            vol_after = abs(logic.bm.calc_volume())
            if vol_after > 1e-6:
                scale = (vol_before / vol_after) ** (1.0 / 3.0)
                if abs(scale - 1.0) > 1e-6:  # skip trivial no-op
                    centroid = sum((bmv.co for bmv in verts), Vector()) / len(verts)
                    for bmv in verts:
                        bmv.co = centroid + (bmv.co - centroid) * scale
                    bmesh.update_edit_mesh(logic.em)

        return {'FINISHED'}

    @staticmethod
    def _build_island_bvh(logic, seed_verts, rings: int = 3) -> 'BVHTree | None':
        ''' Build a world-space BVH from the original (pre-relaxation) face geometry
        surrounding the selected verts.

        Expands outward `rings` times via face adjacency using a frontier-only BFS so each
        step is O(new faces in that ring), not O(all accumulated faces).  Three rings gives
        enough buffer that no selected vert can project onto geometry outside the patch,
        while keeping the BVH small and fast to build on any mesh size. '''
        # Seed: all non-hidden faces that directly touch a selected vert.
        face_set = {
            bmf for bmv in seed_verts
            for bmf in bmv.link_faces
            if not bmf.hide
        }
        frontier = set(face_set)

        for _ in range(rings):
            next_frontier = set()
            for bmf in frontier:
                for bme in bmf.edges:
                    for adj in bme.link_faces:
                        if not adj.hide and adj not in face_set:
                            next_frontier.add(adj)
            face_set |= next_frontier
            frontier = next_frontier
            if not frontier:
                break  # mesh boundary reached, nothing left to expand into

        if not face_set:
            return None

        # Capture vertex positions now — before any relaxation — to freeze the original shape.
        # Build in world space so it matches relax_verts' world-space projections.
        M = logic.matrix_world
        poly_verts   = []
        poly_indices = []
        for bmf in face_set:
            start = len(poly_verts)
            poly_verts.extend(M @ fv.co for fv in bmf.verts)
            poly_indices.append(list(range(start, start + len(bmf.verts))))

        return BVHTree.FromPolygons(poly_verts, poly_indices)
