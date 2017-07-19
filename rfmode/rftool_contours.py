import bpy
import bgl
import math
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec

@RFTool.action_call('contours tool')
class RFTool_Contours(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.edges = []
    
    def name(self): return "Contours"
    def icon(self): return "rf_contours_icon"
    def description(self): return 'Contours!!'
    
    def start(self):
        self.rfwidget.set_widget('line', color=(1.0, 1.0, 1.0))
        self.rfwidget.set_line_callback(self.line)
    
    @RFTool.dirty_when_done
    def line(self):
        xy0,xy1 = self.rfwidget.line2D
        ctr = xy0 + (xy1 - xy0) / 2
        plane = self.rfcontext.Point2D_to_Plane(xy0, xy1)
        ray = self.rfcontext.Point2D_to_Ray(ctr)
        pos,nor,_,_ = self.rfcontext.raycast_sources_Point2D(ctr)
        if not pos: return
        
        self.rfcontext.undo_push('cut')
        
        crawl = self.rfcontext.plane_intersection_crawl(ray, plane)
        self.edges = [elem for i,elem in enumerate(crawl) if i % 2 == 1]
        

    def modal_main(self): pass
    def draw_postview(self):
        bgl.glDepthRange(0, 0.999)
        bgl.glLineWidth(2)
        bgl.glColor4f(1,1,0,1)
        bgl.glBegin(bgl.GL_LINES)
        for bme in self.edges:
            bmv0,bmv1 = bme.verts
            bgl.glVertex3f(*bmv0.co)
            bgl.glVertex3f(*bmv1.co)
        bgl.glEnd()
        bgl.glDepthRange(0,1)
    def draw_postpixel(self): pass