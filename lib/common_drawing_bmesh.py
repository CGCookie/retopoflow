import bmesh
import bgl
import blf
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree

import math

def glColor(color):
    if len(color) == 3:
        bgl.glColor3f(*color)
    else:
        bgl.glColor4f(*color)

def glSetDefaultOptions(opts=None):
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glDisable(bgl.GL_LIGHTING)
    bgl.glEnable(bgl.GL_DEPTH_TEST)

def glSetOptions(prefix, opts):
    if opts == None: return
    prefix = '%s '%prefix if prefix else ''
    if '%sdepth'%prefix in opts: bgl.glDepthRange(*opts['%sdepth'%prefix])
    if '%scolor'%prefix in opts: glColor(opts['%scolor'%prefix])
    if '%swidth'%prefix in opts: bgl.glLineWidth(opts['%swidth'%prefix])
    if '%ssize'%prefix  in opts: bgl.glPointSize(opts['%ssize'%prefix])
    if opts.get('%sstipple'%prefix, False):
        bgl.glLineStipple(4, 0x5555)  #play with this later
        bgl.glEnable(bgl.GL_LINE_STIPPLE)


def glDrawBMFace(bmf, opts=None):
    glDrawBMFaces([bmf], opts=opts)

def glDrawBMFaces(lbmf, opts=None):
    glSetOptions('poly', opts)
    bgl.glBegin(bgl.GL_TRIANGLES)
    for bmf in lbmf:
        bgl.glNormal3f(*bmf.normal)
        bmv0 = bmf.verts[0]
        for bmv1,bmv2 in zip(bmf.verts[1:-1],bmf.verts[2:]):
            bgl.glVertex3f(*bmv0.co)
            bgl.glVertex3f(*bmv1.co)
            bgl.glVertex3f(*bmv2.co)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if opts and opts.get('mirror x', False):
        glSetOptions('poly mirror', opts)
        bgl.glBegin(bgl.GL_TRIANGLES)
        for bmf in lbmf:
            bgl.glNormal3f(-bmf.normal.x, bmf.normal.y, bmf.normal.z)
            bmv0 = bmf.verts[0]
            for bmv1,bmv2 in zip(bmf.verts[1:-1],bmf.verts[2:]):
                bgl.glVertex3f(-bmv0.co.x, bmv0.co.y, bmv0.co.z)
                bgl.glVertex3f(-bmv1.co.x, bmv1.co.y, bmv1.co.z)
                bgl.glVertex3f(-bmv2.co.x, bmv2.co.y, bmv2.co.z)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

def glDrawBMFaceEdges(bmf, opts=None):
    glDrawBMEdges(bmf.edges, opts=opts)

def glDrawBMFaceVerts(bmf, opts=None):
    glDrawBMVerts(bmf.verts, opts=opts)

def glDrawBMEdge(bme, opts=None):
    glDrawBMEdges([bme], opts=opts)

def glDrawBMEdges(lbme, opts=None):
    glSetOptions('line', opts)
    bgl.glBegin(bgl.GL_LINES)
    for bme in lbme:
        bgl.glVertex3f(*bme.verts[0].co)
        bgl.glVertex3f(*bme.verts[1].co)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if opts and opts.get('mirror x', False):
        glSetOptions('line mirror', opts)
        bgl.glBegin(bgl.GL_LINES)
        for bme in lbme:
            co0,co1 = bme.verts[0].co,bme.verts[1].co
            bgl.glVertex3f(-co0.x, co0.y, co0.z)
            bgl.glVertex3f(-co1.x, co1.y, co1.z)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

def glDrawBMEdgeVerts(bme, opts=None):
    glDrawBMVerts(bme.verts, opts=opts)

def glDrawBMVert(bmv, opts=None):
    glDrawBMVerts([bmv], opts=opts)

def glDrawBMVerts(lbmv, opts=None):
    glSetOptions('point', opts)
    bgl.glBegin(bgl.GL_POINTS)
    for bmv in lbmv:
        bgl.glVertex3f(*bmv.co)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if opts and opts.get('mirror x', False):
        glSetOptions('point mirror', opts)
        bgl.glBegin(bgl.GL_POINTS)
        for bmv in lbmv:
            bgl.glVertex3f(-bmv.co.x, bmv.co.y, bmv.co.z)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)


class BMeshRender():
    def __init__(self, bmesh, mx=None):
        self.calllist = None
        self.bmesh = bmesh
        self.mx = mx
        if mx:
            self.bglMatrix = bgl.Buffer(bgl.GL_FLOAT, [16])
            for i,v in enumerate([v for r in self.mx.transposed() for v in r]):
                self.bglMatrix[i] = v
            
        self.is_dirty = True
        self.calllist = bgl.glGenLists(1)
    
    def replace_bmesh(self, bmesh):
        self.bmesh = bmesh
        self.is_dirty = True
    
    def __del__(self):
        if self.calllist:
            bgl.glDeleteLists(self.calllist, 1)
            self.calllist = None
    
    def dirty(self):
        self.is_dirty = True
    
    def draw(self, opts=None):
        if self.is_dirty:
            # make not dirty first in case bad things happen while drawing
            self.is_dirty = False
            
            bgl.glNewList(self.calllist, bgl.GL_COMPILE)
            # do not change attribs if they're not set
            glSetDefaultOptions(opts=opts)
            if self.mx:
                bgl.glPushMatrix()
                bgl.glMultMatrixf(self.bglMatrix)
            glDrawBMFaces(self.bmesh.faces, opts=opts)
            glDrawBMEdges(self.bmesh.edges, opts=opts)
            glDrawBMVerts(self.bmesh.verts, opts=opts)
            bgl.glDepthRange(0, 1)
            if self.mx:
                bgl.glPopMatrix()
            bgl.glEndList()
        
        bgl.glCallList(self.calllist)

