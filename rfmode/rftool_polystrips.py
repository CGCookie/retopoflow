import bgl
import bpy
import math
from mathutils import Vector, Matrix
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.bezier import CubicBezierSpline, CubicBezier
from mathutils.geometry import intersect_point_tri_2d
from ..common.ui import UI_Image

from ..lib.common_utilities import showErrorMessage
from ..lib.classes.logging.logger import Logger

from .rftool_polystrips_utils import *

@RFTool.action_call('polystrips tool')
class RFTool_PolyStrips(RFTool):
    def init(self):
        self.FSM['move bmf'] = self.modal_move_bmf
        self.FSM['manip bezier'] = self.modal_manip_bezier
        self.FSM['rotate outer'] = self.modal_rotate_outer
        
        self.point_size = 10
    
    def name(self): return "PolyStrips"
    def icon(self): return "rf_polystrips_icon"
    def description(self): return 'Strips of quads made easy'
    
    def start(self):
        self.mode = 'main'
        self.rfwidget.set_widget('brush stroke', color=(1.0, 0.5, 0.5))
        self.rfwidget.set_stroke_callback(self.stroke)
        self.hovering = []
        self.hovering_strips = set()
        self.sel_cbpts = []
        self.strokes = []
        self.stroke_cbs = CubicBezierSpline()
        self.update()
    
    def get_ui_icon(self):
        icon = [[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,3],[0,0,0,60],[0,0,0,137],[0,0,0,182],[0,0,0,206],[0,0,0,230],[0,0,0,230],[0,0,0,206],[0,0,0,182],[0,0,0,137],[0,0,0,60],[0,0,0,3],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,17],[0,0,0,137],[0,0,0,236],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[4,4,4,255],[4,4,4,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,236],[0,0,0,137],[0,0,0,17],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,5],[0,0,0,119],[1,1,1,240],[0,0,0,255],[2,2,2,255],[58,58,58,255],[151,151,151,255],[217,217,217,255],[239,239,239,255],[254,254,254,255],[254,254,254,255],[240,240,240,255],[218,218,218,255],[156,156,156,255],[62,62,62,255],[2,2,2,255],[0,0,0,255],[1,1,1,240],[0,0,0,119],[0,0,0,5],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,21],[0,0,0,193],[0,0,0,255],[4,4,4,255],[105,105,105,255],[235,235,235,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[237,237,237,255],[113,113,113,255],[4,4,4,255],[0,0,0,255],[0,0,0,193],[0,0,0,21],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[37,21,11,192],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[103,91,83,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[254,254,254,255],[218,215,213,255],[169,162,157,255],[108,97,90,255],[41,26,16,255],[38,22,10,255],[39,23,11,255],[37,21,11,191],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,22],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[219,216,214,255],[116,105,97,255],[53,38,26,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[0,0,0,22],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[0,0,0,6],[0,0,0,197],[40,23,11,255],[40,23,11,255],[252,194,113,255],[252,194,113,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[59,39,21,255],[107,79,48,255],[157,122,81,255],[207,167,116,255],[241,198,139,255],[40,23,11,255],[40,23,11,255],[0,0,0,197],[0,0,0,6],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[0,0,0,124],[0,0,0,255],[40,23,11,255],[40,23,11,255],[252,194,113,255],[252,194,113,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[41,24,11,255],[124,89,52,255],[221,172,114,255],[250,199,134,255],[251,202,138,255],[252,205,141,255],[253,205,142,255],[254,208,144,255],[40,23,11,255],[40,23,11,255],[0,0,0,255],[0,0,0,124],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[0,0,0,21],[0,0,0,242],[3,3,3,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[194,189,186,255],[49,33,22,255],[40,23,11,255],[52,32,18,255],[40,23,11,255],[73,49,29,255],[230,179,120,255],[250,193,123,255],[249,189,115,255],[250,189,111,255],[251,191,111,255],[253,195,114,255],[40,23,11,255],[40,23,11,255],[3,3,3,255],[0,0,0,242],[0,0,0,21],[255,255,255,0]],[[255,255,255,0],[0,0,0,143],[0,0,0,255],[103,103,103,255],[103,91,83,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[103,91,83,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[240,239,238,255],[54,38,27,255],[40,23,11,255],[119,83,49,255],[225,169,109,255],[73,49,28,255],[40,23,11,255],[73,47,25,255],[228,163,91,255],[248,182,103,255],[250,187,107,255],[244,186,108,255],[244,188,109,255],[40,23,11,255],[40,23,11,255],[92,92,92,255],[0,0,0,255],[0,0,0,143],[255,255,255,0]],[[0,0,0,2],[0,0,0,234],[4,4,4,255],[237,237,237,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[132,122,115,255],[40,23,11,255],[92,60,33,255],[247,185,117,255],[246,185,116,255],[225,155,84,255],[72,46,23,255],[40,23,11,255],[81,54,29,255],[132,94,52,255],[75,51,27,255],[41,24,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[188,188,188,255],[4,4,4,255],[0,0,0,234],[0,0,0,2]],[[0,0,0,61],[0,0,0,255],[64,64,64,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[223,220,219,255],[43,27,15,255],[43,25,12,255],[209,153,94,255],[247,185,117,255],[243,169,93,255],[243,166,88,255],[225,156,84,255],[78,51,26,255],[49,30,15,255],[40,23,11,255],[40,23,11,255],[44,27,16,255],[46,30,19,255],[42,25,13,255],[90,78,70,255],[200,200,200,255],[63,63,63,255],[0,0,0,255],[0,0,0,61]],[[0,0,0,141],[0,0,0,255],[152,152,152,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[159,151,146,255],[40,23,11,255],[114,74,39,255],[246,182,114,255],[246,178,108,255],[241,162,85,255],[243,166,88,255],[171,117,63,255],[43,26,13,255],[40,23,11,255],[76,63,54,255],[163,159,157,255],[189,189,188,255],[186,186,186,255],[179,179,179,255],[198,198,198,255],[194,194,194,255],[122,122,122,255],[0,0,0,255],[0,0,0,141]],[[0,0,0,184],[0,0,0,255],[216,216,216,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[123,113,106,255],[40,23,11,255],[159,108,61,255],[246,182,114,255],[243,169,97,255],[241,162,85,255],[231,157,83,255],[55,34,17,255],[40,23,11,255],[114,104,97,255],[198,197,197,255],[194,194,194,255],[187,187,187,255],[180,180,180,255],[173,173,173,255],[183,183,183,255],[188,188,188,255],[153,153,153,255],[0,0,0,255],[0,0,0,184]],[[0,0,0,208],[0,0,0,255],[239,239,239,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[87,74,65,255],[40,23,11,255],[191,134,80,255],[246,182,114,255],[242,164,88,255],[241,162,85,255],[135,90,47,255],[40,23,11,255],[83,70,61,255],[201,201,201,255],[194,194,194,255],[187,187,187,255],[180,180,180,255],[173,173,173,255],[165,165,165,255],[173,173,173,255],[182,182,182,255],[162,162,162,255],[0,0,0,255],[0,0,0,208]],[[0,0,0,231],[5,5,5,255],[254,254,254,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[45,29,17,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[169,166,163,255],[194,194,194,255],[187,187,187,255],[180,180,180,255],[173,173,173,255],[165,165,165,255],[158,158,158,255],[163,163,163,255],[176,176,176,255],[167,167,167,255],[5,5,5,255],[0,0,0,231]],[[0,0,0,228],[3,3,3,255],[254,254,254,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[211,208,205,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[44,27,13,255],[195,195,195,255],[188,188,188,255],[181,181,181,255],[173,173,173,255],[166,166,166,255],[158,158,158,255],[151,151,151,255],[155,155,155,255],[169,169,169,255],[160,160,160,255],[3,3,3,255],[0,0,0,228]],[[0,0,0,204],[0,0,0,255],[237,237,237,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[97,81,69,255],[40,23,11,255],[125,84,48,255],[238,174,107,255],[233,160,87,255],[233,154,78,255],[190,127,66,255],[40,23,11,255],[76,57,43,255],[188,188,188,255],[181,181,181,255],[173,173,173,255],[166,166,166,255],[159,159,159,255],[152,152,152,255],[145,145,145,255],[152,152,152,255],[162,162,162,255],[142,142,142,255],[0,0,0,255],[0,0,0,204]],[[0,0,0,180],[0,0,0,255],[213,213,213,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[252,251,251,255],[143,132,125,255],[40,23,11,255],[52,31,15,255],[228,165,100,255],[245,178,109,255],[238,154,78,255],[240,158,81,255],[162,107,56,255],[40,23,11,255],[96,83,72,255],[181,181,181,255],[173,173,173,255],[166,166,166,255],[159,159,159,255],[152,152,152,255],[145,145,145,255],[137,137,137,255],[149,149,149,255],[156,156,156,255],[126,126,126,255],[0,0,0,255],[0,0,0,180]],[[0,0,0,129],[0,0,0,255],[146,146,146,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[253,253,253,255],[211,208,205,255],[88,75,66,255],[40,23,11,255],[42,24,12,255],[166,116,66,255],[244,177,107,255],[241,167,95,255],[238,153,77,255],[240,158,81,255],[115,74,39,255],[40,23,11,255],[114,106,100,255],[174,174,174,255],[167,167,167,255],[160,160,160,255],[152,152,152,255],[145,145,145,255],[137,137,137,255],[130,130,130,255],[151,151,151,255],[149,149,149,255],[97,97,97,255],[0,0,0,255],[0,0,0,129]],[[0,0,0,49],[0,0,0,255],[53,53,53,255],[255,255,255,255],[112,100,92,255],[49,32,21,255],[54,36,24,255],[48,30,18,255],[40,23,11,255],[40,23,11,255],[47,27,12,255],[80,53,28,255],[227,163,96,255],[241,166,96,255],[237,150,73,255],[238,153,77,255],[207,136,70,255],[43,25,12,255],[42,25,13,255],[152,150,148,255],[167,167,167,255],[160,160,160,255],[153,153,153,255],[145,145,145,255],[137,137,137,255],[130,130,130,255],[130,130,130,255],[149,149,149,255],[142,142,142,255],[48,48,48,255],[0,0,0,255],[0,0,0,49]],[[255,255,255,0],[0,0,0,225],[1,1,1,255],[227,227,227,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[70,41,19,255],[124,79,41,255],[83,54,29,255],[40,23,11,255],[76,48,25,255],[219,135,66,255],[237,149,73,255],[238,153,77,255],[99,62,32,255],[40,23,11,255],[95,85,78,255],[167,167,167,255],[160,160,160,255],[153,153,153,255],[145,145,145,255],[138,138,138,255],[131,131,131,255],[125,125,125,255],[143,143,143,255],[142,142,142,255],[120,120,120,255],[1,1,1,255],[0,0,0,225],[255,255,255,0]],[[255,255,255,0],[0,0,0,123],[0,0,0,255],[84,84,84,255],[40,23,11,255],[40,23,11,255],[224,148,78,255],[227,152,83,255],[241,163,90,255],[242,167,94,255],[225,155,88,255],[75,46,23,255],[40,23,11,255],[74,45,21,255],[218,137,67,255],[121,76,38,255],[40,23,11,255],[49,33,22,255],[158,157,156,255],[161,161,161,255],[153,153,153,255],[145,145,145,255],[73,62,54,255],[43,26,14,255],[43,25,14,255],[43,26,14,255],[43,26,15,255],[70,58,49,255],[57,57,57,255],[0,0,0,255],[0,0,0,123],[255,255,255,0]],[[255,255,255,0],[0,0,0,10],[0,0,0,230],[0,0,0,255],[40,23,11,255],[40,23,11,255],[236,149,74,255],[237,150,76,255],[236,147,73,255],[235,143,69,255],[232,136,62,255],[216,128,58,255],[74,44,21,255],[40,23,11,255],[54,31,16,255],[40,23,11,255],[44,27,15,255],[128,122,118,255],[161,161,161,255],[153,153,153,255],[146,146,146,255],[139,139,139,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[0,0,0,255],[0,0,0,230],[0,0,0,10],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[0,0,0,101],[0,0,0,255],[40,23,11,255],[40,23,11,255],[225,116,44,255],[227,120,47,255],[228,124,51,255],[230,129,55,255],[231,133,59,255],[211,124,56,255],[126,75,36,255],[41,24,11,255],[40,23,11,255],[41,24,12,255],[42,25,14,255],[43,26,15,255],[43,26,15,255],[43,26,15,255],[43,26,15,255],[43,26,15,255],[40,23,11,255],[40,23,11,255],[220,116,45,255],[220,116,45,255],[40,23,11,255],[40,23,11,255],[0,0,0,255],[0,0,0,101],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[0,0,0,1],[0,0,0,169],[40,23,11,255],[40,23,11,255],[214,110,42,255],[194,103,41,255],[151,82,34,255],[109,62,27,255],[63,38,20,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[226,119,46,255],[226,119,46,255],[40,23,11,255],[40,23,11,255],[0,0,0,169],[0,0,0,1],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,9],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[46,29,18,255],[85,73,65,255],[148,145,142,255],[165,165,164,255],[157,157,156,255],[150,150,149,255],[143,143,142,255],[137,137,136,255],[130,130,129,255],[129,129,128,255],[140,140,139,255],[40,23,11,255],[40,23,11,255],[45,25,12,255],[45,25,12,255],[40,23,11,255],[40,23,11,255],[0,0,0,9],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[39,22,11,189],[40,23,11,255],[38,22,10,255],[38,23,13,255],[84,72,64,255],[140,132,127,255],[178,175,172,255],[205,204,204,255],[202,202,202,255],[188,188,188,255],[176,176,176,255],[166,166,166,255],[159,159,159,255],[155,155,155,255],[152,152,152,255],[153,153,153,255],[150,150,150,255],[143,143,143,255],[67,55,46,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[40,23,11,255],[38,22,11,193],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,9],[0,0,0,159],[0,0,0,255],[0,0,0,255],[68,68,68,255],[179,179,179,255],[203,203,203,255],[196,196,196,255],[191,191,191,255],[184,184,184,255],[178,178,178,255],[171,171,171,255],[164,164,164,255],[157,157,157,255],[150,150,150,255],[143,143,143,255],[117,117,117,255],[54,54,54,255],[1,1,0,255],[1,1,0,255],[2,2,0,162],[17,17,0,15],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,86],[0,0,0,219],[0,0,0,255],[0,0,0,255],[36,36,36,255],[108,108,108,255],[144,144,144,255],[146,146,146,255],[153,153,153,255],[148,148,148,255],[127,127,127,255],[117,117,117,255],[88,88,88,255],[32,32,32,255],[0,0,0,255],[0,0,0,255],[0,0,0,219],[0,0,0,86],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,5],[0,0,0,104],[0,0,0,201],[0,0,0,254],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,254],[0,0,0,201],[0,0,0,104],[0,0,0,5],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]],[[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[0,0,0,26],[0,0,0,103],[0,0,0,144],[0,0,0,170],[0,0,0,197],[0,0,0,197],[0,0,0,170],[0,0,0,144],[0,0,0,103],[0,0,0,26],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0],[255,255,255,0]]]
        self.ui_icon = UI_Image(icon)
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def update(self):
        self.strips = []
        
        # get selected quads
        bmquads = set(bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4)
        if not bmquads: return
        
        # find knots
        knots = set()
        for bmf in bmquads:
            edge0,edge1,edge2,edge3 = [is_edge(bme, bmquads) for bme in bmf.edges]
            if edge0 and edge2 and not (edge1 or edge3): continue
            if edge1 and edge3 and not (edge0 or edge2): continue
            knots.add(bmf)
        
        # find strips between knots
        touched = set()
        self.strips = []
        for bmf0 in knots:
            bme0,bme1,bme2,bme3 = bmf0.edges
            edge0,edge1,edge2,edge3 = [is_edge(bme, bmquads) for bme in bmf0.edges]
            
            def add_strip(bme):
                strip = crawl_strip(bmf0, bme, bmquads, knots)
                bmf1 = strip[-1]
                if len(strip) > 1 and hash_face_pair(bmf0, bmf1) not in touched:
                    touched.add(hash_face_pair(bmf0,bmf1))
                    touched.add(hash_face_pair(bmf1,bmf0))
                    self.strips.append(RFTool_PolyStrips_Strip(strip))
            
            if not edge0: add_strip(bme0)
            if not edge1: add_strip(bme1)
            if not edge2: add_strip(bme2)
            if not edge3: add_strip(bme3)
        
        self.update_strip_viz()
    
    def update_strip_viz(self):
        self.strip_pts = [[cb.eval(i/10) for i in range(10+1)] for strip in self.strips for cb in strip]
    
    @RFTool.dirty_when_done
    def stroke(self):
        radius = self.rfwidget.get_scaled_size()
        stroke2D = list(self.rfwidget.stroke2D)
        bmfaces = []
        all_bmfaces = []
        
        if len(stroke2D) < 10: return
        
        self.rfcontext.undo_push('stroke')
        
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        vis_faces = self.rfcontext.visible_faces()
        vis_faces2D = [(bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]) for bmf in vis_faces]
        
        def get_state(point:Point2D):
            nonlocal vis_faces2D
            point3D = self.rfcontext.get_point3D(point)
            if not point3D: return ('off', None)
            for bmf,cos in vis_faces2D:
                co0 = cos[0]
                for co1,co2 in zip(cos[1:-1],cos[2:]):
                    if intersect_point_tri_2d(point, co0, co1, co2):
                        return ('tar', bmf)
            return ('src', None)
        def next_state():
            nonlocal stroke2D
            pt = stroke2D.pop()
            state,face = get_state(pt)
            return (pt,state,face)
        
        def merge(p0, p1, q0, q1):
            nonlocal bmfaces
            dp = p1.co - p0.co
            dq = q1.co - q0.co
            if dp.dot(dq) < 0: p0,p1 = p1,p0
            q0.merge(p0)
            q1.merge(p1)
            mapping = self.rfcontext.clean_duplicate_bmedges(q0)
            bmfaces = [mapping.get(f, f) for f in bmfaces]
        
        def insert(cb, bme_start, bme_end):
            nonlocal bmfaces
            if bme_start and bme_start == bme_end: return
            if bme_start and bme_end:
                bmv0,bmv1 = bme_start.verts
                bmv2,bmv3 = bme_end.verts
                if bmv0 == bmv2 or bmv0 == bmv3 or bmv1 == bmv2 or bmv1 == bmv3: return
            
            length = cb.approximate_length_uniform(lambda p,q: (p-q).length)
            steps = math.floor((length / radius) / 2)
            
            if steps == 0:
                if bme_start == None or bme_end == None: return
                bmv0,bmv1 = bme_start.verts
                bmv2,bmv3 = bme_end.verts
                dir01,dir23 = bmv1.co - bmv0.co, bmv3.co - bmv2.co
                if dir01.dot(dir23) > 0:
                    bmfaces.append(self.rfcontext.new_face([bmv0,bmv1,bmv3,bmv2]))
                else:
                    bmfaces.append(self.rfcontext.new_face([bmv0,bmv1,bmv2,bmv3]))
                return
            
            intervals = [(i/steps)*length for i in range(steps+1)]
            ts = cb.approximate_ts_at_intervals_uniform(intervals, lambda p,q: (p-q).length)
            
            fp0,fp1 = None,None
            lp2,lp3 = None,None
            p0,p1,p2,p3 = None,None,None,None
            for t in ts:
                center,normal,_,_ = self.rfcontext.nearest_sources_Point(cb.eval(t))
                direction = cb.eval_derivative(t).normalized()
                cross = normal.cross(direction).normalized()
                back,front = center - direction * radius, center + direction * radius
                loc0,loc1 = back  - cross * radius, back  + cross * radius
                loc2,loc3 = front + cross * radius, front - cross * radius
                if p0 is None:
                    p0 = self.rfcontext.new_vert_point(loc0)
                    p1 = self.rfcontext.new_vert_point(loc1)
                else:
                    p0.co = (Vector(p0.co) + Vector(loc0)) * 0.5
                    p1.co = (Vector(p1.co) + Vector(loc1)) * 0.5
                p2 = self.rfcontext.new_vert_point(loc2)
                p3 = self.rfcontext.new_vert_point(loc3)
                bmfaces.append(self.rfcontext.new_face([p0,p1,p2,p3]))
                if not fp0: fp0,fp1 = p0,p1
                p0,p1 = p3,p2
            lp2,lp3 = p2,p3
            
            if bme_start:
                bmv0,bmv1 = bme_start.verts
                merge(fp0, fp1, bmv0, bmv1)
            if bme_end:
                bmv0,bmv1 = bme_end.verts
                merge(lp2, lp3, bmv0, bmv1)
        
        def stroke_to_quads(stroke):
            nonlocal bmfaces, all_bmfaces, vis_faces2D
            cbs = CubicBezierSpline.create_from_points([stroke], radius/20.0)
            nearest_edges_Point = self.rfcontext.nearest_edges_Point
            
            for cb in cbs:
                # pre-pass curve to see if we cross existing geo
                p0,_,_,p3 = cb.points()
                bmes0 = nearest_edges_Point(p0, radius)
                bmes3 = nearest_edges_Point(p3, radius)
                #print('close to %d and %d' % (len(bmes0), len(bmes3)))
                bme0 = None if not bmes0 else sorted(bmes0, key=lambda d:d[1])[0][0]
                bme3 = None if not bmes3 else sorted(bmes3, key=lambda d:d[1])[0][0]
                
                # post-pass to create
                bmfaces = []
                insert(cb, bme0, bme3)
                all_bmfaces += bmfaces
                vis_faces2D += [(bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]) for bmf in bmfaces]
            
            self.stroke_cbs = self.stroke_cbs + cbs
        
        def process_stroke():
            # scan through all the points of stroke
            # if stroke goes off source or crosses a visible face, stop and insert,
            # then skip ahead until stroke goes back on source
            
            self.stroke_cbs = CubicBezierSpline()
            
            strokes = []
            pt,state,face0 = next_state()
            while stroke2D:
                if state == 'src':
                    stroke = []
                    while stroke2D and state == 'src':
                        stroke.append(self.rfcontext.get_point3D(pt))
                        pt,state,face1 = next_state()
                    if len(stroke) > 10:
                        stroke_to_quads(stroke)
                        strokes.append(stroke)
                    face0 = face1
                elif state in {'tar', 'off'}:
                    pt,state,face0 = next_state()
                else:
                    assert False, 'Unexpected state'
            self.strokes = strokes
            
            map(self.rfcontext.update_face_normal, all_bmfaces)
            self.rfcontext.select(all_bmfaces)
        
        try:
            process_stroke()
        except Exception as e:
            Logger.add('Unhandled exception raised while processing stroke\n' + str(e))
            showErrorMessage('Unhandled exception raised while processing stroke.\nPlease try again.')
    
    def modal_main(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        mouse = self.rfcontext.actions.mouse
        self.hovering.clear()
        self.hovering_strips.clear()
        for strip in self.strips:
            for cb in strip:
                for cbpt in cb:
                    v = Point_to_Point2D(cbpt)
                    if v is None: continue
                    if (mouse - v).length < self.point_size:
                        self.hovering.append(cbpt)
                        self.hovering_strips.add(strip)
        if self.hovering:
            self.rfwidget.set_widget('move')
        else:
            self.rfwidget.set_widget('brush stroke')
        
        if self.hovering and self.rfcontext.actions.pressed('action'):
            return self.prep_manip()
        
        if self.hovering and self.rfcontext.actions.pressed('alt action'):
            return self.prep_rotate()
        
        if self.rfcontext.actions.using('select'):
            if self.rfcontext.actions.pressed('select'):
                self.rfcontext.undo_push('select')
                self.rfcontext.deselect_all()
            bmf = self.rfcontext.nearest2D_face_mouse()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
        
        if self.rfcontext.actions.using('select add'):
            if self.rfcontext.actions.pressed('select add'):
                self.rfcontext.undo_push('select add')
            bmf = self.rfcontext.nearest2D_face_mouse()
            if bmf and not bmf.select:
                self.rfcontext.select(bmf, supparts=False, only=False)
            return
        
        if self.rfcontext.actions.pressed('grab'):
            return self.prep_move()
        
        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            faces = self.rfcontext.get_selected_faces()
            self.rfcontext.delete_faces(faces)
            self.rfcontext.deselect_all()
            self.rfcontext.dirty()
            self.update()
            return
    
    def prep_rotate(self):
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        inner,outer = None,None
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.points()
                if p1 in self.hovering: inner,outer = p1,p0
                if p2 in self.hovering: inner,outer = p2,p3
        if not inner or not outer: return ''
        self.sel_cbpts = []
        self.mod_strips = set()
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.points()
                if (outer - p0).length < 0.01:
                    self.sel_cbpts += [(p1, Point(p1), Point_to_Point2D(p1))]
                    self.mod_strips.add(strip)
                if (outer - p3).length < 0.01:
                    self.sel_cbpts += [(p2, Point(p2), Point_to_Point2D(p2))]
                    self.mod_strips.add(strip)
        self.rotate_about = Point_to_Point2D(outer)
        if not self.rotate_about: return ''
        
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('move')
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'alt action'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('rotate outer')
        return 'rotate outer'
    
    @RFTool.dirty_when_done
    def modal_rotate_outer(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfwidget.set_widget('brush stroke')
            self.rfcontext.undo_cancel()
            return 'main'
        
        prev_diff = self.mousedown - self.rotate_about
        prev_rot = math.atan2(prev_diff.x, prev_diff.y)
        cur_diff = self.rfcontext.actions.mouse - self.rotate_about
        cur_rot = math.atan2(cur_diff.x, cur_diff.y)
        angle = prev_rot - cur_rot
        
        rot = Matrix.Rotation(angle, 2)
        
        for cbpt,oco,oco2D in self.sel_cbpts:
            xy = rot * (oco2D - self.rotate_about) + self.rotate_about
            xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(xy)
            if xyz: cbpt.xyz = xyz
        
        for strip in self.mod_strips:
            strip.update(self.rfcontext.nearest_sources_Point, self.rfcontext.raycast_sources_Point, self.rfcontext.update_face_normal)
        
        self.update_strip_viz()
    
    def prep_manip(self):
        cbpts = list(self.hovering)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.points()
                if p0 in cbpts and p1 not in cbpts: cbpts.append(p1)
                if p3 in cbpts and p2 not in cbpts: cbpts.append(p2)
        self.sel_cbpts = [(cbpt, Point(cbpt), self.rfcontext.Point_to_Point2D(cbpt)) for cbpt in cbpts]
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('move')
        self.move_done_pressed = 'confirm'
        self.move_done_released = 'action'
        self.move_cancelled = 'cancel'
        self.rfcontext.undo_push('manipulate bezier')
        return 'manip bezier'
    
    @RFTool.dirty_when_done
    def modal_manip_bezier(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfwidget.set_widget('brush stroke')
            self.rfcontext.undo_cancel()
            return 'main'
        
        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        up,rt = self.rfcontext.Vec_up(),self.rfcontext.Vec_right()
        for cbpt,oco,oco2D in self.sel_cbpts:
            xyz,_,_,_ = self.rfcontext.raycast_sources_Point2D(oco2D + delta)
            #xyz = oco + delta.x * rt - delta.y * up
            if xyz: cbpt.xyz = xyz
        
        for strip in self.hovering_strips:
            strip.update(self.rfcontext.nearest_sources_Point, self.rfcontext.raycast_sources_Point, self.rfcontext.update_face_normal)
        
        self.update_strip_viz()
    
    def prep_move(self, bmfaces=None):
        if not bmfaces: bmfaces = self.rfcontext.get_selected_faces()
        bmverts = set(bmv for bmf in bmfaces for bmv in bmf.verts)
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse
        self.rfwidget.set_widget('default')
        self.rfcontext.undo_push('move grabbed')
        self.move_done_pressed = 'confirm'
        self.move_done_released = None
        self.move_cancelled = 'cancel'
        return 'move bmf'
    
    @RFTool.dirty_when_done
    def modal_move_bmf(self):
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_done_released and self.rfcontext.actions.released(self.move_done_released):
            self.rfwidget.set_widget('brush stroke')
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfwidget.set_widget('brush stroke')
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            set2D_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)
        self.update()
        
    
    def draw_postview(self):
        self.draw_spline()
        
        if False:
            stroke_pts = [[cb.eval(i / 5) for i in range(5+1)] for cb in self.stroke_cbs]
            stroke_der = [[cb.eval_derivative(i / 5) for i in range(5+1)] for cb in self.stroke_cbs]
            self.drawing.line_width(1.0)
            bgl.glColor4f(1,1,1,0.5)
            for pts in stroke_pts:
                bgl.glBegin(bgl.GL_LINE_STRIP)
                for pt in pts:
                    bgl.glVertex3f(*pt)
                bgl.glEnd()
            bgl.glColor4f(0,0,1,0.5)
            bgl.glBegin(bgl.GL_LINES)
            for pts,ders in zip(stroke_pts,stroke_der):
                for pt,der in zip(pts,ders):
                    bgl.glVertex3f(*pt)
                    ptder = pt + der.normalized() * 0.3
                    bgl.glVertex3f(*ptder)
            bgl.glEnd()
        
    
    def draw_spline(self):
        if not self.strips: return
        
        bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit 
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
        bgl.glEnable(bgl.GL_DEPTH_TEST)

        ######################################
        # draw in front of geometry
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        
        # draw control points
        self.drawing.point_size(self.point_size)
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_POINTS)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw outer-inner lines
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,0.5,0.5,0.4)
        bgl.glBegin(bgl.GL_LINES)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw curve
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,1,1,0.5)
        bgl.glBegin(bgl.GL_LINES)
        for pts in self.strip_pts:
            v0 = None
            for v1 in pts:
                if v0:
                    bgl.glVertex3f(*v0)
                    bgl.glVertex3f(*v1)
                v0 = v1
        bgl.glEnd()
        
        ######################################
        # draw behind geometry
        bgl.glDepthFunc(bgl.GL_GREATER)
        
        # draw control points
        self.drawing.point_size(self.point_size)
        bgl.glColor4f(1,1,1,0.25)
        bgl.glBegin(bgl.GL_POINTS)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw outer-inner lines
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,0.5,0.5,0.2)
        bgl.glBegin(bgl.GL_LINES)
        for strip in self.strips:
            for cb in strip:
                p0,p1,p2,p3 = cb.p0,cb.p1,cb.p2,cb.p3
                bgl.glVertex3f(*p0)
                bgl.glVertex3f(*p1)
                bgl.glVertex3f(*p2)
                bgl.glVertex3f(*p3)
        bgl.glEnd()
        
        # draw curve
        self.drawing.line_width(2.0)
        bgl.glColor4f(1,1,1,0.25)
        bgl.glBegin(bgl.GL_LINES)
        for pts in self.strip_pts:
            v0 = None
            for v1 in pts:
                if v0:
                    bgl.glVertex3f(*v0)
                    bgl.glVertex3f(*v1)
                v0 = v1
        bgl.glEnd()
        
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthMask(bgl.GL_TRUE)
    
    def draw_postpixel(self):
        pass
    
