'''
Copyright (C) 2016 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import bmesh
import bgl
import blf
import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Quaternion
from mathutils.bvhtree import BVHTree
from .common_shader import Shader
from .common_utilities import invert_matrix, matrix_normal

import math




#https://www.blender.org/api/blender_python_api_2_77_1/bgl.html
#https://en.wikibooks.org/wiki/GLSL_Programming/Blender/Shading_in_View_Space
shaderVertSource = '''
#version 130

in float offset;
in float dotoffset;

out vec4 vPosition;
out vec3 vNormal;
out float vOffset;
out float vDotOffset;

void main() {
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
    gl_FrontColor = gl_Color;
    
    vPosition = gl_ModelViewMatrix * gl_Vertex;
    vNormal = normalize(gl_NormalMatrix * gl_Normal);
    vOffset = offset;
    vDotOffset = dotoffset;
}
'''
shaderFragSource = '''
#version 130

uniform bool perspective;
uniform float clip_start;
uniform float clip_end;
uniform float object_scale;

in vec4 vPosition;
in vec3 vNormal;
in float vOffset;
in float vDotOffset;

void main() {
    float clip = clip_end - clip_start;
    float hclip = clip / 2.0;
    if(perspective) {
        // perspective projection
        vec3 v = vPosition.xyz / vPosition.w;
        float l = length(v);
        float d = -dot(vNormal, v/l);
        if(d <= 0.0) discard;
        
        // MAGIC!
        gl_FragDepth = gl_FragCoord.z - 0.001*(2.0-d)/(l*l)*vDotOffset - clip*vOffset;
    } else {
        // orthographic projection
        vec3 v = vec3(0,0,hclip) + vPosition.xyz / vPosition.w;
        float l = length(v);
        float d = dot(vNormal, v/l);
        if(d <= 0.0) discard;
        
        // MAGIC!
        //gl_FragDepth = gl_FragCoord.z * (1.0000 + 0.001*d);
        gl_FragDepth = gl_FragCoord.z - clip*(0.001*vOffset + 0.0000001*(1.0-d)*vDotOffset);
    }
    
    gl_FragColor = gl_Color; // vec4(gl_Color.rgb * d, gl_Color.a);
}
'''

def setupBMeshShader(shader):
    spc,r3d = bpy.context.space_data,bpy.context.space_data.region_3d
    shader.assign('perspective', r3d.view_perspective != 'ORTHO')
    shader.assign('clip_start', spc.clip_start)
    shader.assign('clip_end', spc.clip_end)

bmeshShader = Shader(shaderVertSource, shaderFragSource, setupBMeshShader)



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
    #if '%sdepth'%prefix in opts: bgl.glDepthRange(*opts['%sdepth'%prefix])
    if '%soffset'%prefix in opts:
        bmeshShader.assign('offset', opts['%soffset'%prefix])
    if '%sdotoffset'%prefix in opts:
        bmeshShader.assign('dotoffset', opts['%sdotoffset'%prefix])
    if '%scolor'%prefix in opts: glColor(opts['%scolor'%prefix])
    if '%swidth'%prefix in opts: bgl.glLineWidth(opts['%swidth'%prefix])
    if '%ssize'%prefix  in opts: bgl.glPointSize(opts['%ssize'%prefix])
    if opts.get('%sstipple'%prefix, False):
        bgl.glLineStipple(4, 0x5555)  #play with this later
        bgl.glEnable(bgl.GL_LINE_STIPPLE)


def glDrawBMFace(bmf, opts=None, enableShader=True):
    glDrawBMFaces([bmf], opts=opts, enableShader=enableShader)

def glDrawBMFaces(lbmf, opts=None, enableShader=True):
    glSetOptions('poly', opts)
    if enableShader: bmeshShader.enable()
    
    dn = opts['normal'] if opts and 'normal' in opts else 0.0
    bgl.glBegin(bgl.GL_TRIANGLES)
    for bmf in lbmf:
        bgl.glNormal3f(*bmf.normal)
        bmv0 = bmf.verts[0]
        for bmv1,bmv2 in zip(bmf.verts[1:-1],bmf.verts[2:]):
            if bmf.smooth: bgl.glNormal3f(*bmv0.normal)
            bgl.glVertex3f(*(bmv0.co)) #+bmv0.normal*dn))
            if bmf.smooth: bgl.glNormal3f(*bmv1.normal)
            bgl.glVertex3f(*(bmv1.co)) #+bmv1.normal*dn))
            if bmf.smooth: bgl.glNormal3f(*bmv2.normal)
            bgl.glVertex3f(*(bmv2.co)) #+bmv2.normal*dn))
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if opts and opts.get('mirror x', False):
        glSetOptions('poly mirror', opts)
        bgl.glBegin(bgl.GL_TRIANGLES)
        for bmf in lbmf:
            bgl.glNormal3f(-bmf.normal.x, bmf.normal.y, bmf.normal.z)
            bmv0 = bmf.verts[0]
            for bmv1,bmv2 in zip(bmf.verts[1:-1],bmf.verts[2:]):
                if bmf.smooth: bgl.glNormal3f(-bmv0.normal.x, bmv0.normal.y, bmv0.normal.z)
                bgl.glVertex3f(-bmv0.co.x, bmv0.co.y, bmv0.co.z)
                if bmf.smooth: bgl.glNormal3f(-bmv1.normal.x, bmv1.normal.y, bmv1.normal.z)
                bgl.glVertex3f(-bmv1.co.x, bmv1.co.y, bmv1.co.z)
                if bmf.smooth: bgl.glNormal3f(-bmv2.normal.x, bmv2.normal.y, bmv2.normal.z)
                bgl.glVertex3f(-bmv2.co.x, bmv2.co.y, bmv2.co.z)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    if enableShader: bmeshShader.disable()

def glDrawBMFaceEdges(bmf, opts=None, enableShader=True):
    glDrawBMEdges(bmf.edges, opts=opts, enableShader=enableShader)

def glDrawBMFaceVerts(bmf, opts=None, enableShader=True):
    glDrawBMVerts(bmf.verts, opts=opts, enableShader=enableShader)

def glDrawBMEdge(bme, opts=None, enableShader=True):
    glDrawBMEdges([bme], opts=opts, enableShader=enableShader)

def glDrawBMEdges(lbme, opts=None, enableShader=True):
    if opts and 'line width' in opts and opts['line width'] <= 0.0: return
    glSetOptions('line', opts)
    if enableShader: bmeshShader.enable()
    dn = opts['normal'] if opts and 'normal' in opts else 0.0
    bgl.glBegin(bgl.GL_LINES)
    for bme in lbme:
        bmv0,bmv1 = bme.verts
        bgl.glNormal3f(*bmv0.normal)
        bgl.glVertex3f(*(bmv0.co+bmv0.normal*dn))
        bgl.glNormal3f(*bmv1.normal)
        bgl.glVertex3f(*(bmv1.co+bmv1.normal*dn))
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if opts and opts.get('mirror x', False):
        glSetOptions('line mirror', opts)
        bgl.glBegin(bgl.GL_LINES)
        for bme in lbme:
            bmv0,bmv1 = bme.verts
            co0,co1 = bmv0.co,bmv1.co
            bgl.glNormal3f(-bmv0.normal.x, bmv0.normal.y, bmv0.normal.z)
            bgl.glVertex3f(-co0.x, co0.y, co0.z)
            bgl.glNormal3f(-bmv1.normal.x, bmv1.normal.y, bmv1.normal.z)
            bgl.glVertex3f(-co1.x, co1.y, co1.z)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if enableShader: bmeshShader.disable()

def glDrawBMEdgeVerts(bme, opts=None, enableShader=True):
    glDrawBMVerts(bme.verts, opts=opts, enableShader=enableShader)

def glDrawBMVert(bmv, opts=None, enableShader=True):
    glDrawBMVerts([bmv], opts=opts, enableShader=enableShader)

def glDrawBMVerts(lbmv, opts=None, enableShader=True):
    if opts and 'point size' in opts and opts['point size'] <= 0.0: return
    glSetOptions('point', opts)
    if enableShader: bmeshShader.enable()
    dn = opts['normal'] if opts and 'normal' in opts else 0.0
    bgl.glBegin(bgl.GL_POINTS)
    for bmv in lbmv:
        bgl.glNormal3f(*bmv.normal)
        bgl.glVertex3f(*(bmv.co+bmv.normal*dn))
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if opts and opts.get('mirror x', False):
        glSetOptions('point mirror', opts)
        bgl.glBegin(bgl.GL_POINTS)
        for bmv in lbmv:
            bgl.glNormal3f(-bmv.normal.x, bmv.normal.y, bmv.normal.z)
            bgl.glVertex3f(-bmv.co.x, bmv.co.y, bmv.co.z)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    if enableShader: bmeshShader.disable()


class BMeshRender():
    def __init__(self, target_obj, target_mx=None, source_bvh=None, source_mx=None):
        if type(target_obj) is bpy.types.Object:
            print('Creating BMeshRender for ' + target_obj.name)
            self.tar_bmesh = bmesh.new()
            self.tar_bmesh.from_object(target_obj, bpy.context.scene, deform=True)
            self.tar_mx = target_mx or target_obj.matrix_world
        elif type(target_obj) is bmesh.types.BMesh:
            self.tar_bmesh = target_obj
            self.tar_mx = target_mx or Matrix()
        else:
            assert False, 'Unhandled type: ' + str(type(target_obj))
        
        self.src_bvh = source_bvh
        self.src_mx = source_mx or Matrix()
        self.src_imx = invert_matrix(self.src_mx)
        self.src_mxnorm = matrix_normal(self.src_mx)
        
        self.bglMatrix = bgl.Buffer(bgl.GL_FLOAT, [16])
        for i,v in enumerate([v for r in self.tar_mx.transposed() for v in r]):
            self.bglMatrix[i] = v
        
        self.is_dirty = True
        self.calllist = bgl.glGenLists(1)
    
    def replace_target_bmesh(self, target_bmesh):
        self.tar_bmesh = target_bmesh
        self.is_dirty = True
    
    def __del__(self):
        if self.calllist:
            bgl.glDeleteLists(self.calllist, 1)
            self.calllist = None
    
    def dirty(self):
        self.is_dirty = True
    
    def clean(self, opts=None):
        if not self.is_dirty: return
        
        # make not dirty first in case bad things happen while drawing
        self.is_dirty = False
        
        if self.src_bvh:
            # normal_update() will destroy normals of verts not connected to faces :(
            self.tar_bmesh.normal_update()
            for bmv in self.tar_bmesh.verts:
                if len(bmv.link_faces) != 0: continue
                _,n,_,_ = self.src_bvh.find_nearest(self.src_imx * bmv.co)
                bmv.normal = (self.src_mxnorm * n).normalized()
        
        bgl.glNewList(self.calllist, bgl.GL_COMPILE)
        # do not change attribs if they're not set
        glSetDefaultOptions(opts=opts)
        bgl.glPushMatrix()
        bgl.glMultMatrixf(self.bglMatrix)
        glDrawBMFaces(self.tar_bmesh.faces, opts=opts, enableShader=False)
        glDrawBMEdges(self.tar_bmesh.edges, opts=opts, enableShader=False)
        glDrawBMVerts(self.tar_bmesh.verts, opts=opts, enableShader=False)
        bgl.glDepthRange(0, 1)
        bgl.glPopMatrix()
        bgl.glEndList()
    
    def draw(self, opts=None):
        try:
            self.clean(opts=opts)
            bmeshShader.enable()
            bgl.glCallList(self.calllist)
        except:
            pass
        finally:
            bmeshShader.disable()

