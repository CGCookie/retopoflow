import sys
import math
import copy
import json
import random

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

    @profiler.profile
    def __init__(self, rfmesh, opts):
        self.opts = opts
        self.replace_rfmesh(rfmesh)
        self.bglCallList = bgl.glGenLists(1)
        self.bglMatrix = rfmesh.xform.to_bglMatrix()
        self.drawing = Drawing.get_instance()
        self.opts['dpi mult'] = self.drawing.get_dpi_mult()

    def __del__(self):
        if hasattr(self, 'bglCallList'):
            bgl.glDeleteLists(self.bglCallList, 1)
            del self.bglCallList
        if hasattr(self, 'bglMatrix'):
            del self.bglMatrix

    @profiler.profile
    def replace_rfmesh(self, rfmesh):
        self.rfmesh = rfmesh
        self.bmesh = rfmesh.bme
        self.emesh = rfmesh.eme
        self.rfmesh_version = None

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
