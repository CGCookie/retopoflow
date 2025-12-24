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

from mathutils.bvhtree import BVHTree
from bmesh.types import BMVert, BMEdge, BMFace

from ..common.bmesh import get_bmesh_emesh, bme_other_bmv
from ...addon_common.common import bmesh_ops as bmops


class Patches_Context:
    """
    All context-related data is stored in this class so it is much
    easier to detele all references to the data, preventing RF from
    holding onto old, stale, or potentially bad context data that
    could cause Blender to leak memory or even crash.
    """
    def __init__(self, context, *, full_init=False):
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)

        if full_init:
            bmops.flush_selection(self.bm, self.em)
            self.bm.verts.ensure_lookup_table()
            self.bm.edges.ensure_lookup_table()
            self.bm.faces.ensure_lookup_table()

        # TRANSFORMATIONS
        self.M = context.edit_object.matrix_world
        self.Mi = self.M.inverted()
        self.edit_scale = max(self.M.to_scale())            # TODO: needed?

        # LAYERS
        # NOTE: MUST CREATE LAYERS BEFORE GRABBING REFERENCES TO BMELEMENTS!
        # 0+: side verts, used for pinning
        # -1: original verts that are not along side
        # -2: dynamically created verts
        self.layer_labels = bmops.get_layer(self.bm, BMVert, 'int', 'rf_patches_labels')

        # BVH Tree
        self.bvh = BVHTree.FromBMesh(self.bm)

        # SELECTION
        # get selected geo
        self.sel_bmverts = bmops.get_all_selected_bmverts(self.bm)
        self.sel_bmedges = bmops.get_all_selected_bmedges(self.bm)
        self.sel_bmfaces = bmops.get_all_selected_bmfaces(self.bm)

        self.side_bmedges = { bme for bme in self.sel_bmedges if len(bme.link_faces) < 2 }
        self.side_bmverts = { bmv for bme in self.side_bmedges for bmv in bme.verts }

        if full_init:
            # remove old initial and original markings
            for bmv in self.bm.verts:
                bmv[self.layer_labels] = -1
            for i, bmv in enumerate(self.side_bmverts):
                bmv[self.layer_labels] = i

        self.analyze()

    def analyze(self):
        # look at selected geo to determine what state we are in

        if not self.sel_bmverts: return     # nothing selected, so nothing to do
        if not self.sel_bmedges: return     # only verts selected, so nothing to do.  TODO: pole editing??

        if self.sel_bmfaces:
            # faces selected, so we're editing!
            # TODO: implement!
            return

        # only edges selected, so we're creating new faces
        self.corners = { bmv for bmv in self.side_bmverts if len([bme for bme in bmv.link_edges if bme in self.sel_bmedges]) }
        self.cycle = (len(self.corners) == 0)
        scan = self.corners or { next(iter(self.sel_bmverts)) }
        self.sides = []
        touched = set()
        for current in scan:
            if current in touched: continue
            self.sides.append([])
            while True:
                self.sides[-1].append(current)
                touched.add(current)
                for bme in current.link_edges:
                    if bme not in self.sel_bmedges: continue
                    other = bme_other_bmv(bme, current)
                    if other in touched: continue
                    current = other
                    break
                else:
                    # hit other corner of side
                    break


class Patches_Logic:
    def __init__(self, context, event):
        self.ctx = Patches_Context(context, full_init=True)

    def clear_context(self):
        del self.ctx
