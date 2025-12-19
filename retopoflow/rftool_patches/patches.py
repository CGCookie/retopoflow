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
from ..rftool_base import RFTool_Base

from ..common.icons import get_path_to_blender_icon
from ..common.operator import (
    execute_operator,
    poll_retopoflow,
    chain_rf_keymaps,
    RFOperator,
    RFOperator_Execute,
)


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
        self.tickle(context)

    def finish(self, context):
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
