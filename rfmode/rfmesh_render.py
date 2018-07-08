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

from concurrent.futures import ThreadPoolExecutor

import bpy
import bgl
import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

from mathutils import Matrix, Vector
from mathutils.geometry import normal as compute_normal, intersect_point_tri
from ..common.maths import Point, Direction, Normal, Frame
from ..common.maths import Point2D, Vec2D, Direction2D
from ..common.maths import Ray, XForm, BBox, Plane
from ..common.ui import Drawing
from ..common.utils import min_index
from ..common.decorators import stats_wrapper
from ..common import bmesh_render as bmegl
from ..common.bmesh_render import BGLBufferedRender
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage, dprint
from ..lib.classes.profiler.profiler import profiler
from ..options import options

from ..common.utils import hash_object, hash_bmesh
from .rfmesh_wrapper import BMElemWrapper, RFVert, RFEdge, RFFace, RFEdgeSequence


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
        self.dverts = {bmv:v for bmv,v in zip(bmesh.verts, self.verts)}
        self.edges = [RFMeshRender_Simple_Edge(bme, self.dverts) for bme in bmesh.edges]
        self.faces = [RFMeshRender_Simple_Face(bmf, self.dverts) for bmf in bmesh.faces]


def sel(g): return 1.0 if g.select else 0.0
def triangulateFace(verts):
    iv = iter(verts)
    v0,v2 = next(iv),next(iv)
    for v3 in iv:
        v1,v2 = v2,v3
        yield (v0,v1,v2)


