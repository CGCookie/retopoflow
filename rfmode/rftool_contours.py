import bpy
import bgl
import blf
import os
import math
from itertools import chain
from .rftool import RFTool
from ..lib.common_utilities import showErrorMessage
from ..common.utils import max_index
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.ui import UI_Label, UI_IntValue, UI_Image
from .rftool_contours_utils import *
# from ..icons import images

@RFTool.action_call('contours tool')
class RFTool_Contours(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['move']  = self.modal_move
        self.count = 16
    
    def name(self): return "Contours"
    def icon(self): return "rf_contours_icon"
    def description(self): return 'Contours!!'

    def start(self):
        self.rfwidget.set_widget('line', color=(1.0, 1.0, 1.0))
        self.rfwidget.set_line_callback(self.line)
        self.update()

        self.show_cut = True
        self.pts = []
        self.cut_pts = []
        self.connected = False
        self.cuts = []
    
    def get_count(self): return self.count
    def set_count(self, v): self.count = max(3, v)
    def get_ui_options(self):
        self.ui_count = UI_IntValue('Count', self.get_count, self.set_count)
        return [self.ui_count]
    
    def get_ui_icon(self):
        icon = [[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,3],[0,0,0,95],[7,5,2,212],[4,2,1,240],[0,0,0,248],[0,0,0,253],[1,1,0,253],[2,1,1,250],[0,0,0,234],[0,0,0,195],[0,0,0,94],[0,0,0,3],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,30],[0,0,0,196],[0,0,0,252],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[2,1,0,253],[0,0,0,195],[0,0,0,28],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,8],[0,0,0,177],[4,2,1,255],[0,0,0,255],[0,0,0,255],[12,12,12,255],[20,11,5,255],[30,17,8,255],[228,180,107,255],[241,190,113,255],[38,22,10,255],[36,21,10,255],[164,164,164,255],[79,79,79,255],[8,4,2,255],[0,0,0,255],[0,0,0,255],[2,2,1,254],[0,0,0,175],[0,0,0,7],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,34],[0,0,0,237],[0,0,0,255],[0,0,0,255],[13,8,4,255],[199,199,199,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[255,201,120,255],[255,201,120,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[34,19,9,255],[83,65,39,255],[1,1,0,255],[0,0,0,255],[10,6,2,250],[0,0,0,32],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,68],[2,1,1,250],[0,0,0,255],[36,28,17,255],[32,18,9,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[255,201,120,255],[255,201,120,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[255,201,120,255],[200,158,94,255],[5,3,2,255],[0,0,0,255],[0,0,0,249],[0,0,0,66],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,31],[5,3,1,254],[0,0,0,255],[61,48,28,255],[233,183,108,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[254,199,118,255],[254,199,118,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[254,199,118,255],[254,199,118,255],[37,21,10,255],[11,6,3,255],[0,0,0,255],[0,0,0,250],[0,0,0,36],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,9],[0,0,0,238],[0,0,0,255],[11,6,3,255],[248,190,112,255],[253,194,114,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[253,194,114,255],[253,194,114,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[253,194,114,255],[253,194,114,255],[40,23,11,255],[39,23,11,255],[24,24,24,255],[0,0,0,255],[0,0,0,237],[0,0,0,8],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,181],[0,0,0,255],[6,4,2,255],[37,22,10,255],[251,190,110,255],[251,190,110,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[251,189,110,255],[251,189,110,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[251,189,110,255],[251,189,110,255],[40,23,11,255],[40,23,11,255],[208,208,208,255],[7,7,7,255],[0,0,0,255],[0,0,0,179],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,36],[0,0,0,254],[0,0,0,255],[33,19,9,255],[40,23,11,255],[249,185,106,255],[249,185,106,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[249,185,106,255],[249,185,106,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[249,185,106,255],[249,185,106,255],[40,23,11,255],[40,23,11,255],[226,226,226,255],[157,157,157,255],[0,0,0,255],[0,0,0,254],[0,0,0,34],[0,0,0,0]],[[0,0,0,0],[0,0,0,202],[0,0,0,255],[41,41,41,255],[40,23,11,255],[40,23,11,255],[248,181,102,255],[248,181,102,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[248,180,101,255],[248,180,101,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[251,251,251,255],[40,23,11,255],[40,23,11,255],[248,180,101,255],[248,180,101,255],[40,23,11,255],[40,23,11,255],[222,222,222,255],[217,217,217,255],[37,37,37,255],[0,0,0,255],[0,0,0,200],[0,0,0,0]],[[0,0,0,5],[0,0,0,253],[0,0,0,255],[209,209,209,255],[40,23,11,255],[40,23,11,255],[246,176,97,255],[246,176,97,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[246,176,97,255],[246,176,97,255],[40,23,11,255],[40,23,11,255],[252,252,252,255],[244,244,244,255],[40,23,11,255],[40,23,11,255],[246,176,97,255],[246,176,97,255],[40,23,11,255],[40,23,11,255],[212,212,212,255],[211,211,211,255],[165,165,165,255],[0,0,0,255],[0,0,0,253],[0,0,0,5]],[[0,0,0,108],[0,0,0,255],[17,17,17,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[245,171,93,255],[245,171,93,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[245,171,93,255],[245,171,93,255],[40,23,11,255],[40,23,11,255],[245,245,245,255],[237,237,237,255],[40,23,11,255],[40,23,11,255],[245,171,93,255],[245,171,93,255],[40,23,11,255],[40,23,11,255],[193,193,193,255],[206,206,206,255],[200,200,200,255],[15,15,15,255],[0,0,0,255],[0,0,0,105]],[[0,0,0,202],[0,0,0,255],[87,87,87,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[243,167,89,255],[243,167,89,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[243,167,89,255],[243,167,89,255],[40,23,11,255],[40,23,11,255],[237,237,237,255],[230,230,230,255],[40,23,11,255],[40,23,11,255],[243,167,89,255],[243,167,89,255],[40,23,11,255],[40,23,11,255],[179,179,179,255],[198,198,198,255],[195,195,195,255],[68,68,68,255],[0,0,0,255],[0,0,0,201]],[[0,0,0,238],[0,0,0,255],[179,179,179,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[241,162,85,255],[241,162,85,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[241,162,85,255],[241,162,85,255],[40,23,11,255],[40,23,11,255],[230,230,230,255],[223,223,223,255],[40,23,11,255],[40,23,11,255],[241,162,85,255],[241,162,85,255],[40,23,11,255],[40,23,11,255],[173,173,173,255],[184,184,184,255],[188,188,188,255],[125,125,125,255],[0,0,0,255],[0,0,0,237]],[[0,0,0,251],[0,0,0,255],[238,238,238,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[240,158,81,255],[240,158,81,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[240,158,81,255],[240,158,81,255],[40,23,11,255],[40,23,11,255],[224,224,224,255],[216,216,216,255],[40,23,11,255],[40,23,11,255],[240,158,81,255],[240,158,81,255],[40,23,11,255],[40,23,11,255],[165,165,165,255],[172,172,172,255],[182,182,182,255],[158,158,158,255],[0,0,0,255],[0,0,0,251]],[[0,0,0,254],[0,0,0,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[238,153,77,255],[238,153,77,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[238,153,77,255],[238,153,77,255],[40,23,11,255],[40,23,11,255],[217,217,217,255],[209,209,209,255],[40,23,11,255],[40,23,11,255],[238,153,77,255],[238,153,77,255],[40,23,11,255],[40,23,11,255],[158,158,158,255],[163,163,163,255],[176,176,176,255],[168,168,168,255],[0,0,0,255],[0,0,0,254]],[[0,0,0,254],[0,0,0,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[237,149,73,255],[237,149,73,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[237,149,73,255],[237,149,73,255],[40,23,11,255],[40,23,11,255],[209,209,209,255],[202,202,202,255],[40,23,11,255],[40,23,11,255],[237,149,73,255],[237,149,73,255],[40,23,11,255],[40,23,11,255],[151,151,151,255],[155,155,155,255],[170,170,170,255],[161,161,161,255],[0,0,0,255],[0,0,0,253]],[[0,0,0,251],[0,0,0,255],[235,235,235,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[235,144,69,255],[235,144,69,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[253,253,253,255],[40,23,11,255],[40,23,11,255],[235,144,69,255],[235,144,69,255],[40,23,11,255],[40,23,11,255],[202,202,202,255],[195,195,195,255],[40,23,11,255],[40,23,11,255],[235,144,69,255],[235,144,69,255],[40,23,11,255],[40,23,11,255],[145,145,145,255],[152,152,152,255],[162,162,162,255],[138,138,138,255],[0,0,0,255],[0,0,0,250]],[[0,0,0,237],[0,0,0,255],[174,174,174,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[233,140,65,255],[233,140,65,255],[40,23,11,255],[40,23,11,255],[253,253,253,255],[246,246,246,255],[40,23,11,255],[40,23,11,255],[233,139,65,255],[233,139,65,255],[40,23,11,255],[40,23,11,255],[196,196,196,255],[189,189,189,255],[40,23,11,255],[40,23,11,255],[233,139,65,255],[233,139,65,255],[40,23,11,255],[40,23,11,255],[137,137,137,255],[149,149,149,255],[156,156,156,255],[101,101,101,255],[0,0,0,255],[0,0,0,236]],[[0,0,0,197],[0,0,0,255],[82,82,82,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[232,135,61,255],[232,135,61,255],[40,23,11,255],[40,23,11,255],[247,247,247,255],[240,240,240,255],[40,23,11,255],[40,23,11,255],[232,135,60,255],[232,135,60,255],[40,23,11,255],[40,23,11,255],[189,189,189,255],[181,181,181,255],[40,23,11,255],[40,23,11,255],[232,135,60,255],[232,135,60,255],[40,23,11,255],[40,23,11,255],[130,130,130,255],[152,152,152,255],[149,149,149,255],[53,53,53,255],[0,0,0,255],[0,0,0,195]],[[0,0,0,97],[0,0,0,255],[14,14,14,255],[255,255,255,255],[40,23,11,255],[40,23,11,255],[230,130,56,255],[230,130,56,255],[40,23,11,255],[40,23,11,255],[240,240,240,255],[233,233,233,255],[40,23,11,255],[40,23,11,255],[230,130,56,255],[230,130,56,255],[40,23,11,255],[40,23,11,255],[181,181,181,255],[174,174,174,255],[40,23,11,255],[40,23,11,255],[230,130,56,255],[230,130,56,255],[40,23,11,255],[40,23,11,255],[130,130,130,255],[149,149,149,255],[142,142,142,255],[11,11,11,255],[0,0,0,255],[0,0,0,93]],[[0,0,0,3],[0,0,0,252],[0,0,0,255],[200,200,200,255],[40,23,11,255],[40,23,11,255],[229,126,52,255],[229,126,52,255],[40,23,11,255],[40,23,11,255],[233,233,233,255],[225,225,225,255],[40,23,11,255],[40,23,11,255],[229,126,52,255],[229,126,52,255],[40,23,11,255],[40,23,11,255],[174,174,174,255],[167,167,167,255],[40,23,11,255],[40,23,11,255],[229,126,52,255],[229,126,52,255],[40,23,11,255],[40,23,11,255],[140,140,140,255],[142,142,142,255],[104,104,104,255],[0,0,0,255],[0,0,0,252],[0,0,0,3]],[[0,0,0,0],[0,0,0,192],[0,0,0,255],[34,34,34,255],[40,23,11,255],[40,23,11,255],[227,121,48,255],[227,121,48,255],[40,23,11,255],[40,23,11,255],[225,225,225,255],[218,218,218,255],[40,23,11,255],[40,23,11,255],[227,121,48,255],[227,121,48,255],[40,23,11,255],[40,23,11,255],[168,168,168,255],[161,161,161,255],[40,23,11,255],[40,23,11,255],[227,121,48,255],[227,121,48,255],[40,23,11,255],[40,23,11,255],[142,142,142,255],[134,134,134,255],[23,23,23,255],[0,0,0,255],[0,0,0,190],[0,0,0,0]],[[0,0,0,0],[0,0,0,25],[0,0,0,253],[0,0,0,255],[32,19,9,255],[40,23,11,255],[225,117,44,255],[225,117,44,255],[40,23,11,255],[40,23,11,255],[219,219,219,255],[212,212,212,255],[40,23,11,255],[40,23,11,255],[225,117,44,255],[225,117,44,255],[40,23,11,255],[40,23,11,255],[161,161,161,255],[153,153,153,255],[40,23,11,255],[40,23,11,255],[225,117,44,255],[225,117,44,255],[40,23,11,255],[40,23,11,255],[134,134,134,255],[87,87,87,255],[0,0,0,255],[0,0,0,253],[0,0,0,23],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,167],[0,0,0,255],[6,3,2,255],[37,21,10,255],[224,112,40,255],[224,112,40,255],[40,23,11,255],[40,23,11,255],[212,212,212,255],[205,205,205,255],[40,23,11,255],[40,23,11,255],[224,112,40,255],[224,112,40,255],[40,23,11,255],[40,23,11,255],[153,153,153,255],[146,146,146,255],[40,23,11,255],[40,23,11,255],[224,112,40,255],[224,112,40,255],[40,23,11,255],[40,23,11,255],[110,110,110,255],[4,4,4,255],[0,0,0,255],[0,0,0,164],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,4],[0,0,0,229],[0,0,0,255],[12,7,3,255],[219,108,37,255],[223,110,38,255],[40,23,11,255],[40,23,11,255],[205,205,205,255],[197,197,197,255],[40,23,11,255],[40,23,11,255],[223,110,38,255],[223,110,38,255],[40,23,11,255],[40,23,11,255],[146,146,146,255],[139,139,139,255],[40,23,11,255],[40,23,11,255],[223,110,38,255],[223,110,38,255],[40,23,11,255],[39,23,11,255],[13,13,13,255],[0,0,0,255],[0,0,0,228],[0,0,0,3],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,21],[2,1,1,248],[0,0,0,255],[45,24,10,255],[204,101,35,255],[40,23,11,255],[40,23,11,255],[215,215,215,255],[198,198,198,255],[40,23,11,255],[40,23,11,255],[223,110,38,255],[223,110,38,255],[40,23,11,255],[40,23,11,255],[140,140,140,255],[133,133,133,255],[40,23,11,255],[40,23,11,255],[223,110,38,255],[223,110,38,255],[37,21,10,255],[11,6,3,255],[0,0,0,255],[0,0,0,247],[0,0,0,24],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,51],[0,0,0,245],[0,0,0,255],[22,12,5,255],[31,18,8,255],[40,23,11,255],[214,214,214,255],[209,209,209,255],[40,23,11,255],[40,23,11,255],[223,110,38,255],[223,110,38,255],[40,23,11,255],[40,23,11,255],[152,152,152,255],[154,154,154,255],[40,23,11,255],[40,23,11,255],[223,110,38,255],[171,85,29,255],[5,3,1,255],[0,0,0,255],[0,0,0,245],[0,0,0,49],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,19],[0,0,0,225],[0,0,0,255],[0,0,0,255],[13,7,3,255],[149,149,149,255],[202,202,202,255],[40,23,11,255],[40,23,11,255],[223,110,38,255],[223,110,38,255],[40,23,11,255],[40,23,11,255],[157,157,157,255],[150,150,150,255],[40,23,11,255],[33,19,9,255],[62,32,13,255],[0,0,0,255],[0,0,0,255],[10,6,3,248],[0,0,0,19],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,2],[0,0,0,152],[3,2,1,254],[0,0,0,255],[0,0,0,255],[6,6,6,255],[19,11,5,255],[30,17,8,255],[198,97,34,255],[211,104,36,255],[38,22,10,255],[35,20,10,255],[89,89,89,255],[42,42,42,255],[7,4,2,255],[0,0,0,255],[0,0,0,255],[0,0,0,251],[0,0,0,149],[0,0,0,1],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,15],[0,0,0,175],[0,0,0,247],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[5,3,1,253],[0,0,0,173],[0,0,0,14],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,63],[8,5,3,197],[4,2,1,231],[0,0,0,240],[0,0,0,248],[2,1,0,250],[2,1,1,244],[0,0,0,221],[0,0,0,173],[0,0,0,62],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]]]
        self.ui_icon = UI_Image(icon)
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def update(self):
        sel_edges = self.rfcontext.get_selected_edges()
        sel_loops = find_loops(sel_edges)
        sel_strings = find_strings(sel_edges)
        self.loops_data = [{
            'loop': loop,
            'plane': loop_plane(loop),
            'count': len(loop),
            'radius': loop_radius(loop),
            'cl': Contours_Loop(loop, True),
            } for loop in sel_loops]
        self.strings_data = [{
            'string': string,
            'plane': loop_plane(string),
            'count': len(string),
            'cl': Contours_Loop(string, False),
            } for string in sel_strings]
        self.sel_loops = [Contours_Loop(loop, True) for loop in sel_loops]

    @RFTool.dirty_when_done
    def line(self):
        self.pts = []
        self.cut_pts = []
        self.cuts = []
        self.connected = False
        
        xy0,xy1 = self.rfwidget.line2D
        if (xy1-xy0).length < 0.001: return
        xy01 = xy0 + (xy1-xy0) / 2

        plane = self.rfcontext.Point2D_to_Plane(xy0, xy1)
        ray = self.rfcontext.Point2D_to_Ray(xy01)

        crawl = self.rfcontext.plane_intersection_crawl(ray, plane)
        if not crawl: return
        # get crawl data (over source)
        pts = [c for (f0,e,f1,c) in crawl]
        connected = crawl[0][0] is not None
        
        print('before: ' + str((len(pts),connected)))
        pts,connected = self.rfcontext.clip_pointloop(pts, connected)
        print('after: ' + str((len(pts),connected)))
        
        if not pts: return
        
        self.rfcontext.undo_push('cut')

        cl_cut = Contours_Loop(pts, connected)
        
        self.cuts = [cl_cut]
        self.cut_pts = pts
        self.connected = connected
        

        sel_edges = self.rfcontext.get_selected_edges()
        
        # if ray hits target, include the loops, too!
        visible_faces = self.rfcontext.visible_faces()
        hit_face = self.rfcontext.nearest2D_face(point=xy01, faces=visible_faces)
        if hit_face and hit_face.is_quad():
            print('hit quad')
            edges = hit_face.edges
            eseqs = [self.rfcontext.get_quadwalk_edgesequence(edge) for edge in edges]
            print(eseqs)
            
            eloops = [eseq.get_edges() for eseq in eseqs]
            cloops = [Contours_Loop(eseq.get_verts(), True) if eseq.is_loop() else None for eseq in eseqs]
            
            # loops = [self.rfcontext.get_edge_loop(edge) for edge in edges]
            # print(loops)
            # eloops = [loop for loop,_ in loops]
            # vloops = [(verts_of_loop(loop),is_loop) for loop,is_loop in loops]
            # cloops = [Contours_Loop(vloop, is_loop) if vloop and is_loop else None for vloop,is_loop in vloops]
            # use loop that is most parallel to cut
            norm = cl_cut.plane.n
            idx0 = max_index([abs(norm.dot(cloop.plane.n)) if cloop else -1 for cloop in cloops])
            idx1 = (idx0 + 2) % 4
            sel_edges |= set(eloops[idx0]) | set(eloops[idx1])
            print('%d %d' % (idx0,idx1))
        
        if connected:
            # find two closest selected loops, one on each side
            sel_loops = find_loops(sel_edges)
            sel_loop_planes = [loop_plane(loop) for loop in sel_loops]
            sel_loops_pos = sorted([
                (loop, plane.distance_to(p.o), len(loop), loop_length(loop))
                for loop,p in zip(sel_loops, sel_loop_planes) if plane.side(p.o) > 0
                ], key=lambda data:data[1])
            sel_loops_neg = sorted([
                (loop, plane.distance_to(p.o), len(loop), loop_length(loop))
                for loop,p in zip(sel_loops, sel_loop_planes) if plane.side(p.o) < 0
                ], key=lambda data:data[1])
            sel_loop_pos = next(iter(sel_loops_pos), None)
            sel_loop_neg = next(iter(sel_loops_neg), None)
            if sel_loop_pos and sel_loop_neg:
                if sel_loop_pos[2] != sel_loop_neg[2]:
                    # selected loops do not have same count of vertices
                    # choosing the closer loop
                    if sel_loop_pos[1] < sel_loop_neg[1]:
                        sel_loop_neg = None
                    else:
                        sel_loop_pos = None
        else:
            # find two closest selected strings, one on each side
            sel_strings = find_strings(sel_edges)
            sel_string_planes = [loop_plane(string) for string in sel_strings]
            sel_strings_pos = sorted([
                (string, plane.distance_to(p.o), len(string), string_length(string))
                for string,p in zip(sel_strings, sel_string_planes) if plane.side(p.o) > 0
                ], key=lambda data:data[1])
            sel_strings_neg = sorted([
                (string, plane.distance_to(p.o), len(string), string_length(string))
                for string,p in zip(sel_strings, sel_string_planes) if plane.side(p.o) < 0
                ], key=lambda data:data[1])
            sel_string_pos = next(iter(sel_strings_pos), None)
            sel_string_neg = next(iter(sel_strings_neg), None)
            if sel_string_pos and sel_string_neg:
                if sel_string_pos[2] != sel_string_neg[2]:
                    # selected strings do not have same count of vertices
                    # choosing the closer string
                    if sel_string_pos[1] < sel_string_neg[1]:
                        sel_string_neg = None
                    else:
                        sel_string_pos = None
            sel_loop_pos = None
            sel_loop_neg = None
        
        count = sel_loop_pos[2] if sel_loop_pos else sel_loop_neg[2] if sel_loop_neg else self.count
        cl_pos = Contours_Loop(sel_loop_pos[0], True) if sel_loop_pos else None
        cl_neg = Contours_Loop(sel_loop_neg[0], True) if sel_loop_neg else None
        if cl_pos: self.cuts += [cl_pos]
        if cl_neg: self.cuts += [cl_neg]
        
        if connected and sel_loop_pos and sel_loop_neg:
            edges_between = edges_between_loops(sel_loop_pos[0], sel_loop_neg[0])
            if edges_between:
                if False:
                    # ************************************
                    # ************************************
                    # TODO: DO **NOT** DELETE, BUT CUT IN!
                    # ************************************
                    # ************************************
                    edges_between = edges_between_loops(sel_loop_pos[0], sel_loop_neg[0])
                    self.rfcontext.delete_edges(edges_between)
                else:
                    # split all edges between pos and neg loops
                    verts = [edge.split()[1] for edge in edges_between]
                    edges = []
                    for v0,v1 in iter_pairs(verts, wrap=True):
                        # split face by adding edge between v0 and v1
                        bmf0 = next(iter(set(v0.link_faces) & set(v1.link_faces)))
                        bmf1 = bmf0.split(v0,v1)
                        bme01 = next(iter(set(bmf0.edges) & set(bmf1.edges)))
                        edges += [bme01]
                        # reposition v0
                        bmea = next(iter(set(bmf0.edges) & set(v0.link_edges) - set([bme01])))
                        bmeb = next(iter(set(bmf1.edges) & set(v0.link_edges) - set([bme01])))
                        va,vb = bmea.other_vert(v0),bmeb.other_vert(v0)
                        v0.co = cl_cut.get_closest_point(v0.co)
                    self.rfcontext.select(edges)
                    return
        
        if cl_pos and cl_neg:
            cl_neg.align_to(cl_pos)
            cl_cut.align_to(cl_pos)
            lc,lp,ln = cl_cut.length,cl_pos.length,cl_neg.length
            dists = [0.999 * lc * (d0/lp + d1/ln)/2 for d0,d1 in zip(cl_pos.dists,cl_neg.dists)]
        elif cl_pos:
            cl_cut.align_to(cl_pos)
            lc,lp = cl_cut.length,cl_pos.length
            dists = [0.999 * lc * (d/lp) for d in cl_pos.dists]
        elif cl_neg:
            cl_cut.align_to(cl_neg)
            lc,ln = cl_cut.length,cl_neg.length
            dists = [0.999 * lc * (d/ln) for d in cl_neg.dists]
        else:
            step_size = cl_cut.length / (count - (0 if connected else 1))
            dists = [0.999 * step_size for i in range(count)]
        
        # where new verts, edges, and faces are stored
        verts,edges,faces = [],[],[]

        if False and cl_pos and cl_neg:
            for p0,p1 in zip(cl_pos.pts, cl_neg.pts):
                p01 = p0 + (p1 - p0) / 2
                self.pts += [p01]
                pm = cl_cut.get_closest_point(p01)
                verts += [self.rfcontext.new_vert_point(pm)]
            for v0,v1 in iter_pairs(verts, connected):
                edges += [self.rfcontext.new_edge((v0, v1))]
        elif False and cl_pos and not cl_neg:
            for pt in cl_pos.get_points_relative_to(cl_cut):
                self.pts += [pt]
                pt = cl_cut.get_closest_point(pt)
                verts += [self.rfcontext.new_vert_point(pt)]
            for v0,v1 in iter_pairs(verts, connected):
                edges += [self.rfcontext.new_edge((v0, v1))]
        elif False and not cl_pos and cl_neg:
            for pt in cl_neg.get_points_relative_to(cl_cut):
                self.pts += [pt]
                pt = cl_cut.get_closest_point(pt)
                verts += [self.rfcontext.new_vert_point(pt)]
            for v0,v1 in iter_pairs(verts, connected):
                edges += [self.rfcontext.new_edge((v0, v1))]
        else:
            i,dist = 0,0
            for c0,c1 in cl_cut.iter_pts():
                d = (c1-c0).length
                while dist - d <= 0:
                    # create new vert between c0 and c1
                    p = c0 + (c1 - c0) * (dist / d)
                    self.pts += [p]
                    verts += [self.rfcontext.new_vert_point(p)]
                    i += 1
                    if i == len(dists): break
                    dist += dists[i]
                dist -= d
                if i == len(dists): break
            print('len(dists) == %d, len(verts) == %d' % (len(dists), len(verts)))
            #assert len(dists)==len(verts), '%d != %d' % (len(dists), len(verts))
            for v0,v1 in iter_pairs(verts, connected):
                edges += [self.rfcontext.new_edge((v0, v1))]

        if sel_loop_pos: self.rfcontext.bridge_vertloop(verts, cl_pos.verts, connected)
        if sel_loop_neg: self.rfcontext.bridge_vertloop(verts, cl_neg.verts, connected)

        self.rfcontext.select(verts + edges, supparts=False)
        self.update()


    def modal_main(self):
        if self.rfcontext.actions.pressed('select'):
            self.rfcontext.undo_push('select')
            edges = self.rfcontext.visible_edges()
            edge,_ = self.rfcontext.nearest2D_edge(edges=edges)
            if not edge:
                self.rfcontext.deselect_all()
                return
            self.rfcontext.select_edge_loop(edge, only=True)
            self.update()
            return

        if self.rfcontext.actions.pressed('select add'):
            self.rfcontext.undo_push('select add')
            edges = self.rfcontext.visible_edges()
            edge,_ = self.rfcontext.nearest2D_edge(edges=edges)
            if not edge: return
            self.rfcontext.select_edge_loop(edge, only=False)
            self.update()
            return

        if self.rfcontext.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'

        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            self.rfcontext.delete_selection()
            self.rfcontext.dirty()
            self.update()
            return

        if self.rfcontext.actions.pressed('increase count'):
            print('increasing count')
            return
        if self.rfcontext.actions.pressed('decrease count'):
            print('decreasing count')
            return

    def prep_move(self, bmverts=None):
        if not bmverts: bmverts = self.rfcontext.get_selected_verts()
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse

    @RFTool.dirty_when_done
    def modal_move(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_crawl_vert = self.rfcontext.set2D_crawl_vert
        for bmv,xy in self.bmverts:
            set2D_crawl_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    def draw_postview(self):
        if self.show_cut:
            self.drawing.line_width(1.0)
            
            bgl.glBegin(bgl.GL_LINES)
            bgl.glColor4f(1,1,0,1)
            for pt0,pt1 in iter_pairs(self.pts, self.connected):
                bgl.glVertex3f(*pt0)
                bgl.glVertex3f(*pt1)
            
            bgl.glColor4f(0,1,1,1)
            for pt0,pt1 in iter_pairs(self.cut_pts, self.connected):
                bgl.glVertex3f(*pt0)
                bgl.glVertex3f(*pt1)
            bgl.glEnd()

    def draw_postpixel(self):
        point_to_point2d = self.rfcontext.Point_to_Point2D
        up = self.rfcontext.Vec_up()
        size_to_size2D = self.rfcontext.size_to_size2D
        text_draw2D = self.rfcontext.drawing.text_draw2D
        self.rfcontext.drawing.text_size(12)

        for loop_data in self.loops_data:
            loop = loop_data['loop']
            radius = loop_data['radius']
            count = loop_data['count']
            plane = loop_data['plane']
            cl = loop_data['cl']
            cos = [point_to_point2d(vert.co) for vert in loop]
            cos = [co for co in cos if co]
            if cos:
                xy = max(cos, key=lambda co:co.y)
                xy.y += 10
                text_draw2D(count, xy, (1,1,0,1), dropshadow=(0,0,0,0.5))

            # self.drawing.line_width(2.0)
            # p0 = point_to_point2d(plane.o)
            # p1 = point_to_point2d(plane.o+plane.n*0.1)
            # if p0 and p1:
            #     bgl.glColor4f(1,1,0,0.5)
            #     draw2D_arrow(p0, p1)
            # p1 = point_to_point2d(plane.o+cl.up_dir*0.1)
            # if p0 and p1:
            #     bgl.glColor4f(1,0,1,0.5)
            #     draw2D_arrow(p0, p1)

        for cl in self.cuts:
            plane = cl.plane
            self.drawing.line_width(2.0)
            p0 = point_to_point2d(plane.o)
            p1 = point_to_point2d(plane.o+plane.n*0.1)
            if p0 and p1:
                bgl.glColor4f(1,1,0,0.5)
                draw2D_arrow(p0, p1)
            p1 = point_to_point2d(plane.o+cl.up_dir*0.1)
            if p0 and p1:
                bgl.glColor4f(1,0,1,0.5)
                draw2D_arrow(p0, p1)

        for string_data in self.strings_data:
            string = string_data['string']
            count = string_data['count']
            plane = string_data['plane']
            cos = [point_to_point2d(vert.co) for vert in string]
            cos = [co for co in cos if co]
            if cos:
                xy = max(cos, key=lambda co:co.y)
                xy.y += 10
                text_draw2D(count, xy, (1,1,0,1), dropshadow=(0,0,0,0.5))

            p0 = point_to_point2d(plane.o)
            p1 = point_to_point2d(plane.o+plane.n*0.1)
            if p0 and p1:
                d = (p0 - p1) * 0.25
                c = Vec2D((d.y,-d.x))
                p2 = p1 + d + c
                p3 = p1 + d - c
                
                self.drawing.line_width(2.0)
                bgl.glColor4f(1,1,0,0.5)
                bgl.glBegin(bgl.GL_LINE_STRIP)
                bgl.glVertex2f(*p0)
                bgl.glVertex2f(*p1)
                bgl.glVertex2f(*p2)
                bgl.glVertex2f(*p1)
                bgl.glVertex2f(*p3)
                bgl.glEnd()
