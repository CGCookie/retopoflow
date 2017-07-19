import bpy
from bpy.types import Operator
import os
import json

from ..lib.common_utilities import showErrorMessage

class RFRecover(Operator):
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.rf_recover"
    bl_label       = "Recover Auto Save"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    rf_icon = 'rf_recover_icon'
    
    @classmethod
    def filepath(cls):
        tempdir = bpy.context.user_preferences.filepaths.temporary_directory
        filepath = os.path.join(tempdir, 'retopoflow_backup.blend')
        return filepath
    
    @classmethod
    def save_window_state(cls):
        data = {
            'data_wm': {},
            'selected': [o.name for o in bpy.data.objects if o.select],
            'mode': bpy.context.mode,
            'region overlap': False,    # TODO
            'region toolshelf': False,  # TODO
            'region properties': False, # TODO
            }
        for wm in bpy.data.window_managers:
            data_wm = []
            for win in wm.windows:
                data_win = []
                for area in win.screen.areas:
                    data_area = []
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            data_space = {}
                            if space.type == 'VIEW_3D':
                                data_space = {
                                    'show_only_render': space.show_only_render,
                                    'show_manipulator': space.show_manipulator,
                                }
                            data_area.append(data_space)
                    data_win.append(data_area)
                data_wm.append(data_win)
            data['data_wm'][wm.name] = data_wm
        
        tempdir = bpy.context.user_preferences.filepaths.temporary_directory
        filepath = os.path.join(tempdir, 'retopoflow_backup.state')
        open(filepath, 'wt').write(json.dumps(data))
    
    @classmethod
    def restore_window_state(cls):
        tempdir = bpy.context.user_preferences.filepaths.temporary_directory
        filepath = os.path.join(tempdir, 'retopoflow_backup.state')
        if not os.path.exists(filepath): return
        data = json.loads(open(filepath, 'rt').read())
        for wm in bpy.data.window_managers:
            data_wm = data['data_wm'][wm.name]
            for win,data_win in zip(wm.windows, data_wm):
                for area,data_area in zip(win.screen.areas, data_win):
                    if area.type != 'VIEW_3D': continue
                    for space,data_space in zip(area.spaces, data_area):
                        if space.type != 'VIEW_3D': continue
                        space.show_only_render = data_space['show_only_render']
                        space.show_manipulator = data_space['show_manipulator']
        for oname in data['selected']:
            if oname in bpy.data.objects:
                bpy.data.objects[oname].select = True
    
    @classmethod
    def recover(cls):
        bpy.ops.wm.open_mainfile(filepath=cls.filepath())
        
        if 'RetopoFlow_Rotate' in bpy.data.objects:
            # need to remove empty object for rotation
            bpy.data.objects.remove(bpy.data.objects['RetopoFlow_Rotate'], do_unlink=True)
        
        tar_object = next(o for o in bpy.data.objects if o.select)
        bpy.context.scene.objects.active = tar_object
        tar_object.hide = False
        
        cls.restore_window_state()
        
        #showErrorMessage('Auto save recovered.\nDisplay settings may not be correct.')
    
    @classmethod
    def poll(cls, context):
        return os.path.exists(cls.filepath())
    
    def invoke(self, context, event):
        self.recover()
        return {'FINISHED'}
    

class RFRecover_Clear(Operator):
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.rf_recover_clear"
    bl_label       = "Clear Auto Save"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    rf_icon = None
    
    @classmethod
    def poll(cls, context):
        return os.path.exists(RFRecover.filepath())
    
    def invoke(self, context, event):
        filepath = RFRecover.filepath()
        os.remove(filepath)
        return {'FINISHED'}
