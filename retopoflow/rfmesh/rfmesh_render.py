'''
Copyright (C) 2021 CG Cookie
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

import sys
import math
import copy
import json
import time
import random

from queue import Queue
from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl
import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from mathutils import Matrix, Vector
from mathutils.geometry import normal as compute_normal, intersect_point_tri
from ...addon_common.common.globals import Globals
from ...addon_common.common.debug import dprint, Debugger
from ...addon_common.common.profiler import profiler
from ...addon_common.common.maths import Point, Direction, Normal, Frame
from ...addon_common.common.maths import Point2D, Vec2D, Direction2D
from ...addon_common.common.maths import Ray, XForm, BBox, Plane
from ...addon_common.common.utils import min_index
from ...addon_common.common.hasher import hash_object, hash_bmesh
from ...addon_common.common.decorators import stats_wrapper
from ...addon_common.common import bmesh_render as bmegl
from ...addon_common.common.bmesh_render import triangulateFace, BufferedRender_Batch
from ...addon_common.common.blender import tag_redraw_all

from ...config.options import options

from .rfmesh_wrapper import (
    BMElemWrapper, RFVert, RFEdge, RFFace, RFEdgeSequence
)



class RFMeshRender():
    '''
    RFMeshRender handles rendering RFMeshes.
    '''

    cache = {}

    create_count = 0
    delete_count = 0

    @staticmethod
    @profiler.function
    def new(rfmesh, opts, always_dirty=False):
        # TODO: REIMPLEMENT CACHING!!
        #       HAD TO DISABLE THIS BECAUSE 2.83 AND 2.90 WOULD CRASH
        #       WHEN RESTARTING RF.  PROBABLY DUE TO HOLDING REFS TO
        #       OLD DATA (CRASH DUE TO FREEING INVALID DATA??)

        if False:
            with profiler.code('hashing object'):
                ho = hash_object(rfmesh.obj)
            with profiler.code('hashing bmesh'):
                hb = hash_bmesh(rfmesh.bme)
            h = (ho, hb)
            if h not in RFMeshRender.cache:
                RFMeshRender.creating = True
                RFMeshRender.cache[h] = RFMeshRender(rfmesh, opts)
                del RFMeshRender.creating
            rfmrender = RFMeshRender.cache[h]
        else:
            RFMeshRender.creating = True
            rfmrender = RFMeshRender(rfmesh, opts)
            del RFMeshRender.creating

        rfmrender.always_dirty = always_dirty
        return rfmrender

    @profiler.function
    def __init__(self, rfmesh, opts):
        assert hasattr(RFMeshRender, 'creating'), (
            'Do not create new RFMeshRender directly!'
            'Use RFMeshRender.new()')

        RFMeshRender.create_count += 1
        # print('RFMeshRender.__init__', RFMeshRender.create_count, RFMeshRender.delete_count)

        # initially loading asynchronously?
        self.async_load = options['async mesh loading']
        self._is_loading = False
        self._is_loaded = False

        self.load_verts = opts.get('load verts', True)
        self.load_edges = opts.get('load edges', True)
        self.load_faces = opts.get('load faces', True)

        self.buf_data_queue     = Queue()
        self.buf_matrix_model   = rfmesh.xform.to_bglMatrix_Model()
        self.buf_matrix_inverse = rfmesh.xform.to_bglMatrix_Inverse()
        self.buf_matrix_normal  = rfmesh.xform.to_bglMatrix_Normal()
        self.buffered_renders_static  = []
        self.buffered_renders_dynamic = []
        self.split   = None
        self.drawing = Globals.drawing

        self.opts = {}
        self.replace_rfmesh(rfmesh)
        self.replace_opts(opts)

    def __del__(self):
        RFMeshRender.delete_count += 1
        # print('RFMeshRender.__del__', self.rfmesh, RFMeshRender.create_count, RFMeshRender.delete_count)
        self.bmesh.free()
        if hasattr(self, 'buf_matrix_model'):         del self.buf_matrix_model
        if hasattr(self, 'buf_matrix_inverse'):       del self.buf_matrix_inverse
        if hasattr(self, 'buf_matrix_normal'):        del self.buf_matrix_normal
        if hasattr(self, 'buffered_renders_static'):  del self.buffered_renders_static
        if hasattr(self, 'buffered_renders_dynamic'): del self.buffered_renders_dynamic
        if hasattr(self, 'bmesh'):                    del self.bmesh
        if hasattr(self, 'rfmesh'):                   del self.rfmesh

    @profiler.function
    def replace_opts(self, opts):
        opts = dict(opts)
        opts['dpi mult'] = self.drawing.get_dpi_mult()
        if opts == self.opts: return
        self.opts = opts
        self.rfmesh_version = None

    @profiler.function
    def replace_rfmesh(self, rfmesh):
        self.rfmesh = rfmesh
        self.bmesh  = rfmesh.bme
        self.rfmesh_version = None

    def dirty(self):
        self.rfmesh_version = None

    @profiler.function
    def add_buffered_render(self, bgl_type, data, static):
        batch = BufferedRender_Batch(bgl_type)
        batch.buffer(data['vco'], data['vno'], data['sel'], data['warn'])
        if static: self.buffered_renders_static.append(batch)
        else:      self.buffered_renders_dynamic.append(batch)
        # buffered_render = BGLBufferedRender(bgl_type)
        # buffered_render.buffer(data['vco'], data['vno'], data['sel'], data['idx'])
        # self.buffered_renders.append(buffered_render)

    def split_visualization(self, verts=None, edges=None, faces=None):
        if not verts and not edges and not faces:
            self.split = None
        else:
            unwrap = BMElemWrapper._unwrap
            verts = { unwrap(v) for v in verts } if verts else set()
            edges = { unwrap(e) for e in edges } if edges else set()
            faces = { unwrap(f) for f in faces } if faces else set()
            edges.update(e for v in verts for e in v.link_edges)
            faces.update(f for e in edges for f in e.link_faces)
            verts.update(v for e in edges for v in e.verts)
            verts.update(v for f in faces for v in f.verts)
            edges.update(e for f in faces for e in f.edges)
            self.split = {
                'gathered static': False,
                'static verts': { v for v in self.bmesh.verts if v not in verts },
                'static edges': { e for e in self.bmesh.edges if e not in edges },
                'static faces': { f for f in self.bmesh.faces if f not in faces },
                'gathered dynamic': False,
                'dynamic verts': verts,
                'dynamic edges': edges,
                'dynamic faces': faces,
            }
        self.dirty()

    @profiler.function
    def _gather_data(self):
        if not self.split:
            self.buffered_renders_static = []
            self.buffered_renders_dynamic = []
        else:
            if not self.split['gathered dynamic']:
                self.buffered_renders_static = []
                self.split['gathered dynamic'] = True
            self.buffered_renders_dynamic = []

        mirror_axes = self.rfmesh.mirror_mod.xyz if self.rfmesh.mirror_mod else []
        mirror_x = 'x' in mirror_axes
        mirror_y = 'y' in mirror_axes
        mirror_z = 'z' in mirror_axes

        def gather(verts, edges, faces, static):
            vert_count = 100000
            edge_count = 50000
            face_count = 10000

            '''
            IMPORTANT NOTE: DO NOT USE PROFILER INSIDE THIS FUNCTION IF LOADING ASYNCHRONOUSLY!
            '''
            def sel(g):
                return 1.0 if g.select else 0.0
            def warn_vert(g):
                if mirror_x and g.co.x <=  0.0001: return 0.0
                if mirror_y and g.co.y >= -0.0001: return 0.0
                if mirror_z and g.co.z <=  0.0001: return 0.0
                return 0.0 if g.is_manifold and not g.is_boundary else 1.0
            def warn_edge(g):
                if mirror_x:
                    v0,v1 = g.verts
                    if v0.co.x <= 0.0001 and v1.co.x <= 0.0001: return 0.0
                if mirror_y:
                    v0,v1 = g.verts
                    if v0.co.y >= -0.0001 and v1.co.y >= -0.0001: return 0.0
                if mirror_z:
                    v0,v1 = g.verts
                    if v0.co.z <= 0.0001 and v1.co.z <= 0.0001: return 0.0
                return 0.0 if g.is_manifold else 1.0
            def warn_face(g):
                return 1.0

            try:
                time_start = time.time()

                # NOTE: duplicating data rather than using indexing, otherwise
                # selection will bleed
                with profiler.code('gathering', enabled=not self.async_load):
                    if self.load_faces:
                        tri_faces = [(bmf, list(bmvs))
                                     for bmf in faces
                                     if bmf.is_valid and not bmf.hide
                                     for bmvs in triangulateFace(bmf.verts)
                                     ]
                        l = len(tri_faces)
                        for i0 in range(0, l, face_count):
                            i1 = min(l, i0 + face_count)
                            face_data = {
                                'vco': [
                                    tuple(bmv.co)
                                    for bmf, verts in tri_faces[i0:i1]
                                    for bmv in verts
                                ],
                                'vno': [
                                    tuple(bmf.normal)
                                    for bmf, verts in tri_faces[i0:i1]
                                    for bmv in verts
                                ],
                                'sel': [
                                    sel(bmf)
                                    for bmf, verts in tri_faces[i0:i1]
                                    for bmv in verts
                                ],
                                'warn': [
                                    warn_face(bmf)
                                    for bmf, verts in tri_faces[i0:i1]
                                    for bmv in verts
                                ],
                                'idx': None,  # list(range(len(tri_faces)*3)),
                            }
                            if self.async_load:
                                self.buf_data_queue.put((bgl.GL_TRIANGLES, face_data, static))
                            else:
                                self.add_buffered_render(bgl.GL_TRIANGLES, face_data, static)

                    if self.load_edges:
                        edges = [bme for bme in edges if bme.is_valid and not bme.hide]
                        l = len(edges)
                        for i0 in range(0, l, edge_count):
                            i1 = min(l, i0 + edge_count)
                            edge_data = {
                                'vco': [
                                    tuple(bmv.co)
                                    for bme in edges[i0:i1]
                                    for bmv in bme.verts
                                ],
                                'vno': [
                                    tuple(bmv.normal)
                                    for bme in edges[i0:i1]
                                    for bmv in bme.verts
                                ],
                                'sel': [
                                    sel(bme)
                                    for bme in edges[i0:i1]
                                    for bmv in bme.verts
                                ],
                                'warn': [
                                    warn_edge(bme)
                                    for bme in edges[i0:i1]
                                    for bmv in bme.verts
                                ],
                                'idx': None,  # list(range(len(self.bmesh.edges)*2)),
                            }
                            if self.async_load:
                                self.buf_data_queue.put((bgl.GL_LINES, edge_data, static))
                            else:
                                self.add_buffered_render(bgl.GL_LINES, edge_data, static)

                    if self.load_verts:
                        verts = [bmv for bmv in verts if bmv.is_valid and not bmv.hide]
                        l = len(verts)
                        for i0 in range(0, l, vert_count):
                            i1 = min(l, i0 + vert_count)
                            vert_data = {
                                'vco': [tuple(bmv.co) for bmv in verts[i0:i1]],
                                'vno': [tuple(bmv.normal) for bmv in verts[i0:i1]],
                                'sel': [sel(bmv) for bmv in verts[i0:i1]],
                                'warn': [warn_vert(bmv) for bmv in verts[i0:i1]],
                                'idx': None,  # list(range(len(self.bmesh.verts))),
                            }
                            if self.async_load:
                                self.buf_data_queue.put((bgl.GL_POINTS, vert_data, static))
                            else:
                                self.add_buffered_render(bgl.GL_POINTS, vert_data, static)

                    if self.async_load:
                        self.buf_data_queue.put('done')

                time_end = time.time()
                # print('RFMeshRender: Gather time: %0.2f' % (time_end - time_start))

            except Exception as e:
                print('EXCEPTION WHILE GATHERING: ' + str(e))
                raise e

        self._is_loading = True
        self._is_loaded = False

        # with profiler.code('Gathering data for RFMesh (%ssync)' % ('a' if self.async_load else '')):
        if not self.async_load:
            #print(f'RFMeshRender._gather: synchronous')
            #profiler.function(gather)()
            if not self.split:
                #print(f'  v={len(self.bmesh.verts)} e={len(self.bmesh.edges)} f={len(self.bmesh.faces)}')
                gather(self.bmesh.verts, self.bmesh.edges, self.bmesh.faces, True)
            else:
                if not self.split['gathered static']:
                    #print(f'  sv={len(self.split["static verts"])} se={len(self.split["static edges"])} sf={len(self.split["static faces"])}')
                    gather(self.split['static verts'],  self.split['static edges'],  self.split['static faces'],  True)
                    self.split['gathered static'] = True
                #print(f'  dv={len(self.split["dynamic verts"])} de={len(self.split["dynamic edges"])} df={len(self.split["dynamic faces"])}')
                gather(self.split['dynamic verts'], self.split['dynamic edges'], self.split['dynamic faces'], False)
        else:
            #print(f'RFMeshRender._gather: asynchronous')
            #self._gather_submit = ThreadPoolExecutor.submit(gather)
            e = ThreadPoolExecutor()
            if not self.split:
                #print(f'  v={len(self.bmesh.verts)} e={len(self.bmesh.edges)} f={len(self.bmesh.faces)}')
                e.submit(lambda : gather(self.bmesh.verts, self.bmesh.edges, self.bmesh.faces, True))
            else:
                if not self.split['gathered static']:
                    #print(f'  sv={len(self.split["static verts"])} se={len(self.split["static edges"])} sf={len(self.split["static faces"])}')
                    e.submit(lambda : gather(self.split['static verts'],  self.split['static edges'],  self.split['static faces'],  True))
                    self.split['gathered static'] = True
                #print(f'  dv={len(self.split["dynamic verts"])} de={len(self.split["dynamic edges"])} df={len(self.split["dynamic faces"])}')
                e.submit(lambda : gather(self.split['dynamic verts'], self.split['dynamic edges'], self.split['dynamic faces'], False))

    @profiler.function
    def clean(self):
        if not self.buf_data_queue.empty():
            tag_redraw_all('buffer update')
        while not self.buf_data_queue.empty():
            data = self.buf_data_queue.get()
            if data == 'done':
                self._is_loading = False
                self._is_loaded = True
                self.async_load = False
            else:
                self.add_buffered_render(*data)

        try:
            # return if rfmesh hasn't changed
            self.rfmesh.clean()
            ver = self.rfmesh.get_version() if not self.always_dirty else None
            if self.rfmesh_version == ver:
                profiler.add_note('--> is clean')
                return
            # profiler.add_note(
            #     '--> versions: "%s",
            #     "%s"' % (str(self.rfmesh_version),
            #     str(ver))
            # )
            # make not dirty first in case bad things happen while drawing
            self.rfmesh_version = ver
            self._gather_data()
        except:
            Debugger.print_exception()
            profiler.add_note('--> exception')
            pass

        profiler.add_note('--> passed through')

    @profiler.function
    def draw(
        self,
        view_forward, unit_scaling_factor,
        buf_matrix_target, buf_matrix_target_inv,
        buf_matrix_view, buf_matrix_view_invtrans,
        buf_matrix_proj,
        alpha_above, alpha_below,
        cull_backfaces, alpha_backface,
        draw_mirrored,
        symmetry=None, symmetry_view=None,
        symmetry_effect=0.0, symmetry_frame: Frame=None
    ):
        self.clean()
        if not self.buffered_renders_static and not self.buffered_renders_dynamic: return

        try:
            bgl.glDepthMask(bgl.GL_FALSE)       # do not overwrite the depth buffer

            opts = dict(self.opts)

            opts['matrix model'] = self.rfmesh.xform.mx_p
            opts['matrix normal'] = self.rfmesh.xform.mx_n
            opts['matrix target'] = buf_matrix_target
            opts['matrix target inverse'] = buf_matrix_target_inv
            opts['matrix view'] = buf_matrix_view
            opts['matrix view normal'] = buf_matrix_view_invtrans
            opts['matrix projection'] = buf_matrix_proj
            opts['forward direction'] = view_forward
            opts['unit scaling factor'] = unit_scaling_factor

            opts['symmetry'] = symmetry
            opts['symmetry frame'] = symmetry_frame
            opts['symmetry view'] = symmetry_view
            opts['symmetry effect'] = symmetry_effect
            opts['draw mirrored'] = draw_mirrored

            bmegl.glSetDefaultOptions()

            opts['no warning'] = not options['warn non-manifold']

            opts['cull backfaces'] = cull_backfaces
            opts['alpha backface'] = alpha_backface
            opts['dpi mult'] = self.drawing.get_dpi_mult()
            mirror_axes = self.rfmesh.mirror_mod.xyz if self.rfmesh.mirror_mod else []
            for axis in mirror_axes: opts['mirror %s' % axis] = True

            if not opts.get('no below', False):
                # draw geometry hidden behind
                # geometry below
                bgl.glDepthFunc(bgl.GL_GREATER)
                opts['poly hidden']         = 1 - alpha_below
                opts['poly mirror hidden']  = 1 - alpha_below
                opts['line hidden']         = 1 - alpha_below
                opts['line mirror hidden']  = 1 - alpha_below
                opts['point hidden']        = 1 - alpha_below
                opts['point mirror hidden'] = 1 - alpha_below
                for buffered_render in self.buffered_renders_static:
                    buffered_render.draw(opts)
                for buffered_render in self.buffered_renders_dynamic:
                    buffered_render.draw(opts)

            # geometry above
            bgl.glDepthFunc(bgl.GL_LEQUAL)
            opts['poly hidden']         = 1 - alpha_above
            opts['poly mirror hidden']  = 1 - alpha_above
            opts['line hidden']         = 1 - alpha_above
            opts['line mirror hidden']  = 1 - alpha_above
            opts['point hidden']        = 1 - alpha_above
            opts['point mirror hidden'] = 1 - alpha_above
            for buffered_render in self.buffered_renders_static:
                buffered_render.draw(opts)
            for buffered_render in self.buffered_renders_dynamic:
                buffered_render.draw(opts)

            bgl.glDepthFunc(bgl.GL_LEQUAL)
            bgl.glDepthMask(bgl.GL_TRUE)
            bgl.glDepthRange(0, 1)
        except:
            Debugger.print_exception()
            pass
