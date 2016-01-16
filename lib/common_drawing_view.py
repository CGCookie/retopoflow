'''
Created on Jul 11, 2015

@author: Patrick
'''
import bpy
import bgl
import blf

def draw3d_polyline(context, points, color, thickness, LINE_TYPE):
    if context.region_data.view_perspective == 'ORTHO':
        bias = 0.9997
    else:
        bias = 0.997
        
    if LINE_TYPE == "GL_LINE_STIPPLE":
        bgl.glLineStipple(4, 0x5555)  #play with this later
        bgl.glEnable(bgl.GL_LINE_STIPPLE)  
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glColor4f(*color)
    bgl.glLineWidth(thickness)
    bgl.glDepthRange(0.0, bias)
    bgl.glBegin(bgl.GL_LINE_STRIP)
    for coord in points: bgl.glVertex3f(*coord)
    bgl.glEnd()
    bgl.glLineWidth(1)
    if LINE_TYPE == "GL_LINE_STIPPLE":
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
        bgl.glEnable(bgl.GL_BLEND)  # back to uninterrupted lines  

def draw3d_closed_polylines(context, lpoints, color, thickness, LINE_TYPE):
    if context.space_data.region_3d.view_perspective == 'ORTHO':
        bias = 0.9997
    else:
        bias = 0.997
    if LINE_TYPE == "GL_LINE_STIPPLE":
        bgl.glLineStipple(4, 0x5555)  #play with this later
        bgl.glEnable(bgl.GL_LINE_STIPPLE)  
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glColor4f(*color)
    bgl.glLineWidth(thickness)
    bgl.glDepthRange(0.0, bias)
    for points in lpoints:
        bgl.glBegin(bgl.GL_LINE_STRIP)
        for coord in points:
            bgl.glVertex3f(*coord)
        bgl.glVertex3f(*points[0])
        bgl.glEnd()
    bgl.glLineWidth(1)
    if LINE_TYPE == "GL_LINE_STIPPLE":
        bgl.glDisable(bgl.GL_LINE_STIPPLE)
        bgl.glEnable(bgl.GL_BLEND)  # back to uninterrupted lines

def draw3d_arrow(context, pfrom, pto, normal, color, thickness, LINE_TYPE):
    pdiff = pto - pfrom
    l = pdiff.length
    hd = l * 0.10
    hw = l * 0.05
    pdir = pdiff / l
    portho = pdir.cross(normal).normalized()
    pto0 = pto - pdir * hd + portho * hw
    pto1 = pto - pdir * hd - portho * hw
    
    if context.space_data.region_3d.view_perspective == 'ORTHO':
        bias = 0.9997
    else:
        bias = 0.997
    if LINE_TYPE == "GL_LINE_STIPPLE":
        bgl.glLineStipple(4, 0x5555)  #play with this later
        bgl.glEnable(bgl.GL_LINE_STIPPLE)  
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glColor4f(*color)
    bgl.glLineWidth(thickness)
    bgl.glDepthRange(0.0, bias)
    bgl.glBegin(bgl.GL_LINES)
    bgl.glVertex3f(*pfrom)
    bgl.glVertex3f(*pto)
    bgl.glVertex3f(*pto0)
    bgl.glVertex3f(*pto)
    bgl.glVertex3f(*pto1)
    bgl.glVertex3f(*pto)
    bgl.glEnd()
    bgl.glLineWidth(1)
    if LINE_TYPE == "GL_LINE_STIPPLE":
        bgl.glDisable(bgl.GL_LINE_STIPPLE)

def draw3d_quad(context, points, color):
    if context.space_data.region_3d.view_perspective == 'ORTHO':
        bias = 0.9999
    else:
        bias = 0.999
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glColor4f(*color)
    bgl.glDepthRange(0.0, bias)
    bgl.glBegin(bgl.GL_QUADS)
    for coord in points: bgl.glVertex3f(*coord)
    bgl.glEnd()
    
def draw3d_quads(context, lpoints, color):
    if context.space_data.region_3d.view_perspective == 'ORTHO':
        bias = 0.9999
    else:
        bias = 0.999
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glColor4f(*color)
    bgl.glDepthRange(0.0, bias)
    bgl.glBegin(bgl.GL_QUADS)
    for points in lpoints:
        for coord in points:
            bgl.glVertex3f(*coord)
    bgl.glEnd()
    
def draw3d_points(context, points, color, size):
    if context.space_data.region_3d.view_perspective == 'ORTHO':
        bias = 0.9997
    else:
        bias = 0.997
    bgl.glColor4f(*color)
    bgl.glPointSize(size)
    bgl.glDepthRange(0.0, bias)
    bgl.glBegin(bgl.GL_POINTS)
    for coord in points: bgl.glVertex3f(*coord)  
    bgl.glEnd()
    bgl.glPointSize(1.0)