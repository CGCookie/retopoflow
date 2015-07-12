'''
Copyright (C) 2015 CG Cookie
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

import bpy
import bgl
import bmesh
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion
import math

from ..lib import common_utilities
from ..lib.common_utilities import bversion, get_object_length_scale, dprint, profiler, frange, selection_mouse, showErrorMessage


class EdgePatches_UI_Tools:
    def modal_sketching(self, context, eventd):
        settings = common_utilities.get_settings()

        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            if settings.use_pressure:
                p = eventd['pressure']
                r = eventd['mradius']
            else:
                p = 1
                r = self.stroke_radius

            stroke_point = self.sketch[-1]

            (lx, ly) = stroke_point[0]
            lr = stroke_point[1]
            self.sketch_curpos = (x,y)
            self.sketch_pressure = p

            ss0,ss1 = self.stroke_smoothing,1-self.stroke_smoothing
            # Smooth radii
            self.stroke_radius_pressure = lr*ss0 + r*ss1
            if settings.use_pressure:
                self.sketch += [((lx*ss0+x*ss1, ly*ss0+y*ss1), self.stroke_radius_pressure)]
            else:
                self.sketch += [((lx*ss0+x*ss1, ly*ss0+y*ss1), self.stroke_radius)]

            return ''

        if eventd['release'] in {'LEFTMOUSE','SHIFT+LEFTMOUSE', 'CTRL+LEFTMOUSE'}:
            # correct for 0 pressure on release
            if self.sketch[-1][1] == 0:
                self.sketch[-1] = self.sketch[-2]

            # if is selection mouse, check distance
            if 'LEFTMOUSE' in selection_mouse():
                dist_traveled = 0.0
                for s0,s1 in zip(self.sketch[:-1],self.sketch[1:]):
                    dist_traveled += (Vector(s0[0]) - Vector(s1[0])).length

                # user like ly picking, because distance traveled is very small
                if dist_traveled < 5.0:
                    self.pick(eventd)
                    self.sketch = []
                    return 'main'

            p3d = common_utilities.ray_cast_stroke(eventd['context'], self.obj, self.sketch) if len(self.sketch) > 1 else []
            if len(p3d) <= 1: return 'main'

            # tessellate stroke (if needed) so we have good stroke sampling
            # TODO, tesselate pressure/radius values?
            # length_tess = self.length_scale / 700
            # p3d = [(p0+(p1-p0).normalized()*x) for p0,p1 in zip(p3d[:-1],p3d[1:]) for x in frange(0,(p0-p1).length,length_tess)] + [p3d[-1]]
            # stroke = [(p,self.stroke_radius) for i,p in enumerate(p3d)]

            self.sketch = []
            
            self.edgepatches.insert_gedge_from_stroke(p3d, False)
            
            #self.polystrips.remove_unconnected_gverts()
            #self.polystrips.update_visibility(eventd['r3d'])

            self.act_gvert = None
            self.act_gedge = None
            self.act_gpatch = None
            self.sel_gedges = set()
            self.sel_gverts = set()

            return 'main'

        return ''