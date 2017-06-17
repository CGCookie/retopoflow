import bpy
from mathutils import Matrix

from .rfcontext import RFContext

class RFMode_Context:
    def context_start(self):
        tar_object = bpy.context.active_object
        if not tar_object or type(tar_object) is not bpy.types.Object or type(tar_object.data) is not bpy.types.Mesh:
            # generate new target object
            tar_name = "RetopoFlow"
            tar_location = bpy.context.scene.cursor_location
            tar_editmesh = bpy.data.meshes.new(tar_name)
            tar_object = bpy.data.objects.new(tar_name, tar_editmesh)
            tar_object.matrix_world = Matrix.Translation(tar_location)  # place new object at scene's cursor location
            tar_object.layers = list(bpy.context.scene.layers)          # set object on visible layers
            #tar_object.show_x_ray = get_settings().use_x_ray
            bpy.context.scene.objects.link(tar_object)
            bpy.context.scene.objects.active = tar_object
            tar_object.select = True
        
        self.rfctx = RFContext()
        self.rfctx.start()
    
    def context_end(self):
        self.rfctx.end()




