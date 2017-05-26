import bpy
from ...common_utilities import showErrorMessage

class Logger:
    @classmethod
    def add(cls, line):
        if 'RetopoFlow_log' not in bpy.data.texts:
            # create a log file for error writing
            bpy.ops.text.new()
            bpy.data.texts[-1].name = 'RetopoFlow_log'
        
        # TODO: TERRIBLY INEFFICIENT!!
        log = bpy.data.texts['RetopoFlow_log']
        log.from_string(log.as_string() + "\n" + line)
    
    @classmethod
    def openTextFile(cls):
        if 'RetopoFlow_log' not in bpy.data.texts:
            showErrorMessage('Log file not found')
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

