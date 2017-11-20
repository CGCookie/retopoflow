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

from .rfmesh_wrapper import BMElemWrapper, RFVert, RFEdge, RFFace, RFEdgeSequence


class RFMeshRender():
    '''
    RFMeshRender handles rendering RFMeshes.
    '''

    ALWAYS_DIRTY = False
    
    GATHERDATA_EMESH = False
    GATHERDATA_BMESH = False
    executor = ThreadPoolExecutor() if False else None

    @profiler.profile
    def __init__(self, rfmesh, opts):
        self.bglCallList = bgl.glGenLists(1)
        self.bglMatrix = rfmesh.xform.to_bglMatrix()
        self.drawing = Drawing.get_instance()
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
        for xyz in self.rfmesh.symmetry: opts['mirror %s'%xyz] = True

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
            bmegl.glDrawBMFaces(self.bmesh.faces, opts=opts, enableShader=False)
            bmegl.glDrawBMEdges(self.bmesh.edges, opts=opts, enableShader=False)
            bmegl.glDrawBMVerts(self.bmesh.verts, opts=opts, enableShader=False)
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
                bmegl.glDrawBMFaces(self.bmesh.faces, opts=opts, enableShader=False)
                bmegl.glDrawBMEdges(self.bmesh.edges, opts=opts, enableShader=False)
                bmegl.glDrawBMVerts(self.bmesh.verts, opts=opts, enableShader=False)
            pr.done()

        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
        # bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthRange(0, 1)
        bgl.glPopMatrix()

    @profiler.profile
    def clean(self):
        # return if rfmesh hasn't changed
        self.rfmesh.clean()
        if self.rfmesh_version == self.rfmesh.version: return
        self._gather_data()
        pr = profiler.start('cleaning')
        self.rfmesh_version = self.rfmesh.version   # make not dirty first in case bad things happen while drawing
        bgl.glNewList(self.bglCallList, bgl.GL_COMPILE)
        self._draw()
        bgl.glEndList()
        pr.done()

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
