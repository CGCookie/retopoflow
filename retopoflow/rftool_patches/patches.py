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
import os

from mathutils import Vector
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ..rftool_base import RFTool_Base

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.utils import iter_pairs
from ...addon_common.common.maths import Frame
from ...addon_common.common.colors import Color4
from ...addon_common.common.resetter import Resetter
from ..common.bmesh import get_bmesh_emesh
from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    poll_retopoflow,
    chain_rf_keymaps,
    RFOperator,
    RFOperator_Execute,
    RFAssetShelf,
)
from ..common.maths import view_right_direction
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources
from ..preferences import RF_Prefs

from .patches_logic import Patches_Logic

from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_LINE_STRIP,
    CC_2D_LINE_LOOP,
    CC_2D_TRIANGLES,
    CC_2D_TRIANGLE_FAN,
    CC_3D_TRIANGLES,
)



ASSETS_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'assets'))

class RFOperator_Patches(RFOperator):  #RFOperator_PolyStrips_Insert_Properties,
    bl_idname = 'retopoflow.patches'
    bl_label = 'Patches'
    bl_description = 'Fill in holes'
    bl_options = set()

    rf_keymaps = [
        (bl_idname, {'type': 'LEFT_CTRL', 'value': 'PRESS'}, None),
        # (bl_idname, {'type': 'LEFT_CTRL',  'value': 'PRESS'}, None),
        # (bl_idname, {'type': 'RIGHT_CTRL', 'value': 'PRESS'}, None),

        # (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK',        'ctrl': True}, {'km_context': ('init', 'ready'), 'km_label': 'Insert Strip'}),  # prevents object selection with Ctrl+LMB Click
        # (bl_idname, {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK', 'ctrl': True}, None),

        # # below is needed to handle case when CTRL is pressed when mouse is initially outside area
        # (bl_idname, {'type': 'MOUSEMOVE', 'value': 'ANY', 'ctrl': True}, {'km_context': 'insert', 'km_label': 'Draw Strip'}),

        # ('mesh.loop_multi_select', {'type': 'LEFTMOUSE', 'value': 'DOUBLE_CLICK'}, {'km_context': 'init', 'km_label': 'Select Strip'}),
    ]

    rf_status = {
        'ready': ('LMB: Insert', )
        # 'ready': ('LMB: Insert', ),
        # 'insert': ('RMB: Cancel', )
    }


    # brush_radius: wrap_property(
    #     RFBrush_Strokes, 'stroke_radius', 'int',
    #     name='Radius',
    #     description='Radius of the brush in Blender UI units before it gets projected onto the mesh',
    #     min=1,
    #     max=1000,
    #     subtype='PIXEL',
    #     default=50,
    # )

    # stroke_smoothing: bpy.props.FloatProperty(
    #     name='Stabilize',
    #     description='Stroke smoothing factor.  Zero means no smoothing, and higher means more smoothing.',
    #     get=lambda _: RFBrush_Strokes.get_stroke_smooth(),
    #     set=lambda _,v: RFBrush_Strokes.set_stroke_smooth(v),
    #     min=0.00,
    #     max=1.0,
    #     default=0.5,
    # )


    def init(self, context, event):
        # self.km_context = 'ready'
        # RFTool_PolyStrips.rf_brush.set_operator(self)
        # RFTool_PolyStrips.rf_brush.reset_nearest(context)
        # RFTool_PolyStrips.rf_overlay.pause_overlay()
        self.logic = Patches_Logic(context, event)
        self.tickle(context)

    def finish(self, context):
        del self.logic
        self.set_statusbar_override(None)
        self.km_context = 'init'
        # RFTool_PolyStrips.rf_brush.set_operator(None)
        # RFTool_PolyStrips.rf_brush.reset_nearest(context)
        # RFTool_PolyStrips.rf_overlay.unpause_overlay()

    def reset(self):
        # RFTool_PolyStrips.rf_brush.reset()
        pass

    # def process_stroke(self, context, radius2D, snap_distance, stroke2D, stroke3D, is_cycle, snapped_geo, snapped_mirror):
    #     snap_bmf0, snap_bmf1 = snapped_geo[2]
    #     p3D_0, p3D_1 = stroke3D[0], stroke3D[-1]
    #     if not snap_bmf0:
    #         l = len(stroke2D)
    #         p0 = stroke2D[0]
    #         p1 = next((s for s in stroke2D if (s - p0).length >= radius2D), None)
    #         if p1:
    #             d = Direction2D(p0 - p1)
    #             for i in range(1, 101):
    #                 p = p0 + d * (radius2D * (i / 100))
    #                 if not raycast_point_valid_sources(context, p): break
    #                 stroke2D = [p] + stroke2D
    #     if not snap_bmf1:
    #         p0 = stroke2D[-1]
    #         p1 = next((s for s in stroke2D[::-1] if (s - p0).length >= radius2D), None)
    #         if p1:
    #             d = Direction2D(p0 - p1)
    #             for i in range(1, 101):
    #                 p = p0 + d * (radius2D * (i / 100))
    #                 if not raycast_point_valid_sources(context, p): break
    #                 stroke2D += [p]
    #     length2D = sum((p1-p0).length for (p0,p1) in iter_pairs(stroke2D, is_cycle))
    #     stroke3D = [raycast_point_valid_sources(context, pt, world=False) for pt in stroke2D]
    #     stroke3D = [pt for pt in stroke3D if pt]
    #     RFOperator_PolyStrips_Insert.polystrips_insert(
    #         context,
    #         radius2D,
    #         stroke3D, p3D_0, p3D_1,
    #         is_cycle,
    #         length2D,
    #         snap_bmf0, snap_bmf1,
    #         self.split_angle,
    #         self.mirror_correct,
    #     )

    def update(self, context, event):
        return {'FINISHED'}
        # if event.value in {'CLICK', 'DOUBLE_CLICK'} and event_modifier_check(event, ctrl=True, shift=False, alt=False, oskey=False):
        #     # prevents object selection with Ctrl+LMB Click
        #     return {'RUNNING_MODAL'}

        # if RFTool_PolyStrips.rf_brush.is_stroking():
        #     self.set_statusbar_override(self.rf_status['insert'])
        #     if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'LEFTMOUSE'}:
        #         self.RFCore.handle_update(context, event)
        #         return {'RUNNING_MODAL'}
        # else:
        #     self.set_statusbar_override(None)
        #     if not event.ctrl:
        #         Cursors.restore()
        #         self.tickle(context)
        #         return {'FINISHED'}

        # Cursors.set('CROSSHAIR')
        # return {'PASS_THROUGH'}  # TODO: see below
        # # TODO: allow only some operators to work but not all
        # #       however, need a way to not hardcode LEFTMOUSE!
        # return {'PASS_THROUGH'} if event.type in {'MOUSEMOVE', 'LEFTMOUSE'} else {'RUNNING_MODAL'}


