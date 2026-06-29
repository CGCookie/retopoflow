'''
Copyright (C) 2026 CG Cookie
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

from __future__ import annotations
import os
from typing import cast
from collections.abc import Callable, Sequence

import bpy
from mathutils.bvhtree import BVHTree
from mathutils import Vector, Matrix
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from bpy_extras.view3d_utils import location_3d_to_region_2d
from bpy.types import Mesh, Context, Object

from ...addon_common.common import bmesh_ops as bmops
from ...addon_common.common.bmesh_ops import BMLayer
from ...addon_common.common.decorators import add_cache
from ...addon_common.common.colors import Color4
from ...addon_common.common.maths import Frame, Point, Normal
from ...addon_common.common.utils import iter_pairs
from ..common.bmesh import get_bmesh_emesh, bme_other_bmv
from ..common.drawing import (
    Drawing,
    CC_2D_POINTS,
    CC_3D_POINTS,
    CC_2D_LINES,
    CC_2D_TRIANGLES,
)


class Patches_Template:
    _cache : dict[str, Patches_Template] = {}
    _active : Patches_Template | None = None

    height : float
    is_flat : bool
    radius : float
    snap_vs : list[int]
    vcs : list[bool]
    vps : list[Vector]
    vns : list[Vector]
    snapped_vps : list[Vector]
    snapped_vns : list[Vector]
    vc : int
    ec : int
    fc : int
    es : list[tuple[int, ...]]
    fs : list[tuple[int, ...]]

    def __init__(self, data : Mesh | dict[str, list[Sequence[Vector]] | list[Sequence[int]]]):
        self.vc = 0
        self.ec = 0
        self.fc = 0
        self.snapped_vps = []
        self.snapped_vns = []
        self.vns = []
        self.fs = []
        if isinstance(data, Mesh):
            self._from_mesh(data)
        else:
            self._from_data(data)
        self._process()

    def _from_data(self, data : dict[str, list[Sequence[Vector]] | list[Sequence[int]]]):
        self.vc, self.ec, self.fc = len(data['vertices']), len(data['edges']), len(data['polygons'])
        self.vps = [ Vector(co) for (co,_no) in data['vertices'] ]
        self.vns = [ Vector(no) for (_co,no) in data['vertices'] ]
        self.es  = [ tuple(e)   for e in data['edges'] ]
        self.fs  = [ tuple(f)   for f in data['polygons'] ]

    def _from_mesh(self, mesh : Mesh):
        self.vc, self.ec, self.fc = len(mesh.vertices), len(mesh.edges), len(mesh.polygons)
        self.vps = [ Vector(v.co)      for v in mesh.vertices ]
        self.vns = [ Vector(v.normal)  for v in mesh.vertices ]
        self.es  = [ tuple(e.vertices) for e in mesh.edges    ]
        self.fs  = [ tuple(f.vertices) for f in mesh.polygons ]

    def _process(self):
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
        bbox_size = bbox_max - bbox_min

        bbox_center = Vector((
            bbox_min.x + bbox_size.x / 2,
            bbox_min.y + bbox_size.y / 2,
            bbox_min.z,
        ))
        max_size = 0.5 * max(0.000001, bbox_size.x, bbox_size.y)

        # rescale and translate mesh
        self.vps = [(v - bbox_center) / max_size for v in self.vps]

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
        self.snap_vs = [i for (i,c) in enumerate(self.vcs) if c]

        self.height = bbox_size.z / max_size
        self.is_flat = (self.height < 0.001)
        self.radius = max(p.xy.length for p in self.vps)

        self._update(None, None)

    def _update(
        self,
        fn_transform_vertex : Callable[[Point|Vector, Normal|Vector], tuple[Point|Vector, Normal|Vector]] | None,
        fn_snap_vertices : Callable[[list[tuple[Point|Vector, Normal|Vector]], list[int]], None] | None,
    ):
        if fn_transform_vertex is None:
            self.snapped_vps = self.vps
            self.snapped_vns = self.vns
            return

        ptnos = [ fn_transform_vertex(pt, no) for (pt, no) in zip(self.vps, self.vns) ]

        if fn_snap_vertices:
            fn_snap_vertices(ptnos, self.snap_vs)

        # zip with existing geometry
        # snap to nearest surface

        self.snapped_vps = [ pt for (pt, _no) in ptnos ]
        self.snapped_vns = [ no for (_pt, no) in ptnos ]

    @staticmethod
    def update_active(
        fn_transform_vertex: Callable[[Point|Vector, Normal|Vector], tuple[Point|Vector, Normal|Vector]] | None,
        fn_snap_vertices : Callable[[list[tuple[Point|Vector, Normal|Vector]], list[int]], None] | None,
    ):
        active = Patches_Template._active
        if not active: return
        active._update(fn_transform_vertex, fn_snap_vertices)

    @staticmethod
    def get_active_height() -> float:
        active = Patches_Template._active
        return active.height if active else 0.0

    @staticmethod
    def get_active_radius() -> float:
        active = Patches_Template._active
        return active.radius if active else 0.0

    @staticmethod
    def is_active_flat():
        active = Patches_Template._active
        return active.is_flat if active else False

    @staticmethod
    def activate(context : Context, asset_identifier : str | None, library_identifier : str | None, library_type : str | None):
        if not asset_identifier or not library_identifier or not library_type:
            Patches_Template._active = None
            return

        print(f'Activate asset: "{asset_identifier}" from libary: "{library_identifier}" ({library_type})')
        template_id = f'{library_type} {library_identifier} {asset_identifier}'
        cache = Patches_Template._cache

        # library_type: enum in ['ALL', 'LOCAL', 'ESSENTIALS', 'CUSTOM']
        # https://docs.blender.org/api/latest/bpy.types.AssetWeakReference.html#bpy.types.AssetWeakReference.asset_library_type
        # TODO: test how to load from 'ALL' or 'ESSENTIALS'
        if template_id not in cache:
            print('\tNOT IN CACHE!')

            if library_type == 'LOCAL':
                obj_name = asset_identifier.split('/')[-1]
                obj = bpy.data.objects[obj_name]
                if not obj:
                    print(f'Patches_Template.activate failed due to not finding object {obj_name}')
                    return
                mesh = obj.data
                if not mesh:
                    print(f'Patches_Template.activate failed due to not finding mesh for object {obj_name}')
                    return
                cache[template_id] = Patches_Template(cast(Mesh, mesh))

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
                # the following must be **OUTSIDE** the with above
                asset_scene.collection.objects.link(data_to.objects[0])  # does NOT return the object linked!
                asset_object = asset_scene.collection.objects[0]  # should be only one object in temp scene
                assert asset_object

                # grab and process mesh data
                cache[template_id] = Patches_Template(cast(Mesh, asset_object.data))

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
    def draw_active(context : Context, highlight : Color4):
        active = Patches_Template._active
        if active is None: return
        pts = [
            location_3d_to_region_2d(context.region, context.region_data, pt)
            for pt in active.snapped_vps
        ]

        theme = context.preferences.themes[0].view_3d

        color_point       = Color4((highlight[0], highlight[1], highlight[2], 1))
        color_border_mesh = Color4((theme.edge_select[0], theme.edge_select[1], theme.edge_select[2], 1))
        color_stipple     = Color4((theme.edge_select[0], theme.edge_select[1], theme.edge_select[2], 0))
        color_mesh        = theme.face_select
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
            draw.stipple(pattern=[1,0], offset=0, color=color_border_mesh)
            for (e0,e1) in active.es:
                pt0, pt1 = pts[e0], pts[e1]
                if not pt0 or not pt1: continue
                draw.vertex(pt0).vertex(pt1)

            drawn = set()
            for f in active.fs:
                if not all(pts[i] for i in f): continue
                for (e0, e1) in iter_pairs(f, True):
                    if not active.vcs[e0] or not active.vcs[e1]: continue
                    if (e0,e1) in drawn or (e1,e0) in drawn: continue
                    drawn.add((e0,e1))
                    pt0, pt1 = pts[e0], pts[e1]
                    if not pt0 or not pt1: continue
                    draw.vertex(pt0).vertex(pt1)

            # draw face edges
            draw.line_width(1)
            draw.stipple(pattern=[5,5], offset=0, color=color_stipple)
            for f in active.fs:
                if not all(pts[i] for i in f): continue
                for (e0, e1) in iter_pairs(f, True):
                    if (e0,e1) in drawn or (e1,e0) in drawn: continue
                    drawn.add((e0,e1))
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
    bm : BMesh
    em : Mesh
    M : Matrix
    Mi : Matrix
    edit_scale : float
    layer_labels : BMLayer
    sel_bmverts : set[BMVert]
    sel_bmedges : set[BMEdge]
    sel_bmfaces : set[BMFace]
    side_bmedges : set[BMEdge]
    side_bmverts : set[BMVert]
    bvh : BVHTree
    cycle : bool
    sides : list[list[BMVert]]

    def __init__(self, context, *, full_init=False):
        self.bm, self.em = get_bmesh_emesh(context, ensure_lookup_tables=True)

        if full_init:
            bmops.flush_selection(self.bm, self.em)
            self.bm.verts.ensure_lookup_table()
            self.bm.edges.ensure_lookup_table()
            self.bm.faces.ensure_lookup_table()

        # TRANSFORMATIONS
        eo : Object = context.edit_object
        self.M = eo.matrix_world # pyright: ignore[reportConstantRedefinition]
        self.Mi = self.M.inverted_safe()
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
        self.corners = set()
        self.cycle = False
        self.sides = []

        if not self.sel_bmverts: return     # nothing selected, so nothing to do
        if not self.sel_bmedges: return     # only verts selected, so nothing to do.  TODO: pole editing??

        if self.sel_bmfaces:
            # faces selected, so we're editing!
            # TODO: implement!
            return

        # only edges selected, so we're creating new faces
        self.corners : set[BMVert] = {
            bmv
            for bmv in self.side_bmverts
            if len([bme for bme in bmv.link_edges if bme in self.sel_bmedges])
        }
        self.cycle = (len(self.corners) == 0)
        self.sides = []
        first_sel_bmvert = next(iter(self.sel_bmverts), None)
        if not first_sel_bmvert: return
        scan : set[BMVert] = self.corners or { first_sel_bmvert }
        touched : set[BMVert] = set()
        for current in scan:
            if current in touched: continue
            self.sides.append([])
            while True:
                self.sides[-1].append(current)
                touched.add(current)
                for bme in current.link_edges:
                    if bme not in self.sel_bmedges:
                        continue
                    other = bme_other_bmv(bme, current)
                    if not other or other in touched:
                        continue
                    current = other
                    break
                else:
                    # hit other corner of side
                    break


class Patches_Logic:
    ctx : Patches_Context
    rotate : int
    mirror : bool
    error  : bool

    def __init__(self, context : Context):
        self.ctx = Patches_Context(context, full_init=True)
        self.rotate = 0
        self.mirror = False
        self.error = False

    def clear_context(self):
        del self.ctx

    def create(self, _context : Context):
        pass
