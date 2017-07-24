import bpy
import bgl
import blf

from ..common.maths import Point, Point2D

class Drawing:
    def __init__(self):
        self.font_id = 0
        self.text_size(12)
    
    def text_size(self, size):
        blf.size(self.font_id, size, 72)
        self.line_height = round(blf.dimensions(self.font_id, "XMPQpqjI")[1] * 1.5)
    
    def get_text_size(self, text):
        size = blf.dimensions(self.font_id, text)
        return (round(size[0]), round(size[1]))
    def get_text_width(self, text):
        size = blf.dimensions(self.font_id, text)
        return round(size[0])
    def get_text_height(self, text):
        size = blf.dimensions(self.font_id, text)
        return round(size[1])
    
    def text_draw2D(self, text, pos:Point2D, color, dropshadow=None):
        lines = str(text).split('\n')
        x,y = round(pos[0]),round(pos[1])
        
        if dropshadow: self.text_draw2D(text, (x+1,y-1), dropshadow)
        
        bgl.glColor4f(*color)
        for line in lines:
            blf.position(self.font_id, x, y, 0)
            blf.draw(self.font_id, line)
            y -= self.line_height
    
    def textbox_draw2D(self, text, pos:Point2D, padding=5, textbox_position=7):
        '''
        textbox_position specifies where the textbox is drawn in relation to pos.
        ex: if textbox_position==7, then the textbox is drawn where pos is the upper-left corner
        tip: textbox_position is arranged same as numpad
                    +-----+
                    |7 8 9|
                    |4 5 6|
                    |1 2 3|
                    +-----+
        '''
        lh = self.line_height
        
        # TODO: wrap text!
        lines = text.split('\n')
        w = max(self.get_text_width(line) for line in lines)
        h = len(lines) * lh
        
        # find top-left corner (adjusting for textbox_position)
        l,t = round(pos[0]),round(pos[1])
        textbox_position -= 1
        lcr = textbox_position % 3
        tmb = int(textbox_position / 3)
        l += [w+padding,round(w/2),-padding][lcr]
        t += [h+padding,round(h/2),-padding][tmb]
        
        bgl.glEnable(bgl.GL_BLEND)
        
        bgl.glColor4f(0.0, 0.0, 0.0, 0.25)
        bgl.glBegin(bgl.GL_QUADS)
        bgl.glVertex2f(l+w+padding,t+padding)
        bgl.glVertex2f(l-padding,t+padding)
        bgl.glVertex2f(l-padding,t-h-padding)
        bgl.glVertex2f(l+w+padding,t-h-padding)
        bgl.glEnd()
        
        bgl.glColor4f(0.0, 0.0, 0.0, 0.75)
        bgl.glLineWidth(1.0)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l+w+padding,t+padding)
        bgl.glVertex2f(l-padding,t+padding)
        bgl.glVertex2f(l-padding,t-h-padding)
        bgl.glVertex2f(l+w+padding,t-h-padding)
        bgl.glVertex2f(l+w+padding,t+padding)
        bgl.glEnd()
        
        bgl.glColor4f(1,1,1,0.5)
        for i,line in enumerate(lines):
            th = self.get_text_height(line)
            y = t - (i+1)*lh + int((lh-th) / 2)
            blf.position(self.font_id, l, y, 0)
            blf.draw(self.font_id, line)

class RFContext_Drawing:
    def _init_drawing(self):
        self.drawing = Drawing()
