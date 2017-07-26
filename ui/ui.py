import bpy
import bgl
import blf
from bpy.types import BoolProperty

class UI_Element:
    pass

class UI_Container:
    def __init__(self, label):
        self.label = label
        self.entities = []
    
    def add_collapsable(self, label, collapsed=False):
        pass
    
    def add_property(self, prop):
        t = type(property)
        if t is BoolProperty:
            self.entities += [UI_Wrapper_BoolProperty(prop)]
        else:
            assert False, "Unhandled type: %s" % str(t)
    
    def add_checkbox(self, label, fn_get, fn_set):
        pass
    def add_label(self, label):
        pass
    def add_button(self, label, fn_click):
        pass

class Window(UI_Container):
    def __init__(self, context, pos):
        self.context = context
        self.pos = pos
    
    def draw_postview(self):
        bgl.glColor4f(0,0,0,0.5)
        
        pass

class UI_Collapsable(UI_Container):
    pass

class UI_Checkbox:
    pass

class UI_Label:
    pass

class UI_Button:
    pass