class RFMeshRender():
    '''
    RFMeshRender handles rendering RFMeshes.
    '''

    executor = ThreadPoolExecutor()
    
    cache = {}
    
    @staticmethod
    @profiler.profile
    def new(rfmesh, opts, always_dirty=False):
        ho = hash_object(rfmesh.obj)
        hb = hash_bmesh(rfmesh.bme)
        h = (ho,hb)
        if h not in RFMeshRender.cache:
            RFMeshRender.creating = True
            RFMeshRender.cache[h] = RFMeshRender(rfmesh, opts)
            del RFMeshRender.creating
        rfmrender = RFMeshRender.cache[h]
        rfmrender.always_dirty = always_dirty
        return rfmrender
    
    @profiler.profile
    def __init__(self, rfmesh, opts):
        assert hasattr(RFMeshRender, 'creating'), 'Do not create new RFMeshRender directly!  Use RFMeshRender.new()'
        
        self.async_load = options['async mesh loading']   # initially loading asynchronously
        self._is_loading = False
        self._is_loaded = False
        self._buffer_data = None
        
        self.load_verts = opts.get('load verts', True)
        self.load_edges = opts.get('load edges', True)
        
        self.buf_matrix_model = rfmesh.xform.to_bglMatrix_Model()
        self.buf_matrix_normal = rfmesh.xform.to_bglMatrix_Normal()
        self.buf_verts = BGLBufferedRender(bgl.GL_POINTS)
        self.buf_edges = BGLBufferedRender(bgl.GL_LINES)
        self.buf_faces = BGLBufferedRender(bgl.GL_TRIANGLES)
        self.drawing = Drawing.get_instance()
        
        self.replace_rfmesh(rfmesh)
        self.replace_opts(opts)

    def __del__(self):
        if hasattr(self, 'buf_matrix_model'): del self.buf_matrix_model
        if hasattr(self, 'buf_matrix_normal'): del self.buf_matrix_normal
        if hasattr(self, 'buf_verts'): del self.buf_verts
        if hasattr(self, 'buf_edges'): del self.buf_edges
        if hasattr(self, 'buf_faces'): del self.buf_faces

    @profiler.profile
    def replace_opts(self, opts):
        self.opts = opts
        self.opts['dpi mult'] = self.drawing.get_dpi_mult()
        self.rfmesh_version = None
    
    @profiler.profile
    def replace_rfmesh(self, rfmesh):
        self.rfmesh = rfmesh
        self.bmesh = rfmesh.bme
        self.rfmesh_version = None
    
    @profiler.profile
    def _gather_data(self):
        vert_data, edge_data, face_data = None, None, None
        
        def buffer_data():
            nonlocal vert_data, edge_data, face_data
            pr = profiler.start('buffering')
            self.buf_verts.buffer(vert_data['vco'], vert_data['vno'], vert_data['sel'], vert_data['idx'])
            self.buf_edges.buffer(edge_data['vco'], edge_data['vno'], edge_data['sel'], edge_data['idx'])
            self.buf_faces.buffer(face_data['vco'], face_data['vno'], face_data['sel'], face_data['idx'])
            pr.done()
            self._buffer_data = None
            self._is_loading = False
            self._is_loaded = True
            self.async_load = False
        
        def gather():
            '''
            IMPORTANT NOTE: DO NOT USE PROFILER IF LOADING ASYNCHRONOUSLY!
            '''
            nonlocal vert_data, edge_data, face_data
            try:
                if not self.async_load: pr = profiler.start('triangulating faces')
                tri_faces = [(bmf, list(bmvs)) for bmf in self.bmesh.faces  for bmvs in triangulateFace(bmf.verts)]
                if not self.async_load: pr.done()
                
                # NOTE: duplicating data rather than using indexing, otherwise
                # selection will bleed
                if not self.async_load: pr = profiler.start('gathering')
                
                if self.load_verts:
                    vert_data = {
                        'vco': [tuple(bmv.co)     for bmv in self.bmesh.verts],
                        'vno': [tuple(bmv.normal) for bmv in self.bmesh.verts],
                        'sel': [sel(bmv)          for bmv in self.bmesh.verts],
                        'idx': None, #list(range(len(self.bmesh.verts))),
                    }
                else:
                    vert_data = {
                        'vco': [], 'vno': [], 'sel': [], 'idx': [],
                    }
                if self.load_edges:
                    edge_data = {
                        'vco': [tuple(bmv.co)     for bme in self.bmesh.edges for bmv in bme.verts],
                        'vno': [tuple(bmv.normal) for bme in self.bmesh.edges for bmv in bme.verts],
                        'sel': [sel(bme)          for bme in self.bmesh.edges for bmv in bme.verts],
                        'idx': None, #list(range(len(self.bmesh.edges)*2)),
                    }
                else:
                    edge_data = {
                        'vco': [], 'vno': [], 'sel': [], 'idx': [],
                    }
                face_data = {
                    'vco': [tuple(bmv.co)     for bmf,verts in tri_faces for bmv in verts],
                    'vno': [tuple(bmv.normal) for bmf,verts in tri_faces for bmv in verts],
                    'sel': [sel(bmf)          for bmf,verts in tri_faces for bmv in verts],
                    'idx': None, #list(range(len(tri_faces)*3)),
                }
                if not self.async_load: pr.done()
                
                if self.async_load:
                    self._buffer_data = buffer_data
                else:
                    buffer_data()
            except Exception as e:
                print('EXCEPTION WHILE GATHERING: ' + str(e))
                raise e
        
        self._is_loading = True
        self._is_loaded = False
        self._buffer_data = None
        
        pr = profiler.start('Gathering data for RFMesh (%ssync)' % ('a' if self.async_load else ''))
        if not self.async_load:
            profiler.profile(gather)()
        else:
            self._gather_submit = self.executor.submit(gather)
        pr.done()

    @profiler.profile
    def _draw_buffered(self, alpha_above, alpha_below):
        opts = dict(self.opts)
        for xyz in self.rfmesh.symmetry: opts['mirror %s'%xyz] = True
        
        # do not change attribs if they're not set
        bmegl.glSetDefaultOptions(opts=self.opts)
        
        bgl.glDisable(bgl.GL_CULL_FACE)

        pr = profiler.start('geometry above')
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_FALSE)
        opts['poly hidden']         = 1-alpha_above
        opts['poly mirror hidden']  = 1-alpha_above
        opts['line hidden']         = 1-alpha_above
        opts['line mirror hidden']  = 1-alpha_above
        opts['point hidden']        = 1-alpha_above
        opts['point mirror hidden'] = 1-alpha_above
        self.buf_faces.draw(opts)
        self.buf_edges.draw(opts)
        self.buf_verts.draw(opts)
        pr.done()

        if not opts.get('no below', False):
            pr = profiler.start('geometry below')
            bgl.glDepthFunc(bgl.GL_GREATER)
            bgl.glDepthMask(bgl.GL_FALSE)
            opts['poly hidden']         = 1-alpha_below
            opts['poly mirror hidden']  = 1-alpha_below
            opts['line hidden']         = 1-alpha_below
            opts['line mirror hidden']  = 1-alpha_below
            opts['point hidden']        = 1-alpha_below
            opts['point mirror hidden'] = 1-alpha_below
            self.buf_faces.draw(opts)
            self.buf_edges.draw(opts)
            self.buf_verts.draw(opts)
            pr.done()

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
        bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthRange(0, 1)

    @profiler.profile
    def clean(self):
        if self._buffer_data: self._buffer_data()
        
        if self.async_load and self._is_loading:
            if not self._gather_submit.done():
                profiler.start('--> waiting').done()
                return
            # we should not reach this point ever unless something bad happened
            print('ASYNC EXCEPTION!')
            err = self._gather_submit.exception()
            print(str(err))
            return
        
        try:
            # return if rfmesh hasn't changed
            self.rfmesh.clean()
            ver = self.rfmesh.get_version()
            if self.rfmesh_version == ver and not self.always_dirty:
                profiler.start('--> is clean').done()
                return
            #profiler.start('--> versions: "%s", "%s"' % (str(self.rfmesh_version), str(ver))).done()
            self.rfmesh_version = ver   # make not dirty first in case bad things happen while drawing
            self._gather_data()
        except:
            print_exception()
            profiler.start('--> exception').done()
            pass
        
        profiler.start('--> passed through').done()

    @profiler.profile
    def draw(self, view_forward, buf_matrix_target, buf_matrix_view, buf_matrix_view_invtrans, buf_matrix_proj, alpha_above, alpha_below, symmetry=None, symmetry_view=None, symmetry_effect=0.0, symmetry_frame:Frame=None):
        self.clean()
        if not self._is_loaded: return
        
        try:
            bmegl.bmeshShader.enable()
            bmegl.bmeshShader.assign('matrix_m', self.buf_matrix_model)
            bmegl.bmeshShader.assign('matrix_mn', self.buf_matrix_normal)
            bmegl.bmeshShader.assign('matrix_t', buf_matrix_target)
            bmegl.bmeshShader.assign('matrix_v', buf_matrix_view)
            bmegl.bmeshShader.assign('matrix_vn', buf_matrix_view_invtrans)
            bmegl.bmeshShader.assign('matrix_p', buf_matrix_proj)
            bmegl.bmeshShader.assign('dir_forward', view_forward)
            bmegl.glSetMirror(symmetry=symmetry, view=symmetry_view, effect=symmetry_effect, frame=symmetry_frame)
            self._draw_buffered(alpha_above, alpha_below)
        except:
            print_exception()
            pass
        finally:
            try:
                bmegl.bmeshShader.disable()
            except:
                pass
