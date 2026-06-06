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
from bpy.props import IntProperty, BoolProperty, EnumProperty, FloatProperty
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from ..common.operator import RFRegisterClass
from ..common.interface import draw_expandable_enum
from ..common.accel import SourceAccel
from ..common.maths import point_to_bvec3
from ..common.raycast import nearest_point_valid_sources
from ..common.sources import draw_hard_surface_snapping
from ..rftool_relax.relax_logic import Relax_Logic, RelaxOptions


class RFOperator_RelaxSelected(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.relax_selected"
    bl_label = "Relax Vertices (Retopoflow)"
    bl_description = "Relax the selected vertices using the Retopoflow relax algorithm"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    rf_label = "Relax Selected Vertices"
    RFCore = None

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
    snap_to: EnumProperty(
        name='Snap To',
        description='Surface to project vertices onto after each relax step',
        items=[
            ('NONE',           'None',           'Do not snap vertices to any surface'),
            ('ORIGINAL_MESH',  'Original Mesh',  'Project each vertex back onto the original mesh shape before relaxation'),
            ('ALL_VISIBLE',    'All Visible',    'Snap to all visible mesh objects in the scene'),
            ('ALL_SELECTABLE', 'All Selectable', 'Snap to all selectable visible mesh objects in the scene'),
            ('OBJECT',         'Object',         'Snap to a specific object'),
            ('COLLECTION',     'Collection',     'Snap to all mesh objects in a specific collection'),
        ],
        default='NONE',
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
    source_edge_angle: bpy.props.FloatProperty(
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
    source_edge_proximity: bpy.props.FloatProperty(
        name='Proximity',
        description='How close to feature edges vertices must be to snap, as a fraction of the average edge length',
        subtype='FACTOR',
        min=0, max=1, default=0.25,
    )
    source_edge_stickiness: bpy.props.FloatProperty(
        name='Stickiness',
        description='How difficult it is for vertices to escape feature edges',
        min=0, max=1, default=0.5,
    )
    source_edge_guide_loops: bpy.props.FloatProperty(
        name='Guide Loops',
        description='How strongly elected loops are pulled toward the source edge',
        subtype='FACTOR',
        min=0, max=1, default=1.0,
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

    def draw_warning(self, layout):
        row = layout.split(factor=0.4)
        row.alert = True
        row.separator()
        row.label(text='No valid source found', icon='ERROR')

    def draw_snapping_props(self, context, layout):
        layout.prop(self, 'snap_to', text='Snap To')
        if self.snap_to == 'OBJECT':
            layout.prop_search(self, 'snap_object', context.blend_data, 'objects', text='Object')
            obj = context.blend_data.objects.get(self.snap_object)
            if obj and not self._is_snap_candidate(context, obj):
                self.draw_warning(layout)
        elif self.snap_to == 'COLLECTION':
            layout.prop_search(self, 'snap_collection', context.blend_data, 'collections', text='Collection')
            collection = context.blend_data.collections.get(self.snap_collection)
            if collection and not self._build_sources_collection(context, collection):
                self.draw_warning(layout)
        elif self.snap_to == 'ALL_VISIBLE':
            if not self._build_sources_visible(context):
                self.draw_warning(layout)
        elif self.snap_to == 'ALL_SELECTABLE':
            if not self._build_sources_selectable(context):
                self.draw_warning(layout)
        if self.snap_to not in ('NONE', 'ORIGINAL_MESH'):
            draw_hard_surface_snapping(layout, self, guide_loops=True)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'strength', slider=True)
        layout.prop(self, 'iterations', slider=True)
        layout.prop(self, 'preserve_volume')
        layout.prop(self, 'smooth_vertices',      text='Smooth Vertices')
        layout.prop(self, 'straighten_edges',     text='Straighten Edges')
        layout.prop(self, 'average_edge_lengths', text='Average Edge Lengths')
        layout.prop(self, 'equalize_faces',       text='Equalize Faces')

        mask_header, mask_panel = layout.panel('relax_selected_mask', default_closed=True)
        mask_header.label(text='Masking')
        if mask_panel:
            mask_panel.row(heading='Include').prop(self, 'include_corners', text='Corners')
            mask_panel.prop(self, 'mask_boundary',  text='Boundary')
            mask_panel.prop(self, 'mask_angle',     text='Sharp Angles')
            row = mask_panel.row()
            row.enabled = self.mask_angle != 'INCLUDE'
            row.prop(self, 'mask_angle_threshold',  text='Threshold')
            mask_panel.prop(self, 'mask_seams',     text='Seams')
            mask_panel.prop(self, 'mask_sharps',    text='Sharps')
            mask_panel.prop(self, 'mask_creases',   text='Creases')

        snap_header, snap_panel = layout.panel('relax_selected_snap', default_closed=True)
        snap_header.label(text='Snapping')
        if snap_panel:
            self.draw_snapping_props(context, snap_panel)

    def execute(self, context):
        sources = []
        if self.snap_to == 'ALL_VISIBLE':
            sources = self._build_sources_visible(context)
        elif self.snap_to == 'ALL_SELECTABLE':
            sources = self._build_sources_selectable(context)
        elif self.snap_to == 'OBJECT':
            obj = context.blend_data.objects.get(self.snap_object)
            sources = self._build_sources_object(context, obj)
        elif self.snap_to == 'COLLECTION':
            collection = context.blend_data.collections.get(self.snap_collection)
            sources = self._build_sources_collection(context, collection)

        options = RelaxOptions(
            algorithm_method='STEPS',
            algorithm_iterations=self.iterations,
            algorithm_laplacian=self.smooth_vertices,
            algorithm_straighten_edges=self.straighten_edges,
            algorithm_average_edge_lengths=self.average_edge_lengths,
            algorithm_equalize_faces=self.equalize_faces,
            source_edge_angle=self.source_edge_angle if self.source_edge_angle_enabled else math.pi,
            source_edge_seams=self.source_edge_seams,
            source_edge_creases=self.source_edge_creases,
            source_edge_sharps=self.source_edge_sharps,
            source_edge_proximity=self.source_edge_proximity,
            source_edge_stickiness=self.source_edge_stickiness,
            source_edge_guide_loops=self.source_edge_guide_loops
        )
        logic = Relax_Logic.for_options(context, options, rf_options=self)

        logic.sources = sources
        # Rebuild the source feature accel with the correct sources after overriding logic.sources
        logic.source_edge_accel = SourceAccel.build_from_tool(context, options, sources)
        logic.source_sharp_proximity = options.source_edge_proximity
        logic.stickiness = options.source_edge_stickiness if logic.source_edge_accel else 0.0

        raw_verts = { bmv for bmv in logic.bm.verts if bmv.select and not bmv.hide }

        # Further filter by boundary, seams, sharps, creases, angle, pins, corners
        verts = logic.filter_verts(raw_verts)
        if not verts:
            self.report({'WARNING'}, 'Relax: no vertices remain after applying mask settings')
            return {'CANCELLED'}

        # Build island BVH now that logic and verts are available
        snap_bvh = None
        if self.snap_to == 'ORIGINAL_MESH':
            snap_bvh = self._build_island_bvh(logic, verts)

        # Capture volume before relaxation, cube root of volume ratio algorithm
        vol_before = abs(logic.bm.calc_volume()) if self.preserve_volume else 0.0

        # Use vert_strength and not pressure to keeps every algo within its stability bounds
        vert_strength = { bmv: self.strength for bmv in verts }
        logic.relax_verts(context, verts, vert_strength, iterations=self.iterations, snap_bvh=snap_bvh, snap_unforced_verts=(self.snap_to != 'NONE'))

        # Volume preservation
        if self.preserve_volume and vol_before > 1e-6:
            vol_after = abs(logic.bm.calc_volume())
            if vol_after > 1e-6:
                scale = (vol_before / vol_after) ** (1.0 / 3.0)
                if abs(scale - 1.0) > 1e-6:  # skip no-op
                    centroid = sum((bmv.co for bmv in verts), Vector()) / len(verts)
                    for bmv in verts:
                        bmv.co = centroid + (bmv.co - centroid) * scale
                    if logic.sources or snap_bvh:
                        # Re-snap to surface so the scaled positions land back on the mesh
                        M  = logic.matrix_world
                        Mi = logic.matrix_world_inv
                        for bmv in verts:
                            co_world = point_to_bvec3((M @ Vector((*bmv.co, 1.0))).xyz)
                            snapped = nearest_point_valid_sources(context, co_world, world=True, sources=logic.sources)
                            if not snapped and snap_bvh:
                                hit_loc, _, _, _ = snap_bvh.find_nearest(co_world)
                                if hit_loc:
                                    snapped = point_to_bvec3(hit_loc)
                            if snapped:
                                bmv.co = Mi @ snapped
                    bmesh.update_edit_mesh(logic.em)

        return {'FINISHED'}

    # ------------------------------------------------------------------
    # Source-building helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _source_tuple(obj):
        M  = obj.matrix_world
        Mi = M.inverted_safe()
        return (obj, M, Mi, Mi.to_3x3())

    @staticmethod
    def _is_snap_candidate(context, obj) -> bool:
        return (
            obj != context.edit_object
            and obj.mode == 'OBJECT'
            and obj.visible_get()
            and obj.type == 'MESH'
            and bool(obj.data.polygons)
        )

    @classmethod
    def _build_sources_visible(cls, context) -> list:
        return [
            cls._source_tuple(obj)
            for obj in context.view_layer.objects
            if cls._is_snap_candidate(context, obj)
        ]

    @classmethod
    def _build_sources_selectable(cls, context) -> list:
        return [
            cls._source_tuple(obj)
            for obj in context.view_layer.objects
            if cls._is_snap_candidate(context, obj) and not obj.hide_select
        ]

    @classmethod
    def _build_sources_object(cls, context, obj) -> list:
        if obj and cls._is_snap_candidate(context, obj):
            return [cls._source_tuple(obj)]
        return []

    @classmethod
    def _build_sources_collection(cls, context, collection) -> list:
        if not collection:
            return []
        return [
            cls._source_tuple(obj)
            for obj in collection.objects
            if cls._is_snap_candidate(context, obj)
        ]

    @staticmethod
    def _build_island_bvh(logic, seed_verts, rings: int = 3) -> 'BVHTree | None':
        ''' Builds a world-space BVH from the original face geometry surrounding the selected verts.
        Three face steps outwards gives enough buffer that no selected vert can project onto geometry
        outside the patch while keeping the BVH fast. '''
        face_set = {
            bmf for bmv in seed_verts
            for bmf in bmv.link_faces
            if not bmf.hide
        }
        frontier = set(face_set)

        for i in range(rings):
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

        M = logic.matrix_world # World space matches relax_verts' projections
        poly_verts   = []
        poly_indices = []
        for bmf in face_set:
            start = len(poly_verts)
            poly_verts.extend(M @ fv.co for fv in bmf.verts)
            poly_indices.append(list(range(start, start + len(bmf.verts))))

        return BVHTree.FromPolygons(poly_verts, poly_indices)
