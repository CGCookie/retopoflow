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

import os
import time
from itertools import chain
from math import sqrt, atan2, radians

import bpy
from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..rftool_base import RFTool_Base
from ..rfbrushes.stroke_brush import create_stroke_brush
from ..preferences import RF_Prefs

from ...addon_common.common import gpustate
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.colors import Color4
from ...addon_common.common.decorators import add_cache
from ...addon_common.common.debug import debugger
from ...addon_common.common.maths import Frame, Direction
from ...addon_common.common.resetter import Resetter
from ...addon_common.common.utils import iter_pairs

from ..common.bmesh import get_bmesh_emesh
from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_TRIANGLES,
)
from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    poll_retopoflow,
    chain_rf_keymaps,
    RFOperator,
    RFOperator_Execute,
    RFAssetShelf,
    RFRegisterClass,
    wrap_property,
)
from ..common.maths import (
    direction_to_bvec4,
    view_right_direction,
    view_up_direction,
    point_to_bvec4,
    normal_to_bvec4,
    vector_to_bvec4,
)
from ..common.raycast import (
    ray_from_mouse,
    raycast_ray_valid_sources,
    raycast_valid_sources,
    nearest_point_normal_valid_sources,
    size2D_to_size,
)

from ..rfpanels.mesh_cleanup_panel import draw_cleanup_panel
from ..rfpanels.tweaking_panel import draw_tweaking_panel
from ..rfpanels.general_panel import draw_general_panel
from ..rfpanels.mirror_panel import draw_mirror_panel
from ..rfpanels.help_panel import draw_help_panel

from .patches_logic import Patches_Logic, Patches_Template




ASSETS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'assets'))


RFBrush_Patches, RFOperator_PatchesBrush_Adjust = create_stroke_brush(
    'patches_brush',
    'Patches Brush',
    radius=50,
    smoothing=0.5,
)

class Patches_Insert_Modes:
    insert_modes = [
        # (identifier, name, description, icon, number)  or  (identifier, name, description, number)
        # must have number?
        # None is a separator
        ("RAYCAST", "Raycast", "Orient new patch based on normal under mouse", 1),
        ("SCREEN",  "Screen",  "Orient new patch to be aligned with view",     2),
        ("CUT",     "Cut",     "Use cuts to orient new patch",                 3),  # cylindrical patches
    ]
    insert_mode = 1

    @staticmethod
    def generate_operators():
        print('GENERATING PATCHES SET INSERT MODE OPERATORS')
        ops_insert = []
        def gen_insert_mode(idname, label, value):
            nonlocal ops_insert
            mode_idname = f'patches_setinsertmode_{idname.lower()}'
            rf_idname = f'retopoflow.{mode_idname}'
            rf_label = label
            class RFTool_OT_Patches_SetInsertMode:
                bl_idname = rf_idname
                bl_label = rf_label
                bl_description = f'Set Patches Insert Mode to {label}'
                def execute(self, context):
                    Patches_Insert_Modes.set_insert_mode(None, value)
                    context.area.tag_redraw()
                    return {'FINISHED'}
            opname = f'RFTool_OT_Patches_SetInsertMode_{idname}'
            op = type(opname, (RFTool_OT_Patches_SetInsertMode, RFRegisterClass, bpy.types.Operator), {})
            ops_insert += [(rf_idname, rf_label)]
            return op

        gen_insert_mode('Raycast', 'Raycast', 1)
        gen_insert_mode('Screen',  'Screen',  2)
        gen_insert_mode('Cut',     'Cut',     3)

    @staticmethod
    def get_insert_mode(self): return Patches_Insert_Modes.insert_mode
    @staticmethod
    def set_insert_mode(self, v): Patches_Insert_Modes.insert_mode = v

# TODO: DO NOT CALL THIS HERE!  SHOULD ONLY GET CALLED ONCE
#       COULD POTENTIALLY CREATE MULTIPLE OPERATORS WITH SAME NAME
Patches_Insert_Modes.generate_operators()

