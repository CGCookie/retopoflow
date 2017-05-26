import re
import sys
import math

import bpy
import bmesh
from mathutils.bvhtree import BVHTree

from mathutils import Matrix,Vector
from .maths import Point,Direction,Normal,Ray,XForm

from .rfmesh import RFSource,RFTarget


class RFContext:
    '''
    RFContext contains data and functions that are useful across all of RetopoFlow, such as:
    
    - RetopoFlow settings
    - xform matrices, xfrom functions (raycast from screen space coord, etc.)
    - list of source objects, along with associated BVH, BMesh
    - undo stack
    - current state in FSM
    
    Each RetopoFlow target will have its own RFContext.  The context is stored in a text block
    so work can be resumed after saving and quitting (context is saved in .blend), or even for
    debugging purposes.
    '''
    
    
    @staticmethod
    def create(src_objects):
        rfctx = RFContext()
        for src in src_objects: rfctx.source_add(src)
        return rfctx
    
    @staticmethod
    def load_from_textblock(idx):
        return RFContext(idx=idx)
    
    def __init__(self, idx=None):
        if idx is None:
            self.init_idx()
            bpy.opt.text.new()
            self.text = bpy.data.texts[-1]
            self.text.name = self.get_text_name()
            
            self.rfsources = []
            self.rftarget = RFTarget(self.idx)
        else:
            self.idx = idx
            self.text = bpy.data.texts[self.get_text_name()]
            
            self.rfsources = [] # TODO
            self.rftarget = None # TODO
        
        self.state = {}
        self.undo = []
        
        self.text_write()
    
    
    ####################################################################
    # the following two methods use magic text to know the name of
    # text block in bpy.data.texts for storing state
    
    def get_text_name(self):
        return 'RetopoFlow_Context.%03d' % self.idx
    
    def init_idx(self):
        # determine context index (1 more than current maximum)
        reidx = re.compile(r'^RetopoFlow_Context\.(\d+)$')
        l = [reidx.match(t.name).group[0] for t in bpy.data.texts]
        self.idx = max((int(i) for i in n if i), default=0)
    
    ####################################################################
    
    
    def text_write(self):
        # write current state to text block
        state = self.text.as_string()
        # TODO: update state with current state in self
        self.text.from_string(state)
    
    def text_read(self):
        # read current state from text block
        state = self.text.as_string()
        # TODO: update current state in self with state
    
    def source_add(self. srcObj: bpy.types.Object):
        self.rfsources += [ RFSource(srcObj) ]
    
    def start(self):
        # hide all unhidden sources so we can render internally
        pass
    
    def end(self):
        # reveal all previously unhidden sources
        pass
    
    
    def raycast_sources(self, ray:Ray):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            hp,hn,hi,hd = rfsource.raycast(ray)
            if bp is None or (hd is not None and hd < bd):
                bp,bn,bi,bd = hp,bn,hi,hd
        return (bp,bn,bi,bd)
    
    def nearest_sources(self, point:Point, max_dist=sys.float_info.max):
        bp,bn,bi,bd = None,None,None,None
        for rfsource in self.rfsources:
            hp,hn,hi,hd = rfsource.nearest(point, max_dist=max_dist)
            if bp is None or (hd is not None and hd < bd):
                bp,bn,bi,bd = hp,bn,hi,hd
        return (bp,bn,bi,bd)
