'''
Copyright (C) 2021 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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
from ..rftool import RFTool
from ..rfwidgets.rfwidget_brushfalloff import RFWidget_BrushFalloff_Factory

from ...addon_common.common.maths import (
    Vec, Vec2D,
    Point, Point2D,
    Direction,
    Accel2D,
    Color,
)
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs, delay_exec
from ...config.options import options, themes


class RFTool_Relax(RFTool):
    name        = 'Relax'
    description = 'Relax the vertex positions to smooth out topology'
    icon        = 'relax-icon.png'
    help        = 'relax.md'
    shortcut    = 'relax tool'
    quick_shortcut = 'relax quick'
    statusbar   = '{{brush}} Relax\t{{brush alt}} Relax selection\t{{brush radius}} Brush size\t{{brush strength}} Brush strength\t{{brush falloff}} Brush falloff'
    ui_config   = 'relax_options.html'

class Relax_RFWidgets:
    RFWidget_BrushFalloff = RFWidget_BrushFalloff_Factory.create(
        BoundInt('''options['relax radius']''', min_value=1),
        BoundFloat('''options['relax falloff']''', min_value=0.00, max_value=100.0),
        BoundFloat('''options['relax strength']''', min_value=0.01, max_value=1.0),
        fill_color=themes['relax'],
    )

    def init_rfwidgets(self):
        self.rfwidget = self.RFWidget_BrushFalloff(self)

class Relax(RFTool_Relax, Relax_RFWidgets):
    @RFTool_Relax.on_init
    def init(self):
        self.init_rfwidgets()

    def reset_algorithm_options(self):
        options.reset(keys=[
            'relax steps',
            'relax force multiplier',
            'relax edge length',
            'relax face radius',
            'relax face sides',
            'relax face angles',
            'relax correct flipped faces',
            'relax straight edges',
        ])

    def disable_all_options(self):
        for key in [
                'relax edge length',
                'relax face radius',
                'relax face sides',
                'relax face angles',
                'relax correct flipped faces',
                'relax straight edges',
            ]:
            options[key] = False

    def reset_current_brush(self):
        options.reset(keys={'relax radius', 'relax falloff', 'relax strength'})
        self.document.body.getElementById(f'relax-current-radius').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'relax-current-strength').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'relax-current-falloff').dirty(cause='copied preset to current brush')

    def update_preset_name(self, n):
        name = options[f'relax preset {n} name']
        self.document.body.getElementById(f'relax-preset-{n}-summary').innerText = f'Preset: {name}'

    def copy_current_to_preset(self, n):
        options[f'relax preset {n} radius']   = options['relax radius']
        options[f'relax preset {n} strength'] = options['relax strength']
        options[f'relax preset {n} falloff']  = options['relax falloff']
        self.document.body.getElementById(f'relax-preset-{n}-radius').dirty(cause='copied current brush to preset')
        self.document.body.getElementById(f'relax-preset-{n}-strength').dirty(cause='copied current brush to preset')
        self.document.body.getElementById(f'relax-preset-{n}-falloff').dirty(cause='copied current brush to preset')

    def copy_preset_to_current(self, n):
        options['relax radius']   = options[f'relax preset {n} radius']
        options['relax strength'] = options[f'relax preset {n} strength']
        options['relax falloff']  = options[f'relax preset {n} falloff']
        self.document.body.getElementById(f'relax-current-radius').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'relax-current-strength').dirty(cause='copied preset to current brush')
        self.document.body.getElementById(f'relax-current-falloff').dirty(cause='copied preset to current brush')

    @RFTool_Relax.on_ui_setup
    def ui(self):
        self.update_preset_name(1)
        self.update_preset_name(2)
        self.update_preset_name(3)
        self.update_preset_name(4)

    @RFTool_Relax.on_reset
    def reset(self):
        self.sel_only = False

    @RFTool_Relax.FSM_State('main')
    def main(self) :
        if self.rfcontext.actions.pressed(['brush', 'brush alt'], unpress=False):
            self.sel_only = self.rfcontext.actions.using('brush alt')
            self.rfcontext.actions.unpress()
            self.rfcontext.undo_push('relax')
            return 'relax'

        if self.rfcontext.actions.pressed('pie menu alt0', unpress=False):
            def callback(option):
                if option is None: return
                self.copy_preset_to_current(option)
            self.rfcontext.show_pie_menu([
                (f'Preset: {options["relax preset 1 name"]}', 1),
                (f'Preset: {options["relax preset 2 name"]}', 2),
                (f'Preset: {options["relax preset 3 name"]}', 3),
                (f'Preset: {options["relax preset 4 name"]}', 4),
            ], callback)
            return

        # if self.rfcontext.actions.pressed('select single'):
        #     self.rfcontext.undo_push('select')
        #     self.rfcontext.deselect_all()
        #     return 'select'

        # if self.rfcontext.actions.pressed('select single add'):
        #     face,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
        #     if not face: return
        #     if face.select:
        #         self.mousedown = self.rfcontext.actions.mouse
        #         return 'selectadd/deselect'
        #     return 'select'

        # if self.rfcontext.actions.pressed({'select smart', 'select smart add'}, unpress=False):
        #     if self.rfcontext.actions.pressed('select smart'):
        #         self.rfcontext.deselect_all()
        #     self.rfcontext.actions.unpress()
        #     edge,_ = self.rfcontext.accel_nearest2D_edge(max_dist=10)
        #     if not edge: return
        #     faces = set()
        #     walk = {edge}
        #     touched = set()
        #     while walk:
        #         edge = walk.pop()
        #         if edge in touched: continue
        #         touched.add(edge)
        #         nfaces = set(f for f in edge.link_faces if f not in faces and len(f.edges) == 4)
        #         walk |= {f.opposite_edge(edge) for f in nfaces}
        #         faces |= nfaces
        #     self.rfcontext.select(faces, only=False)
        #     return

    # @RFTool_Relax.FSM_State('selectadd/deselect')
    # def selectadd_deselect(self):
    #     if not self.rfcontext.actions.using(['select single','select single add']):
    #         self.rfcontext.undo_push('deselect')
    #         face,_ = self.rfcontext.accel_nearest2D_face()
    #         if face and face.select: self.rfcontext.deselect(face)
    #         return 'main'
    #     delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
    #     if delta.length > self.drawing.scale(5):
    #         self.rfcontext.undo_push('select add')
    #         return 'select'

    # @RFTool_Relax.FSM_State('select')
    # def select(self):
    #     if not self.rfcontext.actions.using(['select single','select single add']):
    #         return 'main'
    #     bmf,_ = self.rfcontext.accel_nearest2D_face(max_dist=10)
    #     if not bmf or bmf.select: return
    #     self.rfcontext.select(bmf, supparts=False, only=False)

    @RFTool_Relax.FSM_State('relax', 'enter')
    def relax_enter(self):
        self._time = time.time()
        self._timer = self.actions.start_timer(120)

        opt_mask_boundary   = options['relax mask boundary']
        opt_mask_symmetry   = options['relax mask symmetry']
        opt_mask_occluded   = options['relax mask occluded']
        opt_mask_selected   = options['relax mask selected']
        opt_steps           = options['relax steps']
        opt_edge_length     = options['relax edge length']
        opt_face_radius     = options['relax face radius']
        opt_face_sides      = options['relax face sides']
        opt_face_angles     = options['relax face angles']
        opt_correct_flipped = options['relax correct flipped faces']
        opt_straight_edges  = options['relax straight edges']
        opt_mult            = options['relax force multiplier']
        is_visible = lambda bmv: self.rfcontext.is_visible(bmv.co, bmv.normal)

        self._bmverts = []
        for bmv in self.rfcontext.iter_verts():
            if self.sel_only and not bmv.select: continue
            if opt_mask_boundary == 'exclude' and bmv.is_on_boundary(): continue
            if opt_mask_symmetry == 'exclude' and bmv.is_on_symmetry_plane(): continue
            if opt_mask_occluded == 'exclude' and not is_visible(bmv): continue
            if opt_mask_selected == 'exclude' and bmv.select: continue
            if opt_mask_selected == 'only' and not bmv.select: continue
            self._bmverts.append(bmv)
        # print(f'Relaxing max of {len(self._bmverts)} bmverts')
        self.rfcontext.split_target_visualization(verts=self._bmverts)

    @RFTool_Relax.FSM_State('relax', 'exit')
    def relax_exit(self):
        self.rfcontext.update_verts_faces(self._bmverts)
        self.rfcontext.clear_split_target_visualization()
        self._timer.done()

    @RFTool_Relax.FSM_State('relax')
    def relax(self):
        st = time.time()

        if self.rfcontext.actions.released(['brush','brush alt']):
            return 'main'
        if self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        if not self.rfcontext.actions.timer: return

        hit_pos = self.rfcontext.actions.hit_pos
        if not hit_pos: return

        # collect data for smoothing
        radius = self.rfwidget.get_scaled_radius()
        nearest = self.rfcontext.nearest_verts_point(hit_pos, radius, bmverts=self._bmverts)
        verts,edges,faces,vert_strength = set(),set(),set(),dict()
        for bmv,d in nearest:
            verts.add(bmv)
            edges.update(bmv.link_edges)
            faces.update(bmv.link_faces)
            vert_strength[bmv] = self.rfwidget.get_strength_dist(d) / radius
        # self.rfcontext.select(verts)

        if not verts or not edges: return
        vert_strength = vert_strength or {}

        # gather options
        # opt_mask_boundary   = options['relax mask boundary']
        opt_mask_symmetry   = options['relax mask symmetry']
        # opt_mask_occluded   = options['relax mask hidden']
        # opt_mask_selected   = options['relax mask selected']
        opt_steps           = options['relax steps']
        opt_edge_length     = options['relax edge length']
        opt_face_radius     = options['relax face radius']
        opt_face_sides      = options['relax face sides']
        opt_face_angles     = options['relax face angles']
        opt_correct_flipped = options['relax correct flipped faces']
        opt_straight_edges  = options['relax straight edges']
        opt_mult            = options['relax force multiplier']

        is_visible = lambda bmv: self.rfcontext.is_visible(bmv.co, bmv.normal)

        cur_time = time.time()
        time_delta = cur_time - self._time
        self._time = cur_time
        strength = (5.0 / opt_steps) * self.rfwidget.strength * time_delta
        radius = self.rfwidget.get_scaled_radius()

        # capture all verts involved in relaxing
        chk_verts = set(verts)
        chk_verts.update(self.rfcontext.get_edges_verts(edges))
        chk_verts.update(self.rfcontext.get_faces_verts(faces))
        chk_edges = self.rfcontext.get_verts_link_edges(chk_verts)
        chk_faces = self.rfcontext.get_verts_link_faces(chk_verts)

        displace = {}
        def reset_forces():
            nonlocal displace
            displace.clear()
        def add_force(bmv, f):
            nonlocal displace, verts, vert_strength
            if bmv not in verts or bmv not in vert_strength: return
            cur = displace[bmv] if bmv in displace else Vec((0,0,0))
            displace[bmv] = cur + f

        def relax_2d():
            pass

        def relax_3d():
            reset_forces()

            # compute average edge length
            avg_edge_len = sum(bme.calc_length() for bme in edges) / len(edges)

            # push edges closer to average edge length
            if opt_edge_length:
                for bme in chk_edges:
                    if bme not in edges: continue
                    bmv0,bmv1 = bme.verts
                    vec = bme.vector()
                    edge_len = vec.length
                    f = vec * (0.1 * (avg_edge_len - edge_len) * strength) #/ edge_len
                    add_force(bmv0, -f)
                    add_force(bmv1, +f)

            # push verts if neighboring faces seem flipped (still WiP!)
            if opt_correct_flipped:
                bmf_flipped = { bmf for bmf in chk_faces if bmf.is_flipped() }
                for bmf in bmf_flipped:
                    # find a non-flipped neighboring face
                    for bme in bmf.edges:
                        bmfs = set(bme.link_faces)
                        bmfs.discard(bmf)
                        if len(bmfs) != 1: continue
                        bmf_other = next(iter(bmfs))
                        if bmf_other not in chk_faces: continue
                        if bmf_other in bmf_flipped: continue
                        # pull edge toward bmf_other center
                        bmf_other_center = bmf_other.center()
                        bme_center = bme.calc_center()
                        vec = bmf_other_center - bme_center
                        bmv0,bmv1 = bme.verts
                        add_force(bmv0, vec * strength * 5)
                        add_force(bmv1, vec * strength * 5)

            # push verts to straighten edges (still WiP!)
            if opt_straight_edges:
                for bmv in chk_verts:
                    if bmv.is_boundary: continue
                    bmes = bmv.link_edges
                    #if len(bmes) != 4: continue
                    center = Point.average(bme.other_vert(bmv).co for bme in bmes)
                    add_force(bmv, (center - bmv.co) * 0.1)

            # attempt to "square" up the faces
            for bmf in chk_faces:
                if bmf not in faces: continue
                bmvs = bmf.verts
                cnt = len(bmvs)
                ctr = Point.average(bmv.co for bmv in bmvs)
                rels = [bmv.co - ctr for bmv in bmvs]

                # push verts toward average dist from verts to face center
                if opt_face_radius:
                    avg_rel_len = sum(rel.length for rel in rels) / cnt
                    for rel, bmv in zip(rels, bmvs):
                        rel_len = rel.length
                        f = rel * ((avg_rel_len - rel_len) * strength * 2) #/ rel_len
                        add_force(bmv, f)

                # push verts toward equal edge lengths
                if opt_face_sides:
                    avg_face_edge_len = sum(bme.length for bme in bmf.edges) / cnt
                    for bme in bmf.edges:
                        bmv0, bmv1 = bme.verts
                        vec = bme.vector()
                        edge_len = vec.length
                        f = vec * ((avg_face_edge_len - edge_len) * strength) / edge_len
                        add_force(bmv0, f * -0.5)
                        add_force(bmv1, f * 0.5)

                # push verts toward equal spread
                if opt_face_angles:
                    avg_angle = 2.0 * math.pi / cnt
                    for i0 in range(cnt):
                        i1 = (i0 + 1) % cnt
                        rel0,bmv0 = rels[i0],bmvs[i0]
                        rel1,bmv1 = rels[i1],bmvs[i1]
                        vec = bmv1.co - bmv0.co
                        fvec0 = rel0.cross(vec).cross(rel0).normalize()
                        fvec1 = rel1.cross(rel1.cross(vec)).normalize()
                        vec_len = vec.length
                        angle = rel0.angle(rel1)
                        f_mag = (0.025 * (avg_angle - angle) * strength) / cnt #/ vec_len
                        add_force(bmv0, fvec0 * -f_mag)
                        add_force(bmv1, fvec1 * -f_mag)

        # perform smoothing
        for step in range(opt_steps):
            if options['relax algorithm'] == '3D':
                relax_3d()
            elif options['relax algorithm'] == '2D':
                relax_2d()

            if len(displace) <= 1: continue

            # update
            for bmv in displace:
                co = bmv.co + displace[bmv] * (opt_mult * vert_strength[bmv])
                if opt_mask_symmetry == 'maintain' and bmv.is_on_symmetry_plane():
                    snap_to_symmetry = self.rfcontext.symmetry_planes_for_point(bmv.co)
                    co = self.rfcontext.snap_to_symmetry(co, snap_to_symmetry)
                bmv.co = co
                self.rfcontext.snap_vert(bmv)
            self.rfcontext.update_verts_faces(displace)
        # print(f'relaxed {len(verts)} ({len(chk_verts)}) in {time.time() - st} with {strength}')

        self.rfcontext.dirty()
