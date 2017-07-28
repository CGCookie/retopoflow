import bpy
import bgl
import blf
import time

from .rftool import RFTool

from ..common.maths import Point, Point2D
from ..common.ui import Drawing, UI_Button, UI_Options, UI_Window, UI_Checkbox


class RFContext_Drawing:
    def _init_drawing(self):
        self.drawing = Drawing.get_instance()
        
        def options_callback(lbl):
            for ids,rft in RFTool.get_tools():
                if rft.bl_label == lbl:
                    self.set_tool(rft.rft_class())
        self.tool_window = UI_Window("Tools", sticky=7)
        self.tool_options = UI_Options(options_callback)
        for i,rft_data in enumerate(RFTool.get_tools()):
            ids,rft = rft_data
            # def create(rft):
            #     def fn_callback(): self.set_tool(rft.rft_class())
            #     return fn_callback
            # button = UI_Button(rft.bl_label, create(rft))
            # self.tool_window.add(button)
            self.tool_options.add_option(rft.bl_label)
            # if type(self.tool) == rft.rft_class:
            #     bgl.glColor4f(1.0, 1.0, 0.0, 1.0)
            # else:
            #     bgl.glColor4f(1.0, 1.0, 1.0, 0.5)
            # th = int(blf.dimensions(font_id, rft.bl_label)[1])
            # y = t - (i+1) * lh + int((lh - th) / 2.0)
            # blf.position(font_id, l, y, 0)
            # blf.draw(font_id, rft.bl_label)
        self.tool_window.add(self.tool_options)
        
        if False:
            # testing UI_Checkbox
            tmp = True
            def get_checked():
                nonlocal tmp
                return tmp
            def set_checked(v):
                nonlocal tmp
                print(v)
                tmp = v
            self.tool_window.add(UI_Checkbox('foo', get_checked, set_checked))


    def draw_postpixel(self):
        if not self.actions.r3d: return

        bgl.glEnable(bgl.GL_MULTISAMPLE)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glEnable(bgl.GL_POINT_SMOOTH)

        self.tool.draw_postpixel()
        self.rfwidget.draw_postpixel()
        
        self.tool_window.draw_postpixel()

        wtime,ctime = self.fps_time,time.time()
        self.frames += 1
        if ctime >= wtime + 1:
            self.fps = self.frames / (ctime - wtime)
            self.frames = 0
            self.fps_time = ctime

        font_id = 0

        if self.show_fps:
            debug_fps = 'fps: %0.2f' % self.fps
            debug_save = 'save: %0.0f' % (self.time_to_save or float('inf'))
            bgl.glColor4f(1.0, 1.0, 1.0, 0.10)
            blf.size(font_id, 12, 72)
            blf.position(font_id, 5, 5, 0)
            blf.draw(font_id, '%s  %s' % (debug_fps,debug_save))

        if False:
            bgl.glColor4f(1.0, 1.0, 1.0, 0.5)
            blf.size(font_id, 12, 72)
            lh = int(blf.dimensions(font_id, "XMPQpqjI")[1] * 1.5)
            w = max(int(blf.dimensions(font_id, rft().name())[0]) for rft in RFTool)
            h = lh * len(RFTool)
            l,t = 10,self.actions.size[1] - 10

            bgl.glEnable(bgl.GL_BLEND)
            bgl.glColor4f(0.0, 0.0, 0.0, 0.25)
            bgl.glBegin(bgl.GL_QUADS)
            bgl.glVertex2f(l+w+5,t+5)
            bgl.glVertex2f(l-5,t+5)
            bgl.glVertex2f(l-5,t-h-5)
            bgl.glVertex2f(l+w+5,t-h-5)
            bgl.glEnd()

            bgl.glColor4f(0.0, 0.0, 0.0, 0.75)
            self.drawing.line_width(1.0)
            bgl.glBegin(bgl.GL_LINE_STRIP)
            bgl.glVertex2f(l+w+5,t+5)
            bgl.glVertex2f(l-5,t+5)
            bgl.glVertex2f(l-5,t-h-5)
            bgl.glVertex2f(l+w+5,t-h-5)
            bgl.glVertex2f(l+w+5,t+5)
            bgl.glEnd()

            for i,rft_data in enumerate(RFTool.get_tools()):
                ids,rft = rft_data
                if type(self.tool) == rft.rft_class:
                    bgl.glColor4f(1.0, 1.0, 0.0, 1.0)
                else:
                    bgl.glColor4f(1.0, 1.0, 1.0, 0.5)
                th = int(blf.dimensions(font_id, rft.bl_label)[1])
                y = t - (i+1) * lh + int((lh - th) / 2.0)
                blf.position(font_id, l, y, 0)
                blf.draw(font_id, rft.bl_label)


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
