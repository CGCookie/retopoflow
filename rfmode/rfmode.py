'''
Copyright (C) 2015 Taylor University, CG Cookie

Created by Dr. Jon Denning and Spring 2015 COS 424 class

Some code copied from CG Cookie Retopoflow project
https://github.com/CGCookie/retopoflow

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
'''

import os
import re
import sys
import json
import math
import time

import bpy
import bgl
from mathutils import Matrix, Vector
from bpy.types import Operator, SpaceView3D, bpy_struct
from bpy.app.handlers import persistent, load_post

from .rfcontext import RFContext
from .rftool import RFTool

from ..common.drawing import Drawing
from ..common.decorators import stats_report, stats_wrapper, blender_version_wrapper
from ..common.debug import dprint, Debugger
from ..common.maths import BBox
from ..common.profiler import profiler
from ..common.logger import Logger
from ..common.utils import get_settings
from ..common.blender import show_blender_popup
from ..options import options

'''

useful reference: https://blender.stackexchange.com/questions/19416/what-do-operator-methods-do-poll-invoke-execute-draw-modal

    For a comprehensive description of operators and their use see: http://www.blender.org/api/blender_python_api_current/bpy.types.Operator.html

    For a quick run-down

    - poll, checked before running the operator, which will never run when poll fails, used to check if an operator can run, menu items will be greyed out and if key bindings should be ignored.
    - invoke, Think of this as "run by a person". Called by default when accessed from a key binding and menu, this takes the current context - mouse location, used for interactive operations such as dragging & drawing. *
    - execute This runs the operator, assuming values are set by the caller (else use defaults), this is used for undo/redo, and executing operators from Python.
    - draw called to draw options, typically in the tool-bar. Without this, options will draw in the order they are defined. This gives you control over the layout.
    - modal this is used for operators which continuously run, eg: fly mode, knife tool, circle select are all examples of modal operators. Modal operators can handle events which would normally access other operators, they keep running until they return FINISHED.
    - cancel - called when Blender cancels a modal operator, not used often. Internal cleanup can be done here if needed.

    * - note, button layouts may set the context of operators to invoke or execute. See: http://www.blender.org/api/blender_python_api_current/bpy.types.UILayout.html?highlight=uilayout#bpy.types.UILayout.operator_context

'''


StructRNA = bpy.types.bpy_struct
rfmode_broken = False
def still_registered(self):
    global rfmode_broken
    if rfmode_broken: return False
    def is_registered():
        if not hasattr(bpy.ops, 'cgcookie'): return False
        if not hasattr(bpy.ops.cgcookie, 'retopoflow'): return False
        try:    StructRNA.path_resolve(self, "properties")
        except: return False
        return True
    if is_registered(): return True
    print('RFMode is broken!')
    rfmode_broken = True
    report_broken_rfmode()
    return False

def report_broken_rfmode():
    show_blender_popup('Something went wrong. Please try restarting Blender or create an error report with CG Cookie so we can fix it!', icon='ERROR', wrap=240)



