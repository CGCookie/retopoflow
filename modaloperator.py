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

from mathutils import Vector, Matrix, Euler
import math

from bpy.types import Operator
from bpy.types import SpaceView3D

from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d

from .lib.common_classes import TextBox

class ModalOperator(Operator):
    events_numpad = {
        'NUMPAD_1',       'NUMPAD_2',       'NUMPAD_3',
        'NUMPAD_4',       'NUMPAD_5',       'NUMPAD_6',
        'NUMPAD_7',       'NUMPAD_8',       'NUMPAD_9',
        'CTRL+NUMPAD_1',  'CTRL+NUMPAD_2',  'CTRL+NUMPAD_3',
        'CTRL+NUMPAD_4',  'CTRL+NUMPAD_5',  'CTRL+NUMPAD_6',
        'CTRL+NUMPAD_7',  'CTRL+NUMPAD_8',  'CTRL+NUMPAD_9',
        'SHIFT+NUMPAD_1', 'SHIFT+NUMPAD_2', 'SHIFT+NUMPAD_3',
        'SHIFT+NUMPAD_4', 'SHIFT+NUMPAD_5', 'SHIFT+NUMPAD_6',
        'SHIFT+NUMPAD_7', 'SHIFT+NUMPAD_8', 'SHIFT+NUMPAD_9',
        'NUMPAD_PLUS', 'NUMPAD_MINUS', # CTRL+NUMPAD_PLUS and CTRL+NUMPAD_MINUS are used elsewhere
        'NUMPAD_PERIOD',
    }

    initialized = False

    def initialize(self, FSM=None):
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
        for fnname,fndef in dfns.items():
            assert fnname in dir(self), 'Must define %s function' % fndef

        self.FSM = {} if not FSM else dict(FSM)
        self.FSM['main'] = self.modal_main
        self.FSM['nav']  = self.modal_nav
        self.FSM['wait'] = self.modal_wait

        self.initialized = True


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

        event_pressure = 1 if not hasattr(event, 'pressure') else event.pressure

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
            'pressure': event_pressure,
            }

    ####################################################################
    # Draw handler function

    def draw_callback_postview(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        self.draw_postview(context)
        bgl.glPopAttrib()                           # restore OpenGL attributes

    def draw_callback_postpixel(self, context):
        bgl.glPushAttrib(bgl.GL_ALL_ATTRIB_BITS)    # save OpenGL attributes
        self.draw_postpxel(context)
        bgl.glPopAttrib()                           # restore OpenGL attributes


    ####################################################################
    # FSM modal functions

    def modal_nav(self, context, eventd):
        '''
        Determine/handle navigation events.
        FSM passes control through to underlying panel if we're in 'nav' state
        '''

        handle_nav = False
        handle_nav |= eventd['type'] == 'MIDDLEMOUSE'
        handle_nav |= eventd['type'] == 'MOUSEMOVE' and self.is_navigating
        handle_nav |= eventd['type'].startswith('NDOF_')
        handle_nav |= eventd['type'].startswith('TRACKPAD')
        handle_nav |= eventd['ftype'] in self.events_numpad
        handle_nav |= eventd['ftype'] in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}

        if handle_nav:
            self.post_update   = True
            self.is_navigating = True
            return 'nav' if eventd['value']=='PRESS' else 'main'

        self.is_navigating = False
        return ''

    def modal_main(self, context, eventd):
        '''
        Main state of FSM.
        This state checks if navigation is occurring.
        This state calls auxiliary wait state to see into which state we transition.
        '''

        # handle general navigationvrot = context.space_data.region_3d.view_rotation
        nmode = self.FSM['nav'](context, eventd)
        if nmode:
            return nmode

        # accept / cancel
        if eventd['press'] in {'RET', 'NUMPAD_ENTER'}:
            # commit the operator
            # (e.g., create the mesh from internal data structure)
            return 'finish'
        if eventd['press'] in {'ESC'}:
            # cancel the operator
            return 'cancel'

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

        self.start(context)

    def modal_end(self, context):
        '''
        finish up stuff, as our tool is leaving modal mode
        '''
        self.end(context)
        SpaceView3D.draw_handler_remove(self.cb_pv_handle, "WINDOW")
        SpaceView3D.draw_handler_remove(self.cb_pp_handle, "WINDOW")
        context.area.header_text_set()

    def modal(self, context, event):
        '''
        Called by Blender while our tool is running modal.
        This is the heart of the finite state machine.
        '''
        if not context.area: return {'RUNNING_MODAL'}

        context.area.tag_redraw()       # force redraw

        eventd = self.get_event_details(context, event)

        self.cur_pos  = eventd['mouse']
        nmode = self.FSM[self.fsm_mode](context, eventd)
        self.mode_pos = eventd['mouse']

        if nmode == 'wait': nmode = 'main'

        self.is_navigating = (nmode == 'nav')
        if nmode == 'nav':
            return {'PASS_THROUGH'}     # pass events (mouse,keyboard,etc.) on to region

        if nmode in {'finish','cancel'}:
            if nmode == 'finish':
                self.end_commit(context)
            else:
                self.end_cancel(context)
            self.modal_end(context)
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
        
        self.help_box = TextBox(context,500,500,300,200,10,20,'No Help!')
        self.help_box.collapse()
        self.help_box.snap_to_corner(context, corner = [1,1])
        self.modal_start(context)
        return {'RUNNING_MODAL'}    # tell Blender to continue running our tool in modal
