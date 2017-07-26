import bpy
import bgl
import blf
from bpy.types import BoolProperty

from itertools import chain

from .maths import Point2D


class Drawing:
    _instance = None
    
    @staticmethod
    def get_instance():
        if not Drawing._instance:
            Drawing._creating = True
            Drawing._instance = Drawing()
            del Drawing._creating
        return Drawing._instance
    
    def __init__(self):
        assert hasattr(self, '_creating'), "Do not instantiate directly.  Use Drawing.get_instance()"
        
        self.font_id = 0
        self.text_size(12)
    
    def text_size(self, size):
        blf.size(self.font_id, size, 72)
        self.line_height = round(blf.dimensions(self.font_id, "XMPQpqjI")[1] * 1.5)
        self.line_base = round(blf.dimensions(self.font_id, "XMPQI")[1])
    
    def get_text_size(self, text):
        size = blf.dimensions(self.font_id, text)
        return (round(size[0]), round(size[1]))
    def get_text_width(self, text):
        size = blf.dimensions(self.font_id, text)
        return round(size[0])
    def get_text_height(self, text):
        size = blf.dimensions(self.font_id, text)
        return round(size[1])
    def get_line_height(self, text=None):
        if not text: return self.line_height
        return self.line_height * (1 + text.count('\n'))
    
    def set_clipping(self, xmin, ymin, xmax, ymax):
        blf.clipping(self.font_id, xmin, ymin, xmax, ymax)
        self.enable_clipping()
    def enable_clipping(self):
        blf.enable(self.font_id, blf.CLIPPING)
    def disable_clipping(self):
        blf.disable(self.font_id, blf.CLIPPING)
    
    def text_draw2D(self, text, pos:Point2D, color, dropshadow=None):
        lines = str(text).split('\n')
        l,t = round(pos[0]),round(pos[1])
        lh = self.line_height
        lb = self.line_base
        
        if dropshadow: self.text_draw2D(text, (l+1,t-1), dropshadow)
        
        bgl.glColor4f(*color)
        for i,line in enumerate(lines):
            th = self.get_text_height(line)
            # x,y = l,t - (i+1)*lh + int((lh-th)/2)
            x,y = l,t - (i+1)*lh + int((lh-lb)/2)
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


class UI_Element:
    def __init__(self):
        self.drawing = Drawing.get_instance()
    
    def draw(self, left, top, width, height):
        #self.drawing.set_clipping(left, top-height, left+width, top)
        self._draw(left, top, width, height)
        #self.drawing.disable_clipping()
    
    def get_width(self): return 0
    def get_height(self): return 0
    def _draw(self, left, top, width, height): pass


class UI_Label(UI_Element):
    def __init__(self, label, icon=None, tooltip=None, color=(1,1,1,1), align=-1):
        super().__init__()
        self.text = str(label)
        self.icon = icon
        self.tooltip = tooltip
        self.color = color
        self.align = align
        
        self.width = self.drawing.get_text_width(self.text)
        self.height = self.drawing.get_line_height(self.text)
    
    def get_width(self): return self.width
    def get_height(self): return self.height
    def _draw(self, left, top, width, height):
        if self.align < 0:
            self.drawing.text_draw2D(self.text, Point2D((left, top)), self.color)
        elif self.align == 0:
            self.drawing.text_draw2D(self.text, Point2D((left+(width-self.width)/2, top)), self.color)
        else:
            self.drawing.text_draw2D(self.text, Point2D((left+width-self.width, top)), self.color)


class UI_Rule(UI_Element):
    def __init__(self, thickness=2, padding=0, color=(1.0,1.0,1.0,0.25)):
        super().__init__()
        self.thickness = thickness
        self.color = color
        self.padding = padding
    def get_width(self): return self.padding*2 + 1
    def get_height(self): return self.padding*2 + self.thickness
    def _draw(self, left, top, width, height):
        t2 = round(self.thickness/2)
        padding = self.padding
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glColor4f(*self.color)
        bgl.glLineWidth(self.thickness)
        bgl.glBegin(bgl.GL_LINES)
        bgl.glVertex2f(left+padding, top-padding-t2)
        bgl.glVertex2f(left+width-padding, top-padding-t2)
        bgl.glEnd()


class UI_Container(UI_Element):
    def __init__(self, vertical=True):
        super().__init__()
        self.vertical = vertical
        self.ui_items = []
    
    def get_width(self):
        if not self.ui_items: return 0
        if self.vertical:
            return max(ui.get_width() for ui in self.ui_items)
        return sum(ui.get_width() for ui in self.ui_items)
    def get_height(self):
        if not self.ui_items: return 0
        if self.vertical:
            return sum(ui.get_height() for ui in self.ui_items)
        return max(ui.get_height() for ui in self.ui_items)
    
    def _draw(self, l, t, w, h):
        if self.vertical:
            y = t
            for ui in self.ui_items:
                eh = ui.get_height()
                ui.draw(l,y,w,eh)
                y -= eh
        else:
            x = l
            for ui in self.ui_items:
                ew,eh = ui.get_width(),ui.get_height()
                ui.draw(x,t,w,eh)
                x += ew
    
    def add(self, ui_item):
        self.ui_items.append(ui_item)
        return ui_item
    
    def add_label(self, *args, **kwargs):
        return self.add(UI_Label(*args, **kwargs))
    
    def add_rule(self, *args, **kwargs):
        return self.add(UI_Rule(*args, **kwargs))
    
    def add_container(self, *args, **kwargs):
        return self.add(UI_Container(*args, **kwargs))
    
    # def add_collapsable(self, label, collapsed=False):
    #     pass
    
    # def add_property(self, prop):
    #     ui = None
    #     t = type(property)
    #     if t is BoolProperty:
    #         ui = UI_BoolProperty(prop)
    #     assert ui, "Unhandled type: %s" % str(t)
    #     self.entities += [ui]
    #     return ui
    
    # def add_checkbox(self, label, fn_get, fn_set):
    #     pass
    # def add_button(self, label, fn_click):
    #     pass


class UI_HBFContainer(UI_Container):
    def __init__(self, label, vertical=True):
        super().__init__()
        self.header = self.add_container()
        self.body = self.add_container(vertical=vertical)
        self.footer = self.add_container()
        self.add_label(label, align=0, header=True)
        self.add_rule(header=True)
    
    def get_width(self): return max(c.get_width() for c in self.ui_items)
    def get_height(self): return sum(c.get_height() for c in self.ui_items)
    
    def add_HBF(self, ui_item, header=False, footer=False):
        if header: self.header.add(ui_item)
        elif footer: self.footer.add(ui_item)
        else: self.body.add(ui_item)
        return ui_item
    
    def add_label(self, *args, header=False, footer=False, **kwargs):
        ui = UI_Label(*args, **kwargs)
        return self.add_HBF(ui, header=header, footer=footer)
    
    def add_rule(self, *args, header=False, footer=False, **kwargs):
        ui = UI_Rule(*args, **kwargs)
        return self.add_HBF(ui, header=header, footer=footer)


class UI_BoolProperty(UI_Element):
    def __init__(self, prop):
        super().__init__()
        self.prop = prop
        


class UI_Window(UI_HBFContainer):
    def __init__(self, label, pos:Point2D=None, sticky=None, vertical=True):
        super().__init__(label, vertical=vertical)
        self.pos = pos or Point2D((0,0))
        self.sticky = sticky
        self.padding = 5
    
    def draw_postpixel(self, screen_width, screen_height):
        bgl.glEnable(bgl.GL_BLEND)
        
        p = self.padding
        sw,sh = screen_width,screen_height
        cw,ch = round(sw/2),round(sh/2)
        positions = {
            None: self.pos,
            0: self.pos,
            7: (0, sh),
            8: (cw, sh),
            9: (sw, sh),
            4: (0, ch),
            5: (cw, ch),
            6: (sw, ch),
            1: (0, 0),
            2: (cw, 0),
            3: (sw, 0),
        }
        l,t = positions.get(self.sticky, self.pos)
        w,h = self.get_width()+p*2,self.get_height()+p*2
        l,t = max(10, min(sw-10-w,l)),max(10+h, min(sh-10,t))     # clamp position so window is always seen
        self.pos = Point2D((l,t))
        
        # draw background
        bgl.glColor4f(0,0,0,0.25)
        bgl.glBegin(bgl.GL_QUADS)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glEnd()
        
        bgl.glColor4f(0,0,0,0.5)
        bgl.glBegin(bgl.GL_LINE_STRIP)
        bgl.glVertex2f(l,t)
        bgl.glVertex2f(l,t-h)
        bgl.glVertex2f(l+w,t-h)
        bgl.glVertex2f(l+w,t)
        bgl.glVertex2f(l,t)
        bgl.glEnd()
        
        self.draw(l+p, t-p, w-p*2, h-p*2)


class UI_Collapsable(UI_Container):
    pass

class UI_Checkbox:
    pass

class UI_Button:
    pass

