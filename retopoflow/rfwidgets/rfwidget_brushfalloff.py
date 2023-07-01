'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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
import random

import gpu

from mathutils import Matrix, Vector

from ..rfwidget import RFWidget

from ...addon_common.common.fsm import FSM
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat
from ...addon_common.common.drawing import DrawCallbacks
from ...addon_common.common.globals import Globals
from ...addon_common.common import gpustate
from ...addon_common.common.maths import Vec, Point, Point2D, Direction, Color, Vec2D
from ...config.options import themes, options


class RFWidget_BrushFalloff_Factory:
    '''
    This is a class factory.  It is needed, because the FSM is shared across instances.
    RFTools might need to share RFWidgets that are independent of each other.
    '''

    @staticmethod
    def create(action_name, radius, falloff, strength, fill_color=Color((1,1,1,1)), outer_color=Color((1,1,1,1)), inner_color=Color((1,1,1,0.5)), below_alpha=Color((1,1,1,0.25))):
        class RFWidget_BrushFalloff(RFWidget):
            rfw_name = 'Brush Falloff'
            rfw_cursor = 'CROSSHAIR'

            @RFWidget.on_init
            def init(self):
                self.action_name = action_name
                self.outer_color = outer_color
                self.inner_color = inner_color
                self.fill_color = fill_color
                self.color_mult_below = below_alpha
                self.redraw_on_mouse = True
                self.last_mouse = None
                self.last_view = None
                self.hit = False
                self.hit_scale = 1.0

            @FSM.on_state('main')
            def main(self):
                self.update_mouse()

                if self.rfcontext.actions.pressed('brush radius increase'):
                    self.radius += 10
                    tag_redraw_all('BrushFalloff increase radius')
                    return
                if self.rfcontext.actions.pressed('brush radius decrease'):
                    self.radius -= 10
                    tag_redraw_all('BrushFalloff decrease radius')
                    return

                if self.rfcontext.actions.pressed('brush radius'):
                    self._dist_to_var_fn = self.dist_to_radius
                    self._var_to_dist_fn = self.radius_to_dist
                    return 'change'
                if self.rfcontext.actions.pressed('brush strength'):
                    self._dist_to_var_fn = self.dist_to_strength
                    self._var_to_dist_fn = self.strength_to_dist
                    return 'change'
                if self.rfcontext.actions.pressed('brush falloff'):
                    self._dist_to_var_fn = self.dist_to_falloff
                    self._var_to_dist_fn = self.falloff_to_dist
                    return 'change'

            @FSM.on_state('change', 'enter')
            def change_enter(self):
                dist = self._var_to_dist_fn()
                actions = self.rfcontext.actions
                self._change_pre = dist
                self._change_center = actions.mouse - Vec2D((dist, 0))
                self._timer = self.actions.start_timer(120)
                tag_redraw_all('BrushFalloff change_enter')

            @FSM.on_state('change')
            def change(self):
                assert self._dist_to_var_fn
                actions = self.rfcontext.actions

                if actions.pressed('cancel', ignoremods=True, ignoredrag=True):
                    self._dist_to_var_fn(self._change_pre)
                    return 'main'
                if actions.pressed({'confirm', 'confirm drag'}, ignoremods=True):
                    return 'main'

                dist = (self._change_center - actions.mouse).length
                self._dist_to_var_fn(dist)

            @FSM.on_state('change', 'exit')
            def change_exit(self):
                self._dist_to_var_fn = None
                self._var_to_dist_fn = None
                self._timer.done()
                tag_redraw_all('BrushFalloff change_exit')

            @DrawCallbacks.on_draw('post3d')
            @FSM.onlyinstate('main')
            def draw_brush(self):
                if not self.hit: return

                ff = math.pow(0.5, 1.0 / max(self.falloff, 0.0001))
                p, n = self.hit_p, self.hit_n
                ro = self.radius * self.hit_scale
                ri = ro * ff
                rm = (ro + ri) / 2.0
                co, ci, cc = self.outer_color, self.inner_color, self.fill_color * self.fill_color_scale

                # draw below
                gpustate.depth_mask(False)
                gpustate.depth_test('GREATER')
                Globals.drawing.draw3D_circle(p, rm, cc * self.color_mult_below, n=n, width=ro - ri,          depth_far=0.99996)
                Globals.drawing.draw3D_circle(p, ro, co * self.color_mult_below, n=n, width=2*self.hit_scale, depth_far=0.99995)
                Globals.drawing.draw3D_circle(p, ri, ci * self.color_mult_below, n=n, width=2*self.hit_scale, depth_far=0.99995)

                # draw above
                gpustate.depth_test('LESS_EQUAL')
                Globals.drawing.draw3D_circle(p, rm, cc, n=n, width=ro - ri,          depth_far=0.99996)
                Globals.drawing.draw3D_circle(p, ro, co, n=n, width=2*self.hit_scale, depth_far=0.99995)
                Globals.drawing.draw3D_circle(p, ri, ci, n=n, width=2*self.hit_scale, depth_far=0.99995)

                # reset
                gpustate.depth_test('LESS_EQUAL')
                gpustate.depth_mask(True)

            @DrawCallbacks.on_draw('post2d')
            @FSM.onlyinstate('change')
            def draw_brush_sizing(self):
                #r = (self._change_center - self.actions.mouse).length
                r = self.radius
                co = self.outer_color
                ci = self.inner_color
                cc = self.fill_color * self.fill_color_scale
                ff = math.pow(0.5, 1.0 / max(self.falloff, 0.0001))
                fs = (1-ff) * self.radius
                Globals.drawing.draw2D_circle(self._change_center, r-fs/2, cc, width=fs)
                Globals.drawing.draw2D_circle(self._change_center, r,      co, width=1)
                Globals.drawing.draw2D_circle(self._change_center, r*ff,   ci, width=1)


            ##################
            # getters

            def get_scaled_radius(self):
                return self.hit_scale * self.radius

            def get_scaled_size(self):
                return self.hit_scale * self.size

            def get_strength_dist(self, dist:float):
                return max(0.0, min(1.0, (1.0 - math.pow(dist / self.get_scaled_radius(), self.falloff)))) * self.strength

            def get_strength_Point(self, point:Point):
                if not self.hit_p: return 0.0
                return self.get_strength_dist((point - self.hit_p).length)


            ###################
            # radius

            @property
            def radius(self):
                return radius.get()
            @radius.setter
            def radius(self, v):
                radius.set(max(1, float(v)))

            def radius_to_dist(self):
                return self.radius

            def dist_to_radius(self, d):
                self.radius = max(1, int(d))

            def radius_gettersetter(self):
                def getter():
                    return int(self.radius)
                def setter(v):
                    self.radius = max(1, int(v))
                return (getter, setter)

            def get_radius_boundvar(self):
                return radius

            ##################
            # strength

            @property
            def strength(self):
                return strength.get()
            @strength.setter
            def strength(self, v):
                # print('strength', v)
                strength.set(max(0.01, min(1.0, float(v))))

            def strength_to_dist(self):
                return self.radius * (1.0 - self.strength)

            def dist_to_strength(self, d):
                self.strength = 1.0 - max(0.01, min(1.0, d / self.radius))

            def strength_gettersetter(self):
                def getter():
                    return int(self.strength * 100)
                def setter(v):
                    self.strength = max(1, min(100, v)) / 100
                return (getter, setter)

            def get_strength_boundvar(self):
                return strength

            ##################
            # falloff

            @property
            def falloff(self):
                return falloff.get()
            @falloff.setter
            def falloff(self, v):
                # print('falloff', v)
                falloff.set(max(0.0, min(100.0, float(v))))

            def falloff_to_dist(self):
                return self.radius * math.pow(0.5, 1.0 / max(self.falloff, 0.0001))

            def dist_to_falloff(self, d):
                self.falloff = math.log(0.5) / math.log(max(0.01, min(0.99, d / self.radius)))

            def falloff_gettersetter(self):
                def getter():
                    return int(100 * math.pow(0.5, 1.0 / max(self.falloff, 0.0001)))
                def setter(v):
                    self.falloff = math.log(0.5) / math.log(max(0.01, min(0.99, v / 100)))
                    pass
                return (getter, setter)

            def get_falloff_boundvar(self):
                return falloff

            ##################
            # fill_color_scale

            @property
            def fill_color_scale(self):
                return Color((1, 1, 1, self.strength * (options['brush max alpha'] - options['brush min alpha']) + options['brush min alpha']))

            ##################
            # mouse

            def update_mouse(self):
                recompute = False
                recompute |= (self.last_mouse != self.actions.mouse)
                recompute |= (self.last_view  != self.rfcontext.get_view_version())
                if not recompute: return
                self.last_mouse = self.actions.mouse
                self.last_view  = self.rfcontext.get_view_version()

                self.hit = False

                # figure out how much to scale so that the brush drawn in 3D appears the same size on screen
                xy = self.actions.mouse
                p,n,_,_ = self.rfcontext.raycast_sources_mouse()
                if not p: return
                depth = self.rfcontext.Point_to_depth(p)
                if not depth: return
                scale = self.rfcontext.size2D_to_size(1.0, depth)
                if scale is None: return

                rmat = Matrix.Rotation(Direction.Z.angle(n), 4, Direction.Z.cross(n))

                self.hit = True
                self.hit_scale = scale
                self.hit_p = p
                self.hit_n = n
                self.hit_x = Vec(rmat @ Direction.X)
                self.hit_y = Vec(rmat @ Direction.Y)
                self.hit_z = Vec(rmat @ Direction.Z)
                self.hit_rmat = rmat

        return RFWidget_BrushFalloff
