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
from ..lib import common_drawing_bmesh as bmegl
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage, dprint
from ..lib.classes.profiler.profiler import profiler

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

class RFMeshRender():
    '''
    RFMeshRender handles rendering RFMeshes.
    '''

    ALWAYS_DIRTY = False
    
    GATHERDATA_EMESH = False
    GATHERDATA_BMESH = False
    executor = ThreadPoolExecutor() if False else None
    
    cache = {}
    
    @staticmethod
    @profiler.profile
    def new(rfmesh, opts):
        ho = hash_object(rfmesh.obj)
        hb = hash_bmesh(rfmesh.bme)
        h = (ho,hb)
        if h not in RFMeshRender.cache:
            RFMeshRender.creating = True
            RFMeshRender.cache[h] = RFMeshRender(rfmesh, opts)
            del RFMeshRender.creating
        return RFMeshRender.cache[h]
    
    @profiler.profile
    def __init__(self, rfmesh, opts):
        assert hasattr(RFMeshRender, 'creating'), 'Do not create new RFMeshRender directly!  Use RFMeshRender.new()'
        self.bglCallList = bgl.glGenLists(1)
        self.bglMatrix = rfmesh.xform.to_bglMatrix()
        self.drawing = Drawing.get_instance()
        
        self.vao = bgl.Buffer(bgl.GL_INT, 1)
        bgl.glGenVertexArrays(1, self.vao)
        bgl.glBindVertexArray(self.vao[0])
        self.vbo = bgl.Buffer(bgl.GL_INT, 10)
        bgl.glGenBuffers(10, self.vbo)
        bgl.glBindVertexArray(0)
        self.n_faces = 0
        self.n_edges = 0
        self.n_verts = 0
        
        self.replace_rfmesh(rfmesh)
        self.replace_opts(opts)

    def __del__(self):
        if hasattr(self, 'bglCallList'):
            bgl.glDeleteLists(self.bglCallList, 1)
            del self.bglCallList
        if hasattr(self, 'bglMatrix'):
            del self.bglMatrix

    @profiler.profile
    def replace_opts(self, opts):
        self.opts = opts
        self.opts['dpi mult'] = self.drawing.get_dpi_mult()
        self.rfmesh_version = None
    
    @profiler.profile
    def replace_rfmesh(self, rfmesh):
        self.rfmesh = rfmesh
        self.bmesh = rfmesh.bme
        self.emesh = rfmesh.eme
        self.rfmesh_version = None
    
    @profiler.profile
    def _gather_data(self):
        self.eme_verts = None
        self.eme_edges = None
        self.eme_faces = None
        self.bme_verts = None
        self.bme_edges = None
        self.bme_faces = None
        
        def triangulateFace(verts):
            iv = iter(verts)
            v0,v2 = next(iv),next(iv)
            for v3 in iv:
                v1,v2 = v2,v3
                yield (v0,v1,v2)
        def buffer(vbo_id, data):
            sizeOfFloat = 4
            buf = bgl.Buffer(bgl.GL_FLOAT, len(data), data)
            bgl.glBindVertexArray(self.vao[0])
            bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, vbo_id)
            bgl.glBufferData(bgl.GL_ARRAY_BUFFER, len(data) * sizeOfFloat, buf, bgl.GL_STATIC_DRAW)
            bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)
            bgl.glBindVertexArray(0)
            del buf
        
        pr = profiler.start('triangulating faces')
        tri_faces = [(bmf, [bmv for bmvs in triangulateFace(bmf.verts) for bmv in bmvs]) for bmf in self.bmesh.faces]
        pr.done()
        
        pr = profiler.start('gathering')
        buf_data = {
            'vert vco': [v for bmv in self.bmesh.verts for v in bmv.co],
            'vert vno': [v for bmv in self.bmesh.verts for v in bmv.normal],
            'vert sel': [1.0 if bmv.select else 0.0 for bmv in self.bmesh.verts],
            'edge vco': [v for bme in self.bmesh.edges for bmv in bme.verts for v in bmv.co],
            'edge vno': [v for bme in self.bmesh.edges for bmv in bme.verts for v in bmv.normal],
            'edge sel': [1.0 if bme.select else 0.0 for bme in self.bmesh.edges for bmv in bme.verts],
            'face vco': [v for bmf,verts in tri_faces for bmv in verts for v in bmv.co],
            'face vno': [v for bmf,verts in tri_faces for bmv in verts for v in bmv.normal],
            'face fno': [v for bmf,verts in tri_faces for bmv in verts for v in bmf.normal],
            'face sel': [1.0 if bmf.select else 0.0 for bmf,verts in tri_faces for bmv in verts],
        }
        pr.done()
        
        pr = profiler.start('buffering')
        buffer(self.vbo[0], buf_data['vert vco'])
        buffer(self.vbo[1], buf_data['vert vno'])
        buffer(self.vbo[2], buf_data['vert sel'])
        buffer(self.vbo[3], buf_data['edge vco'])
        buffer(self.vbo[4], buf_data['edge vno'])
        buffer(self.vbo[5], buf_data['edge sel'])
        buffer(self.vbo[6], buf_data['face vco'])
        buffer(self.vbo[7], buf_data['face vno'])
        buffer(self.vbo[8], buf_data['face fno'])
        buffer(self.vbo[9], buf_data['face sel'])
        self.n_verts = len(buf_data['vert sel'])
        self.n_edges = len(buf_data['edge sel'])
        self.n_faces = len(buf_data['face sel'])
        pr.done()
        
        if not self.GATHERDATA_EMESH and not self.GATHERDATA_BMESH: return
        
        # note: do not profile this function if using ThreadPoolExecutor!!!!
        def gather_emesh():
            if not self.GATHERDATA_EMESH: return
            if not self.emesh: return
            start = time.time()
            #self.eme_verts = [(emv.co, emv.normal) for emv in self.emesh.vertices]
            self.eme_verts = [(emv.co,emv.normal) for emv in self.emesh.vertices]
            self.eme_edges = [[self.eme_verts[iv] for iv in eme.vertices] for eme in self.emesh.edges]
            self.eme_faces = [[self.eme_verts[iv] for iv in emf.vertices] for emf in self.emesh.polygons]
            end = time.time()
            dprint('Gathered edit mesh data!')
            dprint('start: %f' % start)
            dprint('end:   %f' % end)
            dprint('delta: %f' % (end-start))
            dprint('counts: %d %d %d' % (len(self.eme_verts), len(self.eme_edges), len(self.eme_faces)))
        
        # note: do not profile this function if using ThreadPoolExecutor!!!!
        def gather_bmesh():
            if not self.GATHERDATA_BMESH: return
            start = time.time()
            #bme_vert_dict = {bmv:(bmv.co,bmv.normal) for bmv in self.bmesh.verts}
            bme_vert_dict = {bmv:bmv.co for bmv in self.bmesh.verts}
            self.bme_verts = bme_vert_dict.values() # [(bmv.co, bmv.normal) for bmv in self.bmesh.verts]
            self.bme_edges = [[bme_vert_dict[bmv] for bmv in bme.verts] for bme in self.bmesh.edges]
            self.bme_faces = [[bme_vert_dict[bmv] for bmv in bmf.verts] for bmf in self.bmesh.faces]
            end = time.time()
            dprint('Gathered BMesh data!')
            dprint('start: %f' % start)
            dprint('end:   %f' % end)
            dprint('delta: %f' % (end-start))
            dprint('counts: %d %d %d' % (len(self.bme_verts), len(self.bme_edges), len(self.bme_faces)))
        
        pr = profiler.start('Gathering data for RFMesh')
        if self.executor:
            self._gather_emesh_submit = self.executor.submit(gather_emesh)
            self._gather_bmesh_submit = self.executor.submit(gather_bmesh)
        else:
            profiler.profile(gather_emesh)()
            profiler.profile(gather_bmesh)()
        pr.done()

    @profiler.profile
    def _draw(self):
        opts = dict(self.opts)
        opts['vertex dict'] = {}
        for xyz in self.rfmesh.symmetry: opts['mirror %s'%xyz] = True
        
        pr = profiler.start('gathering simple mesh')
        simple = RFMeshRender_Simple(self.bmesh)
        pr.done()

        # do not change attribs if they're not set
        bmegl.glSetDefaultOptions(opts=self.opts)
        bgl.glPushMatrix()
        bgl.glMultMatrixf(self.bglMatrix)

        bgl.glDisable(bgl.GL_CULL_FACE)

        pr = profiler.start('geometry above')
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_FALSE)
        # bgl.glEnable(bgl.GL_CULL_FACE)
        opts['poly hidden'] = 0.0
        opts['poly mirror hidden'] = 0.0
        opts['line hidden'] = 0.0
        opts['line mirror hidden'] = 0.0
        opts['point hidden'] = 0.0
        opts['point mirror hidden'] = 0.0
        if self.eme_faces:
            bmegl.glDrawSimpleFaces(self.eme_faces, opts=opts, enableShader=False)
        else:
            #bmegl.glDrawBufferedTriangles(self.vao[0], self.n_faces, opts=opts, enableShader=False)
            bmegl.glDrawBMFaces(simple.faces, opts=opts, enableShader=False)
            bmegl.glDrawBMEdges(simple.edges, opts=opts, enableShader=False)
            bmegl.glDrawBMVerts(simple.verts, opts=opts, enableShader=False)
        pr.done()

        if not opts.get('no below', False):
            pr = profiler.start('geometry below')
            bgl.glDepthFunc(bgl.GL_GREATER)
            bgl.glDepthMask(bgl.GL_FALSE)
            # bgl.glDisable(bgl.GL_CULL_FACE)
            opts['poly hidden']         = 0.95
            opts['poly mirror hidden']  = 0.95
            opts['line hidden']         = 0.95
            opts['line mirror hidden']  = 0.95
            opts['point hidden']        = 0.95
            opts['point mirror hidden'] = 0.95
            if self.eme_faces:
                bmegl.glDrawSimpleFaces(self.eme_faces, opts=opts, enableShader=False)
            else:
                bmegl.glDrawBMFaces(simple.faces, opts=opts, enableShader=False)
                bmegl.glDrawBMEdges(simple.edges, opts=opts, enableShader=False)
                bmegl.glDrawBMVerts(simple.verts, opts=opts, enableShader=False)
            pr.done()

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
        # bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthRange(0, 1)
        bgl.glPopMatrix()

    @profiler.profile
    def clean(self):
        try:
            # return if rfmesh hasn't changed
            self.rfmesh.clean()
            ver = self.rfmesh.get_version()
            if self.rfmesh_version == ver: return
            self._gather_data()
            pr = profiler.start('cleaning')
            self.rfmesh_version = ver   # make not dirty first in case bad things happen while drawing
            bgl.glNewList(self.bglCallList, bgl.GL_COMPILE)
            self._draw()
            bgl.glEndList()
            pr.done()
        except Exception as e:
            pass

    @profiler.profile
    def draw(self, symmetry=None, frame:Frame=None):
        try:
            if self.ALWAYS_DIRTY:
                self.rfmesh.clean()
                bmegl.bmeshShader.enable()
                bmegl.glSetMirror(symmetry, frame)
                self._draw()
            else:
                self.clean()
                bmegl.bmeshShader.enable()
                bmegl.glSetMirror(symmetry, frame)
                bgl.glCallList(self.bglCallList)
        except:
            print_exception()
            pass
        finally:
            try:
                bmegl.bmeshShader.disable()
            except:
                pass
