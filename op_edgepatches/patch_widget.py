'''
Created on Jun 5, 2016

@author: Patrick
'''
import math

#Blender Imports
import blf
import bgl
from bpy_extras.view3d_utils import location_3d_to_region_2d
from mathutils import Vector

#Common Imports
from ..lib import common_utilities
from ..lib import common_drawing_px
from ..preferences import RetopoFlowPreferences

romans = {}
romans[0] = 'I'
romans[1] = 'II'
romans[2] = 'III'
romans[3] = 'IV'
romans[4] = 'V'
romans[5] = 'VI'
        
class PatchEditorWidget():
    def __init__(self, EPPatch):
        self.eppatch = EPPatch
        self.patterns = []
        self.p_locs = []
        self.pole_locs = []
        
        self.pad_buttons = []  # P0,P1,...Pn
        self.extra_variable_buttones = []
        self.pattern_buttons = [] #valid pattern 
        self.rotate_buttons = [] #arrows at 0 corner
        
    def p_locs_get(self):
        
        if self.eppatch.patch == None: return
        
        self.p_locs = []
        L, (n, fwd), pat, sol = self.eppatch.patch.get_active_solution()
        
        if sol == None:
            print('no solution yet')
            
            return
        
        #c_vs = self.get_corner_locations() #TODO T-Junctions #Done
        #N = len(c_vs)
        ed_loops = self.eppatch.get_edge_loops()
        
        if fwd == -1:
            #a = (n + 1) % N
            #vs = c_vs[n:] + c_vs[:n]
            #vs.reverse()
            #vs = [vs[-1]] + vs[0:len(vs)-1]
            
            new_loops = [ed_l.copy() for ed_l in ed_loops]
            #if n != 0??
            if n != 0:
                new_loops = new_loops[n:] + new_loops[:n] #shift them
            
            new_loops.reverse()  #this just reverses the list of loops
            new_loops = [new_loops[-1]] + new_loops[0:len(ed_loops)-1] #make the tip the tip again
            
            #this reverses each vert chain in the loop
            for ed_l in new_loops:
                ed_l.reverse()
            
            ed_loops = new_loops
                  
        else:
            #vs = c_vs[n:] + c_vs[:n]
            new_loops = [ed_l.copy() for ed_l in ed_loops]
            ed_loops = new_loops[n:] + new_loops[:n]
            
        
        for patch_side in ed_loops:
            mid = math.ceil((len(patch_side)-1)/2)
        
            if len(patch_side) % 2 == 0:
                pt = .5 * patch_side[mid] + .5 * patch_side[mid-1]
            else:
                pt = patch_side[mid]
            
            self.p_locs += [pt]
            
    def pole_inds_get(self):
        '''
        for now this is a dumb search for poles based on edge valence
        in the future, the patch templates will report back the poles
        
        '''
        
        if self.eppatch.bmesh == None:
            self.pole_inds = []
            self.pole_locs = []
            return
        
        if len(self.eppatch.bmesh.verts) == 0:
            self.pole_inds = []
            self.pole_locs = []
            return
        
        bme = self.eppatch.bmesh
        bme.verts.ensure_lookup_table()
        bme.edges.ensure_lookup_table()
        perim_edges = [ed for ed in bme.edges if not ed.is_manifold]
        perim_verts = set()
        pole_inds = []
        for ed in perim_edges:
            perim_verts.add(ed.verts[0])
            perim_verts.add(ed.verts[1])

        for v in perim_verts:
            if len(v.link_edges) == 4:
                pole_inds.append(v.index)
                
        for v in bme.verts:
            if v in perim_verts: continue
            if (len(v.link_edges) == 3 or len(v.link_edges) == 5):
                pole_inds.append(v.index)
                
        self.pole_inds = pole_inds
        self.pole_locs_get()
        
    def pole_locs_get(self):
        if self.eppatch.bmesh == None:
            self.pole_inds = []
            self.pole_locs = []
            return
        
        if len(self.eppatch.bmesh.verts) == 0:
            self.pole_inds = []
            self.pole_locs = []
            return    
        
        bme = self.eppatch.bmesh
        bme.verts.ensure_lookup_table()
        self.pole_locs = [bme.verts[i].co for i in self.pole_inds]
        
    def valid_patterns_get(self):
        self.patterns = list(set(self.eppatch.patch.valid_patterns))
                     
    def pick(self,context, x,y):
        region, r3d = context.region,context.space_data.region_3d
        
        #check the patterns
        width = region.width
        height = region.height
        Y = height - 10 - 30
        Y2 = Y - 30 - 25
        mid = width/2
        
        menu_width = len(self.patterns) * 60 + max(0,len(self.patterns)-1)*5    
        #check the pattern switching buttons
        for i, n in enumerate(self.patterns):
            X = mid + 65*i - menu_width/2
            
            R = (X-x)**2 + (Y-y)**2
            if R < 900: #30 pixel radius
                return ('Pattern', n)
        
        sol_indx = self.eppatch.patch.active_solution_index
        if sol_indx != -1:
            sol_dict = self.eppatch.patch.valid_solutions[sol_indx]
        else:
            sol_dict = {}
        #draw other variables as a button
        #will decide later how to correlate them to geometry
        keys = [k for k in sol_dict.keys() if not k.startswith('p')]
        keys.sort()
        #e_vars = [sol_dict[k] for k in keys] if we want to display them
        menu_width = len(keys) * 40 + max(0,len(self.patterns)-1)*5
        
        for i, k in enumerate(keys):
            X = mid + 45*i - menu_width/2
            
            R = (X-x)**2 + (Y2 - y)**2
            if R < 400: #20 pixel radius
                return ('Variable' + k, i + len(sol_dict.keys()) - len(keys))
            
        #check the Padding Buttons
        for i, pt in enumerate(self.p_locs):    
            screen_loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, pt)
            if not screen_loc: continue
            
            R = (screen_loc[0] - x)**2 + (screen_loc[1]-y)**2
            if R < 225: #15 pixel radius
                return('Padding', i)
            
        return
    
    def draw2D(self,context):
        settings = common_utilities.get_settings()
        region,r3d = context.region,context.space_data.region_3d
        
        color_inactive = RetopoFlowPreferences.theme_colors_mesh[settings.theme]
        color_selection = RetopoFlowPreferences.theme_colors_selection[settings.theme]
        color_active = RetopoFlowPreferences.theme_colors_active[settings.theme]

        color_frozen = RetopoFlowPreferences.theme_colors_frozen[settings.theme]
        color_warning = RetopoFlowPreferences.theme_colors_warning[settings.theme]
        
        
        bgl.glEnable(bgl.GL_POINT_SMOOTH)
        
        #draw the Padding buttons
        for i, info_pt in enumerate(self.p_locs):
 
            screen_loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, info_pt)
            if not screen_loc: continue
            button = common_utilities.simple_circle(screen_loc[0], screen_loc[1], 15, 20)
            
            if i == self.eppatch.patch.param_index:
                common_drawing_px.draw_outline_or_region('GL_POLYGON', button, color_active)
            else:
                common_drawing_px.draw_outline_or_region('GL_POLYGON', button, (.2,.2,.2,.8))
                
            common_drawing_px.draw_polyline_from_points(context, button + [button[0]], color_warning, 3, 'GL_LINE')
            bgl.glColor4f(*(1,1,1,1))
            info = 'P' + str(i)
            dims = blf.dimensions(0,info)
            
            blf.position(0, screen_loc[0]-dims[0]/2, screen_loc[1]-dims[1]/2, 0)
            blf.draw(0, info)
        
        
        
        
        
        
        width = region.width
        height = region.height
        y = height - 10 - 30
        y2 = y - 30 - 25
        mid = width/2
        res = len(self.eppatch.get_edge_loops())
        
        sol_indx = self.eppatch.patch.active_solution_index
        if sol_indx != -1:
            pattern_id = self.eppatch.patch.valid_patterns[sol_indx]
            sol_dict = self.eppatch.patch.valid_solutions[sol_indx]
        else:
            pattern_id = -1
            sol_dict = {}
        #draw other variables as a button
        #will decide later how to correlate them to geometry
        keys = [k for k in sol_dict.keys() if not k.startswith('p')]
        keys.sort()
        #e_vars = [sol_dict[k] for k in keys] if we want to display them
        menu_width = len(keys) * 40 + max(0,len(self.patterns)-1)*5
        
        for i, k in enumerate(keys):
            x = mid + 45*i - menu_width/2
            button = common_utilities.simple_circle(x, y2, 20, 20)
            if i + len(sol_dict) - len(keys) == self.eppatch.patch.param_index:
                common_drawing_px.draw_outline_or_region('GL_POLYGON', button, color_active)
            else:
                common_drawing_px.draw_outline_or_region('GL_POLYGON', button, (.2,.2,.2,.8))
                
            common_drawing_px.draw_polyline_from_points(context, button + [button[0]], color_warning, 3, 'GL_LINE')
            
            bgl.glColor4f(*(1,1,1,1))
            dims = blf.dimensions(0,k)
            blf.position(0, x-dims[0]/2, y2-dims[1]/2, 0)
            blf.draw(0, k)
        menu_width = len(self.patterns) * 60 + max(0,len(self.patterns)-1)*5    
        #draw the pattern switching buttons
        for i, n in enumerate(self.patterns):
            x = mid + 65*i - menu_width/2
            
            button = common_utilities.simple_circle(x, y, 30, res)
            if n == pattern_id:
                common_drawing_px.draw_outline_or_region('GL_POLYGON', button, color_active)
            else:
                common_drawing_px.draw_outline_or_region('GL_POLYGON', button, (.2,.2,.2,.8))
            common_drawing_px.draw_polyline_from_points(context, button + [button[0]], color_warning, 3, 'GL_LINE')
            
            bgl.glColor4f(*(1,1,1,1))
            info = romans[n]
            dims = blf.dimensions(0,info)
            blf.position(0, x-dims[0]/2, y-dims[1]/2, 0)
            blf.draw(0, info)
        
        #draw a circle around the poles    
        for p_loc in self.pole_locs:
            screen_loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, p_loc)
            if not screen_loc: continue
            button = common_utilities.simple_circle(screen_loc[0], screen_loc[1], 10, 20)
            common_drawing_px.draw_outline_or_region('GL_POLYGON', button, (.2,.2,.2,.1))
            common_drawing_px.draw_polyline_from_points(context, button + [button[0]], color_selection, 3, 'GL_LINE')
            
    def draw3D(self):
        pass
    
#Identify P0 side
#Identify midpoints of all sides
#Get all