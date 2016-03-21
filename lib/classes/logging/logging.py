import os
import bpy
#from ...common_utilities import showErrorMessage

def logPath():
    # TODO: what if we don't have write privileges?
    pathLog = os.path.abspath(bpy.data.filepath)
    if pathLog.endswith('.blend'):
        pathLog = '%s.RetopoFlow_log' % pathLog
    else:
        pathLog = '%s/RetopoFlow_log' % pathLog
    if not os.path.exists(pathLog):
        # touch file
        with open(pathLog, 'wt') as f:
            f.write('')
    return pathLog

def logPrint(s):
    with open(logPath(), 'at') as log:
        log.write('%s\n' % s)

class OpenLog(bpy.types.Operator):
    """Open log text files in new window"""
    bl_idname = "wm.open_log"
    bl_label = "Open Log in Text Editor"

    def execute(self, context):
        self.openTextFile(logPath())
        return {'FINISHED'}

    def openTextFile(self, filename):
        if 'RetopoFlow_log' in bpy.data.texts:
            # clear out previous log text block
            bpy.data.texts.remove(bpy.data.texts['RetopoFlow_log'])
        # create new text block by opening log file and rename text block to RetopoFlow_log
        before = set(bpy.data.texts.keys())
        bpy.ops.text.open(filepath=logPath())
        after = set(bpy.data.texts.keys())
        logname = (after - before).pop()
        bpy.data.texts[logname].name = 'RetopoFlow_log'
        log = bpy.data.texts['RetopoFlow_log']
        ## TODO: these two lines don't work correctly (new window does not refresh properly... why?)
        # log.current_line_index = len(log.lines) - 1     # move cursor to last line
        # log.write('')                                   # move cursor to end of line

        # duplicate the current area then change it to a text editor
        area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
        win = bpy.context.window_manager.windows[-1]
        area = win.screen.areas[-1]
        area.type = 'TEXT_EDITOR'

        # load the text file into the correct space
        found = False
        for space in area.spaces:
            if space.type == 'TEXT_EDITOR':
                space.text = log
                found = True
        if not found:
            # TODO: fix!
            pass


