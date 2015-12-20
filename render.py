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
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d
from bpy_extras.view3d_utils import region_2d_to_location_3d, region_2d_to_origin_3d
from mathutils import Vector, Matrix
import math


from .modaloperator import ModalOperator


class OP_Render(ModalOperator):
    ''' ModalOperator Prototype '''
    bl_category = "Retopology"
    bl_idname = "cgcookie.render"        # unique identifier for buttons and menu items to reference
    bl_label = "RetopoFlow Render"       # display name in the interface
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    #bl_options = {'REGISTER', 'UNDO'}       # enable undo for the operator.
    
    def __init__(self):
        FSM = {}
        
        '''
        fill FSM with 'state':function(self, eventd) to add states to modal finite state machine
        FSM['example state'] = example_fn, where `def example_fn(self, context)`.
        each state function returns a string to tell FSM into which state to transition.
        main, nav, and wait states are automatically added in initialize function, called below.
        '''
        
        self.initialize('help_empty.txt', FSM)
    
    def start_poll(self, context):
        ''' Called when tool is invoked to determine if tool can start '''
        return len(bpy.data.objects) > 0
    
    def start(self, context):
        ''' Called when tool has been invoked '''
        
        # create C and gfx buffers
        #self.buffer = bgl.Buffer(bgl.GL_INT, 1)
        #bgl.glGenBuffers(1, self.buffer)
        
        # create quads and edges
        quads = []
        edges = []
        m = bpy.data.objects[-1].data
        for p in m.polygons:
            if len(p.vertices) != 4: continue
            for v in p.vertices:
                quads += list(m.vertices[v].co)
            for v0,v1 in zip(p.vertices,p.vertices[1:]+p.vertices[:1]):
                edges += list(m.vertices[v0].co)
                edges += list(m.vertices[v1].co)
        self.render_quads = bgl.Buffer(bgl.GL_FLOAT, len(quads), quads)
        self.render_edges = bgl.Buffer(bgl.GL_FLOAT, len(edges), edges)
        self.render_quads_sz = int(len(quads)/3)
        self.render_edges_sz = int(len(edges)/3)
        
        # transfer local data to gfx buffer
        #bgl.glBufferData(bgl.GL_ARRAY_BUFFER, len(self.render), self.render, bgl.GL_DYNAMIC_DRAW)
        
        bpy.data.objects[-1].hide = True
    
    def end(self, context):
        ''' Called when tool is ending modal '''
        bpy.data.objects[-1].hide = False
    
    def end_commit(self, context):
        ''' Called when tool is committing '''
        pass
    
    def end_cancel(self, context):
        ''' Called when tool is canceled '''
        pass
    
    def draw_preview(self, context):
        ''' Place pre view drawing code in here '''
        pass
    
    def draw_postview(self, context):
        ''' Place post pixel drawing code in here '''
        
        bgl.glDisable(bgl.GL_CULL_FACE)
        
        bgl.glDepthRange(0.0, 0.999)
        bgl.glEnable(bgl.GL_BLEND)
        bgl.glColor4f(0.7,0.7,1.0,0.3)
        bgl.glEnableClientState(bgl.GL_VERTEX_ARRAY)
        bgl.glVertexPointer(3, bgl.GL_FLOAT, 0, self.render_quads)
        bgl.glDrawArrays(bgl.GL_QUADS, 0, self.render_quads_sz)
        
        bgl.glLineWidth(1.0)
        bgl.glDepthRange(0, 0.997)
        bgl.glDisable(bgl.GL_BLEND)
        bgl.glColor4f(0,0,0,1)
        bgl.glVertexPointer(3, bgl.GL_FLOAT, 0, self.render_edges)
        bgl.glDrawArrays(bgl.GL_LINES, 0, self.render_edges_sz
)
    
    def draw_postpixel(self, context):
        ''' Place post pixel drawing code in here '''
        pass
    
    def update(self,context):
        '''Place update stuff here'''
        pass
    def modal_wait(self, context, eventd):
        '''
        Place code here to handle commands issued by user
        Return string that corresponds to FSM key, used to change states.  For example:
        - '':     do not change state
        - 'main': transition to main state
        - 'nav':  transition to a navigation state (passing events through to 3D view)
        '''
        return ''
