import bpy
import bmesh
import math
import bgl
from .rftool import RFTool
from ..common.maths import Point,Point2D,Vec2D,Vec
from ..common.ui import UI_Image

@RFTool.action_call('polypen tool')
class RFTool_PolyPen(RFTool):
    ''' Called when RetopoFlow is started, but not necessarily when the tool is used '''
    def init(self):
        self.FSM['insert'] = self.modal_insert
        self.FSM['insert alt0'] = self.modal_insert
        self.FSM['move']  = self.modal_move

    def name(self): return "PolyPen"
    def icon(self): return "rf_polypen_icon"
    def description(self): return 'Insert vertices one at a time'

    def start(self):
        self.rfwidget.set_widget('default', color=(1.0, 1.0, 1.0))
        self.next_state = None
        
        self.target_version = None
        self.view_version = None

    def get_ui_icon(self):
        icon = [[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,3],[0,0,0,95],[0,0,0,195],[0,0,0,234],[0,0,0,249],[0,0,0,253],[0,0,0,253],[0,0,0,249],[0,0,0,234],[0,0,0,195],[0,0,0,94],[0,0,0,3],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,30],[0,0,0,196],[0,0,0,252],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,252],[0,0,0,195],[0,0,0,29],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,8],[0,0,0,177],[0,0,0,254],[0,0,0,255],[0,0,0,255],[12,12,12,255],[77,77,77,255],[164,164,164,255],[221,221,221,255],[240,240,240,255],[240,240,240,255],[221,221,221,255],[164,164,164,255],[78,78,78,255],[12,12,12,255],[0,0,0,255],[0,0,0,255],[0,0,0,254],[0,0,0,175],[0,0,0,7],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,33],[0,0,0,237],[0,0,0,255],[0,0,0,255],[36,36,36,255],[198,198,198,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[199,199,199,255],[37,37,37,255],[0,0,0,255],[0,0,0,255],[0,0,0,235],[0,0,0,32],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,67],[0,0,0,250],[0,0,0,255],[7,7,7,255],[176,176,176,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[175,175,175,255],[7,7,7,255],[0,0,0,255],[0,0,0,249],[0,0,0,66],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,31],[0,0,0,249],[0,0,0,255],[19,19,19,255],[190,186,184,255],[155,146,139,255],[153,143,136,255],[208,204,201,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[252,252,252,255],[224,224,224,255],[24,24,24,255],[0,0,0,255],[0,0,0,250],[0,0,0,35],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,9],[0,0,0,238],[0,0,0,255],[24,24,24,255],[154,145,138,255],[48,29,15,255],[46,27,13,255],[46,27,13,255],[47,28,14,255],[145,135,128,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[251,251,251,255],[249,249,249,255],[245,245,245,255],[234,234,234,255],[24,24,24,255],[0,0,0,255],[0,0,0,236],[0,0,0,8],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,181],[0,0,0,255],[8,8,8,255],[195,191,189,255],[48,29,15,255],[51,32,19,255],[138,127,119,255],[143,133,125,255],[53,34,21,255],[46,27,13,255],[202,197,193,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[250,250,250,255],[243,243,243,255],[238,238,238,255],[240,240,240,255],[236,236,236,255],[208,208,208,255],[7,7,7,255],[0,0,0,255],[0,0,0,178],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,36],[0,0,0,254],[0,0,0,255],[184,184,184,255],[154,145,138,255],[46,27,13,255],[139,129,121,255],[255,255,255,255],[255,255,255,255],[152,142,135,255],[46,27,13,255],[106,92,82,255],[236,234,233,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[251,251,251,255],[244,244,244,255],[237,237,237,255],[229,229,229,255],[224,224,224,255],[231,231,231,255],[226,226,226,255],[157,157,157,255],[0,0,0,255],[0,0,0,254],[0,0,0,34],[0,0,0,0]],[[0,0,0,0],[0,0,0,202],[0,0,0,255],[41,41,41,255],[255,255,255,255],[153,144,137,255],[46,27,13,255],[141,131,123,255],[255,255,255,255],[255,255,255,255],[153,144,137,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[80,65,53,255],[144,133,126,255],[199,194,190,255],[251,251,250,255],[255,255,255,255],[251,251,251,255],[244,244,244,255],[194,190,187,255],[132,122,115,255],[124,113,105,255],[162,156,152,255],[216,216,216,255],[222,222,222,255],[217,217,217,255],[37,37,37,255],[0,0,0,255],[0,0,0,200],[0,0,0,0]],[[0,0,0,5],[0,0,0,253],[0,0,0,255],[209,209,209,255],[255,255,255,255],[212,208,205,255],[48,29,15,255],[52,33,20,255],[144,133,126,255],[148,139,132,255],[54,36,22,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[62,44,31,255],[118,106,96,255],[173,166,161,255],[139,130,122,255],[48,29,15,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[101,88,79,255],[211,211,211,255],[211,211,211,255],[166,166,166,255],[0,0,0,255],[0,0,0,253],[0,0,0,5]],[[0,0,0,108],[0,0,0,255],[17,17,17,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[152,142,135,255],[47,28,14,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[140,130,122,255],[229,226,225,255],[169,161,155,255],[109,96,86,255],[55,37,23,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[46,28,13,255],[50,31,18,255],[146,136,129,255],[160,151,145,255],[61,43,30,255],[46,27,13,255],[142,135,130,255],[206,206,206,255],[200,200,200,255],[15,15,15,255],[0,0,0,255],[0,0,0,104]],[[0,0,0,202],[0,0,0,255],[88,88,88,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[169,162,156,255],[46,27,13,255],[46,27,13,255],[179,173,167,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[249,249,248,255],[196,191,188,255],[135,124,116,255],[75,59,47,255],[46,27,13,255],[46,27,13,255],[131,120,112,255],[255,255,255,255],[255,255,255,255],[170,162,156,255],[46,27,13,255],[96,85,76,255],[198,198,198,255],[195,195,195,255],[68,68,68,255],[0,0,0,255],[0,0,0,201]],[[0,0,0,238],[0,0,0,255],[180,180,180,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[203,199,195,255],[46,27,13,255],[46,27,13,255],[223,220,218,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[253,253,253,255],[245,245,245,255],[237,237,237,255],[230,230,230,255],[136,127,120,255],[46,27,13,255],[123,111,102,255],[255,255,255,255],[255,255,255,255],[162,153,147,255],[46,27,13,255],[97,85,77,255],[184,184,184,255],[188,188,188,255],[125,125,125,255],[0,0,0,255],[0,0,0,237]],[[0,0,0,251],[0,0,0,255],[239,239,239,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[203,198,194,255],[46,27,13,255],[46,27,13,255],[225,222,220,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[253,253,253,255],[245,245,245,255],[238,238,238,255],[231,231,231,255],[224,224,224,255],[192,190,188,255],[52,33,20,255],[48,29,15,255],[125,114,105,255],[139,129,121,255],[53,35,22,255],[46,27,13,255],[130,124,120,255],[172,172,172,255],[182,182,182,255],[159,159,159,255],[0,0,0,255],[0,0,0,250]],[[0,0,0,254],[0,0,0,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[201,196,192,255],[46,27,13,255],[46,27,13,255],[225,223,221,255],[255,255,255,255],[255,255,255,255],[253,253,253,255],[245,245,245,255],[238,238,238,255],[231,231,231,255],[224,224,224,255],[217,217,217,255],[209,209,209,255],[142,134,129,255],[50,31,18,255],[46,27,13,255],[46,27,13,255],[47,28,14,255],[100,90,82,255],[158,158,158,255],[163,163,163,255],[176,176,176,255],[168,168,168,255],[0,0,0,255],[0,0,0,254]],[[0,0,0,254],[0,0,0,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[200,195,191,255],[46,27,13,255],[46,27,13,255],[227,225,223,255],[255,255,255,255],[253,253,253,255],[246,246,246,255],[238,238,238,255],[231,231,231,255],[224,224,224,255],[203,203,203,255],[181,181,181,255],[175,175,175,255],[184,184,184,255],[167,164,162,255],[123,115,109,255],[113,105,98,255],[141,137,134,255],[158,158,158,255],[151,151,151,255],[155,155,155,255],[170,170,170,255],[161,161,161,255],[0,0,0,255],[0,0,0,253]],[[0,0,0,250],[0,0,0,255],[253,253,253,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[199,194,190,255],[46,27,13,255],[46,27,13,255],[228,225,224,255],[253,253,253,255],[246,246,246,255],[239,239,239,255],[232,232,232,255],[225,225,225,255],[178,178,178,255],[7,7,7,255],[10,8,5,255],[10,8,5,255],[11,11,11,255],[160,160,160,255],[173,173,173,255],[166,166,166,255],[159,159,159,255],[152,152,152,255],[145,145,145,255],[152,152,152,255],[162,162,162,255],[138,138,138,255],[0,0,0,255],[0,0,0,250]],[[0,0,0,237],[0,0,0,255],[197,197,197,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[198,193,190,255],[46,27,13,255],[46,27,13,255],[227,224,223,255],[246,246,246,255],[239,239,239,255],[232,232,232,255],[225,225,225,255],[217,217,217,255],[128,128,128,255],[0,0,0,255],[229,178,104,255],[237,184,108,255],[0,0,0,255],[120,120,120,255],[166,166,166,255],[159,159,159,255],[152,152,152,255],[145,145,145,255],[137,137,137,255],[149,149,149,255],[156,156,156,255],[101,101,101,255],[0,0,0,255],[0,0,0,235]],[[0,0,0,197],[0,0,0,255],[82,82,82,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[160,150,144,255],[46,27,13,255],[46,27,13,255],[173,166,161,255],[240,240,240,255],[232,232,232,255],[225,225,225,255],[217,217,217,255],[210,210,210,255],[123,123,123,255],[0,0,0,255],[235,176,101,255],[243,182,104,255],[0,0,0,255],[115,115,115,255],[159,159,159,255],[152,152,152,255],[145,145,145,255],[137,137,137,255],[130,130,130,255],[152,152,152,255],[149,149,149,255],[53,53,53,255],[0,0,0,255],[0,0,0,194]],[[0,0,0,97],[0,0,0,255],[14,14,14,255],[255,255,255,255],[255,255,255,255],[255,255,255,255],[145,135,128,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[46,27,13,255],[123,112,104,255],[225,225,225,255],[179,179,179,255],[127,127,127,255],[122,122,122,255],[71,71,71,255],[0,0,0,255],[233,168,94,255],[240,173,96,255],[0,0,0,255],[66,66,66,255],[92,92,92,255],[89,89,89,255],[121,121,121,255],[130,130,130,255],[130,130,130,255],[149,149,149,255],[142,142,142,255],[11,11,11,255],[0,0,0,255],[0,0,0,92]],[[0,0,0,3],[0,0,0,252],[0,0,0,255],[200,200,200,255],[255,255,255,255],[208,204,201,255],[47,28,14,255],[53,35,22,255],[151,141,134,255],[156,147,140,255],[57,39,25,255],[46,27,13,255],[158,153,149,255],[7,7,7,255],[11,7,4,255],[16,11,6,255],[16,11,6,255],[16,11,6,255],[232,161,86,255],[237,164,88,255],[16,11,6,255],[16,11,6,255],[16,11,6,255],[10,7,4,255],[18,18,18,255],[124,124,124,255],[140,140,140,255],[142,142,142,255],[104,104,104,255],[0,0,0,255],[0,0,0,252],[0,0,0,2]],[[0,0,0,0],[0,0,0,192],[0,0,0,255],[34,34,34,255],[255,255,255,255],[152,142,135,255],[46,27,13,255],[144,134,127,255],[255,255,255,255],[255,255,255,255],[157,148,141,255],[46,27,13,255],[101,91,85,255],[3,2,1,255],[234,156,81,255],[241,160,83,255],[240,160,83,255],[240,160,83,255],[240,160,83,255],[240,160,83,255],[240,159,83,255],[240,159,83,255],[240,159,83,255],[227,150,77,255],[2,2,2,255],[126,126,126,255],[142,142,142,255],[134,134,134,255],[23,23,23,255],[0,0,0,255],[0,0,0,190],[0,0,0,0]],[[0,0,0,0],[0,0,0,25],[0,0,0,253],[0,0,0,255],[172,172,172,255],[156,147,140,255],[46,27,13,255],[136,125,117,255],[255,255,255,255],[255,255,255,255],[148,139,132,255],[46,27,13,255],[102,93,86,255],[3,2,1,255],[211,134,67,255],[221,141,70,255],[221,141,70,255],[221,141,70,255],[236,150,74,255],[237,151,74,255],[221,140,69,255],[221,140,69,255],[221,140,69,255],[204,129,64,255],[2,2,2,255],[139,139,139,255],[134,134,134,255],[87,87,87,255],[0,0,0,255],[0,0,0,253],[0,0,0,23],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,167],[0,0,0,255],[5,5,5,255],[187,184,181,255],[49,31,17,255],[49,31,17,255],[130,119,111,255],[135,124,116,255],[51,32,19,255],[47,28,14,255],[154,149,146,255],[13,13,13,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[223,134,63,255],[226,136,64,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[26,26,26,255],[134,134,134,255],[110,110,110,255],[4,4,4,255],[0,0,0,255],[0,0,0,164],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,4],[0,0,0,229],[0,0,0,255],[18,18,18,255],[151,143,137,255],[49,31,17,255],[46,27,13,255],[46,27,13,255],[48,29,15,255],[123,113,106,255],[190,190,190,255],[164,164,164,255],[129,129,129,255],[124,124,124,255],[72,72,72,255],[0,0,0,255],[221,126,55,255],[223,127,56,255],[0,0,0,255],[63,63,63,255],[93,93,93,255],[103,103,103,255],[127,127,127,255],[122,122,122,255],[13,13,13,255],[0,0,0,255],[0,0,0,228],[0,0,0,3],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,21],[0,0,0,245],[0,0,0,255],[14,14,14,255],[173,170,167,255],[148,140,134,255],[143,134,128,255],[184,180,177,255],[198,198,198,255],[184,184,184,255],[176,176,176,255],[169,169,169,255],[161,161,161,255],[94,94,94,255],[0,0,0,255],[218,118,48,255],[219,118,48,255],[0,0,0,255],[97,97,97,255],[142,142,142,255],[135,135,135,255],[109,109,109,255],[12,12,12,255],[0,0,0,255],[0,0,0,247],[0,0,0,24],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,51],[0,0,0,245],[0,0,0,255],[4,4,4,255],[140,140,140,255],[219,219,219,255],[214,214,214,255],[209,209,209,255],[202,202,202,255],[188,188,188,255],[176,176,176,255],[166,166,166,255],[97,97,97,255],[0,0,0,255],[194,99,36,255],[199,101,37,255],[0,0,0,255],[100,100,100,255],[136,136,136,255],[81,81,81,255],[3,3,3,255],[0,0,0,255],[0,0,0,245],[0,0,0,49],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,20],[0,0,0,225],[0,0,0,255],[0,0,0,255],[23,23,23,255],[148,148,148,255],[202,202,202,255],[197,197,197,255],[191,191,191,255],[185,185,185,255],[178,178,178,255],[147,147,147,255],[14,14,14,255],[0,0,0,255],[0,0,0,255],[17,17,17,255],[88,88,88,255],[17,17,17,255],[0,0,0,255],[0,0,0,255],[0,0,0,223],[0,0,0,19],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,2],[0,0,0,152],[0,0,0,251],[0,0,0,255],[0,0,0,255],[6,6,6,255],[52,52,52,255],[108,108,108,255],[135,135,135,255],[147,147,147,255],[141,141,141,255],[116,116,116,255],[82,82,82,255],[39,39,39,255],[5,5,5,255],[0,0,0,255],[0,0,0,255],[0,0,0,251],[0,0,0,149],[0,0,0,1],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,15],[0,0,0,175],[0,0,0,247],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,255],[0,0,0,247],[0,0,0,174],[0,0,0,14],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]],[[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,64],[0,0,0,174],[0,0,0,221],[0,0,0,240],[0,0,0,248],[0,0,0,248],[0,0,0,240],[0,0,0,221],[0,0,0,174],[0,0,0,62],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]]]
        self.ui_icon = UI_Image(icon)
        self.ui_icon.set_size(16, 16)
        return self.ui_icon
    
    def update(self):
        # selection has changed, undo/redo was called, etc.
        self.target_version = None
        self.set_next_state()
    
    def set_next_state(self):
        # TODO: optimize this!!!
        target_version = self.rfcontext.get_target_version()
        view_version = self.rfcontext.get_view_version()
        
        recompute = False
        recompute |= self.target_version != target_version
        recompute |= self.view_version != view_version
        
        if recompute:
            # print('recompute! ' + str(view_version))
            
            self.target_version = target_version
            self.view_version = view_version
            
            # get visible geometry
            self.vis_verts = self.rfcontext.visible_verts()
            self.vis_edges = self.rfcontext.visible_edges(verts=self.vis_verts)
            self.vis_faces = self.rfcontext.visible_faces(verts=self.vis_verts)
            
            # get selected geometry
            self.sel_verts = self.rfcontext.rftarget.get_selected_verts()
            self.sel_edges = self.rfcontext.rftarget.get_selected_edges()
            self.sel_faces = self.rfcontext.rftarget.get_selected_faces()
            num_verts = len(self.sel_verts)
            num_edges = len(self.sel_edges)
            num_faces = len(self.sel_faces)
            
            # determine next state based on current selection
            if num_verts == 1 and num_edges == 0 and num_faces == 0:
                self.next_state = 'vert-edge'
            elif num_edges == 1 and num_faces == 0:
                self.next_state = 'edge-face'
            elif num_edges == 2 and num_faces == 0:
                self.next_state = 'edges-face'
            elif num_verts == 3 and num_edges == 3 and num_faces == 1:
                self.next_state = 'tri-quad'
            else:
                self.next_state = 'new vertex'
        
        # get visible geometry near mouse
        nearby_verts = self.rfcontext.nearest2D_verts(verts=self.vis_verts)
        nearby_edges = self.rfcontext.nearest2D_edges(edges=self.vis_edges)
        nearby_faces = [] # TODO: get nearby faces
        
        # get hover geometry in sorted order
        self.hover_verts = [v for v,_ in sorted(nearby_verts, key=lambda vd:vd[1])]
        self.hover_edges = [e for e,_ in sorted(nearby_edges, key=lambda ed:ed[1])]
        self.hover_faces = [f for f,_ in sorted(nearby_faces, key=lambda fd:fd[1])]
        
        # get nearest geometry
        self.nearest_vert = next(iter(self.hover_verts), None)
        self.nearest_edge = next(iter(self.hover_edges), None)
        self.nearest_face = next(iter(self.hover_faces), None)
        

    def modal_main(self):
        self.set_next_state()

        if self.rfcontext.actions.pressed('insert'):
            return 'insert'

        if self.rfcontext.actions.pressed('insert alt0'):
            return 'insert alt0'

        if self.rfcontext.actions.pressed(['select','select add'], unpress=False):
            sel_only = self.rfcontext.actions.pressed('select')
            self.rfcontext.actions.unpress()
            
            if sel_only: self.rfcontext.undo_push('select')
            else: self.rfcontext.undo_push('select add')
            
            sel = self.nearest_vert or self.nearest_edge or self.nearest_face
            self.rfcontext.select(sel, only=sel_only)
            
            if not sel_only: return     # do not move selection if adding
            
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = ['select']
            self.move_cancelled = 'cancel no select'
            self.rfcontext.undo_push('move single')
            
            return 'move'

        if self.rfcontext.actions.pressed('grab'):
            self.rfcontext.undo_push('move grabbed')
            self.prep_move()
            self.move_done_pressed = 'confirm'
            self.move_done_released = None
            self.move_cancelled = 'cancel'
            return 'move'

        # if self.rfcontext.actions.pressed('SPACE'):
        #     bmes = self.sel_edges
        #     bmvs = []
        #     for bme in bmes:
        #         _,bmv = bme.split()
        #         bmvs.append(bmv)
        #     self.rfcontext.select(bmvs)
        #     self.rfcontext.dirty()
        
        if self.rfcontext.actions.pressed('delete'):
            self.rfcontext.undo_push('delete')
            self.rfcontext.delete_selection()
            self.rfcontext.dirty()
            return

    def prep_move(self, bmverts=None):
        if not bmverts: bmverts = self.sel_verts
        self.bmverts = [(bmv, self.rfcontext.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        self.mousedown = self.rfcontext.actions.mouse

    @RFTool.dirty_when_done
    def modal_insert(self):
        self.rfcontext.undo_push('insert')

        self.move_done_pressed = None
        self.move_done_released = ['insert', 'insert alt0']
        self.move_cancelled = 'cancel'

        if self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl and not self.next_state in ['new vertex', 'vert-edge']:
            self.next_state = 'vert-edge'
            nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts)
            self.rfcontext.select(nearest_vert)

        sel_verts = self.sel_verts
        sel_edges = self.sel_edges
        sel_faces = self.sel_faces

        if self.next_state == 'vert-edge':
            bmv0 = next(iter(sel_verts))
            if not self.rfcontext.actions.shift and self.rfcontext.actions.ctrl:
                bmv1 = self.rfcontext.new2D_vert_mouse()
                if not bmv1:
                    self.rfcontext.undo_cancel()
                    return 'main'
                bme = self.rfcontext.new_edge((bmv0, bmv1))
                self.rfcontext.select(bme)
            elif self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl:
                if self.nearest_vert:
                    bmv1 = self.nearest_vert
                else:
                    bmv1 = self.rfcontext.new2D_vert_mouse()
                    if not bmv1:
                        self.rfcontext.undo_cancel()
                        return 'main'
                bme = self.rfcontext.new_edge((bmv0, bmv1))
                self.rfcontext.select(bmv1)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                print('Could not insert: ' + str(bmv1.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            return 'move'

        if self.next_state == 'edge-face' or self.next_state == 'edges-face':
            if self.next_state == 'edges-face':
                bme0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                bmv0,bmv1 = bme0.verts

            if self.next_state == 'edge-face':
                bme = next(iter(self.sel_edges))
                bmv0,bmv1 = bme.verts

            if self.nearest_vert and not self.nearest_vert.select:
                bmv2 = self.nearest_vert
                bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2])
                self.rfcontext.clean_duplicate_bmedges(bmv2)
                # else:
                #     self.rfcontext.undo_cancel()
                #     return 'main'
            else:
                bmv2 = self.rfcontext.new2D_vert_mouse()
                if not bmv2:
                    self.rfcontext.undo_cancel()
                    return 'main'
                bmf = self.rfcontext.new_face([bmv0, bmv1, bmv2])

            self.rfcontext.select(bmf)
            self.mousedown = self.rfcontext.actions.mousedown
            xy = self.rfcontext.Point_to_Point2D(bmv2.co)
            if not xy:
                print('Could not insert: ' + str(bmv2.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv2, xy)]
            return 'move'

        if self.next_state == 'tri-quad':
            hit_pos = self.rfcontext.actions.hit_pos
            if not hit_pos:
                self.rfcontext.undo_cancel()
                return 'main'
            if not self.sel_edges:
                return 'main'
            bme0,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
            bmv0,bmv2 = bme0.verts
            bme1,bmv1 = bme0.split()
            self.rfcontext.select(bmv1.link_edges)
            if self.nearest_vert and not self.nearest_vert.select:
                self.nearest_vert.merge(bmv1)
                bmv1 = self.nearest_vert
                self.rfcontext.clean_duplicate_bmedges(bmv1)
                for bme in bmv1.link_edges: bme.select &= len(bme.link_faces)==1
                # else:
                #     self.rfcontext.undo_cancel()
                #     return 'main'
            else:
                bmv1.co = hit_pos
            self.mousedown = self.rfcontext.actions.mousedown
            self.rfcontext.select(bmv1, only=False)
            xy = self.rfcontext.Point_to_Point2D(bmv1.co)
            if not xy:
                print('Could not insert: ' + str(bmv3.co))
                self.rfcontext.undo_cancel()
                return 'main'
            self.bmverts = [(bmv1, xy)]
            return 'move'

        bmv = self.rfcontext.new2D_vert_mouse()
        if not bmv:
            self.rfcontext.undo_cancel()
            return 'main'
        self.rfcontext.select(bmv)
        self.mousedown = self.rfcontext.actions.mousedown
        xy = self.rfcontext.Point_to_Point2D(bmv.co)
        if not xy:
            print('Could not insert: ' + str(bmv.co))
            self.rfcontext.undo_cancel()
            return 'main'
        self.bmverts = [(bmv, xy)]
        return 'move'

    @RFTool.dirty_when_done
    def modal_move(self):
        released = self.rfcontext.actions.released
        if self.move_done_pressed and self.rfcontext.actions.pressed(self.move_done_pressed):
            return 'main'
        if self.move_done_released and all(released(item) for item in self.move_done_released):
            return 'main'
        if self.move_cancelled and self.rfcontext.actions.pressed('cancel'):
            self.rfcontext.undo_cancel()
            return 'main'

        delta = Vec2D(self.rfcontext.actions.mouse - self.mousedown)
        set2D_vert = self.rfcontext.set2D_vert
        for bmv,xy in self.bmverts:
            set2D_vert(bmv, xy + delta)
        self.rfcontext.update_verts_faces(v for v,_ in self.bmverts)

    def draw_lines(self, coords):
        # 2d lines
        self.drawing.line_width(2.0)
        bgl.glDisable(bgl.GL_CULL_FACE)
        bgl.glDepthMask(bgl.GL_FALSE)

        # draw above
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glColor4f(1,1,1,0.5)
        if len(coords) == 1:
            bgl.glBegin(bgl.GL_POINTS)
        if len(coords) == 2:
            bgl.glBegin(bgl.GL_LINES)
        elif len(coords) == 3:
            bgl.glBegin(bgl.GL_TRIANGLES)
        else:
            bgl.glBegin(bgl.GL_QUADS)
        for co in coords:
            bgl.glVertex3f(co.x, co.y, co.z)
        bgl.glEnd()

        # draw below
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glColor4f(1,1,1,0.1)
        if len(coords) == 1:
            bgl.glBegin(bgl.GL_POINTS)
        elif len(coords) == 2:
            bgl.glBegin(bgl.GL_LINES)
        elif len(coords) == 3:
            bgl.glBegin(bgl.GL_TRIANGLES)
        else:
            bgl.glBegin(bgl.GL_QUADS)
        for co in coords:
            bgl.glVertex3f(co.x, co.y, co.z)
        bgl.glEnd()

        bgl.glEnable(bgl.GL_CULL_FACE)
        bgl.glDepthMask(bgl.GL_TRUE)
        bgl.glDepthFunc(bgl.GL_LEQUAL)


    def draw_postview(self):
        if self.rfcontext.actions.shift or self.rfcontext.actions.ctrl:
            hit_pos = self.rfcontext.actions.hit_pos
            if not hit_pos: return
            
            self.set_next_state()

            if self.next_state == 'new vertex':
                return

            if self.next_state == 'vert-edge':
                sel_verts = self.sel_verts
                bmv0 = next(iter(sel_verts))
                if self.nearest_vert:
                    p0 = self.nearest_vert.co
                else:
                    p0 = hit_pos
                self.draw_lines([bmv0.co, p0])
                return

            if self.rfcontext.actions.shift and not self.rfcontext.actions.ctrl:
                if self.next_state in ['edge-face', 'edges-face', 'tri-quad']:
                    nearest_vert,_ = self.rfcontext.nearest2D_vert(verts=self.sel_verts)
                    self.draw_lines([nearest_vert.co, hit_pos])

            elif not self.rfcontext.actions.shift and self.rfcontext.actions.ctrl:
                if self.next_state == 'edge-face':
                    sel_edges = self.sel_edges
                    e1 = next(iter(sel_edges))
                    bmv1,bmv2 = e1.verts
                    if self.nearest_vert and not self.nearest_vert.select:
                        p0 = self.nearest_vert.co
                    else:
                        p0 = hit_pos
                    self.draw_lines([p0, bmv1.co, bmv2.co])
                    return

                if self.next_state == 'edges-face' or self.next_state == 'tri-quad':
                    e1,_ = self.rfcontext.nearest2D_edge(edges=self.sel_edges)
                    bmv1,bmv2 = e1.verts
                    if self.nearest_vert and not self.nearest_vert.select:
                        p0 = self.nearest_vert.co
                    else:
                        p0 = hit_pos
                    self.draw_lines([p0, bmv1.co, bmv2.co])
                    return
