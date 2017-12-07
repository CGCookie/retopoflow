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
#version 430

uniform float use_selection;
uniform vec4 color;
uniform vec4 color_selected;

uniform mat4 matrix_m;
uniform mat3 matrix_n;
uniform mat4 matrix_v;
uniform mat4 matrix_p;

in vec3  vert_pos;      // position wrt model
in vec3  vert_norm;     // normal wrt model
in float selected;      // is vertex selected?

/* can the following be uniforms? */
in float offset;
in float dotoffset;
in float hidden;        // affects alpha for geometry below surface. 0=opaque, 1=transparent
in vec3  vert_scale;    // used for mirroring

out vec4  vPPosition;   // final position (projected)
out vec4  vMPosition;   // position wrt model
out vec4  vPosition;    // position wrt camera
out vec3  vNormal;      // normal wrt world  (should be camera?)
out float vOffset;
out float vDotOffset;
out vec4  vColor;

void main() {
    if(use_selection > 0.5 && selected > 0.5) {
        vColor = color_selected;
    } else {
        vColor = color;
    }
    vColor.a *= 1.0 - hidden;
    
    vec4 pos  = vec4(vert_pos * vert_scale, 1.0);
    vec3 norm = vert_norm * vert_scale;
    
    vMPosition  = pos;
    vPosition   = matrix_v * matrix_m * pos;
    vPPosition  = matrix_p * vPosition;
    gl_Position = vPPosition;
    
    vNormal     = normalize(matrix_n * norm);
    vOffset     = offset;
    vDotOffset  = dotoffset;
}
'''
shaderFragSource = '''
#version 430

uniform bool  perspective;
uniform float clip_start;
uniform float clip_end;
uniform float view_distance;

uniform float focus_mult;

uniform vec3 mirroring;     // mirror along axis: 0=false, 1=true
uniform vec3 mirror_o;
uniform vec3 mirror_x;
uniform vec3 mirror_y;
uniform vec3 mirror_z;

in vec4  vPPosition;
in vec4  vMPosition;
in vec4  vPosition;
in vec3  vNormal;
in float vOffset;
in float vDotOffset;
in vec4  vColor;

