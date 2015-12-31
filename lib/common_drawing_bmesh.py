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

class BMeshRender():
    def __init__(self, bmesh):
        self.bmesh = bmesh
        self.is_dirty = True
        self.calllist = bgl.glGenLists(1)
    
    def __del__(self):
        bgl.glDeleteLists(self.calllist, 1)
        self.calllist = None
    
    def dirty(self):
        self.is_dirty = True
    
    def draw(self, opts=None):
        if self.is_dirty:
            # make not dirty first in case bad things happen while drawing
            self.is_dirty = False
            bgl.glNewList(self.calllist, bgl.GL_COMPILE)
            self._draw_immediate(opts=opts)
            bgl.glEndList()
        bgl.glCallList(self.calllist)
    
    def _draw_immediate(self, opts=None):
        # do not change attribs if they're not set
        if not opts: opts = {}
        print(str(opts))
        
        if 'poly depth' in opts: bgl.glDepthRange(*opts['poly depth'])
        if 'poly color' in opts: glColor(opts['poly color'])
        #bgl.glEnable(bgl.GL_LIGHTS)
        bgl.glDisable(bgl.GL_LIGHTING)
        bgl.glEnable(bgl.GL_DEPTH_TEST)
        bgl.glBegin(bgl.GL_TRIANGLES)
        for bmf in self.bmesh.faces:
            bmv0 = bmf.verts[0]
            bgl.glNormal3f(*bmf.normal)
            for bmv1,bmv2 in zip(bmf.verts[1:-1],bmf.verts[2:]):
                bgl.glVertex3f(*bmv0.co)
                bgl.glVertex3f(*bmv1.co)
                bgl.glVertex3f(*bmv2.co)
        bgl.glEnd()
        
        if 'line width' in opts: bgl.glLineWidth(opts['line width'])
        if 'line depth' in opts: bgl.glDepthRange(*opts['line depth'])
        if 'line color' in opts: glColor(opts['line color'])
        bgl.glBegin(bgl.GL_LINES)
        for bme in self.bmesh.edges:
            bmv0,bmv1 = bme.verts
            bgl.glVertex3f(*bmv0.co)
            bgl.glVertex3f(*bmv1.co)
        bgl.glEnd()
        
        if 'point size'  in opts: bgl.glPointSize(opts['point size'])
        if 'point depth' in opts: bgl.glDepthRange(*opts['point depth'])
        if 'point color' in opts: glColor(opts['point color'])
        bgl.glBegin(bgl.GL_POINTS)
        for bmv in self.bmesh.verts:
            bgl.glVertex3f(*bmv.co)
        bgl.glEnd()
        
        bgl.glDepthRange(0, 1)