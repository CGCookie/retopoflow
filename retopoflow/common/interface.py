import bpy

def line_separator(layout):
    if bpy.app.version >= (4,2,0):
        return layout.separator(type='LINE')
    else: 
        return layout.separator()