out vec4  diffuseColor;

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
    focus = (view_distance - clip_start) / clip + 0.04;
    
    float alpha = vColor.a;
    
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
        float dist_push = pow(view_distance, 3.0) * 0.000001;
        
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
    
    diffuseColor = coloring(vec4(vColor.rgb, alpha));
}
'''

def setupBMeshShader(shader):
    spc,r3d = bpy.context.space_data,bpy.context.space_data.region_3d
    shader.assign('perspective', r3d.view_perspective != 'ORTHO')
    shader.assign('clip_start', spc.clip_start)
    shader.assign('clip_end', spc.clip_end)
    shader.assign('view_distance', r3d.view_distance)
    shader.assign('vert_scale', Vector((1,1,1)))

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

def triangulateFace(verts):
    iv = iter(verts)
    v0,v2 = next(iv),next(iv)
    for v3 in iv:
        v1,v2 = v2,v3
        yield (v0,v1,v2)

@profiler.profile
def glDrawBMFaces(lbmf, opts=None, enableShader=True):
    opts_ = opts or {}
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    vdict = opts_.get('vertex dict', {})
    
    bmeshShader.assign('focus_mult', opts_.get('focus mult', 1.0))
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)
    
    @profiler.profile
    def render_general(sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx,sy,sz))
        bmeshShader.assign('selected', 0.0)
        for bmf in lbmf:
            bmeshShader.assign('selected', 1.0 if bmf.select else 0.0)
            if bmf.smooth:
                for v0,v1,v2 in triangulateFace(bmf.verts):
                    if v0 not in vdict: vdict[v0] = (v0.co, v0.normal)
                    if v1 not in vdict: vdict[v1] = (v1.co, v1.normal)
                    if v2 not in vdict: vdict[v2] = (v2.co, v2.normal)
                    (c0,n0),(c1,n1),(c2,n2) = vdict[v0],vdict[v1],vdict[v2]
                    bmeshShader.assign('vert_norm', n0)
                    bmeshShader.assign('vert_pos',  c0)
                    #bgl.glNormal3f(*n0)
                    #bgl.glVertex3f(*c0)
                    bmeshShader.assign('vert_norm', n1)
                    bmeshShader.assign('vert_pos',  c1)
                    #bgl.glNormal3f(*n1)
                    #bgl.glVertex3f(*c1)
                    bmeshShader.assign('vert_norm', n2)
                    bmeshShader.assign('vert_pos',  c2)
                    #bgl.glNormal3f(*n2)
                    #bgl.glVertex3f(*c2)
            else:
                bgl.glNormal3f(*bmf.normal)
                bmeshShader.assign('vert_norm', bmf.normal)
                for v0,v1,v2 in triangulateFace(bmf.verts):
                    if v0 not in vdict: vdict[v0] = (v0.co, v0.normal)
                    if v1 not in vdict: vdict[v1] = (v1.co, v1.normal)
                    if v2 not in vdict: vdict[v2] = (v2.co, v2.normal)
                    (c0,n0),(c1,n1),(c2,n2) = vdict[v0],vdict[v1],vdict[v2]
                    bmeshShader.assign('vert_pos', c0)
                    #bgl.glVertex3f(*c0)
                    bmeshShader.assign('vert_pos', c1)
                    #bgl.glVertex3f(*c1)
                    bmeshShader.assign('vert_pos', c2)
                    #bgl.glVertex3f(*c2)
    
    @profiler.profile
    def render_triangles(sx, sy, sz):
        # optimized for triangle-only meshes (source meshes that have been triangulated)
        bmeshShader.assign('vert_scale', (sx,sy,sz))
        bmeshShader.assign('selected', 0.0)
        for bmf in lbmf:
            bmeshShader.assign('selected', 1.0 if bmf.select else 0.0)
            if bmf.smooth:
                v0,v1,v2 = bmf.verts
                if v0 not in vdict: vdict[v0] = (v0.co, v0.normal)
                if v1 not in vdict: vdict[v1] = (v1.co, v1.normal)
                if v2 not in vdict: vdict[v2] = (v2.co, v2.normal)
                (c0,n0),(c1,n1),(c2,n2) = vdict[v0],vdict[v1],vdict[v2]
                bmeshShader.assign('vert_norm', n0)
                bmeshShader.assign('vert_pos',  c0)
                #bgl.glNormal3f(*n0)
                #bgl.glVertex3f(*c0)
                bmeshShader.assign('vert_norm', n1)
                bmeshShader.assign('vert_pos',  c1)
                #bgl.glNormal3f(*n1)
                #bgl.glVertex3f(*c1)
                bmeshShader.assign('vert_norm', n2)
                bmeshShader.assign('vert_pos',  c2)
                #bgl.glNormal3f(*n2)
                #bgl.glVertex3f(*c2)
            else:
                bgl.glNormal3f(*bmf.normal)
                v0,v1,v2 = bmf.verts
                if v0 not in vdict: vdict[v0] = (v0.co, v0.normal)
                if v1 not in vdict: vdict[v1] = (v1.co, v1.normal)
                if v2 not in vdict: vdict[v2] = (v2.co, v2.normal)
                (c0,n0),(c1,n1),(c2,n2) = vdict[v0],vdict[v1],vdict[v2]
                bmeshShader.assign('vert_pos',  c0)
                #bgl.glVertex3f(*c0)
                bmeshShader.assign('vert_pos',  c1)
                #bgl.glVertex3f(*c1)
                bmeshShader.assign('vert_pos',  c2)
                #bgl.glVertex3f(*c2)
    
    render = render_triangles if opts_.get('triangles only', False) else render_general
    
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

buf_zero = bgl.Buffer(bgl.GL_BYTE, 1, [0])

@profiler.profile
def glDrawBufferedObject(buffered_obj, opts=None):
    opts_ = opts or {}
    nosel    = opts_.get('no selection', False)
    mx,my,mz = opts_.get('mirror x', False),opts_.get('mirror y', False),opts_.get('mirror z', False)
    focus    = opts_.get('focus mult', 1.0)
    
    print(buffered_obj)
    count     = buffered_obj['count']
    gl_type   = buffered_obj['type']
    vbo_vpos  = buffered_obj['vbo pos']
    vbo_vnorm = buffered_obj['vbo norm']
    vbo_vsel  = buffered_obj['vbo sel']
    vbo_idx   = buffered_obj['vbo idx']
    
    bmeshShader.assign('focus_mult', focus)
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)
    
    #bmeshShader.assign('vert_pos', (1.0,0.5,0.1))
    bmeshShader.vertexAttribPointer(vbo_vpos,  'vert_pos',  3, bgl.GL_FLOAT)
    bmeshShader.vertexAttribPointer(vbo_vnorm, 'vert_norm', 3, bgl.GL_FLOAT)
    bmeshShader.vertexAttribPointer(vbo_vsel,  'selected',  1, bgl.GL_FLOAT)
    bgl.glBindBuffer(bgl.GL_ELEMENT_ARRAY_BUFFER, vbo_idx)
    # bgl.glEnableClientState(bgl.GL_VERTEX_ARRAY)
    
    gl_type_name,gl_count,type_name = {
        bgl.GL_POINTS:('points',1,'point'),
        bgl.GL_LINES:('lines',2,'line'),
        bgl.GL_TRIANGLES:('triangles',3,'poly')
    }[gl_type]
    def render(sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx,sy,sz))
        print('==> drawing %d %s  (%d verts)' % (count / gl_count, gl_type_name, count))
        bgl.glDrawArrays(gl_type, 0, count)
        #bgl.glDrawElements(gl_type, count, bgl.GL_INT, buf_zero)
        err = bgl.glGetError()
        if err == bgl.GL_INVALID_ENUM: print('ERROR: invalid enum')
        elif err == bgl.GL_INVALID_VALUE: print('ERROR: invalid value')
        elif err == bgl.GL_INVALID_OPERATION: print('ERROR: invalid operation')
        else: print('err = %d' % err)
    
    glSetOptions('%s' % type_name, opts)
    render(1, 1, 1)
    
    if mx or my or mz:
        glSetOptions('%s mirror' % type_name, opts)
        if mx: render(-1,  1,  1)
        if my: render( 1, -1,  1)
        if mz: render( 1,  1, -1)
        if mx and my: render(-1, -1,  1)
        if mx and mz: render(-1,  1, -1)
        if my and mz: render( 1, -1, -1)
        if mx and my and mz: render(-1, -1, -1)
    
    #bgl.glDisableClientState(bgl.GL_VERTEX_ARRYA)
    bmeshShader.disableVertexAttribArray('vert_pos')
    bmeshShader.disableVertexAttribArray('vert_norm')
    bmeshShader.disableVertexAttribArray('selected')
    bgl.glBindBuffer(bgl.GL_ELEMENT_ARRAY_BUFFER, 0)
    bgl.glBindBuffer(bgl.GL_ARRAY_BUFFER, 0)


@profiler.profile
def glDrawSimpleFaces(lsf, opts=None, enableShader=True):
    opts_ = opts or {}
    nosel = opts_.get('no selection', False)
    mx = opts_.get('mirror x', False)
    my = opts_.get('mirror y', False)
    mz = opts_.get('mirror z', False)
    dn = opts_.get('normal', 0.0)
    
    bmeshShader.assign('focus_mult', opts_.get('focus mult', 1.0))
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)
    bmeshShader.assign('selected', 0.0)
    
    @profiler.profile
    def render(sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx,sy,sz))
        for sf in lsf:
            for v0,v1,v2 in triangulateFace(sf):
                (c0,n0),(c1,n1),(c2,n2) = v0,v1,v2
                bgl.glNormal3f(*n0)
                bgl.glVertex3f(*c0)
                bgl.glNormal3f(*n1)
                bgl.glVertex3f(*c1)
                bgl.glNormal3f(*n2)
                bgl.glVertex3f(*c2)
    
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
    vdict = opts_.get('vertex dict', {})
    
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)
    
    @profiler.profile
    def render(sx, sy, sz):
        bmeshShader.assign('vert_scale', (sx,sy,sz))
        for bme in lbme:
            bmeshShader.assign('selected', 1.0 if bme.select else 0.0)
            v0,v1 = bme.verts
            if v0 not in vdict: vdict[v0] = (v0.co, v0.normal)
            if v1 not in vdict: vdict[v1] = (v1.co, v1.normal)
            (c0,n0),(c1,n1) = vdict[v0],vdict[v1]
            c0,c1 = c0+n0*dn,c1+n1*dn
            bmeshShader.assign('vert_norm', n0)
            bmeshShader.assign('vert_pos',  c0)
            #bgl.glVertex3f(0,0,0)
            bmeshShader.assign('vert_norm', n1)
            bmeshShader.assign('vert_pos',  c1)
            #bgl.glVertex3f(0,0,0)
    
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
    vdict = opts_.get('vertex dict', {})
    
    bmeshShader.assign('use_selection', 0.0 if nosel else 1.0)
    
    @profiler.profile
    def render(sx, sy, sz):
        bmeshShader.assign('vert_scale', Vector((sx,sy,sz)))
        for bmv in lbmv:
            bmeshShader.assign('selected', 1.0 if bmv.select else 0.0)
            if bmv not in vdict: vdict[bmv] = (bmv.co, bmv.normal)
            c,n = vdict[bmv]
            c = c + dn * n
            bmeshShader.assign('vert_norm', n)
            bmeshShader.assign('vert_pos',  c)
            #bgl.glNormal3f(*n)
            #bgl.glVertex3f(*c)
    
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
        #bgl.glPushMatrix()
        #bgl.glMultMatrixf(self.bglMatrix)
        glDrawBMFaces(self.tar_bmesh.faces, opts=opts, enableShader=False)
        glDrawBMEdges(self.tar_bmesh.edges, opts=opts, enableShader=False)
        glDrawBMVerts(self.tar_bmesh.verts, opts=opts, enableShader=False)
        bgl.glDepthRange(0, 1)
        #bgl.glPopMatrix()
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

