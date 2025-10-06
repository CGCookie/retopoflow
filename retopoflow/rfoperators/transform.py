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

import bmesh
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_location_3d
from mathutils import Vector

import heapq

from ..preferences import RF_Prefs
from ..common.bmesh import (
    get_bmesh_emesh,
    NearestBMVert, NearestBMEdge, NearestBMFace,
)
from ..common.bmesh_maths import is_bmvert_hidden
from ..common.operator import execute_operator, RFOperator
from ..common.raycast import raycast_valid_sources, raycast_point_valid_sources, mouse_from_event, nearest_point_valid_sources
from ..common.maths import view_forward_direction, proportional_edit, xform_direction
from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import sign_threshold
from ..common.drawing import Drawing, CC_2D_POINTS

from ..rfoverlays.proportional_edit_overlay import ProportionalEditOverlay


class RFOperator_Translate(RFOperator):
    bl_idname = "retopoflow.translate"
    bl_label = 'Translate'
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = set()

    rf_keymaps = [
        (f'{bl_idname}_grab', {'type': 'G', 'value': 'PRESS'}, None),
        (bl_idname, {'type': 'LEFTMOUSE', 'value': 'CLICK_DRAG'}, None),
    ]
    rf_status = ['LMB: Commit', 'MMB: (nothing)', 'RMB: Cancel']

    color_highlight_border = Color4((255/255, 255/255, 40/255, 1.0))
    color_highlight_fill = Color4((255/255, 255/255, 40/255, 0.0))

    use_native: bpy.props.EnumProperty(
        name='Use Native',
        description="Use Blender's built-in translate rather than the custom Retopoflow translate",
        items=[
            ('TRUE', 'True', ''),
            ('FALSE', 'False', ''),
            ('AUTO', 'Follow Preferences', ''),
        ],
        default='AUTO',
    )
    snap_method: bpy.props.EnumProperty(
        name='Snapping Method',
        description='Whether the snapping happens in screen space, world space, or is automatic',
        items=[
            ('PROJECTED', 'Screen Space', ''),
            ('NEAREST', 'World Space', ''),
            ('AUTO', 'Automatic', ''),
        ],
        default='AUTO',
    )
    move_hovered: bpy.props.BoolProperty(
        name='Select and Move Hovered',
        description='If False, currently selected geometry is moved.  If True, hovered geometry is selected then moved.',
        default=True,
    )
    used_keyboard: bpy.props.BoolProperty(
        name='Used Keyboard',
        description='Set as true if the user hit a hotkey to transform rather than used the mouse',
        default=False,
    )

    @staticmethod
    @execute_operator(f'{bl_idname}_grab', f'{bl_label} Grab')
    def grab_selected(context):
        idname = RFOperator_Translate.bl_idname.split('.')[1]
        op = getattr(bpy.ops.retopoflow, f'{idname}')
        op('INVOKE_DEFAULT', used_keyboard=True)

    def init(self, context, event):
        # print(f'STARTING TRANSLATE')
        prefs = RF_Prefs.get_prefs(context)
        self.matrix_world = context.edit_object.matrix_world
        self.matrix_world_inv = self.matrix_world.inverted()
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)
        M, Mi = self.matrix_world, self.matrix_world_inv
        self.nearest_bmv = NearestBMVert(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=False)
        self.nearest_bme = NearestBMEdge(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=False)
        self.nearest_bmf = NearestBMFace(self.bm, self.matrix_world, self.matrix_world_inv, ensure_lookup_tables=False)
        if self.use_native == 'AUTO':
            self.use_native = 'TRUE' if prefs.tweaking_use_native else 'FALSE'

        if self.used_keyboard:
            move_hovered = self.move_hovered and prefs.tweaking_move_hovered_keyboard
        else:
            move_hovered = self.move_hovered and prefs.tweaking_move_hovered_mouse

        if move_hovered:
            hit = raycast_valid_sources(context, mouse_from_event(event))
            if hit:
                co = hit['co_local']

                distance2d = prefs.tweaking_distance
                self.nearest_bmv.update(context, co, distance2d=distance2d, filter_fn=lambda bmv: not is_bmvert_hidden(context, bmv))
                self.nearest_bme.update(context, co, distance2d=distance2d, filter_fn=lambda bme: not any(map(lambda bmv:is_bmvert_hidden(context, bmv), bme.verts)))
                self.nearest_bmf.update(context, co, distance2d=distance2d, filter_fn=lambda bmf: not any(map(lambda bmv:is_bmvert_hidden(context, bmv), bmf.verts)))
                # bmesh.geometry.intersect_face_point(face, point)
                # select hovered geometry
                mode = context.tool_settings.mesh_select_mode
                nearest_bmelem = None
                if mode[0] and not nearest_bmelem: nearest_bmelem = self.nearest_bmv.bmv
                if mode[1] and not nearest_bmelem: nearest_bmelem = self.nearest_bme.bme
                if mode[2] and not nearest_bmelem: nearest_bmelem = self.nearest_bmf.bmf

                if nearest_bmelem:
                    bmops.deselect_all(self.bm)
                    bmops.select(self.bm, nearest_bmelem)
                    #self.bm.select_history.validate()
                    bmops.flush_selection(self.bm, self.em)

        if self.use_native == 'TRUE':
            if self.snap_method == 'AUTO':
                bpy.ops.transform.translate('INVOKE_DEFAULT')

            ts = context.scene.tool_settings
            prev_snap_individual = ts.snap_elements_individual

            if self.snap_method == 'PROJECTED':
                ts.snap_elements_individual = {'FACE_PROJECT'}
                bpy.ops.transform.translate('INVOKE_DEFAULT', use_snap_project=True)
            elif self.snap_method == 'NEAREST':
                ts.snap_elements_individual = {'FACE_NEAREST'}
                bpy.ops.transform.translate('INVOKE_DEFAULT', use_snap_project=False)

            ts.snap_elements_individual = prev_snap_individual

        self.bmvs = list(bmops.get_all_selected_bmverts(self.bm))
        # self.bmvs_co_orig = [Vector(bmv.co) for bmv in self.bmvs]
        # self.bmvs_co2d_orig = [location_3d_to_region_2d(context.region, context.region_data, (self.matrix_world @ Vector((*bmv.co, 1.0))).xyz) for bmv in self.bmvs]

        if self.snap_method == 'AUTO':
            if len(self.bmvs) < 3 or context.scene.tool_settings.snap_elements_individual == {'FACE_PROJECT'}:
                self.snap_method = 'PROJECTED'
            else:
                self.snap_method = 'NEAREST'

        # gather neighboring geo
        if self.bmvs and context.tool_settings.use_proportional_edit:
            connected_only = context.tool_settings.use_proportional_connected
            if connected_only:
                all_bmvs = {}
                # NOTE: an exception is thrown if BMVerts are compared, so we are adding in bmv.index
                #       into tuple to break ties with same distances before bmvs are compared
                queue = [(0, bmv.index, bmv) for bmv in self.bmvs]
                while queue:
                    (d, _, bmv) = heapq.heappop(queue)
                    if bmv in all_bmvs: continue
                    all_bmvs[bmv] = d
                    for bmf in bmv.link_faces:
                        for bmv_ in bmf.verts:
                            heapq.heappush(queue, (d + (M @ bmv.co - M @ bmv_.co).length, bmv_.index, bmv_))
            else:
                cos_sel = [M @ bmv.co for bmv in self.bmvs]
                all_bmvs = {}
                for bmv in self.bm.verts:
                    co = M @ bmv.co
                    d = min((co - co_sel).length for co_sel in cos_sel)
                    all_bmvs[bmv] = d

            self.proportional_edit_overlay = ProportionalEditOverlay(context, event, self.bm)
        else:
            all_bmvs = { bmv: 0.0 for bmv in self.bmvs }

        self.data = all_bmvs
        self.last_success = { bmv:Vector(bmv.co) for bmv in all_bmvs }
        self.bmvs = all_bmvs.keys()
        self.bmvs_co_orig = { bmv: Vector(bmv.co) for bmv in self.bmvs }
        self.bmvs_co2d_orig = {
            bmv: location_3d_to_region_2d(context.region, context.region_data, (M @ Vector((*bmv.co, 1.0))).xyz)
            for bmv in self.bmvs
        }
        self.moving = None

        self.mirror = set()
        self.mirror_clip = False
        self.mirror_threshold = Vector((0, 0, 0))
        for mod in context.edit_object.modifiers:
            if mod.type != 'MIRROR': continue
            if not mod.use_clip: continue
            if mod.use_axis[0]: self.mirror.add('x')
            if mod.use_axis[1]: self.mirror.add('y')
            if mod.use_axis[2]: self.mirror.add('z')
            mt, scale = mod.merge_threshold, context.edit_object.scale
            self.mirror_threshold = Vector(( mt / scale.x, mt / scale.y, mt / scale.z ))
            self.mirror_clip = mod.use_clip

        self.bmfs = [(bmf, Vector(bmf.normal)) for bmf in { bmf for bmv in self.bmvs for bmf in bmv.link_faces }]
        self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_orig = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_prev = Vector((event.mouse_region_x, event.mouse_region_y))
        self.mouse_center = Vector((context.window.width // 2, context.window.height // 2))
        # self.RFCore.cursor_warp(context, self.mouse_center)  # NOTE: initial warping might not happen right away
        self.delay_delta_update = True
        self.delta = Vector((0, 0))
        self.delta_slow = Vector((0, 0))
        self.slow = False

        self.highlight = set()

        # Cursors.set('NONE')  # PAINT_CROSS

    def update(self, context, event):
        if self.use_native == 'TRUE':
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'}:
            self.cancel_reset(context, event)
            # self.RFCore.cursor_warp(context, self.mouse_orig)
            # print(f'CANCEL TRANSLATE')
            return {'CANCELLED'}

        if event.type == 'LEFTMOUSE':
            # HANDLE MERGE!!!
            self.automerge(context, event)
            # self.RFCore.cursor_warp(context, self.mouse_orig)
            bpy.ops.ed.undo_push(message='Transform')
            # print(f'COMMIT TRANSLATE')
            return {'FINISHED'}

        if event.type in {'WHEELDOWNMOUSE', 'WHEELUPMOUSE'}:
            if event.type in {'WHEELUPMOUSE'}:
                context.tool_settings.proportional_distance *= 0.90
            if event.type in {'WHEELDOWNMOUSE'}:
                context.tool_settings.proportional_distance /= 0.90
            if self.moving:
                for bmv in self.moving:
                    bmv.co = self.bmvs_co_orig[bmv]
            self.moving = None

        if event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT'} and event.value in {'PRESS', 'RELEASE'}:
            self.slow = (event.value == 'PRESS')
            if event.value == 'RELEASE':
                self.delta += self.delta_slow
                self.delta_slow = Vector((0, 0))

        if self.delay_delta_update:
            self.delay_delta_update = False
        elif event.type in {'MOUSEMOVE', 'WHEELDOWNMOUSE', 'WHEELUPMOUSE'}:
            self.mouse_prev = self.mouse
            self.mouse = Vector((event.mouse_region_x, event.mouse_region_y))
            self.translate(context, event)

        return {'RUNNING_MODAL'}

    def draw_postpixel(self, context):
        if self.highlight and not self.use_native == 'TRUE':
            theme = context.preferences.themes[0]
            with Drawing.draw(context, CC_2D_POINTS) as draw:
                draw.point_size(theme.view_3d.vertex_size + 4)
                draw.border(width=2, color=self.color_highlight_border)
                draw.color(self.color_highlight_fill)
                for bmv in self.highlight:
                    co = self.matrix_world @ bmv.co
                    p = location_3d_to_region_2d(context.region, context.region_data, co)
                    draw.vertex(p)

        if hasattr(self, 'proportional_edit_overlay'):
            self.proportional_edit_overlay.draw_2d(context)

    def automerge(self, context, event):
        prop_use = context.tool_settings.use_proportional_edit
        if not context.tool_settings.use_mesh_automerge or prop_use: return

        merging = {}
        for bmv in self.bmvs:
            self.nearest_bmv.update(context, bmv.co)
            if not self.nearest_bmv.bmv: continue
            bmv_into = self.nearest_bmv.bmv
            merging[bmv_into] = bmv
        bmesh.ops.weld_verts(self.bm, targetmap=merging)

        self.update_normals(context, event)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def cancel_reset(self, context, event):
        for bmv, co in self.bmvs_co_orig.items(): bmv.co = co
        for bmf, norm_orig in self.bmfs:
            bmf.normal_update()
            if norm_orig.dot(bmf.normal) < 0: bmf.normal_flip()
        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def translate(self, context, event):
        # self.delta += self.mouse - self.mouse_center
        # self.RFCore.cursor_warp(context, self.mouse_center)
        # self.delta = self.mouse - self.mouse_orig
        if not self.slow:
            self.delta += self.mouse - self.mouse_prev
        else:
            self.delta_slow += (self.mouse - self.mouse_prev) * 0.1
        delta = self.delta + self.delta_slow

        prop_use = context.tool_settings.use_proportional_edit
        prop_dist_world = context.tool_settings.proportional_distance
        prop_falloff = context.tool_settings.proportional_edit_falloff

        if self.moving is None:
            self.moving = [
                bmv for bmv in self.bmvs
                if self.data[bmv] <= prop_dist_world
            ]

        self.highlight = set()
        for bmv in self.moving:
            distance = self.data[bmv]
            co2d_orig = self.bmvs_co2d_orig[bmv]
            co_orig = self.bmvs_co_orig[bmv]
            if prop_use:
                dist = max(1 - distance / prop_dist_world, 0)
                factor = proportional_edit(prop_falloff, dist)
            else:
                factor = 1

            if self.snap_method == 'PROJECTED':
                co = raycast_point_valid_sources(context, co2d_orig + delta * factor, world=False)
                if not co:
                    co_world = region_2d_to_location_3d(context.region, context.region_data, co2d_orig + delta * factor, self.last_success[bmv])
                    co = nearest_point_valid_sources(context, co_world, world=False)
            elif self.snap_method == 'NEAREST':
                co = region_2d_to_location_3d(context.region, context.region_data, co2d_orig + delta * factor, self.matrix_world @ co_orig)
                co = nearest_point_valid_sources(context, co, world=True)
                co = self.matrix_world_inv @ co

            if self.mirror:
                t = self.mirror_threshold
                zero = {
                    'x': ('x' in self.mirror and (sign_threshold(co.x, t.x) != sign_threshold(co_orig.x, t.x) or sign_threshold(co_orig.x, t.x) == 0)),
                    'y': ('y' in self.mirror and (sign_threshold(co.y, t.y) != sign_threshold(co_orig.y, t.y) or sign_threshold(co_orig.y, t.y) == 0)),
                    'z': ('z' in self.mirror and (sign_threshold(co.z, t.z) != sign_threshold(co_orig.z, t.z) or sign_threshold(co_orig.z, t.z) == 0)),
                }
                # iteratively zero out the component
                for _ in range(1000):
                    d = 0
                    if zero['x']: co.x, d = co.x * 0.95, max(abs(co.x), d)
                    if zero['y']: co.y, d = co.y * 0.95, max(abs(co.y), d)
                    if zero['z']: co.z, d = co.z * 0.95, max(abs(co.z), d)
                    co_world = self.matrix_world @ Vector((*co, 1.0))
                    co_world_snapped = nearest_point_valid_sources(context, co_world.xyz / co_world.w, world=True)
                    co = self.matrix_world_inv @ co_world_snapped
                    if d < 0.001: break  # break out if change was below threshold
                if zero['x']: co.x = 0
                if zero['y']: co.y = 0
                if zero['z']: co.z = 0

            self.last_success[bmv] = co
            if distance > prop_dist_world: continue
            if context.tool_settings.use_mesh_automerge and not prop_use:
                self.nearest_bmv.update(context, co)
                if self.nearest_bmv.bmv:
                    co = self.nearest_bmv.bmv.co
                    self.highlight.add(self.nearest_bmv.bmv)
            bmv.co = co

        self.update_normals(context, event)

        bmesh.update_edit_mesh(self.em)
        context.area.tag_redraw()

    def update_normals(self, context, event):
        if self.snap_method == 'PROJECTED':
            forward = xform_direction(self.matrix_world_inv, view_forward_direction(context))
            for bmf, _ in self.bmfs:
                if not bmf.is_valid: continue
                bmf.normal_update()
                if forward.dot(bmf.normal) > 0:
                    bmf.normal_flip()
        elif self.snap_method == 'NEAREST':
            # workaround fix for issue #1462
            # TODO: revisit this and handle correctly!
            pass