class RFOperator_Patches_Drag_template(RFOperator):
    bl_idname = 'retopoflow.patches_drag_template'
    bl_label = 'Patches: Drag in template'
    bl_description = 'Add template'
    bl_options = set()

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

    def init(self, context, event):
        print(f"Dragging asset: {self.relative_asset_identifier}")
        print(f"From library: {self.asset_library_identifier} ({self.asset_library_type})")
        fn = os.path.split(self.relative_asset_identifier)[1]
        path = os.path.join(ASSETS_PATH, f'{fn}.template')
        print(f'PATH: {path}')

        with open(path, 'rt') as f:
            vc,ec,fc = map(int, f.readline().split(' '))
            self.vs = [
                Vector(tuple(map(float, f.readline().split(' '))))  # x,y,z,outside (crease)
                for _ in range(vc)
            ]
            self.es = [
                tuple(int(v) for v in f.readline().split(' '))
                for _ in range(ec)
            ]
            self.fs = [
                tuple(int(v) for v in f.readline().split(' '))
                for _ in range(fc)
            ]

        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.scale = 0.1
        self.rotate = 0.0

        context.space_data.show_region_asset_shelf = False

    def draw_postpixel(self, context):
        if not self.RFCore.is_current_area(context): return

        hit = raycast_valid_sources(context, self.mouse)
        if not hit: return

        M = context.edit_object.matrix_world
        fo, fz = hit['co_local'], hit['no_local']
        fy = fz.cross(view_right_direction(context)).normalized()
        fx = fy.cross(fz).normalized()
        f = Frame(fo, fx, fy, fz)
        f.rotate_about_z(self.rotate)

        vs = [
            f.l2w_point(v * self.scale)
            for v in self.vs
        ]
        pts = [
            location_3d_to_region_2d(context.region, context.region_data, M @ v)
            for v in vs
        ]
        pts = [
            raycast_point_valid_sources(context, pt) if pt else None
            for pt in pts
        ]
        pts = [
            location_3d_to_region_2d(context.region, context.region_data, pt) if pt else None
            for pt in pts
        ]

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


    def update(self, context, event):
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            print(f'DONE!')

            hit = raycast_valid_sources(context, self.mouse)
            if hit is not None:
                bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
                M = context.edit_object.matrix_world
                fo, fz = hit['co_local'], hit['no_local']
                fy = fz.cross(view_right_direction(context)).normalized()
                fx = fy.cross(fz).normalized()
                f = Frame(fo, fx, fy, fz)
                f.rotate_about_z(self.rotate)

                vs = [
                    f.l2w_point(v * self.scale)
                    for v in self.vs
                ]
                pts = [
                    location_3d_to_region_2d(context.region, context.region_data, M @ v)
                    for v in vs
                ]
                pts = [
                    raycast_point_valid_sources(context, pt) if pt else None
                    for pt in pts
                ]
                bmvs = [
                    bm.verts.new(pt) if pt else None for pt in pts
                ]
                bmes = [
                    bm.edges.new((bmvs[i0],bmvs[i1])) for (i0,i1) in self.es
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
        if event.type == 'WHEELUPMOUSE':
            self.scale *= 1.1
        if event.type == 'WHEELDOWNMOUSE':
            self.scale /= 1.1
        if event.type == 'ONE':
            self.rotate += 0.1
        if event.type == 'TWO':
            self.rotate -= 0.1
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

class RFAssetShelf_Patches(RFAssetShelf):
    bl_idname = 'retopoflow.patches'
    bl_category = 'Patches Templates'
    bl_drag_operator = "retopoflow.patches_drag_template"

    # bl_label = 'Patches'
    # bl_description = 'Fill in holes'
    # bl_options = set()

    # Filter to only show object assets
    filter_object = True
    show_names = True               # TODO: does not work???
    bl_default_preview_size = 128

    @classmethod
    def asset_poll(cls, asset):
        return asset.metadata.description.startswith('Retopoflow Patches Template')

    @classmethod
    def can_start(cls, context):
        return RFAssetShelf.RFCore.selected_RFTool_idname == RFTool_Patches.bl_idname



@execute_operator('switch_to_patches', 'RetopoFlow: Switch to Patches', fn_poll=poll_retopoflow)
def switch_rftool(context):
    import bl_ui
    bl_ui.space_toolsystem_common.activate_by_id(context, 'VIEW_3D', 'retopoflow.patches')  # matches bl_idname of RFTool_Base below


class RFTool_Patches(RFTool_Base):
    bl_idname = "retopoflow.patches"
    bl_label = "Patches"
    bl_description = "Retopologize holes!"
    bl_icon = get_path_to_blender_icon('patches')
    bl_widget = None
    bl_operator = 'retopoflow.patches'

    bl_keymap = chain_rf_keymaps(
        RFOperator_Patches,
    )

    @classmethod
    def activate(cls, context):
        cls.resetter = Resetter('Patches')
        space_data = context.space_data
        asset_libs = context.preferences.filepaths.asset_libraries
        def delayed_settings(attempts=3):
            nonlocal cls, space_data, asset_libs
            if 'Retopoflow Assets' not in asset_libs:
                bpy.types.AssetLibraryCollection.new(
                    name="Retopoflow Assets",
                    directory=ASSETS_PATH,
                )
                # asset_libs['Retopoflow Assets'].import_method = 'LINK'
            if not hasattr(space_data, 'show_region_asset_shelf'):
                # this can happen if context is not quite right, so find space that we can
                # ex: after saving
                return
                space_data = None
                for d in RFOperator.RFCore.iter_spaces():
                    space_data = d['space']
                if not space_data: return
            try:
                cls.resetter['space_data.show_region_asset_shelf'] = True
            except:
                if attempts > 0:
                    bpy.app.timers.register(lambda:delayed_settings(attempts-1), first_interval=0.25)
        bpy.app.timers.register(delayed_settings, first_interval=0.25)
        #return super().activate(context)

    @classmethod
    def deactivate(cls, context):
        cls.resetter.reset()
