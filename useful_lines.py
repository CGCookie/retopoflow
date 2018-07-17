if False:
    r3d = next(s for s in next(a for a in bpy.data.screens['Default'].areas if a.type=='VIEW_3D').spaces if s.type=='VIEW_3D').region_3d
    next(s for s in next(a for a in bpy.data.screens['Default'].areas if a.type=='VIEW_3D').spaces if s.type=='VIEW_3D').region_3d.view_distance