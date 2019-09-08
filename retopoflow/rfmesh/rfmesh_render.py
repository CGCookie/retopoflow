'''
Copyright (C) 2017 CG Cookie
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
from ...addon_common.common.ui import Drawing
from ...addon_common.common.utils import min_index
from ...addon_common.common.hasher import hash_object, hash_bmesh
from ...addon_common.common.decorators import stats_wrapper
from ...addon_common.common import bmesh_render as bmegl
from ...addon_common.common.bmesh_render import BGLBufferedRender, triangulateFace

from ...config.options import options

from .rfmesh_wrapper import (
    BMElemWrapper, RFVert, RFEdge, RFFace, RFEdgeSequence
)


class RFMeshRender_Simple_Vert:
    def __init__(self, bmv):
        self.co = bmv.co
        self.normal = bmv.normal
        self.select = bmv.select


class RFMeshRender_Simple_Edge:
    def __init__(self, bme, dverts):
        self.verts = [dverts[bmv] for bmv in bme.verts]
        self.select = bme.select


class RFMeshRender_Simple_Face:
    def __init__(self, bmf, dverts):
        self.verts = [dverts[bmv] for bmv in bmf.verts]
        self.select = bmf.select
        self.smooth = bmf.smooth
        self.normal = bmf.normal


class RFMeshRender_Simple:
    def __init__(self, bmesh):
        self.verts = [RFMeshRender_Simple_Vert(bmv) for bmv in bmesh.verts]
        self.dverts = {bmv: v for (bmv, v) in zip(bmesh.verts, self.verts)}
        self.edges = [
            RFMeshRender_Simple_Edge(bme, self.dverts)
            for bme in bmesh.edges
        ]
        self.faces = [
            RFMeshRender_Simple_Face(bmf, self.dverts)
            for bmf in bmesh.faces
        ]



class RFMeshRender():
    '''
    RFMeshRender handles rendering RFMeshes.
    '''

    executor = ThreadPoolExecutor()
    cache = {}

    @staticmethod
    @profiler.function
    def new(rfmesh, opts, always_dirty=False):
        ho = hash_object(rfmesh.obj)
        hb = hash_bmesh(rfmesh.bme)
        h = (ho, hb)
        if h not in RFMeshRender.cache:
            RFMeshRender.creating = True
            RFMeshRender.cache[h] = RFMeshRender(rfmesh, opts)
            del RFMeshRender.creating
        rfmrender = RFMeshRender.cache[h]
        rfmrender.always_dirty = always_dirty
        return rfmrender

    @profiler.function
    def __init__(self, rfmesh, opts):
        assert hasattr(RFMeshRender, 'creating'), (
            'Do not create new RFMeshRender directly!'
            'Use RFMeshRender.new()')

        # initially loading asynchronously?
        self.async_load = options['async mesh loading']
        self._is_loading = False
        self._is_loaded = False

        self.load_verts = opts.get('load verts', True)
        self.load_edges = opts.get('load edges', True)
        self.load_faces = opts.get('load faces', True)

        self.buf_data_queue = Queue()
        self.buf_matrix_model = rfmesh.xform.to_bglMatrix_Model()
        self.buf_matrix_inverse = rfmesh.xform.to_bglMatrix_Inverse()
        self.buf_matrix_normal = rfmesh.xform.to_bglMatrix_Normal()
        self.buffered_renders = []
        self.drawing = Globals.drawing

        self.replace_rfmesh(rfmesh)
        self.replace_opts(opts)

    def __del__(self):
        if hasattr(self, 'buf_matrix_model'):
            del self.buf_matrix_model
        if hasattr(self, 'buf_matrix_inverse'):
            del self.buf_matrix_inverse
        if hasattr(self, 'buf_matrix_normal'):
            del self.buf_matrix_normal
        if hasattr(self, 'buffered_renders'):
            del self.buffered_renders

    @profiler.function
    def replace_opts(self, opts):
        self.opts = opts
        self.opts['dpi mult'] = self.drawing.get_dpi_mult()
        self.rfmesh_version = None

    @profiler.function
    def replace_rfmesh(self, rfmesh):
        self.rfmesh = rfmesh
        self.bmesh = rfmesh.bme
        self.rfmesh_version = None

    @profiler.function
    def add_buffered_render(self, bgl_type, data):
        buffered_render = BGLBufferedRender(bgl_type)
        buffered_render.buffer(data['vco'], data['vno'], data['sel'], data['idx'])
        self.buffered_renders.append(buffered_render)

    @profiler.function
    def _gather_data(self):
        self.buffered_renders = []

        def gather():
            vert_count = 100000
            edge_count = 50000
            face_count = 10000

            '''
            IMPORTANT NOTE: DO NOT USE PROFILER INSIDE THIS FUNCTION IF LOADING ASYNCHRONOUSLY!
            '''
            def sel(g):
                return 1.0 if g.select else 0.0

            try:
                time_start = time.time()

                # NOTE: duplicating data rather than using indexing, otherwise
                # selection will bleed
                with profiler.code('gathering', enabled=not self.async_load):
                    if self.load_faces:
                        tri_faces = [(bmf, list(bmvs))
                                     for bmf in self.bmesh.faces
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
                                    tuple(bmv.normal)
                                    for bmf, verts in tri_faces[i0:i1]
                                    for bmv in verts
                                ],
                                'sel': [
                                    sel(bmf)
                                    for bmf, verts in tri_faces[i0:i1]
                                    for bmv in verts
                                ],
                                'idx': None,  # list(range(len(tri_faces)*3)),
                            }
                            if self.async_load:
                                self.buf_data_queue.put((bgl.GL_TRIANGLES, face_data))
                            else:
                                self.add_buffered_render(bgl.GL_TRIANGLES, face_data)

                    if self.load_edges:
                        edges = self.bmesh.edges
                        l = len(edges)
                        for i0 in range(0, l, edge_count):
                            i1 = min(l, i0 + edge_count)
                            edge_data = {
                                'vco': [
                                    tuple(bmv.co)
                                    for bme in self.bmesh.edges[i0:i1]
                                    for bmv in bme.verts
                                ],
                                'vno': [
                                    tuple(bmv.normal)
                                    for bme in self.bmesh.edges[i0:i1]
                                    for bmv in bme.verts
                                ],
                                'sel': [
                                    sel(bme)
                                    for bme in self.bmesh.edges[i0:i1]
                                    for bmv in bme.verts
                                ],
                                'idx': None,  # list(range(len(self.bmesh.edges)*2)),
                            }
                            if self.async_load:
                                self.buf_data_queue.put((bgl.GL_LINES, edge_data))
                            else:
                                self.add_buffered_render(bgl.GL_LINES, edge_data)

                    if self.load_verts:
                        verts = self.bmesh.verts
                        l = len(verts)
                        for i0 in range(0, l, vert_count):
                            i1 = min(l, i0 + vert_count)
                            vert_data = {
                                'vco': [tuple(bmv.co) for bmv in verts[i0:i1]],
                                'vno': [tuple(bmv.normal) for bmv in verts[i0:i1]],
                                'sel': [sel(bmv) for bmv in verts[i0:i1]],
                                'idx': None,  # list(range(len(self.bmesh.verts))),
                            }
                            if self.async_load:
                                self.buf_data_queue.put((bgl.GL_POINTS, vert_data))
                            else:
                                self.add_buffered_render(bgl.GL_POINTS, vert_data)

                    if self.async_load:
                        self.buf_data_queue.put('done')

                time_end = time.time()
                dprint('Gather time: %0.2f' % (time_end - time_start))

            except Exception as e:
                print('EXCEPTION WHILE GATHERING: ' + str(e))
                raise e

        self._is_loading = True
        self._is_loaded = False

        with profiler.code('Gathering data for RFMesh (%ssync)' % ('a' if self.async_load else '')):
            if not self.async_load:
                profiler.profile(gather)()
            else:
                self._gather_submit = self.executor.submit(gather)

    @profiler.function
    def _draw_buffered(self, alpha_above, alpha_below, cull_backfaces, alpha_backface):
        bmegl.glSetDefaultOptions()
        bgl.glDepthMask(bgl.GL_FALSE)       # do not overwrite the depth buffer

        opts = dict(self.opts)
        opts['cull backfaces'] = cull_backfaces
        opts['alpha backface'] = alpha_backface
        opts['dpi mult'] = self.drawing.get_dpi_mult()
        mirror_axes = self.rfmesh.mirror_mod.xyz if self.rfmesh.mirror_mod else []
        for axis in mirror_axes: opts['mirror %s' % axis] = True

        with profiler.code('geometry above'):
            bgl.glDepthFunc(bgl.GL_LEQUAL)
            opts['poly hidden']         = 1 - alpha_above
            opts['poly mirror hidden']  = 1 - alpha_above
            opts['line hidden']         = 1 - alpha_above
            opts['line mirror hidden']  = 1 - alpha_above
            opts['point hidden']        = 1 - alpha_above
            opts['point mirror hidden'] = 1 - alpha_above
            for buffered_render in self.buffered_renders:
                buffered_render.draw(opts)

        if not opts.get('no below', False):
            # draw geometry hidden behind
            with profiler.code('geometry below'):
                bgl.glDepthFunc(bgl.GL_GREATER)
                opts['poly hidden']         = 1 - alpha_below
                opts['poly mirror hidden']  = 1 - alpha_below
                opts['line hidden']         = 1 - alpha_below
                opts['line mirror hidden']  = 1 - alpha_below
                opts['point hidden']        = 1 - alpha_below
                opts['point mirror hidden'] = 1 - alpha_below
                for buffered_render in self.buffered_renders:
                    buffered_render.draw(opts)

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
        bgl.glDepthRange(0, 1)

    @profiler.function
    def clean(self):
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
            ver = self.rfmesh.get_version()
            if self.rfmesh_version == ver and not self.always_dirty:
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
        view_forward,
        buf_matrix_target, buf_matrix_target_inv,
        buf_matrix_view, buf_matrix_view_invtrans,
        buf_matrix_proj,
        alpha_above, alpha_below,
        cull_backfaces, alpha_backface,
        symmetry=None, symmetry_view=None,
        symmetry_effect=0.0, symmetry_frame: Frame=None
    ):
        self.clean()
        if not self.buffered_renders: return

        try:
            bmegl.bmeshShader.enable()
            bmegl.bmeshShader.assign('matrix_m', self.buf_matrix_model)
            bmegl.bmeshShader.assign('matrix_mn', self.buf_matrix_normal)
            bmegl.bmeshShader.assign('matrix_t', buf_matrix_target)
            bmegl.bmeshShader.assign('matrix_ti', buf_matrix_target_inv)
            bmegl.bmeshShader.assign('matrix_v', buf_matrix_view)
            bmegl.bmeshShader.assign('matrix_vn', buf_matrix_view_invtrans)
            bmegl.bmeshShader.assign('matrix_p', buf_matrix_proj)
            bmegl.bmeshShader.assign('dir_forward', view_forward)
            bmegl.glSetMirror(symmetry=symmetry, view=symmetry_view,
                              effect=symmetry_effect, frame=symmetry_frame)
            self._draw_buffered(alpha_above, alpha_below, cull_backfaces, alpha_backface)
        except:
            Debugger.print_exception()
            pass
        finally:
            try:
                bmegl.bmeshShader.disable()
            except:
                pass
