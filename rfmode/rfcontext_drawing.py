import bpy
import bgl
import blf
import math
import time

from .rftool import RFTool

from ..lib.classes.profiler.profiler import profiler
from ..common.maths import Point, Point2D
from ..common.ui import Drawing
from ..common.ui import (
    UI_WindowManager,
    UI_Button,
    UI_Options,
    UI_Checkbox, UI_Checkbox2,
    UI_Label,
    UI_Spacer,
    UI_Container, UI_Collapsible,
    UI_IntValue,
    )
from ..lib import common_drawing_bmesh as bmegl


class RFContext_Drawing:
    def quit(self): self.exit = True
    
    def set_symmetry(self, axis, enable):
        if enable: self.rftarget.enable_symmetry(axis)
        else: self.rftarget.disable_symmetry(axis)
        #for rfs in self.rfsources: rfs.dirty()
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
        self.tool_window.add(UI_Button('Exit', self.quit, align=0))
        
        window_info = self.window_manager.create_window('Info', {'sticky':1, 'visible':True})
        window_info.add(UI_Label('ver: 2.0.0'))
        info_debug = window_info.add(UI_Collapsible('Debug', collapsed=True))
        self.window_debug_fps = info_debug.add(UI_Label('fps: 0.00'))
        self.window_debug_save = info_debug.add(UI_Label('save: inf'))
        
        if profiler.debug:
            info_profiler = info_debug.add(UI_Collapsible('Profiler', collapsed=False, vertical=False))
            info_profiler.add(UI_Button('Print', profiler.printout, align=0))
            info_profiler.add(UI_Button('Reset', profiler.clear, align=0))
        
        window_tool_options = self.window_manager.create_window('Options', {'sticky':9})
        window_tool_options.add(UI_Button('Maximize Area', self.rfmode.ui_toggle_maximize_area, align=0))
        window_tool_options.add(UI_Button('Snap All Verts', self.snap_all_verts, align=0))
        ui_symmetry = window_tool_options.add(UI_Collapsible('Symmetry', equal=True, vertical=False))
        ui_symmetry.add(UI_Checkbox2('x', lambda: self.get_symmetry('x'), lambda v: self.set_symmetry('x',v), options={'spacing':0}))
        ui_symmetry.add(UI_Checkbox2('y', lambda: self.get_symmetry('y'), lambda v: self.set_symmetry('y',v), options={'spacing':0}))
        ui_symmetry.add(UI_Checkbox2('z', lambda: self.get_symmetry('z'), lambda v: self.set_symmetry('z',v), options={'spacing':0}))
        for tool_name,tool_options in tools_options:
            # window_tool_options.add(UI_Spacer(height=5))
            ui_options = window_tool_options.add(UI_Collapsible(tool_name))
            for tool_option in tool_options: ui_options.add(tool_option)
        
        self.window_reporting = self.window_manager.create_window('Reporting', {'sticky':5, 'visible':False, 'movable':False})
        self.ui_reporting = self.window_reporting.add(UI_Label(''))

    def get_view_version(self):
        m = self.actions.r3d.view_matrix
        return [v for r in m for v in r]

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

    def draw_preview(self):
        if not self.actions.r3d: return
        
        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)
        bgl.glDisable(bgl.GL_DEPTH_TEST)
        
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        
        bgl.glBegin(bgl.GL_TRIANGLES)
        for i in range(0,360,10):
            r0,r1 = i*math.pi/180.0, (i+10)*math.pi/180.0
            x0,y0 = math.cos(r0)*2,math.sin(r0)*2
            x1,y1 = math.cos(r1)*2,math.sin(r1)*2
            bgl.glColor4f(0,0,0.01,0.0)
            bgl.glVertex2f(0,0)
            bgl.glColor4f(0,0,0.01,0.8)
            bgl.glVertex2f(x0,y0)
            bgl.glVertex2f(x1,y1)
        bgl.glEnd()
        
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPopMatrix()
        bgl.glMatrixMode(bgl.GL_MODELVIEW)
        bgl.glPopMatrix()

    @profiler.profile
    def draw_postview(self):
        if not self.actions.r3d: return

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        pr = profiler.start('render sources')
        ft = self.rftarget.get_frame()
        for rs,rfs in zip(self.rfsources, self.rfsources_draw):
            fs = rs.get_frame()
            ft_ = fs.w2l_frame(ft)
            rfs.draw(self.rftarget.symmetry, ft_)
        pr.done()
        
        pr = profiler.start('render target')
        self.rftarget_draw.draw()
        pr.done()
        
        pr = profiler.start('render other')
        self.tool.draw_postview()
        self.rfwidget.draw_postview()
        pr.done()

