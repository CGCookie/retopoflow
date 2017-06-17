from bpy.types import Operator
from .rfmode import RFMode

class RFMode_Operator(Operator):
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.retopoflow"
    bl_label       = "Retopoflow"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    def invoke(self, context, event):
        self.rfmode = RFMode()
        return self.rfmode.invoke(context, event)
    
    def modal(self, context, event):
        return self.rfmode.modal(context, event)
