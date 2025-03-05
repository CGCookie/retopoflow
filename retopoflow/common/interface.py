import bpy

def draw_line_separator(layout):
    if bpy.app.version >= (4,2,0):
        return layout.separator(type='LINE')
    else: 
        return layout.separator()
    

def update_toolbar(self, context):
    from ..rftool_base import RFTool_Base
    RFTool_Base.unregister_all()
    RFTool_Base.register_all()