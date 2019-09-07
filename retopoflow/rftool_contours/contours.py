'''
Copyright (C) 2019 CG Cookie
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

from .contours_ops import Contours_Ops
from .contours_utils import (
    find_loops,
    find_strings,
    loop_plane,
    Contours_Loop,
)

from ..rftool import RFTool

from ...addon_common.common.utils import iter_pairs

class RFTool_Contours(RFTool):
    name        = 'Contours'
    description = 'Retopologize cylindrical forms, like arms and legs'
    icon        = 'contours_32.png'


class Contours(RFTool_Contours, Contours_Ops):
    def update(self):
        sel_edges = self.rfcontext.get_selected_edges()
        #sel_faces = self.rfcontext.get_selected_faces()

        # find verts along selected loops and strings
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges)

        # filter out any loops or strings that are in the middle of a selected patch
        def in_middle(bmvs, is_loop):
            return any(len(bmv0.shared_edge(bmv1).link_faces) > 1 for bmv0,bmv1 in iter_pairs(bmvs, is_loop))
        sel_loops = [loop for loop in sel_loops if not in_middle(loop, True)]
        sel_strings = [string for string in sel_strings if not in_middle(string, False)]

        # filter out long loops that wrap around patches, sharing edges with other strings
        bmes = {bmv0.shared_edge(bmv1) for string in sel_strings for bmv0,bmv1 in iter_pairs(string,False)}
        sel_loops = [loop for loop in sel_loops if not any(bmv0.shared_edge(bmv1) in bmes for bmv0,bmv1 in iter_pairs(loop,True))]

        mirror_mod = self.rfcontext.rftarget.mirror_mod
        symmetry_threshold = mirror_mod.symmetry_threshold
        def get_string_length(string):
            nonlocal mirror_mod, symmetry_threshold
            c = len(string)
            if c == 0: return 0
            touches_mirror = False
            (x0,y0,z0),(x1,y1,z1) = string[0].co,string[-1].co
            if mirror_mod.x:
                if abs(x0) < symmetry_threshold or abs(x1) < symmetry_threshold:
                    c = (c - 1) * 2
                    touches_mirror = True
            if mirror_mod.y:
                if abs(y0) < symmetry_threshold or abs(y1) < symmetry_threshold:
                    c = (c - 1) * 2
                    touches_mirror = True
            if mirror_mod.z:
                if abs(z0) < symmetry_threshold or abs(z1) < symmetry_threshold:
                    c = (c - 1) * 2
                    touches_mirror = True
            if not touches_mirror: c -= 1
            return c

        self.loops_data = [{
            'loop': loop,
            'plane': loop_plane(loop),
            'count': len(loop),
            'radius': loop_radius(loop),
            'cl': Contours_Loop(loop, True),
            } for loop in sel_loops]
        self.strings_data = [{
            'string': string,
            'plane': loop_plane(string),
            'count': get_string_length(string),
            'cl': Contours_Loop(string, False),
            } for string in sel_strings]
        self.sel_loops = [Contours_Loop(loop, True) for loop in sel_loops]

    @RFTool_Contours.FSM_State('main')
    def main(self) :
        pass