class RFOperator_Patches_Insert_Properties:
    rotate: bpy.props.FloatProperty(
        name='Rotate Topology',
        description='Angle to rotate the topology',
        default=0.0,
    )

    shift: bpy.props.IntProperty(
        name='Shift Topology',
        description='Number of edges to shift the topology',
        default=0,
    )

    mirror: bpy.props.BoolProperty(
        name='Mirror Topology',
        description='Should the topology get mirrored/flipped',
        default=False,
    )



class RFOperator_Patches_Insert(RFOperator_Patches_Insert_Properties, RFOperator_Execute):
    bl_idname = 'retopoflow.patches_insert'
    bl_label = 'Insert Patch'
    bl_description = 'Insert Patch'
    bl_options = { 'REGISTER', 'UNDO', 'INTERNAL' }

    logic : Patches_Logic | None = None

    @staticmethod
    def patches_insert(context, radius2D, point3D):
        RFOperator_Patches_Insert.logic = Patches_Logic(context, radius2D, point3D)
        RFOperator_Patches_Insert.patches_reinsert(context)

    @staticmethod
    def patches_reinsert(context):
        logic = RFOperator_Patches_Insert.logic
        if not logic or logic.error: return
        bpy.ops.retopoflow.patches_insert(
            'INVOKE_DEFAULT', True,
            rotate=logic.rotate,
            mirror=logic.mirror,
        )

    def execute(self, context):
        logic = RFOperator_Patches_Insert.logic
        if not logic: return {'CANCELLED'}
        try:
            logic.rotate = self.rotate
            logic.mirror = self.mirror
            logic.create(context)
            self.rotate = logic.rotate
            self.mirror = self.mirror
        except Exception as e:
            print(f'{type(self).__name__}.execute: Caught Exception {e}')
            debugger.print_exception()
            return {'CANCELLED'}
        return {'FINISHED'}