class RFMode(Operator):
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.rfmode"
    bl_label       = "RetopoFlow Mode"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    rf_icon = None


    ################################################
    # Blender Operator methods

    @classmethod
    def poll(cls, context):
        ''' returns True (modal can start) if there is at least one mesh object visible that is not active '''
        return RFContext.has_valid_source() and RFContext.is_in_valid_mode()

    @staticmethod
    @profiler.profile
    def get_polygon_count(obj, check_modifiers=True):
        if not obj: return 0
        if obj.type != 'MESH': return 0
        count = len(obj.data.polygons)
        if check_modifiers:
            for mod in obj.modifiers:
                if mod.type == 'SUBSURF':
                    # each level of subdivision roughly quadruples the poly count
                    count *= 4 ** mod.levels
        return count

    @staticmethod
    @profiler.profile
    def dense_target():
        count = RFMode.get_polygon_count(RFContext.get_target(), check_modifiers=False)
        return count > 5000

    @staticmethod
    @profiler.profile
    def dense_sources():
        count = sum((RFMode.get_polygon_count(s) for s in RFContext.get_sources()), 0)
        return count > 1000000

    @staticmethod
    @profiler.profile
    def large_sources():
        def get_vs(s):
            x,y,z = s.scale
            return [Vector((v[0]*x, v[1]*y, v[2]*z)) for v in s.bound_box]
        sources = RFContext.get_sources()
        if not sources: return False
        vs = [v for s in sources for v in get_vs(s)]
        bbox = BBox(from_coords=vs)
        sz = (bbox.max-bbox.min).length_squared
        return sz > 15

    @staticmethod
    def save_window_state():
        data = {
            'data_wm': {},
            'selected': [o.name for o in bpy.data.objects if o.select],
            'mode': bpy.context.mode,
            'region overlap': False,    # TODO
            'region toolshelf': False,  # TODO
            'region properties': False, # TODO
            }
        for wm in bpy.data.window_managers:
            data_wm = []
            for win in wm.windows:
                data_win = []
                for area in win.screen.areas:
                    data_area = []
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            data_space = {}
                            if space.type == 'VIEW_3D':
                                data_space = {
                                    'show_only_render': space.show_only_render,
                                    'show_manipulator': space.show_manipulator,
                                }
                            data_area.append(data_space)
                    data_win.append(data_area)
                data_wm.append(data_win)
            data['data_wm'][wm.name] = data_wm

        filepath = options.temp_filepath('state')
        open(filepath, 'wt').write(json.dumps(data))

    @staticmethod
    def restore_window_state():
        filepath = options.temp_filepath('state')
        if not os.path.exists(filepath): return
        data = json.loads(open(filepath, 'rt').read())
        for wm in bpy.data.window_managers:
            data_wm = data['data_wm'][wm.name]
            for win,data_win in zip(wm.windows, data_wm):
                for area,data_area in zip(win.screen.areas, data_win):
                    if area.type != 'VIEW_3D': continue
                    for space,data_space in zip(area.spaces, data_area):
                        if space.type != 'VIEW_3D': continue
                        space.show_only_render = data_space['show_only_render']
                        space.show_manipulator = data_space['show_manipulator']
        for oname in data['selected']:
            if oname in bpy.data.objects:
                bpy.data.objects[oname].select = True

    @staticmethod
    def backup_recover():
        bpy.ops.wm.open_mainfile(filepath=options.temp_filepath('blend'))
        if 'RetopoFlow_Rotate' in bpy.data.objects:
            # need to remove empty object for rotation
            bpy.data.objects.remove(bpy.data.objects['RetopoFlow_Rotate'], do_unlink=True)
        tar_object = next(o for o in bpy.data.objects if o.select)
        bpy.context.scene.objects.active = tar_object
        tar_object.hide = False

        RFMode.restore_window_state()

    @staticmethod
    def backup_save():
        use_auto_save_temporary_files = bpy.context.user_preferences.filepaths.use_auto_save_temporary_files
        filepath = options.temp_filepath('blend')
        dprint('saving backup to %s' % filepath)
        if os.path.exists(filepath):
            os.remove(filepath)
        bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=False, copy=True)

    def invoke(self, context, event):
        ''' called when the user invokes (calls/runs) our tool '''
        if not still_registered(self):
            report_broken_rfmode()
            return {'CANCELLED'}
        if not self.poll(context): return {'CANCELLED'}    # tool cannot start
        self.framework_start(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal

    def modal(self, context, event):
        return self.framework_modal(context, event)

    def check(self, context):
        return True

    #############################################
    # initialization method

    def __init__(self):
        ''' called once when RFMode plugin is enabled in Blender '''
        #self.cb_pl_handle = load_post.append(self.)
        self.logger = Logger()
        self.settings = get_settings()
        self.exceptions_caught = None
        self.exception_quit = None
        self.prev_mode = None
        print('RFTools: %s' % ' '.join(str(n) for n in RFTool))


    ###############################################
    # start up and shut down methods

    def framework_start(self, context):
        ''' called every time RFMode is started (invoked, executed, etc) '''
        self.exceptions_caught = []
        self.exception_quit = False
        profiler.reset()

        # remember current mode and set to object mode so we can control
        # how the target mesh is rendered and so we can push new data
        # into target mesh
        self.prev_mode = {
            'OBJECT':        'OBJECT',          # for some reason, we must
            'EDIT_MESH':     'EDIT',            # translate bpy.context.mode
            'SCULPT':        'SCULPT',          # to something that
            'PAINT_VERTEX':  'VERTEX_PAINT',    # bpy.ops.object.mode_set()
            'PAINT_WEIGHT':  'WEIGHT_PAINT',    # accepts (for ui_end())...
            'PAINT_TEXTURE': 'TEXTURE_PAINT',
            }[bpy.context.mode]                 # WHY DO YOU DO THIS, BLENDER!?!?!?
        if self.prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        #print([(k,str(getattr(context,k))) for k in sorted(dir(context))])
        self.context = context
        self.area = self.context.area
        self.space = self.area.spaces[0]
        self.region_3d = self.space.region_3d

        self.context_start()
        self.ui_start()

    def framework_end(self):
        '''
        finish up stuff, as our tool is leaving modal mode
        '''
        err = False
        try:    self.ui_end()
        except:
            Debugger.print_exception()
            err = True
        try:    self.context_end()
        except:
            Debugger.print_exception()
            err = True
        if err: self.handle_exception(serious=True)

        # restore previous mode
        bpy.ops.object.mode_set(mode=self.prev_mode)

        stats_report()

    def context_start(self):
        @blender_version_wrapper('<','2.80')
        def set_object_layers(o):
            o.layers = list(bpy.context.scene.layers)
        @blender_version_wrapper('>=','2.80')
        def set_object_layers(o):
            print('unhandled: set_object_layers')
            pass

        @blender_version_wrapper('<','2.80')
        def set_object_selection(o, sel):
            o.select = sel
        @blender_version_wrapper('>=','2.80')
        def set_object_selection(o, sel):
            o.select_set('SELECT' if sel else 'DESELECT')

        @blender_version_wrapper('<','2.80')
        def link_object(o):
            bpy.context.scene.objects.link(o)
        @blender_version_wrapper('>=','2.80')
        def link_object(o):
            print('unhandled: link_object')
            pass

        @blender_version_wrapper('<','2.80')
        def set_active_object(o):
            bpy.context.scene.objects.active = o
        @blender_version_wrapper('>=','2.80')
        def set_active_object(o):
            print('unhandled: set_active_object')
            pass

        @blender_version_wrapper('<','2.80')
        def get_active_object():
            return bpy.context.scene.objects.active
        @blender_version_wrapper('>=','2.80')
        def get_active_object():
            return bpy.context.active_object

        # should we generate new target object?
        if not RFContext.has_valid_target():
            dprint('generating new target')
            tar_name = "RetopoFlow"
            tar_location = bpy.context.scene.cursor_location
            tar_editmesh = bpy.data.meshes.new(tar_name)
            tar_object = bpy.data.objects.new(tar_name, tar_editmesh)
            tar_object.matrix_world = Matrix.Translation(tar_location)  # place new object at scene's cursor location
            set_object_layers(tar_object)                               # set object on visible layers
            #tar_object.show_x_ray = get_settings().use_x_ray
            link_object(tar_object)
            set_active_object(tar_object)
            set_object_selection(tar_object, True)

        tar_object = get_active_object()

        # remember selection and unselect all
        self.selected_objects = [o for o in bpy.data.objects if o != tar_object and o.select]
        for o in self.selected_objects: set_object_selection(o, False)

        starting_tool = self.context_start_tool()
        self.rfctx = RFContext(self, starting_tool)


    def context_start_tool(self):
        assert False, "Each RFTool should overwrite this!"

    def context_end(self):
        if hasattr(self, 'rfctx'):
            self.rfctx.end()
            del self.rfctx

        # restore selection
        for o in self.selected_objects: o.select = True


    def ui_start(self):
        # report something useful to user
        # bpy.context.area.header_text_set('RetopoFlow Mode')

        # remember space info and hide all non-renderable items
        RFMode.save_window_state()
        self.space_info = {}
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for area in win.screen.areas:
                    if area.type != 'VIEW_3D': continue
                    for space in area.spaces:
                        if space.type != 'VIEW_3D': continue
                        self.space_info[space] = {
                            'show_only_render': space.show_only_render,
                            'show_manipulator': space.show_manipulator,
                        }
                        space.show_only_render = True
                        space.show_manipulator = False

        # add callback handlers
        self.cb_pr_handle = SpaceView3D.draw_handler_add(self.draw_callback_preview,   (bpy.context, ), 'WINDOW', 'PRE_VIEW')
        self.cb_pv_handle = SpaceView3D.draw_handler_add(self.draw_callback_postview,  (bpy.context, ), 'WINDOW', 'POST_VIEW')
        self.cb_pp_handle = SpaceView3D.draw_handler_add(self.draw_callback_postpixel, (bpy.context, ), 'WINDOW', 'POST_PIXEL')
        # darken other spaces
        self.spaces = [
            bpy.types.SpaceClipEditor,
            bpy.types.SpaceConsole,
            bpy.types.SpaceDopeSheetEditor,
            bpy.types.SpaceFileBrowser,
            bpy.types.SpaceGraphEditor,
            bpy.types.SpaceImageEditor,
            bpy.types.SpaceInfo,
            bpy.types.SpaceLogicEditor,
            bpy.types.SpaceNLA,
            bpy.types.SpaceNodeEditor,
            bpy.types.SpaceOutliner,
            bpy.types.SpaceProperties,
            bpy.types.SpaceSequenceEditor,
            bpy.types.SpaceTextEditor,
            bpy.types.SpaceTimeline,
            #bpy.types.SpaceUVEditor,       # <- does not exist?
            bpy.types.SpaceUserPreferences,
            #'SpaceView3D',                 # <- specially handled
            ]
        self.areas = [ 'WINDOW', 'HEADER' ]
        # ('WINDOW', 'HEADER', 'CHANNELS', 'TEMPORARY', 'UI', 'TOOLS', 'TOOL_PROPS', 'PREVIEW')
        self.cb_pp_tools   = SpaceView3D.draw_handler_add(self.draw_callback_cover, (bpy.context, ), 'TOOLS',      'POST_PIXEL')
        self.cb_pp_props   = SpaceView3D.draw_handler_add(self.draw_callback_cover, (bpy.context, ), 'TOOL_PROPS', 'POST_PIXEL')
        self.cb_pp_ui      = SpaceView3D.draw_handler_add(self.draw_callback_cover, (bpy.context, ), 'UI',         'POST_PIXEL')
        self.cb_pp_header  = SpaceView3D.draw_handler_add(self.draw_callback_cover, (bpy.context, ), 'HEADER',     'POST_PIXEL')
        self.cb_pp_all = [
            (s, a, s.draw_handler_add(self.draw_callback_cover, (bpy.context,), a, 'POST_PIXEL'))
            for s in self.spaces
            for a in self.areas
            ]
        self.tag_redraw_all()

        self.blender_op_context = {
            'window': bpy.context.window,
            'area': bpy.context.area,
            'space_data': bpy.context.space_data,
            'region': bpy.context.region,
        }

        self.maximize_area = False
        self.rgn_toolshelf = bpy.context.area.regions[1]
        self.rgn_properties = bpy.context.area.regions[3]
        self.show_toolshelf = self.rgn_toolshelf.width > 1
        self.show_properties = self.rgn_properties.width > 1
        self.region_overlap = bpy.context.user_preferences.system.use_region_overlap
        if self.region_overlap:
            if self.show_toolshelf: bpy.ops.view3d.toolshelf()
            if self.show_properties: bpy.ops.view3d.properties()

        self.wrap_panels()

        self.rfctx.timer = bpy.context.window_manager.event_timer_add(1.0 / 120, bpy.context.window)

        self.drawing = Drawing.get_instance()
        self.drawing.set_cursor('CROSSHAIR')

        # hide meshes so we can render internally
        self.rfctx.rftarget.obj_hide()
        #for rfsource in rfctx.rfsources: rfsource.obj_hide()

    def ui_toggle_maximize_area(self, use_hide_panels=True):
        try:
            bpy.ops.screen.screen_full_area(use_hide_panels=use_hide_panels)
        except Exception as e:
            print('Exception caught while trying to toggle area')
            print(e)
            raise e
        self.maximize_area = not self.maximize_area

    def ui_end(self):
        if self.maximize_area: self.ui_toggle_maximize_area()
        if self.region_overlap:
            try:
                # TODO: CONTEXT IS INCORRECT when maximize_area was True????
                ctx = { 'area': self.area, 'space_data': self.space }
                if self.show_toolshelf and self.rgn_toolshelf.width <= 1: bpy.ops.view3d.toolshelf(ctx)
                if self.show_properties and self.rgn_properties.width <= 1: bpy.ops.view3d.properties(ctx)
            except:
                pass
                #self.ui_toggle_maximize_area(use_hide_panels=False)

        if not hasattr(self, 'rfctx'): return
        # restore states of meshes
        self.rfctx.rftarget.restore_state()
        #for rfsource in self.rfctx.rfsources: rfsource.restore_state()

        if self.rfctx.timer:
            bpy.context.window_manager.event_timer_remove(self.rfctx.timer)
            self.rfctx.timer = None

        # remove callback handlers
        if hasattr(self, 'cb_pr_handle'):
            SpaceView3D.draw_handler_remove(self.cb_pr_handle, "WINDOW")
            del self.cb_pr_handle
        if hasattr(self, 'cb_pv_handle'):
            SpaceView3D.draw_handler_remove(self.cb_pv_handle, "WINDOW")
            del self.cb_pv_handle
        if hasattr(self, 'cb_pp_handle'):
            SpaceView3D.draw_handler_remove(self.cb_pp_handle, "WINDOW")
            del self.cb_pp_handle
        if hasattr(self, 'cb_pp_tools'):
            SpaceView3D.draw_handler_remove(self.cb_pp_tools,  "TOOLS")
            del self.cb_pp_tools
        if hasattr(self, 'cb_pp_props'):
            SpaceView3D.draw_handler_remove(self.cb_pp_props,  "TOOL_PROPS")
            del self.cb_pp_props
        if hasattr(self, 'cb_pp_ui'):
            SpaceView3D.draw_handler_remove(self.cb_pp_ui,     "UI")
            del self.cb_pp_ui
        if hasattr(self, 'cb_pp_header'):
            SpaceView3D.draw_handler_remove(self.cb_pp_header, "HEADER")
            del self.cb_pp_header
        if hasattr(self, 'cb_pp_all'):
            for s,a,cb in self.cb_pp_all: s.draw_handler_remove(cb, a)
            del self.cb_pp_all

        self.drawing.set_cursor('DEFAULT')

        # restore space info
        for space,data in self.space_info.items():
            for k,v in data.items(): space.__setattr__(k, v)

        # remove useful reporting
        self.area.header_text_set()

        self.tag_redraw_all()

    def tag_redraw(self):
        if bpy.context.area and bpy.context.area.type == 'VIEW_3D': self.area = bpy.context.area
        self.area.tag_redraw()
        self.area.header_text_set('RetopoFlow Mode')

    def tag_redraw_all(self):
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for ar in win.screen.areas:
                    ar.tag_redraw()

    def wrap_panels(self):
        # https://wiki.blender.org/index.php/User%3aIdeasman42/Blender_UI_Shenanigans
        return

        classes = ['Panel', 'Menu', 'Header']
        def draw_override(func_orig, self_real, context):
            # print("override draw:", self_real)
            ret = None
            ret = func_orig(self_real, context)
            return ret
        def poll_override(func_orig, cls, context):
            # print("override poll:", func_orig.__self__)
            ret = False
            ret = func_orig(context)
            return ret
        for cls_name in classes:
            cls = getattr(bpy.types, cls_name)
            for subcls in cls.__subclasses__():
                if "draw" in subcls.__dict__:  # dont want to get parents draw()
                    def replace_draw():
                        # function also serves to hold draw_orig in a local namespace
                        draw_orig = subcls.draw
                        def draw(self, context):
                            return draw_override(draw_orig, self, context)
                        subcls.draw = draw
                    replace_draw()
                if "poll" in subcls.__dict__:  # dont want to get parents poll()
                    def replace_poll():
                        # function also serves to hold poll_orig in a local namespace
                        poll_orig = subcls.poll
                        def poll(cls, context):
                            return poll_override(poll_orig, cls, context)
                        subcls.poll = classmethod(poll)
                    replace_poll()

    ####################################################################
    # Draw handler function

    def draw_callback_preview(self, context):
        if not still_registered(self): return
        self.drawing.update_dpi()
        self.drawing.set_font_size(12, force=True)
        self.drawing.point_size(1)
        self.drawing.line_width(1)
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:    self.rfctx.draw_preview()
        except: self.handle_exception()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_postview(self, context):
        if not still_registered(self): return
        self.drawing.update_dpi()
        self.drawing.set_font_size(12, force=True)
        self.drawing.point_size(1)
        self.drawing.line_width(1)
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:    self.rfctx.draw_postview()
        except: self.handle_exception()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_postpixel(self, context):
        if not still_registered(self): return
        self.drawing.update_dpi()
        self.drawing.set_font_size(12, force=True)
        self.drawing.point_size(1)
        self.drawing.line_width(1)
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:
            self.rfctx.draw_postpixel()
        except:
            dprint('Exception in draw_postpixel')
            self.handle_exception()
        #if self.settings.show_help and self.help_box: self.help_box.draw()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_cover(self, context):
        if not still_registered(self): return
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)
        bgl.glMatrixMode(bgl.GL_PROJECTION)
        bgl.glPushMatrix()
        bgl.glLoadIdentity()
        bgl.glColor4f(0,0,0,0.5)    # TODO: use window background color??
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glDisable(bgl.GL_DEPTH_TEST)
        bgl.glBegin(bgl.GL_QUADS)   # TODO: not use immediate mode
        bgl.glVertex2f(-1, -1)
        bgl.glVertex2f( 1, -1)
        bgl.glVertex2f( 1,  1)
        bgl.glVertex2f(-1,  1)
        bgl.glEnd()
        bgl.glPopMatrix()
        bgl.glPopAttrib()


    ####################################################################
    # exception handling method

    def handle_exception(self, serious=False):
        errormsg = Debugger.print_exception()
        # if max number of exceptions occur within threshold of time, abort!
        curtime = time.time()
        self.exceptions_caught += [(errormsg, curtime)]
        # keep exceptions that have occurred within the last 5 seconds
        self.exceptions_caught = [(m,t) for m,t in self.exceptions_caught if curtime-t < 5]
        # if we've seen the same message before (within last 5 seconds), assume
        # that something has gone badly wrong
        c = sum(1 for m,t in self.exceptions_caught if m == errormsg)
        if serious or c > 1:
            self.logger.add('\n'*5)
            self.logger.add('-'*100)
            self.logger.add('Something went wrong. Please start an error report with CG Cookie so we can fix it!')
            self.logger.add('-'*100)
            self.logger.add('\n'*5)
            show_blender_popup('Something went wrong. Please start an error report with CG Cookie so we can fix it!', wrap=240)
            self.exception_quit = True
            self.ui_end()

        self.fsm_mode = 'main'


    ##################################################################
    # modal method

    def framework_modal(self, context, event):
        '''
        Called by Blender while our tool is running modal.
        This state checks if navigation is occurring.
        This state calls auxiliary wait state to see into which state we transition.
        '''

        if not still_registered(self):
            # something bad happened, so bail!
            return {'CANCELLED'}

        if self.exception_quit:
            # something bad happened, so bail!
            self.framework_end()
            return {'CANCELLED'}

        if profiler.is_broken():
            # something bad happened, so bail!
            self.rfctx.alert_user(title='Broken Profiler', message='The profiler is in an unexpected state.', level='exception')
            profiler.reset()
            #self.framework_end()
            #return {'CANCELLED'}

        # # handle strange edge cases
        # if not context.area:
        #     #dprint('Context with no area')
        #     #dprint(context)
        #     return {'RUNNING_MODAL'}
        # if not hasattr(context.space_data, 'region_3d'):
        #     #dprint('context.space_data has no region_3d')
        #     #dprint(context)
        #     #dprint(context.space_data)
        #     return {'RUNNING_MODAL'}

        profiler.printfile()

        # TODO: can we not redraw only when necessary?
        self.tag_redraw()
        #context.area.tag_redraw()       # force redraw

        try:
            ret = self.rfctx.modal(context, event) or {}
        except:
            self.handle_exception()
            return {'RUNNING_MODAL'}

        if 'pass' in ret:
            # pass navigation events (mouse,keyboard,etc.) on to region
            return {'PASS_THROUGH'}


        if 'confirm' in ret:
            # commit the operator
            # (e.g., create the mesh from internal data structure)
            if 'edit mode' in ret: self.prev_mode = 'EDIT'
            self.rfctx.commit()
            self.framework_end()
            return {'FINISHED'}

        if 'edit mode' in ret:
            # commit the operator
            # (e.g., create the mesh from internal data structure)
            self.rfctx.commit()
            self.framework_end()
            return {'FINISHED'}


        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal


