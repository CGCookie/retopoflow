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
from ..common.maths import Point,Direction,Frame
from .classes.profiler.profiler import profiler

import math




#https://www.blender.org/api/blender_python_api_2_77_1/bgl.html
#https://en.wikibooks.org/wiki/GLSL_Programming/Blender/Shading_in_View_Space
#https://www.khronos.org/opengl/wiki/Built-in_Variable_(GLSL)
shaderVertSource = '''
#version 110

uniform vec4 color;
uniform vec4 color_selected;

attribute float offset;
attribute float dotoffset;
attribute float selected;
attribute float hidden;

varying vec4  vMPosition;
varying vec4  vPosition;
varying vec3  vNormal;
varying float vOffset;
varying float vDotOffset;

void main() {
    gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
    if(selected > 0.5) {
        gl_FrontColor.rgb = color_selected.rgb;
        gl_FrontColor.a = color_selected.a * (1.0 - hidden);
    } else {
        gl_FrontColor.rgb = color.rgb;
        gl_FrontColor.a = color.a * (1.0 - hidden);
    }
    //gl_FrontColor = gl_Color;
    gl_BackColor = gl_Color;
    
    vMPosition = gl_Vertex;
    vPosition = gl_ModelViewMatrix * gl_Vertex;
    vNormal = normalize(gl_NormalMatrix * gl_Normal);
    vOffset = offset;
    vDotOffset = dotoffset;
}
'''
shaderFragSource = '''
#version 110

uniform bool  perspective;
uniform float clip_start;
uniform float clip_end;
uniform float object_scale;

uniform float focus_mult;

uniform vec3 mirroring;
uniform vec3 mirror_o;
uniform vec3 mirror_x;
uniform vec3 mirror_y;
uniform vec3 mirror_z;

varying vec4  vMPosition;
varying vec4  vPosition;
varying vec3  vNormal;
varying float vOffset;
varying float vDotOffset;

vec4 coloring(vec4 c) {
    vec4 mixer = vec4(0.6, 0.6, 0.6, 0.0);
    if(mirroring.x > 0.5) {
        if(dot(vMPosition.xyz - mirror_o, mirror_x) < 0.0) {
            mixer.r = 1.0;
            mixer.a = 0.5;
        }
    }
    if(mirroring.y > 0.5) {
        if(dot(vMPosition.xyz - mirror_o, mirror_y) > 0.0) {
            mixer.g = 1.0;
            mixer.a = 0.5;
        }
    }
    if(mirroring.z > 0.5) {
        if(dot(vMPosition.xyz - mirror_o, mirror_z) < 0.0) {
            mixer.b = 1.0;
            mixer.a = 0.5;
        }
    }
    c.rgb = c.rgb * (1.0 - mixer.a) + mixer.rgb * mixer.a;
    c.a = c.a * (1.0 - mixer.a) + mixer.a;
    return c;
}

void main() {
    float clip = clip_end - clip_start;
    float focus = 0.04;
    
    float alpha = gl_Color.a;
    
    if(perspective) {
        // perspective projection
        vec3 v = vPosition.xyz / vPosition.w;
        float l = length(v);
        float l_clip = (l - clip_start) / clip;
        float d = -dot(vNormal, v) / l;
        if(d <= 0.0) {
            alpha *= 0.5;
            //discard;
        }
        
        float focus_push = focus_mult * sign(focus - l_clip) * pow(abs(focus - l_clip), 4.0) * 400.0;
        
        // MAGIC!
        gl_FragDepth =
            gl_FragCoord.z
            - vOffset    * l_clip * 200.0
            - vDotOffset * l_clip * 0.0001 * (1.0 - d)
            - focus_push
            ;
    } else {
        // orthographic projection
        vec3 v = vec3(0, 0, clip * 0.5) + vPosition.xyz / vPosition.w;
        float l = length(v);
        float l_clip = (l - clip_start) / clip;
        float d = dot(vNormal, v) / l;
        if(d <= 0.0) {
            alpha *= 0.5;
            //discard;
        }
        
        // MAGIC!
        gl_FragDepth =
            gl_FragCoord.z
            - vOffset    * l_clip * 1.0
            + vDotOffset * l_clip * 0.000001 * (1.0 - d)
            ;
    }
    
    gl_FragColor = coloring(vec4(gl_Color.rgb, alpha));
    // gl_FragColor.r = focus_push;
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
    bgl.glEnable(bgl.GL_POINT_SMOOTH)


def glEnableStipple(enable=True):
    if enable:
        bgl.glLineStipple(4, 0x5555)
        bgl.glEnable(bgl.GL_LINE_STIPPLE)
    else:
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

def glEnableBackfaceCulling(enable=True):
    if enable:
        bgl.glDisable(bgl.GL_CULL_FACE)
        bgl.glDepthFunc(bgl.GL_GEQUAL)
    else:
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glEnable(bgl.GL_CULL_FACE)

def glSetOptions(prefix, opts):
    if not opts: return
    
    prefix = '%s '%prefix if prefix else ''
    def set_if_set(opt, cb):
        opt = '%s%s' % (prefix, opt)
        if opt in opts:
            cb(opts[opt])
    dpi_mult = opts.get('dpi mult', 1.0)
    set_if_set('offset',         lambda v: bmeshShader.assign('offset', v))
    set_if_set('dotoffset',      lambda v: bmeshShader.assign('dotoffset', v))
    set_if_set('color',          lambda v: bmeshShader.assign('color', v))
    set_if_set('color selected', lambda v: bmeshShader.assign('color_selected', v))
    set_if_set('hidden',         lambda v: bmeshShader.assign('hidden', v))
    set_if_set('width',          lambda v: bgl.glLineWidth(v*dpi_mult))
    set_if_set('size',           lambda v: bgl.glPointSize(v*dpi_mult))
    set_if_set('stipple',        lambda v: glEnableStipple(v))

def glSetMirror(symmetry=None, f:Frame=None):
    mirroring = (0,0,0)
    if symmetry and f:
        mx = 1.0 if 'x' in symmetry else 0.0
        my = 1.0 if 'y' in symmetry else 0.0
        mz = 1.0 if 'z' in symmetry else 0.0
        mirroring = (mx,my,mz)
        bmeshShader.assign('mirror_o', f.o)
        bmeshShader.assign('mirror_x', f.x)
        bmeshShader.assign('mirror_y', f.y)
        bmeshShader.assign('mirror_z', f.z)
    bmeshShader.assign('mirroring', mirroring)
    

def glDrawBMFace(bmf, opts=None, enableShader=True):
    glDrawBMFaces([bmf], opts=opts, enableShader=enableShader)

@profiler.profile
def glDrawBMFaces(lbmf, opts=None, enableShader=True):
    opts_ = opts or {}
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    
    bmeshShader.assign('focus_mult', opts_.get('focus mult', 1.0))
    
    def render(sx, sy, sz):
        for bmf in lbmf:
            if not nosel: bmeshShader.assign('selected', 1.0 if bmf.select else 0.0)
            if bmf.smooth:
                v0,v2 = bmf.verts[:2]
                c0,n0,c2,n2 = v0.co,v0.normal,v2.co,v2.normal
                for v3 in bmf.verts[2:]:
                    c1,n1,c2,n2 = c2,n2,v3.co,v3.normal
                    bgl.glNormal3f(sx*n0.x, sy*n0.y, sz*n0.z)
                    bgl.glVertex3f(sx*c0.x, sy*c0.y, sz*c0.z)
                    bgl.glNormal3f(sx*n1.x, sy*n1.y, sz*n1.z)
                    bgl.glVertex3f(sx*c1.x, sy*c1.y, sz*c1.z)
                    bgl.glNormal3f(sx*n2.x, sy*n2.y, sz*n2.z)
                    bgl.glVertex3f(sx*c2.x, sy*c2.y, sz*c2.z)
            else:
                bgl.glNormal3f(sx*bmf.normal.x, sy*bmf.normal.y, sz*bmf.normal.z)
                c0,c2 = bmf.verts[0].co,bmf.verts[1].co
                for bmv2 in bmf.verts[2:]:
                    c1,c2 = c2,bmv2.co
                    bgl.glVertex3f(sx*c0.x, sy*c0.y, sz*c0.z)
                    bgl.glVertex3f(sx*c1.x, sy*c1.y, sz*c1.z)
                    bgl.glVertex3f(sx*c2.x, sy*c2.y, sz*c2.z)
    
    if enableShader: bmeshShader.enable()
    
    glSetOptions('poly', opts)
    bgl.glBegin(bgl.GL_TRIANGLES)
    render(1, 1, 1)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    if mx or my or mz:
        glSetOptions('poly mirror', opts)
        bgl.glBegin(bgl.GL_TRIANGLES)
        if mx: render(-1,  1,  1)
        if my: render( 1, -1,  1)
        if mz: render( 1,  1, -1)
        if mx and my: render(-1, -1,  1)
        if mx and mz: render(-1,  1, -1)
        if my and mz: render( 1, -1, -1)
        if mx and my and mz: render(-1, -1, -1)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    if enableShader: bmeshShader.disable()

def glDrawBMFaceEdges(bmf, opts=None, enableShader=True):
    glDrawBMEdges(bmf.edges, opts=opts, enableShader=enableShader)

def glDrawBMFaceVerts(bmf, opts=None, enableShader=True):
    glDrawBMVerts(bmf.verts, opts=opts, enableShader=enableShader)

def glDrawBMEdge(bme, opts=None, enableShader=True):
    glDrawBMEdges([bme], opts=opts, enableShader=enableShader)

@profiler.profile
def glDrawBMEdges(lbme, opts=None, enableShader=True):
    opts_ = opts or {}
    if opts_.get('line width', 1.0) <= 0.0: return
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    
    def render(sx, sy, sz):
        for bme in lbme:
            if not nosel: bmeshShader.assign('selected', 1.0 if bme.select else 0.0)
            bmv0,bmv1 = bme.verts
            c0,n0,c1,n1 = bmv0.co,bmv0.normal,bmv1.co,bmv1.normal
            c0,c1 = c0+n0*dn,c1+n1*dn
            bgl.glNormal3f(sx*n0.x, sy*n0.y, sz*n0.z)
            bgl.glVertex3f(sx*c0.x, sy*c0.y, sz*c0.z)
            bgl.glNormal3f(sx*n1.x, sy*n1.y, sz*n1.z)
            bgl.glVertex3f(sx*c1.x, sy*c1.y, sz*c1.z)
    
    if enableShader: bmeshShader.enable()
    
    glSetOptions('line', opts)
    bgl.glBegin(bgl.GL_LINES)
    render(1,1,1)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    if mx or my or mz:
        glSetOptions('line mirror', opts)
        bgl.glBegin(bgl.GL_LINES)
        if mx: render(-1,  1,  1)
        if my: render( 1, -1,  1)
        if mz: render( 1,  1, -1)
        if mx and my: render(-1, -1,  1)
        if mx and mz: render(-1,  1, -1)
        if my and mz: render( 1, -1, -1)
        if mx and my and mz: render(-1, -1, -1)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    if enableShader: bmeshShader.disable()

def glDrawBMEdgeVerts(bme, opts=None, enableShader=True):
    glDrawBMVerts(bme.verts, opts=opts, enableShader=enableShader)

def glDrawBMVert(bmv, opts=None, enableShader=True):
    glDrawBMVerts([bmv], opts=opts, enableShader=enableShader)

@profiler.profile
def glDrawBMVerts(lbmv, opts=None, enableShader=True):
    opts_ = opts or {}
    if opts_.get('point size', 1.0) <= 0.0: return
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    
    def render(sx, sy, sz):
        for bmv in lbmv:
            if not nosel: bmeshShader.assign('selected', 1.0 if bmv.select else 0.0)
            c,n = bmv.co,bmv.normal
            c = c + dn * n
            bgl.glNormal3f(sx*n.x, sy*n.y, sz*n.z)
            bgl.glVertex3f(sx*c.x, sy*c.y, sz*c.z)
    
    if enableShader: bmeshShader.enable()
    glSetOptions('point', opts)
    bgl.glBegin(bgl.GL_POINTS)
    render(1,1,1)
    bgl.glEnd()
    bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    if mx or my or mz:
        glSetOptions('point mirror', opts)
        bgl.glBegin(bgl.GL_POINTS)
        if mx: render(-1,  1,  1)
        if my: render( 1, -1,  1)
        if mz: render( 1,  1, -1)
        if mx and my: render(-1, -1,  1)
        if mx and mz: render(-1,  1, -1)
        if my and mz: render( 1, -1, -1)
        if mx and my and mz: render(-1, -1, -1)
        bgl.glEnd()
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
    
    if enableShader: bmeshShader.disable()


class BMeshRender():
    @profiler.profile
    def __init__(self, target_obj, target_mx=None, source_bvh=None, source_mx=None):
        self.calllist = None
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
    
    @profiler.profile
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
    
    @profiler.profile
    def draw(self, opts=None):
        try:
            self.clean(opts=opts)
            bmeshShader.enable()
            bgl.glCallList(self.calllist)
        except:
            pass
        finally:
            bmeshShader.disable()

