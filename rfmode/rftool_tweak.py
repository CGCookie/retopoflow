import bpy
from .rftool import RFTool

class RFTool_Tweak(RFTool):
    ''' Called when RetopoFlow plugin is '''
    def init_tool(self):
        pass
    
    def init(self):
        ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
        pass
    
    def start(self):
        ''' Called the tool is being switched into '''
        pass

    def modal_main(self):
        pass
    
    def draw_postview(self): pass
    def draw_postpixel(self): pass
    