class RFOperator_Patches(RFOperator_Patches_Insert_Properties, RFOperator):  #RFOperator_PolyStrips_Insert_Properties,
    bl_idname = 'retopoflow.patches'
    bl_label = 'Patches'
    bl_description = 'Fill in holes and add templated geometry'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'I', 'value': 'PRESS'}, None),
        # (bl_idname, {'type': 'LEFT_CTRL', 'value': 'PRESS'}, None),
        # (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        # (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, {'km_context': 'insert', 'km_label': 'Insert Patch'}),

        # ('mesh.loop_multi_select', {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, {'km_context': 'init', 'km_label': 'Select Strip'}),
    ]

    rf_status = {
        'ready': ('LMB: Insert', ),
        'insert': ('RMB: Cancel', )
    }

    insert_mode: wrap_property(
        Patches_Insert_Modes, 'insert_mode', 'enum',
        name='Insert Mode',
        description='Insertion mode for Patches',
        items=Patches_Insert_Modes.insert_modes,
        default="RAYCAST",
    )

    brush_radius: wrap_property(
        RFBrush_Patches, 'stroke_radius', 'int',
        name='Radius',
        description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
        min=1,
        max=1000,
        subtype='PIXEL',
        default=50,
    )

    def init(self, context, event):
        # self.km_context = 'ready'
        RFTool_Patches.rf_brush.set_operator(self)
        RFTool_Patches.rf_brush.reset_nearest(context)
        # RFTool_PolyStrips.rf_overlay.pause_overlay()
        self.logic = Patches_Logic(context)
        self.tickle(context)
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_hit = None

    def finish(self, context):
        del self.logic
        self.set_statusbar_override(None)
        self.km_context = 'ready'
        RFTool_Patches.rf_brush.set_operator(None)
        RFTool_Patches.rf_brush.reset_nearest(context)
        # RFTool_PolyStrips.rf_overlay.unpause_overlay()

    def reset(self):
        RFTool_Patches.rf_brush.reset()
        pass

    def update(self, context, event):
        if event.type == 'ESC':
            return {'CANCELLED'}

        if event.type == 'WHEELUPMOUSE':
            self.rotate = self.rotate + radians(10)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'WHEELDOWNMOUSE':
            self.rotate = self.rotate - radians(10)
            context.area.tag_redraw()
            return {'RUNNING_MODAL'}
        if event.type == 'MOUSEMOVE':
            context.area.tag_redraw()

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_hit = raycast_valid_sources(context, self.mouse)
        self.mouse_ray = ray_from_mouse(context, event)

        Cursors.set('CROSSHAIR')
        return {'PASS_THROUGH'}

    def compute_orientation(self, context, *, world=True) -> Direction:
        if not self.mouse_hit or not self.mouse_ray or not self.mouse_ray[1]:
            return Vector((0, 0, 1))
        match self.insert_mode:
            case 'RAYCAST':
                z = self.mouse_hit['no_world']
            case 'SCREEN':
                z = -self.mouse_ray[1].xyz
            case _:
                print(f'WARNING: UNHANDLED ORIENTATION: {self.compute_orientation}')
                z = Vector((0,0,1))
        if not world:
            Mi = context.edit_object.matrix_world.inverted()
            return (Mi @ direction_to_bvec4(z)).xyz
        return z

    def draw_postview(self, context):
        if not self.mouse_hit or not self.mouse_ray[1]: return

        viewport_size = (context.region.width, context.region.height)
        p = self.mouse_hit['co_world']
        z = self.compute_orientation(context)

        # M = context.edit_object.matrix_world
        # edit_scale = max(M.to_scale())
        radius3D = self.brush_radius * size2D_to_size(context, self.mouse_hit['distance'])
        def xform(p, n):
            return (p * radius3D, n)
        height = Patches_Template.compute_active_height(xform)

        gpustate.blend('ALPHA')
        gpustate.depth_mask(False)

        # draw below
        gpustate.depth_test('GREATER')
        Drawing.draw_circle_3d(
            p,
            z,
            Color4((1,1,0,0.25)),
            radius3D * sqrt(2),
            scale=1.0,
            thickness=1.0,
            viewport_size=viewport_size,
        )

        # # draw above
        gpustate.depth_test('LESS_EQUAL')
        Drawing.draw_circle_3d(
            p,
            z,
            Color4((1,1,0,0.5)),
            radius3D*sqrt(2),
            scale=1.0,
            thickness=2.0,
            viewport_size=viewport_size,
        )
        if not Patches_Template.is_active_flat():
            Drawing.draw_circle_3d(
                p + z * height,
                z,
                Color4((1,1,0,0.25)),
                radius3D*sqrt(2),
                scale=1.0,
                thickness=1.0,
                viewport_size=viewport_size,
            )
    def draw_postpixel(self, context):
        if not self.mouse_hit: return

        M = context.edit_object.matrix_world
        Mi = M.inverted()
        Mit = Mi.transposed()
        edit_scale = max(M.to_scale())
        radius3D = self.brush_radius * size2D_to_size(context, self.mouse_hit['distance']) / edit_scale

        right_local = (Mi @ direction_to_bvec4(view_right_direction(context))).xyz

        fo = self.mouse_hit['co_local']
        fz = self.compute_orientation(context, world=False)
        fy = fz.cross(right_local).normalized()
        fx = fy.cross(fz).normalized()
        f = Frame(fo, fx, fy, fz)
        f.rotate_about_z(self.rotate)

        def xform(p, n):
            nonlocal M, f, radius3D
            # transform v
            p = M @ f.l2w_point(p * radius3D)
            n = Mit @ f.l2w_normal(n)
            return [p,n]

        props = RF_Prefs.get_prefs(context)
        highlight = props.highlight_color
        Patches_Template.draw_active(context, xform, highlight)

    def process_stroke(self, context, radius2D, snap_distance, stroke2D, stroke3D, is_cycle, snapped_geo, snapped_mirror):
        print('PROCESS!')


@add_cache('active', {'asset identifier': None, 'library identifier': None, 'library type': None})
@execute_operator('patches_activate_template', 'Patches: Activate Template from Asset Shelf', pass_self=True, asset_shelf=True)
def activate_template(self, context):
    Patches_Template.activate(
        context,
        self.relative_asset_identifier,
        self.asset_library_identifier,
        self.asset_library_type,
    )


