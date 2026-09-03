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

from ..rfglobals import RFGlobals
from ..common.operator import RFRegisterClass, hotkey_owns_context
from ..common.interface import draw_expandable_enum
from ..common.accel import SourceAccel
from ..common.bmesh import get_falloff_verts
from ..common.maths import point_to_bvec3
from ..common.raycast import nearest_point_valid_sources
from ..common.snapping import (
    build_island_bvh, build_snap_sources, draw_snap_to_props, seed_source_snap_props,
)
from ..rfpanels.rfpanel_snapping import draw_hard_surface_snapping
from ..rftool_relax.relax_logic import Relax_Logic, RelaxOptions


class RFOperator_RelaxSelected(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.relax_selected"
    bl_label = "Relax (Retopoflow)"
    bl_description = "Relax the selected vertices using the Retopoflow relax algorithm"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    rf_label = "Relax Selected Vertices"

    # set on the standalone Mesh-keymap item only, so hotkey_owns_context governs the key
    # and not the right-click menu entry
    hotkey: BoolProperty(
        name='From Hotkey',
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    # -------------------------------------------------------------------------
    # Algorithm settings
    # -------------------------------------------------------------------------
    iterations: IntProperty(
        name='Iterations',
        description='Number of times to run the relax simulation. Higher is smoother and slower',
        min=1, max=100, default=25,
    )
    strength: FloatProperty(
        name='Strength',
        description='How far vertices move per iteration',
        subtype='FACTOR',
        min=0.01, max=1.0, default=1,
    )
    smooth_vertices: BoolProperty(
        name='Smooth Vertices',
        description='Average vertex locations using Laplacian smoothing',
        default=True,
    )
    straighten_edges: BoolProperty(
        name='Straighten Edges',
        description='Move each vertex toward making its connected edges straighter, using loop information when possible',
        default=False,
    )
    average_edge_lengths: BoolProperty(
        name='Average Edge Lengths',
        description='Squash or stretch each edge toward the average edge length. Can cause skewing when used by itself',
        default=False,
    )
    equalize_faces: BoolProperty(
        name='Equalize Faces',
        description='Push faces towards ideal geometric shapes and average their sizes',
        default=False,
    )
    shaping: EnumProperty(
        name='Shaping',
        description='Post-processing applied after each relax step to control overall shape',
        items=[
            ('NONE', 'None', 'No additional shaping'),
            ('PRESERVE_VOLUME', 'Preserve Volume', 'Scales relaxed vertices so the mesh stays the same size'),
            ('INTERPOLATE_LOOPS', 'Interpolate Loop Curvature',
                "Uses the loop edges just outside the selection to create the loop's curvature. "
                "Can be used to reconstruct a quad patch on a sphere, for example"),
            ('SLIDE_EDGES', 'Slide Edges', 'Restrict vertex movement to be along their connected edges'),
        ],
        default='PRESERVE_VOLUME',
    )
    use_proportional_edit: BoolProperty(
        name='Proportional Editing',
        description='Relax nearby connected vertices with a falloff for the strength',
        default=False,
    )
    proportional_distance: FloatProperty(
        name='Distance',
        description='Radius within which connected vertices are included',
        subtype='DISTANCE',
        min=0.001,
        default=1.0,
    )
    proportional_falloff: EnumProperty(
        name='Falloff',
        description='Shape of the strength curve from center to edge of the proportional radius',
        items=[
            ('SMOOTH',         'Smooth',         'Smooth falloff (3t² - 2t³)',                'SMOOTHCURVE',   0),
            ('SPHERE',         'Sphere',         'Spherical falloff (√(1 - t²))',            'SPHERECURVE',   1),
            ('ROOT',           'Root',           'Root falloff (√(1 - t))',                  'ROOTCURVE',     2),
            ('INVERSE_SQUARE', 'Inverse Square', 'Inverse-square falloff (1/(1+t))',          'INVERSESQUARECURVE', 3),
            ('SHARP',          'Sharp',          'Sharp falloff (t²)',                        'SHARPCURVE',    4),
            ('LINEAR',         'Linear',         'Linear falloff (1 - t)',                    'LINCURVE',      5),
            ('CONSTANT',       'Constant',       'No falloff — all verts get full strength',  'NOCURVE',       6),
            ('RANDOM',         'Random',         'Random falloff',                            'RNDCURVE',      7),
        ],
        default='SMOOTH',
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
    source_edge_use_fixed_distance: bpy.props.BoolProperty(
        name='Fixed Distance',
        description='Snap within a fixed world space distance instead of scaling the snap distance by the local edge length',
        default=False,
    )
    source_edge_fixed_distance: bpy.props.FloatProperty(
        name='Distance',
        description='World space distance within which vertices snap to source feature edges and corners',
        subtype='DISTANCE',
        min=0.0, soft_max=1.0, default=0.05,
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

    # -------------------------------------------------------------------------
    # Debug settings
    # -------------------------------------------------------------------------
    debug_select: EnumProperty(
        name='Select',
        description='After relaxing, replace the selection with the chosen guide-loop vert set for debugging',
        items=[
            ('ALL',      'All',      'Leave selection unchanged after relaxing'),
            ('PROMOTED', 'Promoted', 'Select only the elected guide-loop vertices'),
            ('DEMOTED',  'Demoted',  'Select only the demoted (pushed-away) vertices'),
        ],
        default='ALL',
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'EDIT_MESH'

    def invoke(self, context, event):
        if self.hotkey and not hotkey_owns_context(context, 'relax_tool_context'):
            return {'PASS_THROUGH'}
        ts = context.tool_settings
        self.use_proportional_edit  = ts.use_proportional_edit
        self.proportional_distance  = ts.proportional_size
        self.proportional_falloff   = ts.proportional_edit_falloff
        RFCore = RFGlobals.RFCore_None
        if RFCore and RFCore.is_running:
            # Start from the tool's own snapping settings rather than this operator's defaults.
            # Redo keeps any tweaks and the next fresh run re-seeds.
            seed_source_snap_props(context, self)
        return self.execute(context)

    def draw_warning(self, layout):
        row = layout.split(factor=0.4)
        row.alert = True
        row.separator()
        row.label(text='No valid source found', icon='ERROR')

    def draw_snapping_props(self, context, layout, show_snap_to=True):
        if show_snap_to:
            draw_snap_to_props(self, context, layout, self.draw_warning)
        if not show_snap_to or self.snap_to not in ('NONE', 'ORIGINAL_MESH'):
            draw_hard_surface_snapping(layout, context, self, guide_loops=True)
            # layout.prop(self, 'debug_select', text='Select') # highlight for debugging promoted / demoted

    def draw(self, context):
        RFCore = RFGlobals.RFCore_None

        rf_is_running = RFCore and RFCore.is_running

        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'strength', slider=True)
        layout.prop(self, 'iterations', slider=True)
        layout.prop(self, 'shaping', text='Shaping')
        layout.separator()
        layout.row(heading="Smooth").prop(self, 'smooth_vertices', text='Vertices')
        layout.row(heading="Average").prop(self, 'average_edge_lengths', text='Edges')
        layout.row(heading="Straighten").prop(self, 'straighten_edges', text='Edges')
        layout.row(heading="Equalize").prop(self, 'equalize_faces', text='Faces')

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
            self.draw_snapping_props(context, snap_panel, show_snap_to=not rf_is_running)

        prop_header, prop_panel = layout.panel('relax_selected_proportional', default_closed=True)
        prop_header.use_property_split=False
        prop_header.prop(self, 'use_proportional_edit', text='Proportional Editing')
        if prop_panel:
            prop_panel.use_property_split = True
            prop_panel.use_property_decorate = False
            prop_panel.enabled = self.use_proportional_edit
            prop_panel.prop(self, 'proportional_distance', text='Distance')
            prop_panel.prop(self, 'proportional_falloff',  text='Falloff')

    def execute(self, context):
        RFCore = RFGlobals.RFCore_None

        rf_is_running = RFCore and RFCore.is_running

        sources = []
        if not rf_is_running:
            sources = build_snap_sources(
                context, self.snap_to,
                snap_object=self.snap_object, snap_collection=self.snap_collection,
            )

        options = RelaxOptions(
            algorithm_method='STEPS',
            algorithm_iterations=self.iterations,
            algorithm_laplacian=self.smooth_vertices,
            algorithm_straighten_edges=self.straighten_edges,
            algorithm_average_edge_lengths=self.average_edge_lengths,
            algorithm_equalize_faces=self.equalize_faces,
            algorithm_interpolate_loops=self.shaping == 'INTERPOLATE_LOOPS',
            algorithm_slide_edges=self.shaping == 'SLIDE_EDGES',
            source_edge_angle=self.source_edge_angle if self.source_edge_angle_enabled else math.pi,
            source_edge_seams=self.source_edge_seams,
            source_edge_creases=self.source_edge_creases,
            source_edge_sharps=self.source_edge_sharps,
            source_edge_proximity=self.source_edge_proximity,
            source_edge_use_fixed_distance=self.source_edge_use_fixed_distance,
            source_edge_fixed_distance=self.source_edge_fixed_distance,
            source_edge_stickiness=self.source_edge_stickiness,
            source_edge_guide_loops=self.source_edge_guide_loops
        )
        logic = Relax_Logic.for_options(context, options, rf_options=self)

        if not rf_is_running:
            logic.sources = sources

        # Always rebuild the source feature accel from the operator's own settings.
        # When RF is running, logic.sources already holds the RF sources from initial_setup,
        # so the accel is built against those sources but controlled by the operator's props.
        logic.source_edge_accel = SourceAccel.build_from_tool(context, options, logic.sources)
        logic.source_sharp_proximity = options.source_edge_proximity
        logic.source_use_fixed = options.source_edge_use_fixed_distance
        logic.source_fixed_distance = options.source_edge_fixed_distance
        logic.stickiness = options.source_edge_stickiness if logic.source_edge_accel else 0.0

        raw_verts = { bmv for bmv in logic.bm.verts if bmv.select and not bmv.hide }

        # Further filter by boundary, seams, sharps, creases, angle, pins, corners
        verts = logic.filter_verts(raw_verts)
        if not verts:
            self.report({'WARNING'}, 'Relax: no vertices remain after applying mask settings')
            return {'CANCELLED'}

        # Build proportional vert set: flood-fill along connected edges within the radius,
        # restricted to unselected verts so selected verts always get full strength.
        vert_strength: dict = { bmv: self.strength for bmv in verts }
        if self.use_proportional_edit and self.proportional_distance > 0:
            mw = context.edit_object.matrix_world
            prop_weights = get_falloff_verts(verts, mw, self.proportional_distance, self.proportional_falloff)
            prop_verts = {v: w * self.strength for v, w in prop_weights.items() if v not in verts}
            vert_strength.update(prop_verts)
            verts = verts | set(prop_verts.keys())

        # Build island BVH now that logic and verts are available
        snap_bvh = None
        if not rf_is_running and self.snap_to == 'ORIGINAL_MESH':
            snap_bvh = build_island_bvh(logic.matrix_world, verts)

        # Capture volume before relaxation, cube root of volume ratio algorithm
        preserve_volume = self.shaping == 'PRESERVE_VOLUME'
        vol_before = abs(logic.bm.calc_volume()) if preserve_volume else 0.0

        # Use vert_strength and not pressure to keeps every algo within its stability bounds
        snap_unforced = bool(logic.sources) if rf_is_running else (self.snap_to != 'NONE')
        logic.relax_verts(context, verts, vert_strength, iterations=self.iterations, snap_bvh=snap_bvh, snap_unforced_verts=snap_unforced)

        # Volume preservation
        if preserve_volume and vol_before > 1e-6:
            vol_after = abs(logic.bm.calc_volume())
            if vol_after > 1e-6:
                scale = (vol_before / vol_after) ** (1.0 / 3.0)
                if abs(scale - 1.0) > 1e-6:  # skip no-op
                    centroid = sum((bmv.co for bmv in verts), Vector()) / len(verts)
                    strength_max = max(self.strength, 1e-8)
                    for bmv in verts:
                        co_scaled = centroid + (bmv.co - centroid) * scale
                        w = vert_strength.get(bmv, 0.0) / strength_max
                        bmv.co = bmv.co.lerp(co_scaled, w)
                    if logic.sources or snap_bvh:
                        # Re-snap to surface so the scaled positions land back on the mesh
                        M  = logic.matrix_world
                        Mi = logic.matrix_world_inv
                        for bmv in verts:
                            co_world = point_to_bvec3((M @ Vector((*bmv.co, 1.0))).xyz)
                            snapped = nearest_point_valid_sources(context, co_world, world=True, sources=logic.sources, respect_clip_planes=True)
                            if not snapped and snap_bvh:
                                hit_loc, _, _, _ = snap_bvh.find_nearest(co_world)
                                if hit_loc:
                                    snapped = point_to_bvec3(hit_loc)
                            if snapped:
                                bmv.co = Mi @ snapped
                    bmesh.update_edit_mesh(logic.em)

        if not rf_is_running and self.debug_select != 'ALL':
            target = logic.promoted_loop_verts if self.debug_select == 'PROMOTED' else logic.demoted_verts
            for bmv in logic.bm.verts:
                bmv.select = bmv in target
            logic.bm.select_flush_mode()
            bmesh.update_edit_mesh(logic.em)

        logic.bm.normal_update()
        bmesh.update_edit_mesh(logic.em, loop_triangles=False)

        return {'FINISHED'}


keymaps = []

def register():
    keyconfigs = bpy.context.window_manager.keyconfigs.addon
    if not keyconfigs: return
    km = keyconfigs.keymaps.new(name='Mesh')
    kmi = km.keymap_items.new(RFOperator_RelaxSelected.bl_idname, 'R', 'PRESS', ctrl=False, shift=True, alt=False)
    kmi.properties.hotkey = True
    keymaps.append((km, kmi))

def unregister():
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()
