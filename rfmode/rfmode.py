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

import sys
import math
import os
import time

import bpy
import bgl
from mathutils import Matrix
from bpy.types import Operator, SpaceView3D, bpy_struct
from bpy.app.handlers import persistent, load_post

from ..lib import common_utilities
from ..lib.common_utilities import print_exception, print_exception2, showErrorMessage
from ..lib.classes.logging.logger import Logger

from .rfcontext import RFContext
from .rftool import RFTool

from ..common.maths import stats_report

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
    showErrorMessage('Something went wrong. Please try restarting Blender or create an error report with CG Cookie so we can fix it!', wrap=240)



class RFMode(Operator):
    bl_category    = "Retopology"
    bl_idname      = "cgcookie.retopoflow"
    bl_label       = "Retopoflow Mode"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    
    
    ################################################
    # Blender Operator methods
    
    @classmethod
    def poll(cls, context):
        ''' returns True (modal can start) if there is at least one mesh object visible that is not active '''
        return 0 < len([
            o for o in context.scene.objects if
                type(o.data) is bpy.types.Mesh and                                      # mesh object
                any(vl and ol for vl,ol in zip(context.scene.layers, o.layers)) and     # on visible layer
                not o.hide and                                                          # not hidden
                (o != context.active_object or not o.select) and                        # not active or not selected
                len(o.data.polygons) > 0                                                # at least one polygon
            ])
    
    def invoke(self, context, event):
        ''' called when the user invokes (calls/runs) our tool '''
        if not still_registered(self):
            report_broken_rfmode()
            return {'CANCELLED'}
        if not self.poll(context): return {'CANCELLED'}    # tool cannot start
        self.framework_start()
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
        self.settings = common_utilities.get_settings()
        self.exceptions_caught = None
        self.exception_quit = None
        self.prev_mode = None
        print('RFTools: %s' % ' '.join(str(n) for n in RFTool))
    
    ###############################################
    # start up and shut down methods
    
    def framework_start(self):
        ''' called every time RFMode is started (invoked, executed, etc) '''
        self.exceptions_caught = []
        self.exception_quit = False
        self.context_start()
        self.ui_start()

    def framework_end(self):
        '''
        finish up stuff, as our tool is leaving modal mode
        '''
        err = False
        try:    self.ui_end()
        except:
            print_exception()
            err = True
        try:    self.context_end()
        except:
            print_exception()
            err = True
        if err: self.handle_exception(serious=True)
        
        stats_report()
    
    
    def context_start(self):
        # should we generate new target object?
        def generate_target():
            tar_object = bpy.context.active_object
            if tar_object is None: return True
            if type(tar_object) is not bpy.types.Object: return True
            if type(tar_object.data) is not bpy.types.Mesh: return True
            if not tar_object.select: return True
            if not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, tar_object.layers)): return True
            return False
        if generate_target():
            print('generating new target')
            tar_name = "RetopoFlow"
            tar_location = bpy.context.scene.cursor_location
            tar_editmesh = bpy.data.meshes.new(tar_name)
            tar_object = bpy.data.objects.new(tar_name, tar_editmesh)
            tar_object.matrix_world = Matrix.Translation(tar_location)  # place new object at scene's cursor location
            tar_object.layers = list(bpy.context.scene.layers)          # set object on visible layers
            #tar_object.show_x_ray = get_settings().use_x_ray
            bpy.context.scene.objects.link(tar_object)
            bpy.context.scene.objects.active = tar_object
            tar_object.select = True
        
        self.rfctx = RFContext()
    
    def context_end(self):
        if hasattr(self, 'rfctx'):
            self.rfctx.end()
            del self.rfctx
    
    def ui_start(self):
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
        bpy.ops.object.mode_set(mode='OBJECT')
        
        # report something useful to user
        bpy.context.area.header_text_set('RetopoFlow Mode')
        
        # remember space info and hide all non-renderable items
        self.space_info = {}
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for area in win.screen.areas:
                    if area.type != 'VIEW_3D': continue
                    for space in area.spaces:
                        if space.type != 'VIEW_3D': continue
                        self.space_info[space] = {
                            'show_only_render': space.show_only_render,
                        }
                        space.show_only_render = True
        
        # add callback handlers
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
        
        self.rfctx.timer = bpy.context.window_manager.event_timer_add(1.0 / 120, bpy.context.window)
        
        self.rfctx.set_cursor('CROSSHAIR')
        
        # hide meshes so we can render internally
        self.rfctx.rftarget.obj_hide()
        #for rfsource in rfctx.rfsources: rfsource.obj_hide()
    
    def ui_end(self):
        if not hasattr(self, 'rfctx'): return
        # restore states of meshes
        self.rfctx.rftarget.restore_state()
        #for rfsource in self.rfctx.rfsources: rfsource.restore_state()
        
        if self.rfctx.timer:
            bpy.context.window_manager.event_timer_remove(self.rfctx.timer)
            self.rfctx.timer = None
        
        # remove callback handlers
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
        
        self.rfctx.restore_cursor()
       
        # restore space info
        for space,data in self.space_info.items():
            space.show_only_render = data['show_only_render']
        
        # remove useful reporting
        bpy.context.area.header_text_set()
        
        # restore previous mode
        bpy.ops.object.mode_set(mode=self.prev_mode)
        
        self.tag_redraw_all()
    
    def tag_redraw_all(self):
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for ar in win.screen.areas:
                    ar.tag_redraw()
    
    
    ####################################################################
    # Draw handler function
    
    def draw_callback_postview(self, context):
        if not still_registered(self): return
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:    self.rfctx.draw_postview()
        except: self.handle_exception()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_postpixel(self, context):
        if not still_registered(self): return
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:    self.rfctx.draw_postpixel()
        except: self.handle_exception()
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
        #print_exception2()
        errormsg = print_exception()
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
            showErrorMessage('Something went wrong. Please start an error report with CG Cookie so we can fix it!', wrap=240)
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

        # TODO: is this necessary?
        if not context.area:
            print('Context with no area')
            print(context)
            return {'RUNNING_MODAL'}

        # TODO: can we not redraw only when necessary?
        context.area.tag_redraw()       # force redraw
        
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
            self.rfctx.commit()
            self.framework_end()
            return {'FINISHED'}
        
        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal
    




