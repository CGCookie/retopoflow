import bpy
from ..lib.common_utilities import showErrorMessage
from ..options import options, help_quickstart

class OpenQuickStart(bpy.types.Operator):
    """Open log text files in new window"""
    bl_idname = "wm.open_quickstart"
    bl_label = "Quick Start Guide"
    
    @classmethod
    def poll(cls, context): return True

    def execute(self, context):
        self.openTextFile()
        return {'FINISHED'}

    def openTextFile(self):

        # play it safe!
        if options['quickstart_filename'] not in bpy.data.texts:
            # create a log file for error writing
            bpy.data.texts.new(options['quickstart_filename'])
        
        # restore data, just in case
        txt = bpy.data.texts[options['quickstart_filename']]
        txt.from_string(help_quickstart)
        txt.current_line_index = 0

        # duplicate the current area then change it to a text edito
        area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        win = bpy.context.window_manager.windows[-1]
        area = win.screen.areas[-1]
        area.type = 'TEXT_EDITOR'

        # load the text file into the correct space
        for space in area.spaces:
            if space.type == 'TEXT_EDITOR':
                space.text = txt
                space.show_word_wrap = True
                space.top = 0

