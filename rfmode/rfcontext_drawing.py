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
    UI_Button, UI_Image,
    UI_Options,
    UI_Checkbox, UI_Checkbox2,
    UI_Label, UI_WrappedLabel, UI_Markdown,
    UI_Spacer, UI_Rule,
    UI_Container, UI_Collapsible, UI_Scrollable,
    UI_IntValue,
    )
from ..lib import common_drawing_bmesh as bmegl
from .load_image import load_image_png

from ..options import retopoflow_version, options, firsttime_message


class RFContext_Drawing:
    def quit(self): self.exit = True
    
    def set_symmetry(self, axis, enable):
        if enable: self.rftarget.enable_symmetry(axis)
        else: self.rftarget.disable_symmetry(axis)
        #for rfs in self.rfsources: rfs.dirty()
        self.rftarget.dirty()
    def get_symmetry(self, axis): return self.rftarget.has_symmetry(axis)
    
    def toggle_tool_help(self):
        if self.window_help.visible:
            self.window_help.visible = False
        else:
            self.ui_helplabel.set_markdown(self.tool.helptext())
            self.window_help.visible = True
    
    def _init_drawing(self):
        self.drawing = Drawing.get_instance()
        self.window_manager = UI_WindowManager()
        
        def options_callback(lbl):
            for ids,rft in RFTool.get_tools():
                if rft.bl_label == lbl:
                    self.set_tool(rft.rft_class())
        
        self.tool_window = self.window_manager.create_window('Tools', {'sticky':7})
        self.tool_max = UI_Container(margin=0)
        self.tool_min = UI_Container(margin=0, vertical=False)
        self.tool_selection_max = UI_Options(options_callback, vertical=True)
        self.tool_selection_min = UI_Options(options_callback, vertical=False)
        tools_options = []
        for i,rft_data in enumerate(RFTool.get_tools()):
            ids,rft = rft_data
            self.tool_selection_max.add_option(rft.bl_label, icon=rft.rft_class().get_ui_icon())
            self.tool_selection_min.add_option(rft.bl_label, icon=rft.rft_class().get_ui_icon(), showlabel=False)
            ui_options = rft.rft_class().get_ui_options()
            if ui_options: tools_options.append((rft.bl_label,ui_options))
        def get_tool_collapsed():
            b = options['tools_min']
            self.tool_min.visible = b
            self.tool_max.visible = not b
            return b
        def set_tool_collapsed(b):
            options['tools_min'] = b
            self.tool_min.visible = b
            self.tool_max.visible = not b
        get_tool_collapsed()
        self.tool_max.add(self.tool_selection_max)
        
        extra = self.tool_max.add(UI_Container())
        #help_icon = UI_Image(load_image_png('help_32.png'))
        #help_icon.set_size(16, 16)
        extra.add(UI_Button('Tool Help', self.toggle_tool_help, align=0, margin=0)) # , icon=help_icon
        extra.add(UI_Button('Collapse', lambda: set_tool_collapsed(True), align=0, margin=0))
        #extra.add(UI_Checkbox('Collapsed', get_tool_collapsed, set_tool_collapsed))
        extra.add(UI_Button('Exit', self.quit, align=0, margin=0))
        self.tool_min.add(self.tool_selection_min)
        self.tool_min.add(UI_Checkbox(None, get_tool_collapsed, set_tool_collapsed))
        self.tool_window.add(self.tool_max)
        self.tool_window.add(self.tool_min)
        
        
        def show_reporting():
            options['welcome'] = True
            self.window_welcome.visible = options['welcome']
        def hide_reporting():
            options['welcome'] = False
            self.window_welcome.visible = options['welcome']
        
        def open_github():
            bpy.ops.wm.url_open(url="https://github.com/CGCookie/retopoflow/issues")
        
        window_info = self.window_manager.create_window('Info', {'sticky':1, 'visible':True})
        window_info.add(UI_Label('RetopoFlow %s' % retopoflow_version))
        container = window_info.add(UI_Container(margin=0, vertical=False))
        container.add(UI_Button('Welcome!', show_reporting, align=0))
        container.add(UI_Button('Report Issue', open_github, align=0))
        info_adv = window_info.add(UI_Collapsible('Advanced', collapsed=True))
        fps_save = info_adv.add(UI_Container(vertical=False))
        self.window_debug_fps = fps_save.add(UI_Label('fps: 0.00'))
        self.window_debug_save = fps_save.add(UI_Label('save: inf'))
        def get_instrument(): return options['instrument']
        def set_instrument(v): options['instrument'] = v
        info_adv.add(UI_Checkbox('Instrument', get_instrument, set_instrument))
        info_adv.add(UI_Button('Reset Options', options.reset, align=0))
        
        def set_profiler_visible():
            nonlocal prof_print, prof_reset, prof_disable, prof_enable
            v = profiler.debug
            prof_print.visible = v
            prof_reset.visible = v
            prof_disable.visible = v
            prof_enable.visible = not v
        def enable_profiler():
            profiler.enable()
            set_profiler_visible()
        def disable_profiler():
            profiler.disable()
            set_profiler_visible()
        info_profiler = info_adv.add(UI_Collapsible('Profiler', collapsed=True, vertical=False))
        prof_print = info_profiler.add(UI_Button('Print', profiler.printout, align=0))
        prof_reset = info_profiler.add(UI_Button('Reset', profiler.clear, align=0))
        prof_disable = info_profiler.add(UI_Button('Disable', disable_profiler, align=0))
        prof_enable = info_profiler.add(UI_Button('Enable', enable_profiler, align=0))
        set_profiler_visible()
        
        window_tool_options = self.window_manager.create_window('Options', {'sticky':9})
        
        dd_general = window_tool_options.add(UI_Collapsible('General', collapsed=False))
        dd_general.add(UI_Button('Maximize Area', self.rfmode.ui_toggle_maximize_area, align=0))
        dd_general.add(UI_Button('Snap All Verts', self.snap_all_verts, align=0))
        
        dd_symmetry = window_tool_options.add(UI_Collapsible('Symmetry', equal=True, vertical=False))
        dd_symmetry.add(UI_Checkbox2('x', lambda: self.get_symmetry('x'), lambda v: self.set_symmetry('x',v), options={'spacing':0}))
        dd_symmetry.add(UI_Checkbox2('y', lambda: self.get_symmetry('y'), lambda v: self.set_symmetry('y',v), options={'spacing':0}))
        dd_symmetry.add(UI_Checkbox2('z', lambda: self.get_symmetry('z'), lambda v: self.set_symmetry('z',v), options={'spacing':0}))
        
        for tool_name,tool_options in tools_options:
            # window_tool_options.add(UI_Spacer(height=5))
            ui_options = window_tool_options.add(UI_Collapsible(tool_name))
            for tool_option in tool_options: ui_options.add(tool_option)
        
        self.window_welcome = self.window_manager.create_window('Welcome!', {'sticky':5, 'visible':options['welcome'], 'movable':False, 'bgcolor':(0.2,0.2,0.2,0.95)})
        self.window_welcome.add(UI_Rule())
        self.window_welcome.add(UI_Markdown(firsttime_message))
        self.window_welcome.add(UI_Rule())
        self.window_welcome.add(UI_Button('Close', hide_reporting, align=0, bgcolor=(0.5,0.5,0.5,0.4), margin=2), footer=True)
        
        self.window_help = self.window_manager.create_window('Tool Help', {'sticky':5, 'visible':False, 'movable':False, 'bgcolor':(0.2,0.2,0.2,0.95)})
        self.window_help.add(UI_Rule())
        self.ui_helplabel = UI_Markdown('help text here!')
        # self.window_help.add(UI_Scrollable(self.ui_helplabel))
        self.window_help.add(self.ui_helplabel)
        self.window_help.add(UI_Rule())
        self.window_help.add(UI_Button('Close', self.toggle_tool_help, align=0, bgcolor=(0.5,0.5,0.5,0.4), margin=2), footer=True)

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

