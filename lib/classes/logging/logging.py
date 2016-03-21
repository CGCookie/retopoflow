import bpy
#from ...common_utilities import showErrorMessage

def getLog():
    if 'RetopoFlow_log' not in bpy.data.texts:
        # log file does not exist; create!
        bpy.ops.text.new()
        bpy.data.texts[-1].name = 'RetopoFlow_log'
    return bpy.data.texts['RetopoFlow_log']

def logPrint(s):
    log = getLog()
    log.current_line_index = len(log.lines) - 1     # move cursor to last line
    log.write('')                                   # position cursor at end of line
    log.write('%s\n' % s)

class OpenLog(bpy.types.Operator):
    """Open log text files in new window"""
    bl_idname = "wm.open_log"
    bl_label = "Open Log in Text Editor"

    def execute(self, context):

        self.openTextFile('RetopoFlow_log')

        return {'FINISHED'}

    def openTextFile(self, filename):

        # play it safe!
        if filename not in bpy.data.texts:
            #showErrorMessage('Log file not found')
            return

        # duplicate the current area then change it to a text edito
        area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        win = bpy.context.window_manager.windows[-1]
        area = win.screen.areas[-1]
        area.type = 'TEXT_EDITOR'

        # load the text file into the correct space
        for space in area.spaces:
            if space.type == 'TEXT_EDITOR':
                space.text = bpy.data.texts[filename]


