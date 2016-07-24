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

import bpy
import bgl
from bpy.types import Operator
from bpy.types import SpaceView3D
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix, Euler

import sys
import math
import os
import time

from .lib.classes.textbox.textbox import TextBox
from . import key_maps
from .lib import common_utilities
from .lib.common_utilities import print_exception, showErrorMessage

class ModalOperator(Operator):

    initialized = False
    
    def initialize(self, helpText=None, FSM=None):
        # create a log file for error writing
        if 'RetopoFlow_log' not in bpy.data.texts:
            bpy.ops.text.new()
            self.log = bpy.data.texts[-1]
            self.log.name = 'RetopoFlow_log'
        else:
            self.log = bpy.data.texts['RetopoFlow_log']

        self.settings = common_utilities.get_settings()
        self.keymap = key_maps.rtflow_default_keymap_generate()

        # check keymap against system language
        key_maps.navigation_language()

        self.events_nav = key_maps.rtflow_user_keymap_generate()['navigate']

        # make sure that the appropriate functions are defined!
        # note: not checking signature, though :(
        dfns = {
            'start_poll':       'start_poll(self,context)',
            'start':            'start(self,context)',
            'end':              'end(self,context)',
            'end_commit':       'end_commit(self,context)',
            'end_cancel':       'end_cancel(self,context)',
            'update':           'update(self,context)',
            'draw_postview':    'draw_postview(self,context)',
            'draw_postpixel':   'draw_postpixel(self,context)',
            'modal_wait':       'modal_wait(self,context,eventd)',
        }
        lbad = [fnname for fnname in dfns.keys() if not hasattr(self, fnname)]
        if lbad:
            print('Critical Error! Missing definitions for the following functions:')
            for fnname in lbad: print('  %s' % dfns[fnname])
            assert False, 'Modal operator missing definitions: %s' % ','.join(dfns[fnname] for fnname in lbad)

        self.FSM = {} if not FSM else dict(FSM)
        self.FSM['main'] = self.modal_main
        self.FSM['nav']  = self.modal_nav
        self.FSM['wait'] = self.modal_wait

        # help file stuff
        if helpText:
            path = os.path.split(os.path.abspath(__file__))[0]
            path = os.path.join(path, 'help', helpText)
            if os.path.isfile(path):
                helpText = open(path, mode='r').read()
            self.help_box = TextBox(500,500,300,200,10,20, helpText)
            if not self.settings.help_def:
                self.help_box.collapse()
            #self.help_box.snap_to_corner(context, corner = [1,1])
        else:
            self.help_box = None
        
        self.exceptions_caught = []
        self.exception_quit = False
        
        self.initialized = True


    def handle_exception(self):
        errormsg = print_exception()
        # if max number of exceptions occur within threshold of time, abort!
        curtime = time.time()
        self.exceptions_caught += [(errormsg, curtime)]
        # keep exceptions that have occurred within the last 5 seconds
        self.exceptions_caught = [(m,t) for m,t in self.exceptions_caught if curtime-t < 5]
        # if we've seen the same message before (within last 5 seconds), assume
        # that something has gone badly wrong
        c = sum(1 for m,t in self.exceptions_caught if m == errormsg)
        if c > 1:
            print('\n'*5)
            print('-'*100)
            print('Something went wrong. Please start an error report with CG Cookie so we can fix it!')
            print('-'*100)
            print('\n'*5)
            showErrorMessage('Something went wrong. Please start an error report with CG Cookie so we can fix it!', wrap=240)
            self.exception_quit = True
        self.fsm_mode = 'main'

    def get_event_details(self, context, event):
        '''
        Construct an event dictionary that is *slightly* more
        convenient than stringing together a bunch of logical
        conditions
        '''

        event_ctrl  = 'CTRL+'  if event.ctrl  else ''
        event_shift = 'SHIFT+' if event.shift else ''
        event_alt   = 'ALT+'   if event.alt   else ''
        event_oskey = 'OSKEY+' if event.oskey else ''
        event_ftype = event_ctrl + event_shift + event_alt + event_oskey + event.type


        return {
            'context': context,
            'region':  context.region,
            'r3d':     context.space_data.region_3d,

            'ctrl':    event.ctrl,
            'shift':   event.shift,
            'alt':     event.alt,
            'value':   event.value,
            'type':    event.type,
            'ftype':   event_ftype,
            'press':   event_ftype if event.value=='PRESS'   else None,
            'release': event_ftype if event.value=='RELEASE' else None,

            'mouse':   (float(event.mouse_region_x), float(event.mouse_region_y)),
            }

    ####################################################################
    # Draw handler function

    def draw_callback_postview(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:
            self.draw_postview(context)
        except:
            self.handle_exception()
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_postpixel(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        try:
            self.draw_postpixel(context)
        except:
            self.handle_exception()
        if self.settings.show_help and self.help_box:
            self.help_box.draw()
        bgl.glPopAttrib()                           # restore OpenGL attributes


    ####################################################################
    # FSM modal functions

    def modal_nav(self, context, eventd):
        '''
        Determine/handle navigation events.
        FSM passes control through to underlying panel if we're in 'nav' state
        '''
 
        handle_nav = False
        handle_nav |= eventd['ftype'] in self.events_nav
        
        if handle_nav:
            self.post_update   = True
            self.is_navigating = True
            return 'main' if eventd['value']=='RELEASE' else 'nav'

        self.is_navigating = False
        return ''

    def modal_main(self, context, eventd):
        '''
        Main state of FSM.
        This state checks if navigation is occurring.
        This state calls auxiliary wait state to see into which state we transition.
        '''

        # handle general navigationvrot = context.space_data.region_3d.view_rotation
        try:
            nmode = self.FSM['nav'](context, eventd)
        except:
            self.handle_exception()
            return ''
        if nmode:
            return nmode

        # accept / cancel
        if eventd['press'] in self.keymap['confirm']: # {'RET', 'NUMPAD_ENTER'}:
            # commit the operator
            # (e.g., create the mesh from internal data structure)
            return 'finish'
        if eventd['press'] in self.keymap['cancel']: # {'ESC'}:
            # cancel the operator
            return 'cancel'
        
        # help textbox
        if self.help_box:
            if eventd['press'] in self.keymap['help']:
                if  self.help_box.is_collapsed:
                    self.help_box.uncollapse()
                else:
                    self.help_box.collapse()
                self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
            if eventd['press'] in self.keymap['action']: # {'LEFTMOUSE', 'SHIFT+LEFTMOUSE', 'CTRL+LEFTMOUSE'}:
                if self.help_box.is_hovered:
                    if  self.help_box.is_collapsed:
                        self.help_box.uncollapse()
                    else:
                        self.help_box.collapse()
                    self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
                    return ''
            if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering
                #update brush and brush size
                x,y = eventd['mouse']
                self.help_box.hover(x,y)

        # handle general waiting
        nmode = self.FSM['wait'](context, eventd)
        if nmode:
            return nmode

        return ''


    def modal_start(self, context):
        '''
        get everything ready to be run as modal tool
        '''
        self.fsm_mode      = 'main'
        self.mode_pos      = (0, 0)
        self.cur_pos       = (0, 0)
        self.is_navigating = False
        self.cb_pv_handle  = SpaceView3D.draw_handler_add(self.draw_callback_postview, (context, ), 'WINDOW', 'POST_VIEW')
        self.cb_pp_handle  = SpaceView3D.draw_handler_add(self.draw_callback_postpixel, (context, ), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        #context.area.header_text_set(self.bl_label)

        self.footer = ''
        self.footer_last = ''
        
        try:
            self.start(context)
        except:
            self.handle_exception()
    def modal_end(self, context):
        '''
        finish up stuff, as our tool is leaving modal mode
        '''
        try:
            self.end(context)
        except:
            self.handle_exception()
        SpaceView3D.draw_handler_remove(self.cb_pv_handle, "WINDOW")
        SpaceView3D.draw_handler_remove(self.cb_pp_handle, "WINDOW")
        context.area.header_text_set()

    def modal(self, context, event):
        '''
        Called by Blender while our tool is running modal.
        This is the heart of the finite state machine.
        '''

        if self.exception_quit: return {'CANCELLED'}

        if not context.area: return {'RUNNING_MODAL'}

        context.area.tag_redraw()       # force redraw

        eventd = self.get_event_details(context, event)

        self.cur_pos  = eventd['mouse']
        try:
            nmode = self.FSM[self.fsm_mode](context, eventd)
        except:
            self.handle_exception()
            nmode = ''
        self.mode_pos = eventd['mouse']

        if nmode == 'wait': nmode = 'main'

        self.is_navigating = (nmode == 'nav')
        if nmode == 'nav':
            return {'PASS_THROUGH'}     # pass events (mouse,keyboard,etc.) on to region

        if nmode in {'finish','cancel'}:
            if nmode == 'finish':
                try:
                    self.end_commit(context)
                except:
                    self.handle_exception()
                    return {'RUNNING_MODAL'}
            else:
                try:
                    self.end_cancel(context)
                except:
                    self.handle_exception()
                    return {'RUNNING_MODAL'}
            
            try:
                self.modal_end(context)
            except:
                self.handle_exception()
            
            return {'FINISHED'} if nmode == 'finish' else {'CANCELLED'}

        if nmode: self.fsm_mode = nmode

        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal

    def invoke(self, context, event):
        '''
        called by Blender when the user invokes (calls/runs) our tool
        '''
        assert self.initialized, 'Must initialize operator before invoking'
        
        if not self.start_poll(context):    # can the tool get started?
            return {'CANCELLED'}
        
        if self.help_box:
            self.help_box.collapse()
            self.help_box.snap_to_corner(context, corner = [1,1])
        
        self.modal_start(context)
        
        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal
