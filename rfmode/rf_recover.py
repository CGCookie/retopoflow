import bpy
from bpy.types import Operator
import os
from ..lib.common_utilities import showErrorMessage

class RFRecover(Operator):
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.rf_recover"
    bl_label       = "Recover Auto Save"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    rf_icon = None
    
    @classmethod
    def filepath(cls):
        tempdir = bpy.context.user_preferences.filepaths.temporary_directory
        filepath = os.path.join(tempdir, 'retopoflow_backup.blend')
        return filepath
    
    @classmethod
    def recover(cls):
        bpy.ops.wm.open_mainfile(filepath=cls.filepath())
        
        if 'RetopoFlow_Rotate' in bpy.data.objects:
            # need to remove empty object for rotation
            bpy.data.objects.remove(bpy.data.objects['RetopoFlow_Rotate'], do_unlink=True)
        
        tar_object = next(o for o in bpy.data.objects if o.select)
        bpy.context.scene.objects.active = tar_object
        tar_object.hide = False
        
        #showErrorMessage('Auto save recovered.\nDisplay settings may not be correct.')
    
    @classmethod
    def poll(cls, context):
        return os.path.exists(cls.filepath())
    
    def invoke(self, context, event):
        self.recover()
        return set()
    
