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
from typing import Self

import bpy
from mathutils.bvhtree import BVHTree
from mathutils import Vector
from bmesh.types import BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.decorators import add_cache
from ...addon_common.common.colors import Color4
from ...addon_common.common.utils import iter_pairs
from ..common.bmesh import get_bmesh_emesh, bme_other_bmv
from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_2D_LINES,
    CC_2D_TRIANGLES,
)


class Patches_Template:
    _cache : dict[tuple[str, str, str], Self] = {}
    _active : Self | None = None

    def __init__(self, data):
        if type(data) is bpy.types.Mesh:
            self._from_mesh(data)
        else:
            self._from_data(data)
        self._process()

    def _from_data(self, data):
        self.vc, self.ec, self.fc = len(data['vertices']), len(data['edges']), len(data['polygons'])
        self.vps = [ Vector(co) for (co,no) in data['vertices'] ]
        self.vns = [ Vector(no) for (co,no) in data['vertices'] ]
        self.es  = [ tuple(e)   for e in data['edges']    ]
        self.fs  = [ tuple(f)   for f in data['polygons'] ]

    def _from_mesh(self, mesh):
        self.vc, self.ec, self.fc = len(mesh.vertices), len(mesh.edges), len(mesh.polygons)
        self.vps = [ Vector(v.co)      for v in mesh.vertices ]
        self.vns = [ Vector(v.normal)  for v in mesh.vertices ]
        self.es  = [ tuple(e.vertices) for e in mesh.edges    ]
        self.fs  = [ tuple(f.vertices) for f in mesh.polygons ]

    def _process(self):
        # rescale and translate mesh
        bbox_min = Vector((
            min(v.x for v in self.vps),
            min(v.y for v in self.vps),
            min(v.z for v in self.vps),
        ))
        bbox_max = Vector((
            max(v.x for v in self.vps),
            max(v.y for v in self.vps),
            max(v.z for v in self.vps),
        ))
        bbox_center = Vector((
            bbox_min.x + (bbox_max.x - bbox_min.x) / 2,
            bbox_min.y + (bbox_max.y - bbox_min.y) / 2,
            bbox_min.z
        ))
        bbox_size = 0.5 * max(0.000001, bbox_max.x - bbox_min.x, bbox_max.y - bbox_min.y) #, bbox_max.z - bbox_min.z)
        self.vps = [(v - bbox_center) / bbox_size for v in self.vps]

        # filter out face edges
        fes = { e for f in self.fs for (i,j) in iter_pairs(f, True) for e in [(i,j), (j,i)] }
        self.es  = [ e for e in self.es if e not in fes ]
        self.ec = len(self.es)

        # count faces and edges per vert
        fes = {}
        self.vcs = [False for _ in range(self.vc)]
        for f in self.fs:
            for (i,j) in iter_pairs(f, True):
                i,j = min(i,j), max(i,j)
                fes.setdefault((i,j), 0)
                fes[(i,j)] += 1
        for f in self.fs:
            for (i,j) in iter_pairs(f, True):
                i,j = min(i,j), max(i,j)
                if fes[(i,j)] == 2: continue
                self.vcs[i] = True
                self.vcs[j] = True
        for e in self.es:
            for v in e:
                self.vcs[v] = True

        self.is_flat = (bbox_max.z - bbox_min.z) < 0.001
        self.radius = max(self.vps, key=lambda p:p.xy.length)

    @staticmethod
    def is_active_flat():
        active = Patches_Template._active
        if active is None: return False
        return active.is_flat

    @staticmethod
    def activate(context, asset_identifier, library_identifier, library_type):
        print(f'Activate asset: "{asset_identifier}" from libary: "{library_identifier}" ({library_type})')
        template_id = (library_type, library_identifier, asset_identifier)
        cache = Patches_Template._cache

        # library_type: enum in ['ALL', 'LOCAL', 'ESSENTIALS', 'CUSTOM']
        # https://docs.blender.org/api/latest/bpy.types.AssetWeakReference.html#bpy.types.AssetWeakReference.asset_library_type
        # TODO: test how to load from 'ALL' or 'ESSENTIALS'
        if template_id not in cache:
            print('  NOT IN CACHE!')

            if library_type == 'LOCAL':
                obj_name = asset_identifier.split('/')[-1]
                mesh = bpy.data.objects[obj_name].data
                cache[template_id] = Patches_Template(mesh)

            elif library_type == 'CUSTOM':
                blend, object_type, object_name = asset_identifier.split('/')
                assert object_type == 'Object', 'Cannot activate non-object'
                blend_path = os.path.join(
                    context.preferences.filepaths.asset_libraries[library_identifier].path,
                    blend
                )

                # link asset into a temporary scene (makes finding object easier)
                print(f'temporarily linking in {object_type} {object_name} from {blend_path}')
                asset_scene = bpy.data.scenes.new('RF Patches')
                # link in asset (THIS IS REALLY AWKWARD, BUT SEEMS TO BE THE ONLY WAY?)
                with bpy.data.libraries.load(blend_path, link=True) as (data_from, data_to):
                    assert object_name in data_from.objects, f'Could not find {object_name} ({object_type}) in {blend} ({blend_path})'
                    data_to.objects = [object_name]
                asset_scene.collection.objects.link(data_to.objects[0])  # does NOT return the object linked!
                asset_object = asset_scene.collection.objects[0]  # should be only one object in temp scene

                # grab and process mesh data
                cache[template_id] = Patches_Template(asset_object.data)

                # clean up!
                bpy.data.objects.remove(asset_object, do_unlink=True)
                bpy.data.scenes.remove(asset_scene)

            else:
                # default is a quad
                cache[template_id] = Patches_Template({
                    'vertices': [
                        (Vector((-1, -1, 0)), Vector((0, 0, 1))),
                        (Vector(( 1, -1, 0)), Vector((0, 0, 1))),
                        (Vector(( 1,  1, 0)), Vector((0, 0, 1))),
                        (Vector((-1,  1, 0)), Vector((0, 0, 1))),
                    ],
                    'edges': [],
                    'polygons': [
                        (0, 1, 2, 3)
                    ],
                })

        Patches_Template._active = cache[template_id]

    @staticmethod
    def compute_active_height(fn_transform_vertex):
        active = Patches_Template._active
        if active is None: return 0.0
        ptnos = [ fn_transform_vertex(pt, no) for (pt, no) in zip(active.vps, active.vns) ]
        z_min = min(pt.z for (pt,no) in ptnos)
        z_max = max(pt.z for (pt,no) in ptnos)
        return z_max - z_min

    @staticmethod
    def draw_active(context, fn_transform_vertex, highlight):
        active = Patches_Template._active
        if active is None: return
        ptnos = [ fn_transform_vertex(pt, no) for (pt, no) in zip(active.vps, active.vns) ]
        pts = [
            location_3d_to_region_2d(context.region, context.region_data, pt)
            for (pt, no) in ptnos
        ]

        theme = context.preferences.themes[0].view_3d

        color_point =               Color4((highlight[0], highlight[1], highlight[2], 1))
        color_border_mesh =         Color4((theme.edge_select[0], theme.edge_select[1], theme.edge_select[2], 1))
        color_stipple =             Color4((theme.face_select[0], theme.face_select[1], theme.face_select[2], 0))
        color_mesh = theme.face_select
        vertex_size = theme.vertex_size

        with Drawing.draw(context, CC_2D_POINTS) as draw:
            draw.point_size(vertex_size + 4)
            draw.color(color_point)
            for pt, c in zip(pts, active.vcs):
                if not c or not pt: continue
                draw.vertex(pt)

        with Drawing.draw(context, CC_2D_LINES) as draw:
            draw.color(color_border_mesh)

            # draw non-face edges
            draw.line_width(2)
            draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
            for (e0,e1) in active.es:
                pt0, pt1 = pts[e0], pts[e1]
                if not pt0 or not pt1: continue
                draw.vertex(pt0).vertex(pt1)

            # draw face edges
            draw.line_width(1)
            draw.stipple(pattern=[5,0], offset=0, color=color_stipple)
            for f in active.fs:
                if not all(pts[i] for i in f): continue
                for (e0, e1) in iter_pairs(f, True):
                    pt0, pt1 = pts[e0], pts[e1]
                    if not pt0 or not pt1: continue
                    draw.vertex(pt0).vertex(pt1)

        with Drawing.draw(context, CC_2D_TRIANGLES) as draw:
            draw.color(color_mesh)
            for f in active.fs:
                if not all(pts[i] for i in f): continue
                v0 = f[0]
                pt0 = pts[v0]
                for (v1, v2) in iter_pairs(f[1:], False):
                    pt1, pt2 = pts[v1], pts[v2]
                    draw.vertex(pt0).vertex(pt1).vertex(pt2)


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
    rotate:int
    mirror:bool
    error:bool

    def __init__(self, context):
        self.ctx = Patches_Context(context, full_init=True)
        self.rotate = 0
        self.mirror = False
        self.error = False

    def clear_context(self):
        del self.ctx

    def create(self, context):
        pass