rfmode_tools = {}

@stats_wrapper
def setup_tools():
    for rft in RFTool:
        def classfactory(rft):
            rft_name = rft().name()
            pylegal_name = re.sub(r'[ ()-]+', '_', rft_name)
            cls_name = 'RFMode_' + pylegal_name
            id_name = 'cgcookie.rfmode_' + pylegal_name.lower()
            dprint('Creating: ' + cls_name)
            def context_start_tool(self): return rft()
            newclass = type(cls_name, (RFMode,),{
                "context_start_tool": context_start_tool,
                'bl_idname': id_name,
                "bl_label": rft_name,
                'rf_label': rft_name,
                'bl_description': rft().description(),
                'rf_icon': rft().icon(),
                'rft_class': rft,
                'get_tooltip': rft().get_tooltip,
                'get_label': rft().get_label,
                })
            rfmode_tools[id_name] = newclass
            globals()[cls_name] = newclass
        classfactory(rft)

    listed,unlisted = [None]*len(RFTool.preferred_tool_order),[]
    for ids,rft in rfmode_tools.items():
        name = rft.bl_label
        if name in RFTool.preferred_tool_order:
            idx = RFTool.preferred_tool_order.index(name)
            listed[idx] = (ids,rft)
        else:
            unlisted.append((ids,rft))
    # sort unlisted entries by name
    unlisted.sort(key=lambda k:k[1].bl_label)
    listed = [data for data in listed if data]
    RFTool.order = listed + unlisted

setup_tools()

