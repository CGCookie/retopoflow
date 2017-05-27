import bpy
from mathutils import Matrix

from .rfcontext import RFContext

class RFMode_Context:
    def init_context(self):
        ctx = bpy.context
        
        newtarobj = False
        if ctx.active_object:
            newtarobj = True
        elif type(ctx.active_object.data) is not bpy.types.Mesh:
            newtarobj = True
        elif not ctx.active_object.select:
            newtarobj = True
        
        if newtarobj:
            # generate new target object
            tar_name = self.obj_orig.name + "_polystrips"
            tar_eme = bpy.data.meshes.new(tar_name)
            tar_obj = bpy.data.objects.new(tar_name, tar_eme)
            tar_obj.matrix_world = Matrix.Translation(ctx.scene.cursor_location)
            tar_obj.layers = list(ctx.scene.layers)
            #tar_obj.show_x_ray = get_settings().use_x_ray
            ctx.scene.objects.link(tar_obj)
            ctx.scene.objects.active = tar_obj
            tar_obj.select = True
        
        self.rfctx = RFContext()        # current context