class RFAssetShelf_Patches(RFAssetShelf):
    bl_idname = 'VIEW3D_AST_Retopoflow_Patches' #'retopoflow.patches'
    bl_category = 'Patches Templates'

    bl_activate_operator = 'retopoflow.patches_activate_template'
    # bl_drag_operator = "retopoflow.patches_drag_template"

    bl_default_preview_size = 128   # show assets fairly large by default
    filter_object = True            # Filter to only show object assets (asset_poll filters further)
    show_names = True               # TODO: does not work???

    @classmethod
    def poll(cls, context):
        # active asset is lost when asset shelf is hidden!
        # also, the 3D View jumps if region overlap is False
        # return not RFOperator_Patches.is_active()
        return True

    @classmethod
    def asset_poll(cls, asset):
        return asset.metadata.description.startswith('Retopoflow Patches Template')

    @classmethod
    def can_start(cls, context):
        return RFAssetShelf.RFCore.selected_RFTool_idname == RFTool_Patches.bl_idname



class RFTool_Patches(RFTool_Base):
    bl_idname = "retopoflow.patches"
    bl_label = "Patches"
    bl_description = "Retopologize holes!"
    bl_icon = get_path_to_blender_icon('patches')
    bl_widget = None
    bl_operator = 'retopoflow.patches'

    bl_keymap = chain_rf_keymaps(
        RFOperator_Patches,
        RFOperator_PatchesBrush_Adjust,
    )

    rf_brush = RFBrush_Patches()

    def draw_settings(context, layout, tool):
        props_patches = tool.operator_properties(RFOperator_Patches.bl_idname)
        RFTool_Patches.props = props_patches

        if context.region.type == 'TOOL_HEADER':
            layout.label(text="Insert:")
            row = layout.row(align=True)
            row.prop(props_patches, 'insert_mode', text='')
            if props_patches.insert_mode in {'RAYCAST', 'SCREEN'}:
                row.prop(props_patches, 'brush_radius', text='')

        else:
            header, panel = layout.panel(idname='patches_insert_panel', default_closed=False)
            header.label(text="Insert")
            if panel:
                panel.prop(props_patches, 'insert_mode', text='Method')
                if props_patches.insert_mode in {'RAYCAST', 'SCREEN'}:
                    panel.prop(props_patches, 'brush_radius', text='Radius')
            draw_cleanup_panel(context, layout)
            draw_tweaking_panel(context, layout)
            draw_mirror_panel(context, layout)
            draw_general_panel(context, layout)
            draw_help_panel(context, layout)

    @classmethod
    def activate(cls, context):
        cls.resetter = Resetter('Patches')
        space_data = context.space_data
        asset_libs = context.preferences.filepaths.asset_libraries
        def delayed_settings(attempts=3):
            nonlocal cls, space_data, asset_libs
            if 'Retopoflow Patches Templates' not in asset_libs:
                bpy.types.AssetLibraryCollection.new(
                    name="Retopoflow Patches Templates",
                    directory=ASSETS_PATH,
                )
                # asset_libs['Retopoflow Assets'].import_method = 'LINK'
            if not hasattr(space_data, 'show_region_asset_shelf'):
                # this can happen if context is not quite right, so find space that we can
                # ex: after saving
                return
            try:
                cls.resetter['space_data.show_region_asset_shelf'] = True
            except:
                if attempts > 0:
                    bpy.app.timers.register(lambda:delayed_settings(attempts-1), first_interval=0.25)
        bpy.app.timers.register(delayed_settings, first_interval=0.25)
        Patches_Template.activate(context, None, None, None)  # asset shelf will have nothing selected initially
        #return super().activate(context)

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()


@execute_operator('switch_to_patches', 'RetopoFlow: Switch to Patches', fn_poll=poll_retopoflow)
def switch_rftool(context):
    RFTool_Patches.activate_tool(context)




################################################################################################################################
################################################################################################################################
#
#
# the class below will be removed
#
#
################################################################################################################################
################################################################################################################################

