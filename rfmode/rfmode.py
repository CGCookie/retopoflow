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
from bpy.types import Operator
from bpy.types import SpaceView3D
from bpy.app.handlers import persistent, load_post

from .. import key_maps
from ..lib import common_utilities
from ..lib.common_utilities import print_exception, showErrorMessage
from ..lib.eventdetails import EventDetails
from ..lib.classes.logging.logger import Logger

from .rfcontext import RFContext
from .rftool import RFTool

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
                o is not context.active_object                                          # not active
            ])
    
    def invoke(self, context, event):
        ''' called when the user invokes (calls/runs) our tool '''
        if not self.poll(context): return {'CANCELLED'}    # tool cannot start
        self.framework_start(context, event)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal
    
    def modal(self, context, event):
        return self.framework_modal(context, event)
    
    
    #############################################
    # initialization method
    
    def __init__(self):
        ''' called once when RFMode plugin is enabled in Blender '''
        #self.cb_pl_handle = load_post.append(self.)
        self.logger = Logger()
        self.settings = common_utilities.get_settings()
        self.exceptions_caught = None
        self.exception_quit = None
        self.cb_pv_handle = None
        self.cb_pp_handle = None
        self.rfctx = None
        self.keymap = None
        self.event_nav = None
        print('RFTools: %s' % ' '.join(str(n) for n in RFTool))
    
    ###############################################
    # start up and shut down methods
    
    def framework_start(self, context, event):
        ''' called every time RFMode is started (invoked, executed, etc) '''
        self.exceptions_caught = []
        self.exception_quit = False
        self.context_start(context, event)
        self.ui_start(context, event)

    def framework_end(self):
        '''
        finish up stuff, as our tool is leaving modal mode
        '''
        err = False
        try:    self.context_end()
        except: err = True
        try:    self.ui_end()
        except: err = True
        if err: self.handle_exception(serious=True)
    
    def context_start(self, context, event):
        generate_target = False
        
        # should we generate new target object?
        tar_object = bpy.context.active_object
        generate_target |= not tar_object
        generate_target |= type(tar_object) is not bpy.types.Object
        generate_target |= type(tar_object.data) is not bpy.types.Mesh
        generate_target |= tar_object.select
        generate_target |= not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, tar_object.layers))
        if generate_target:
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
        
        self.rfctx = RFContext(context, event)
    
    def context_end(self):
        self.rfctx.end()
        self.rfctx = None
    
    def ui_start(self, context, event):
        # handle user-defined key mappings
        self.keymap = key_maps.rtflow_default_keymap_generate()
        key_maps.navigation_language() # check keymap against system language
        self.events_nav = key_maps.rtflow_user_keymap_generate()['navigate']
        
        # report something useful to user
        context.area.header_text_set('RetopoFlow Mode')
        
        # add callback handlers
        self.cb_pv_handle  = SpaceView3D.draw_handler_add(self.draw_callback_postview,  (self.context, ), 'WINDOW', 'POST_VIEW')
        self.cb_pp_handle  = SpaceView3D.draw_handler_add(self.draw_callback_postpixel, (self.context, ), 'WINDOW', 'POST_PIXEL')
        
        # hide meshes so we can render internally
        self.rfctx.rftarget.obj_hide()
        #for rfsource in rfctx.rfsources: rfsource.obj_hide()
    
    def ui_end(self):
        # restore states of meshes
        self.rfctx.rftarget.restore_state()
        #for rfsource in self.rfctx.rfsources: rfsource.restore_state()
        
        # remove callback handlers
        if self.cb_pv_handle:
            SpaceView3D.draw_handler_remove(self.cb_pv_handle, "WINDOW")
            self.cb_pv_handle = None
        if self.cb_pp_handle:
            SpaceView3D.draw_handler_remove(self.cb_pp_handle, "WINDOW")
            self.cb_pp_handle = None
        
        # remove useful reporting
        self.context.area.header_text_set()
    
    
    ####################################################################
    # Draw handler function
    
    def draw_callback_postview(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:    self.draw_postview()
        except: self.handle_exception()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_postpixel(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:    self.draw_postpixel()
        except: self.handle_exception()
        #if self.settings.show_help and self.help_box: self.help_box.draw()
        bgl.glPopAttrib()                           # restore OpenGL attributes
    
    
    ####################################################################
    # exception handling method
    
    def handle_exception(self, serious=False):
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
            self.log.add('\n'*5)
            self.log.add('-'*100)
            self.log.add('Something went wrong. Please start an error report with CG Cookie so we can fix it!')
            self.log.add('-'*100)
            self.log.add('\n'*5)
            showErrorMessage('Something went wrong. Please start an error report with CG Cookie so we can fix it!', wrap=240)
            self.exception_quit = True
            self.modal_end()
        
        self.fsm_mode = 'main'
    
    
    ##################################################################
    # modal method
    
    def framework_modal(self, context, event):
        '''
        Called by Blender while our tool is running modal.
        This state checks if navigation is occurring.
        This state calls auxiliary wait state to see into which state we transition.
        '''

        self.rfctx.update(context, event)
        
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
            ret = self.rfctx.modal() or {}
        except:
            self.handle_exception()
            return {'RUNNING_MODAL'}
        
        if 'pass' in ret:
            # pass navigation events (mouse,keyboard,etc.) on to region
            return {'PASS_THROUGH'}
        
        
        if 'confirm' in ret:
            # commit the operator
            # (e.g., create the mesh from internal data structure)
            self.framework_end()
            return {'FINISHED'}
        
        return {'RUNNING_MODAL'}            # tell Blender to continue running our tool in modal
    




