import bpy
import bgl
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call('contours tool')
class RFTool_Contours(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.pts = []
        self.connected = False
        self.length = 0
    
    def name(self): return "Contours"
    def icon(self): return "rf_contours_icon"
    def description(self): return 'Contours!!'
    
    def start(self):
        self.rfwidget.set_widget('line', color=(1.0, 1.0, 1.0))
        self.rfwidget.set_line_callback(self.line)
    
    @RFTool.dirty_when_done
    def line(self):
        self.pts = []
        self.connected = False
        
        xy0,xy1 = self.rfwidget.line2D
        diff = xy1 - xy0
        if diff.length < 0.001: return
        ctr = xy0 + diff / 2
        plane = self.rfcontext.Point2D_to_Plane(xy0, xy1)
        ray = self.rfcontext.Point2D_to_Ray(ctr)
        
        crawl = self.rfcontext.plane_intersection_crawl(ray, plane)
        if not crawl: return
        
        self.rfcontext.undo_push('cut')
        
        self.pts = [c for f0,e,f1,c in crawl]
        self.connected = crawl[0][0] is not None
        self.length = sum((c0-c1).length for c0,c1 in zip(self.pts[:-1],self.pts[1:]))
        if self.connected: self.length += (self.pts[0]-self.pts[-1]).length
        
        count = 16
        step_size = self.length / count
        verts,edges,faces = [],[],[]
        dist = 0
        for c0,c1 in zip(self.pts[:-1],self.pts[1:]):
            d = (c1-c0).length
            while dist - d <= 0:
                # create new vert between c0 and c1
                p = c0 + (c1 - c0) * (dist / d)
                verts += [self.rfcontext.new_vert_point(p)]
                dist += step_size
            dist -= d
        for v0,v1 in zip(verts[:-1],verts[1:]):
            edges += [self.rfcontext.new_edge((v0, v1))]
        if self.connected:
            v0,v1 = verts[-1],verts[0]
            edges += [self.rfcontext.new_edge((v0, v1))]
        
        self.rfcontext.select(verts + edges + faces)
        
        print(self.length)

    def modal_main(self): pass
    def draw_postview(self):
        bgl.glDepthRange(0, 0.999)
        bgl.glLineWidth(2)
        
        if self.pts and False:
            bgl.glColor4f(1,0,0,1)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            for co in self.pts:
                bgl.glVertex3f(*co)
            if self.connected:
                bgl.glVertex3f(*self.pts[0])
            bgl.glEnd()
        
        bgl.glDepthRange(0,1)
    def draw_postpixel(self): pass