class RFOperator_Patches_Drag_template(RFOperator):
    bl_idname = 'retopoflow.patches_drag_template'
    bl_label = 'Patches: Drag in template'
    bl_description = 'Add template'
    bl_options = set()

    rf_status = {
        'ready': ('LMB: Insert', ),
        'insert': ('RMB: Cancel', )
    }

    asset_library_type: bpy.props.EnumProperty(
        name="Asset Library Type",
        description="Asset Library Type",
        items=[
            ("ALL", "All", "All", "", 2),
            ("LOCAL", "Local", "Local", "", 1),
            ("ESSENTIALS", "Essentials", "Essentials", "", 3),
            ("CUSTOM", "Custom", "Custom", "", 100),
        ],
        # options={'HIDDEN'}
    )
    asset_library_identifier: bpy.props.StringProperty() # = 'CUSTOM'
    relative_asset_identifier: bpy.props.StringProperty()

    ORIENTATIONS = [
        'screen',
        'normal',
        'perpendicular_y_positive',
        'perpendicular_y_negative',
        'perpendicular_x_positive',
        'perpendicular_x_negative',
    ]

    def init(self, context, event):
        print(f"Dragging asset: {self.relative_asset_identifier}")
        print(f"From library: {self.asset_library_identifier} ({self.asset_library_type})")
        if self.asset_library_type == 'LOCAL':
            obj_name = self.relative_asset_identifier.split('/')[1]
            mesh = bpy.data.objects[obj_name].data
            # TODO: rescale mesh
            self.vc, self.ec, self.fc = len(mesh.vertices), len(mesh.edges), len(mesh.polygons)
            self.vps = [ Vector(v.co) for v in mesh.vertices ]
            self.vns = [ Vector(v.normal) for v in mesh.vertices ]
            self.vcs = [ 1.0 for _ in mesh.vertices ]
            self.es = [ tuple(e.vertices) for e in mesh.edges ]
            self.fs = [ tuple(f.vertices) for f in mesh.polygons ]
        else:
            fn = os.path.split(self.relative_asset_identifier)[1]
            path = os.path.join(ASSETS_PATH, f'{fn}.template')
            print(f'PATH: {path}')

            with open(path, 'rt') as f:
                self.vc, self.ec, self.fc = map(int, f.readline().split(' '))
                # px,py,pz, nx,ny,nz, outside (crease)
                verts = [list(map(float, f.readline().split(' '))) for _ in range(self.vc)]
                self.vps = [ Vector(v[0:3]) for v in verts ]
                self.vns = [ Vector(v[3:6]) for v in verts ]
                self.vcs = [ v[6] > 0.001   for v in verts ]
                self.es = [
                    tuple(int(v) for v in f.readline().split(' '))
                    for _ in range(self.ec)
                ]
                self.fs = [
                    tuple(int(v) for v in f.readline().split(' '))
                    for _ in range(self.fc)
                ]

        self.setup_springs()

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_hit = None
        self.scale = 0.1
        self.rotate = 0.0
        self.time = time.time()
        self.orientation = self.ORIENTATIONS[0]

        context.space_data.show_region_asset_shelf = False

    def setup_springs(self):
        self.ves = { v:{} for v in range(self.vc) }

        # springs for each non-face edge
        for (e0, e1) in self.es:
            v0, v1 = self.vps[e0], self.vps[e1]
            d = (v1 - v0).length
            self.ves[e0][e1] = d
            self.ves[e1][e0] = d

        # springs for each face
        for f in self.fs:
            for e0 in f:
                for e1 in f:
                    if e0 <= e1: continue
                    v0, v1 = self.vps[e0], self.vps[e1]
                    d = (v1 - v0).length
                    self.ves[e0][e1] = d
                    self.ves[e1][e0] = d
            for (e0, e1) in zip(f, chain(f[2:], f[:2])):
                v0, v1 = self.vps[e0], self.vps[e1]
                d = (v1 - v0).length
                self.ves[e0][e1] = d
                self.ves[e1][e0] = d

        # normalize resting lengths based on local neighborhood
        for v in self.ves:
            if not self.ves[v]: continue
            avg = sum(self.ves[v].values()) / len(self.ves[v])
            self.ves[v] = { ov: d / avg for (ov, d) in self.ves[v].items() }

    def compute_orientation(self, context, *, world=True):
        if not self.mouse_hit: return None
        if not self.mouse_ray or not self.mouse_ray[1]: return None
        match self.orientation:
            case 'screen':
                z = -self.mouse_ray[1].xyz
            case 'normal':
                z = self.mouse_hit['no_world']
            case 'perpendicular_y_positive':
                up = view_up_direction(context)
                back = self.mouse_hit['no_world']
                z = up.cross(back).normalized()
            case 'perpendicular_y_negative':
                up = view_up_direction(context)
                back = self.mouse_hit['no_world']
                z = back.cross(up).normalized()
            case 'perpendicular_x_positive':
                right = view_right_direction(context)
                back = self.mouse_hit['no_world']
                z = right.cross(back).normalized()
            case 'perpendicular_x_negative':
                right = view_right_direction(context)
                back = self.mouse_hit['no_world']
                z = back.cross(right).normalized()
            case _:
                assert False, f'Unhandled orientation: {self.orientation}'
        if not world:
            Mi = context.edit_object.matrix_world.inverted()
            return (Mi @ direction_to_bvec4(z)).xyz
        return z

    def compute_points(self, context):
        if not self.mouse_hit: return [ [None, None] for v in self.vps ]

        M = context.edit_object.matrix_world
        Mi = M.inverted()
        Mit = Mi.transposed()
        Mt = M.transposed()

        fo = self.mouse_hit['co_local']
        fz = self.compute_orientation(context)
        fz = (M @ direction_to_bvec4(fz)).xyz

        fx = view_up_direction(context).cross(fz).normalized()
        fy = fz.cross(fx).normalized()
        f = Frame(fo, fx, fy, fz)
        f.rotate_about_z(self.rotate)

        def xform(f, p, n, c):
            # transform v
            p = M @ f.l2w_point(p * self.scale)
            n = Mit @ f.l2w_normal(n)
            return [p,n]

            # raycast to surface
            if not c:
                pt, no = p, n
            else:
                pt, no = None, None
                p2d = location_3d_to_region_2d(context.region, context.region_data, p)
                if p2d:
                    hit = raycast_valid_sources(context, p2d)
                    if hit:
                        pt, no = hit['co_local'], hit['no_local']
                    else:
                        pt, no = None, None
                if not pt or not no:
                    pt, no = nearest_point_normal_valid_sources(context, p)

            return [point_to_bvec4(pt), normal_to_bvec4(no)]

        def nearest(pt, no):
            return pt
            closest_dist = float('inf')
            closest_pt = None
            for m in [-1.0, -0.5, -0.25, -0.1, 0, 0.1, 0.25, 0.5, 1.0]:
                p = pt.xyz + no.xyz * (self.scale * m)
                npt, nno = nearest_point_normal_valid_sources(context, p)
                dot = no.xyz.dot(nno)
                dist = (pt.xyz - npt.xyz).length * abs(dot)
                if dot < 0: dist += 1.0
                if dist < closest_dist:
                    closest_pt, closest_dist = npt, dist
            return closest_pt


        # transform points
        steps = 0
        for istep in range(steps, 0, -1):
            tx, ty = 0, 0
            for (v, n, c) in zip(self.vps, self.vns, self.vcs):
                if not c: continue
                p, _ = xform(f, v, n, c)
                d = M @ direction_to_bvec4(f.z)
                hit_p = raycast_ray_valid_sources(context, (p, d))
                hit_n = raycast_ray_valid_sources(context, (p, -d))
                dist_p = (p - hit_p).length if hit_p else float('inf')
                dist_n = (p - hit_n).length if hit_n else float('inf')
                hit = hit_p if dist_p < dist_n else hit_n
                if not hit: continue
                hit = f.w2l_point(Mi @ hit)
                tx += hit.x * hit.z
                ty += hit.y * hit.z
            tx = atan2(tx, self.scale)
            ty = atan2(ty, self.scale)
            f.rotate_about_y( tx * istep / steps * 0.1)
            f.rotate_about_x(-ty * istep / steps * 0.1)
        ptnos = [ xform(f, v, n, c) for (v, n, c) in zip(self.vps, self.vns, self.vcs) ]

        return ptnos

        # relax
        iterations = 100
        time_step  = 0.01
        spring_k = 0.05     # spring stiffness
        spring_b = 0.95     # spring restitution
        vel = [ Vector((0,0,0)) for v in self.ves ]
        for iloop in range(iterations):
            acc = [ Vector((0,0,0)) for v in self.ves ]
            for v in self.ves:
                if not self.ves[v]: continue
                if self.vcs[v]: continue
                if ptnos[v][0] is None: continue
                good = { o:r for (o,r) in self.ves[v].items() if ptnos[o][0] is not None }
                avg = sum((ptnos[v][0] - ptnos[o][0]).length for o in good) / len(good)
                if avg < 0.00001: continue
                for (o, rest_dist) in good.items():
                    if ptnos[o][0] is None: continue
                    delta_pos = (ptnos[o][0] - ptnos[v][0]).xyz
                    delta_dist = delta_pos.length / avg - rest_dist
                    delta_dir = delta_pos.normalized()
                    delta_vel = delta_dir.dot(vel[o] - vel[v])
                    force_magnitude = delta_dist * spring_k - delta_vel * spring_b
                    force_vector = delta_dir * force_magnitude
                    acc[v] += force_vector
                    acc[o] -= force_vector
            for v in self.ves:
                vel[v] += acc[v] * time_step
                ppt = ptnos[v][0]
                npt = ppt + vector_to_bvec4(vel[v] * time_step) + vector_to_bvec4(acc[v] * (0.5 * time_step * time_step))
                if self.vcs[v] or True:
                    npt = nearest(npt, ptnos[v][1]) # nearest_point_valid_sources(context, npt.xyz)
                    npt = ppt.xyz + (npt.xyz - ppt.xyz) * (iloop / (iterations-1))
                ptnos[v][0] = point_to_bvec4(npt)
                vel[v] = npt.xyz - ppt.xyz

        return ptnos

    def draw_postview(self, context):
        if not self.mouse_hit or not self.mouse_ray[1]: return

        viewport_size = (context.region.width, context.region.height)
        p = self.mouse_hit['co_world']
        z = self.compute_orientation(context)

        gpustate.blend('ALPHA')
        gpustate.depth_mask(False)

        # draw below
        gpustate.depth_test('GREATER')
        Drawing.draw_circle_3d(
            p,
            z,
            Color4((1,1,0,0.5)), #co * self.below_alpha,
            self.scale,
            scale=1.0, # self.hit_scale_above,
            thickness=1.0, #thickness,
            viewport_size=viewport_size,
        )
        Drawing.draw_circle_3d(
            p,
            z,
            Color4((1,1,0,0.25)), #co * self.below_alpha,
            self.scale * sqrt(2),
            scale=1.0, # self.hit_scale_above,
            thickness=1.0, #thickness,
            viewport_size=viewport_size,
        )

        # # draw above
        gpustate.depth_test('LESS_EQUAL')
        Drawing.draw_circle_3d(
            p,
            z,
            Color4((1,1,0,1)), #co * self.below_alpha,
            self.scale,
            scale=1.0, # self.hit_scale_above,
            thickness=2.0, #thickness,
            viewport_size=viewport_size,
        )
        Drawing.draw_circle_3d(
            p,
            z,
            Color4((1,1,0,0.5)), #co * self.below_alpha,
            self.scale*sqrt(2),
            scale=1.0, # self.hit_scale_above,
            thickness=2.0, #thickness,
            viewport_size=viewport_size,
        )


    def draw_postpixel(self, context):
        if not self.RFCore.is_current_area(context): return

        ptnos = self.compute_points(context)
        # project to screen
        pts = [ location_3d_to_region_2d(context.region, context.region_data, pt) if pt else None for (pt,no) in ptnos ]

        theme = context.preferences.themes[0].view_3d
        props = RF_Prefs.get_prefs(context)
        highlight = props.highlight_color

        color_point =               Color4((highlight[0], highlight[1], highlight[2], 1))
        color_border_transparent =  Color4((highlight[0], highlight[1], highlight[2], 0))
        color_border_mesh =         Color4((theme.edge_select[0], theme.edge_select[1], theme.edge_select[2], 1))
        color_border_open =         Color4((highlight[0], highlight[1], highlight[2], 1.0))
        color_stipple =             Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_size = theme.vertex_size

        with Drawing.draw(context, CC_2D_POINTS) as draw:
            draw.point_size(vertex_size + 4)
            draw.color(color_point)
            for pt in pts:
                if not pt: continue
                draw.vertex(pt)

        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.line_width(2)
            draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
            draw.color(color_border_mesh)
            for (e0,e1) in self.es:
                pt0, pt1 = pts[e0], pts[e1]
                if not pt0 or not pt1: continue
                draw.vertex(pt0).vertex(pt1)
            draw.line_width(1)
            draw.stipple(pattern=[5,0], offset=0, color=color_stipple)
            for f in self.fs:
                if not all(pts[i] for i in f): continue
                for (e0, e1) in iter_pairs(f, True):
                    pt0, pt1 = pts[e0], pts[e1]
                    if not pt0 or not pt1: continue
                    draw.vertex(pt0).vertex(pt1)

        with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
            draw.color(color_mesh)
            for f in self.fs:
                if not all(pts[i] for i in f): continue
                v0 = f[0]
                pt0 = pts[v0]
                for (v1, v2) in iter_pairs(f[1:], False):
                    pt1, pt2 = pts[v1], pts[v2]
                    draw.vertex(pt0).vertex(pt1).vertex(pt2)

        gpustate.blend('ALPHA')
        Drawing.draw2D_smooth_circle(context, self.mouse, self.scale, Color4((1,1,0,1)), width=3)
        #Drawing.draw2D_smooth_circle(context, self.mouse, radius-1, color_in, width=1)
        gpustate.blend('NONE')


    def update(self, context, event):
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_hit = raycast_valid_sources(context, self.mouse)
        self.mouse_ray = ray_from_mouse(context, event)

        if event.type == 'ESC' and event.value == 'PRESS':
            context.space_data.show_region_asset_shelf = True
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            print(f'DONE!')

            if self.mouse_hit is not None:
                ptnos = self.compute_points(context)
                bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
                bmvs = [ bm.verts.new(pt.xyz) if pt else None for (pt, _) in ptnos ]
                bmes = [
                    bm.edges.new((bmvs[i0],bmvs[i1]))
                    for (i0,i1) in self.es
                    if all([bmvs[i0] is not None, bmvs[i1] is not None])
                ]
                bmfs = [
                    bm.faces.new((bmvs[i] for i in f))
                    for f in self.fs
                    if all(bmvs[i] is not None for i in f)
                ]
                bmops.deselect_all(bm)
                for v in bmvs:
                    if v is not None: bmops.select(bm, v)
                bmops.flush_selection(bm, em)

            context.space_data.show_region_asset_shelf = True
            return {'FINISHED'}

        if event.value == 'PRESS':
            if event.type == 'WHEELUPMOUSE':
                self.scale *= 1.1
            if event.type == 'WHEELDOWNMOUSE':
                self.scale /= 1.1
            if event.type == 'ONE':
                self.rotate += 0.1
            if event.type == 'TWO':
                self.rotate -= 0.1
            if event.type == 'O':
                n = len(self.ORIENTATIONS)
                i = self.ORIENTATIONS.index(self.orientation)
                o = 1 if not event.shift else n - 1
                self.orientation = self.ORIENTATIONS[(i + o) % n]

        context.area.tag_redraw()
        return {'RUNNING_MODAL'}
