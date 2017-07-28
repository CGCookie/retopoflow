import bpy
import bgl
import blf
import time

from .rftool import RFTool

from ..common.maths import Point, Point2D
from ..common.ui import Drawing
from ..common.ui import (
    UI_WindowManager,
    UI_Button,
    UI_Options,
    UI_Checkbox,
    UI_Label,
    UI_Spacer,
    UI_Collapsible,
    UI_IntValue,
    )


class RFContext_Drawing:
    def set_symmetry(self, axis, enable):
        if enable: self.rftarget.enable_symmetry(axis)
        else: self.rftarget.disable_symmetry(axis)
        self.rftarget.dirty()
    def get_symmetry(self, axis): return self.rftarget.has_symmetry(axis)
    
    def _init_drawing(self):
        self.drawing = Drawing.get_instance()
        self.window_manager = UI_WindowManager()
        
        def options_callback(lbl):
            for ids,rft in RFTool.get_tools():
                if rft.bl_label == lbl:
                    self.set_tool(rft.rft_class())
        self.tool_window = self.window_manager.create_window('Tools', {'sticky':7})
        self.tool_selection = UI_Options(options_callback)
        tools_options = []
        for i,rft_data in enumerate(RFTool.get_tools()):
            ids,rft = rft_data
            self.tool_selection.add_option(rft.bl_label, icon=rft.rft_class().get_ui_icon())
            ui_options = rft.rft_class().get_ui_options()
            if ui_options: tools_options.append((rft.bl_label,ui_options))
        self.tool_window.add(self.tool_selection)
        
        self.window_debug = self.window_manager.create_window('Debug', {'sticky':1, 'vertical':False, 'visible':True})
        self.window_debug_fps = UI_Label('fps: 0.00')
        self.window_debug_save = UI_Label('save: inf')
        self.window_debug.add(self.window_debug_fps)
        self.window_debug.add(UI_Spacer(width=10))
        self.window_debug.add(self.window_debug_save)
        
        window_tool_options = self.window_manager.create_window('Options', {'sticky':9})
        window_tool_options.add(UI_Checkbox('Symmetry: X', lambda: self.get_symmetry('x'), lambda v: self.set_symmetry('x',v)))
        window_tool_options.add(UI_Spacer(height=5))
        for tool_name,tool_options in tools_options:
            ui_options = window_tool_options.add(UI_Collapsible(tool_name))
            for tool_option in tool_options: ui_options.add(tool_option)


    def draw_postpixel(self):
        if not self.actions.r3d: return

        wtime,ctime = self.fps_time,time.time()
        self.frames += 1
        if ctime >= wtime + 1:
            self.fps = self.frames / (ctime - wtime)
            self.frames = 0
            self.fps_time = ctime

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        self.tool.draw_postpixel()
        self.rfwidget.draw_postpixel()
        
        self.window_debug_fps.set_label('fps: %0.2f' % self.fps)
        self.window_debug_save.set_label('save: %0.0f' % (self.time_to_save or float('inf')))
        self.window_manager.draw_postpixel()


    def draw_postview(self):
        if not self.actions.r3d: return

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        self.draw_yz_mirror()

        self.rftarget_draw.draw()
        self.tool.draw_postview()
        self.rfwidget.draw_postview()

    def draw_yz_mirror(self):
        if 'x' not in self.rftarget.symmetry: return
        self.drawing.line_width(3.0)
        bgl.glDepthMask(bgl.GL_FALSE)
        bgl.glDepthRange(0.0, 0.9999)

        bgl.glColor4f(0.5, 1.0, 1.0, 0.15)
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glBegin(bgl.GL_LINES)
        for p0,p1 in self.zy_intersections:
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
        bgl.glEnd()

        bgl.glColor4f(0.5, 1.0, 1.0, 0.01)
        bgl.glDepthFunc(bgl.GL_GREATER)
        bgl.glBegin(bgl.GL_LINES)
        for p0,p1 in self.zy_intersections:
            bgl.glVertex3f(*p0)
            bgl.glVertex3f(*p1)
        bgl.glEnd()

        bgl.glDepthRange(0.0, 1.0)
        bgl.glDepthFunc(bgl.GL_LEQUAL)
        bgl.glDepthMask(bgl.GL_TRUE)
