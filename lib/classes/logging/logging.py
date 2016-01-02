import bpy

class OpenLog(bpy.types.Operator):
    """Open log text files in new window"""
    bl_idname = "wm.open_log"
    bl_label = "Open Log in Text Editor"

    def execute(self, context):
        
        self.openTextFile()

        return {'FINISHED'}

    def openTextFile(self):
        area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        bpy.context.screen.areas[-1].type = 'TEXT_EDITOR'

    # test call
    #bpy.ops.object.simple_operator()
