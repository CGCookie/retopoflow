import bpy
# from ...common_utilities import showErrorMessage

class Logger:
    @classmethod
    def add(cls, line):
        if 'RetopoFlow_log' not in bpy.data.texts:
            # create a log file for error writing
            bpy.ops.text.new()
            bpy.data.texts[-1].name = 'RetopoFlow_log'
        
        divider = '=' * 80
        
        log = bpy.data.texts['RetopoFlow_log']
        log.write("\n\n" + divider + "\n" + line)
    
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

def showErrorMessage(message, wrap=80):
    if not message: return
    lines = message.splitlines()
    if wrap > 0:
        nlines = []
        for line in lines:
            spc = len(line) - len(line.lstrip())
            while len(line) > wrap:
                i = line.rfind(' ',0,wrap)
                if i == -1:
                    nlines += [line[:wrap]]
                    line = line[wrap:]
                else:
                    nlines += [line[:i]]
                    line = line[i+1:]
                if line:
                    line = ' '*spc + line
            nlines += [line]
        lines = nlines
    def draw(self,context):
        for line in lines:
            self.layout.label(line)
    bpy.context.window_manager.popup_menu(draw, title="Error Message", icon="ERROR")
    return

