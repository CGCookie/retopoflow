'''
Copyright (C) 2014 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of dedicated retopology tools for Blender",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore",
    "version":     (1, 0, 1),
    "blender":     (2, 7, 5),
    "location":    "View 3D > Tool Shelf",
    "warning":     "",  # used for warning icon and text in addons panel
    "wiki_url":    "http://cgcookiemarkets.com/blender/all-products/retopoflow/?view=docs",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
    }


# System imports
import os
import sys

import copy
import math
import random
import time
from math import sqrt
from mathutils import Vector, Matrix, Quaternion
from mathutils.geometry import intersect_line_plane, intersect_point_line
import itertools

# Blender imports
import bgl
import blf
import bmesh
import bpy
from bpy.props import EnumProperty, StringProperty, BoolProperty, IntProperty, FloatVectorProperty, FloatProperty
from bpy.types import Operator, AddonPreferences
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d

global bversion
bversion = '%03d.%03d.%03d' % (bpy.app.version[0],bpy.app.version[1],bpy.app.version[2])
if bversion > '002.074.004':
    import bpy.utils.previews

# Common imports
from .lib import common_utilities
from .lib import common_drawing
from .lib.common_utilities import get_object_length_scale, dprint, profiler, frange, selection_mouse, showErrorMessage
from .lib.common_classes import SketchBrush, TextBox
from . import key_maps

# Polystrip imports
from . import polystrips_utilities
from .polystrips import PolyStrips
from .polystrips_draw import draw_gedge_info

# Contour imports
from . import contour_utilities
from .contour_classes import ContourCutLine, ExistingVertList, CutLineManipulatorWidget, ContourCutSeries, ContourStatePreserver

# Create a class that contains all location information for addons
AL = common_utilities.AddonLocator()

#a place to store stokes for later
global contour_cache 
contour_cache = {}
contour_undo_cache = []

#store any temporary triangulated objects
#store the bmesh to prevent recalcing bmesh
#each time :-)
global contour_mesh_cache
contour_mesh_cache = {}

# Used to store undo snapshots
polystrips_undo_cache = []


class RetopoFlowPreferences(AddonPreferences):
    bl_idname = __name__
    
    def update_theme(self, context):
        print('theme updated to ' + str(theme))

    # Theme definitions
    theme = EnumProperty(
        items=[
            ('blue', 'Blue', 'Blue color scheme'),
            ('green', 'Green', 'Green color scheme'),
            ('orange', 'Orange', 'Orange color scheme'),
            ],
        name='theme',
        default='blue'
        )

    def rgba_to_float(r, g, b, a):
        return (r/255.0, g/255.0, b/255.0, a/255.0)

    theme_colors_active = {
        'blue': rgba_to_float(78, 207, 81, 255),
        'green': rgba_to_float(26, 111, 255, 255),
        'orange': rgba_to_float(207, 135, 78, 255)
    }
    theme_colors_selection = {
        'blue': rgba_to_float(78, 207, 81, 255),
        'green': rgba_to_float(26, 111, 255, 255),
        'orange': rgba_to_float(207, 135, 78, 255)
    }
    theme_colors_mesh = {
        'blue': rgba_to_float(26, 111, 255, 255),
        'green': rgba_to_float(78, 207, 81, 255),
        'orange': rgba_to_float(26, 111, 255, 255)
    }
    theme_colors_frozen = {
        'blue': rgba_to_float(255, 255, 255, 255),
        'green': rgba_to_float(255, 255, 255, 255),
        'orange': rgba_to_float(255, 255, 255, 255)
    }
    theme_colors_warning = {
        'blue': rgba_to_float(182, 31, 0, 125),
        'green': rgba_to_float(182, 31, 0, 125),
        'orange': rgba_to_float(182, 31, 0, 125)
    }

    # User settings
    show_help = BoolProperty(
        name='Show Help Box',
        description='A help text box will float on 3d view',
        default=True
        )
    help_def = BoolProperty(
        name='Show Help at Start',
        description='Check to have help expanded when starting operator',
        default=False
        )
    show_segment_count = BoolProperty(
        name='Show Selected Segment Count',
        description='Show segment count on selection',
        default=True
        )

    use_pressure = BoolProperty(
        name='Use Pressure Sensitivity',
        description='Adjust size of Polystrip with pressure of tablet pen',
        default=False
        )

    # Tool settings
    contour_panel_settings = BoolProperty(
        name="Show Contour Settings",
        description = "Show the Contour settings",
        default=False,
        )
    polystrips_panel_settings = BoolProperty(
        name="Show Polystrips Settings",
        description = "Show the Polystrips settings",
        default=False,
        )

    # System settings
    quad_prev_radius = IntProperty(
        name="Pixel Brush Radius",
        description="Pixel brush size",
        default=15,
        )

    show_edges = BoolProperty(
            name="Show Span Edges",
            description = "Display the extracted mesh edges. Usually only turned off for debugging",
            default=True,
            )
    
    show_ring_edges = BoolProperty(
            name="Show Ring Edges",
            description = "Display the extracted mesh edges. Usually only turned off for debugging",
            default=True,
            )

    draw_widget = BoolProperty(
            name="Draw Widget",
            description = "Turn display of widget on or off",
            default=True,
            )
    
    show_axes = BoolProperty(
            name = "show_axes",
            description = "Show Cut Axes",
            default = False)

    show_experimental = BoolProperty(
            name="Enable Experimental",
            description = "Enable experimental features and functions that are still in development, useful for experimenting and likely to crash",
            default=False,
            )
    
    vert_size = IntProperty(
            name="Vertex Size",
            default=4,
            min = 1,
            max = 10,
            )
    edge_thick = IntProperty(
            name="Edge Thickness",
            default=1,
            min=1,
            max=10,
            )

    #TODO  Theme this out nicely :-) 
    widget_color = FloatVectorProperty(name="Widget Color", description="Choose Widget color", min=0, max=1, default=(0,0,1), subtype="COLOR")
    widget_color2 = FloatVectorProperty(name="Widget Color", description="Choose Widget color", min=0, max=1, default=(1,0,0), subtype="COLOR")
    widget_color3 = FloatVectorProperty(name="Widget Color", description="Choose Widget color", min=0, max=1, default=(0,1,0), subtype="COLOR")
    widget_color4 = FloatVectorProperty(name="Widget Color", description="Choose Widget color", min=0, max=1, default=(0,0.2,.8), subtype="COLOR")
    widget_color5 = FloatVectorProperty(name="Widget Color", description="Choose Widget color", min=0, max=1, default=(.9,.1,0), subtype="COLOR")
 
    handle_size = IntProperty(
            name="Handle Vertex Size",
            default=8,
            min = 1,
            max = 10,
            )
    
    line_thick = IntProperty(
            name="Line Thickness",
            default=1,
            min = 1,
            max = 10,
            )
    
    stroke_thick = IntProperty(
            name="Stroke Thickness",
            description = "Width of stroke lines drawn by user",
            default=1,
            min = 1,
            max = 10,
            )
    
    auto_align = BoolProperty(
            name="Automatically Align Vertices",
            description = "Attempt to automatically align vertices in adjoining edgeloops. Improves outcome, but slows performance",
            default=True,
            )
    
    live_update = BoolProperty(
            name="Live Update",
            description = "Will live update the mesh preview when transforming cut lines. Looks good, but can get slow on large meshes",
            default=True,
            )
    
    use_x_ray = BoolProperty(
            name="X-Ray",
            description = 'Enable X-Ray on Retopo-mesh upon creation',
            default=False,
            )
    
    use_perspective = BoolProperty(
            name="Use Perspective",
            description = 'Make non parallel cuts project from the same view to improve expected outcome',
            default=True,
            )
    
    widget_radius = IntProperty(
            name="Widget Radius",
            description = "Size of cutline widget radius",
            default=25,
            min = 20,
            max = 100,
            )
    
    widget_radius_inner = IntProperty(
            name="Widget Inner Radius",
            description = "Size of cutline widget inner radius",
            default=10,
            min = 5,
            max = 30,
            )
    
    widget_thickness = IntProperty(
            name="Widget Line Thickness",
            description = "Width of lines used to draw widget",
            default=2,
            min = 1,
            max = 10,
            )
    
    widget_thickness2 = IntProperty(
            name="Widget 2nd Line Thick",
            description = "Width of lines used to draw widget",
            default=4,
            min = 1,
            max = 10,
            )
        
    arrow_size = IntProperty(
            name="Arrow Size",
            default=12,
            min=5,
            max=50,
            )   
    
    arrow_size2 = IntProperty(
            name="Translate Arrow Size",
            default=10,
            min=5,
            max=50,
            )      
    
    vertex_count = IntProperty(
            name = "Vertex Count",
            description = "The Number of Vertices Per Edge Ring",
            default=10,
            min = 3,
            max = 250,
            )
    
    ring_count = IntProperty(
        name="Ring Count",
        description="The Number of Segments Per Guide Stroke",
        default=10,
        min=3,
        max=100,
        )

    cyclic = BoolProperty(
            name = "Cyclic",
            description = "Make contour loops cyclic",
            default = False)
    
    recover = BoolProperty(
            name = "Recover",
            description = "Recover strokes from last session",
            default = False)
    
    recover_clip = IntProperty(
            name = "Recover Clip",
            description = "Number of cuts to leave out, usually set to 0 or 1",
            default=1,
            min = 0,
            max = 10,
            )
    
    search_factor = FloatProperty(
            name = "Search Factor",
            description = "Factor of existing segment length to connect a new cut",
            default=5,
            min = 0,
            max = 30,
            )
        
    intersect_threshold = FloatProperty(
            name = "Intersect Factor",
            description = "Stringence for connecting new strokes",
            default=1.,
            min = .000001,
            max = 1,
            )
    
    merge_threshold = FloatProperty(
            name = "Intersect Factor",
            description = "Distance below which to snap strokes together",
            default=1.,
            min = .000001,
            max = 1,
            )
    
    cull_factor = IntProperty(
            name = "Cull Factor",
            description = "Fraction of screen drawn points to throw away. Bigger = less detail",
            default = 4,
            min = 1,
            max = 10,
            )
    
    smooth_factor = IntProperty(
            name = "Smooth Factor",
            description = "Number of iterations to smooth drawn strokes",
            default = 5,
            min = 1,
            max = 10,
            )
    
    feature_factor = IntProperty(
            name = "Smooth Factor",
            description = "Fraction of sketch bounding box to be considered feature. Bigger = More Detail",
            default = 4,
            min = 1,
            max = 20,
            )
    
    extend_radius = IntProperty(
            name="Snap/Extend Radius",
            default=20,
            min=5,
            max=100,
            )

    undo_depth = IntProperty(
        name="Undo Depth",
        description="Max number of undo steps",
        min = 0,
        max = 100,
        default=15,
        )
    
    smooth_method = EnumProperty(
        items=[
            ('ENDPOINT', 'ENDPOINT', 'Blend Between Endpoints'),
            ('CENTER_MASS', 'CENTER_MASS', 'Use Cut Locations to smooth'),
            ('PATH_NORMAL', 'PATH_NORMAL', 'Use Cut Orientation only'),
            ],
        name='Smooth Method',
        default='ENDPOINT'
        )
    ## Debug Settings
    show_debug = BoolProperty(
            name="Show Debug Settings",
            description = "Show the debug settings, useful for troubleshooting",
            default=False,
            )

    debug = IntProperty(
        name="Debug Level",
        default=1,
        min=0,
        max=4,
        )

    raw_vert_size = IntProperty(
            name="Raw Vertex Size",
            default=1,
            min = 1,
            max = 10,
            )

    simple_vert_inds = BoolProperty(
            name="Simple Inds",
            default=False,
            )
    
    vert_inds = BoolProperty(
            name="Vert Inds",
            description = "Display indices of the raw contour verts",
            default=False,
            )

    show_backbone = BoolProperty(
            name = "show_backbone",
            description = "Show Cut Series Backbone",
            default = False)

    show_nodes = BoolProperty(
            name = "show_nodes",
            description = "Show Cut Nodes",
            default = False)

    show_ring_inds = BoolProperty(
            name = "show_ring_inds",
            description = "Show Ring Indices",
            default = False)

    show_verts = BoolProperty(
            name="Show Raw Verts",
            description = "Display the raw contour verts",
            default=False,
            )

    show_cut_indices = BoolProperty(
            name="Show Cut Indices",
            description = "Display the order the operator stores cuts. Usually only turned on for debugging",
            default=False,
            )

    new_method = BoolProperty(
            name="New Method",
            description = "Use robust cutting, may be slower, more accurate on dense meshes",
            default=True,
            )

    distraction_free = BoolProperty(
            name = "distraction_free",
            description = "Switch to distraction-free mode",
            default = False,
            )
    
    symmetry_plane = EnumProperty(
        items=[
            ('none', 'None', 'Disable symmetry plane'),
            ('x', 'X', 'Clip to X-axis (YZ plane)'),
            # ('y', 'Y', 'Clip to Y-axis (XZ plane)'),
            # ('z', 'Z', 'Clip to Z-axis (XY plane)'),
            ],
        name='Symmetry Plane',
        description = "Clamp and clip to symmetry plane",
        default='none'
        )


    def draw(self, context):
        
        layout = self.layout

        row = layout.row(align=True)
        row.prop(self, "theme", "Theme")
        row.prop(self,"show_help")
        row.prop(self,"help_def")
        
        ## Polystrips 
        row = layout.row(align=True)
        row.label("POLYSTRIPS SETTINGS:")

        row = layout.row(align=True)
        row.prop(self, "use_pressure")
        row.prop(self, "show_segment_count")

        ##Contours
        row = layout.row(align=True)
        row.label("CONTOURS SETTINGS:")

        # Interaction Settings
        row = layout.row(align=True)
        row.prop(self, "use_x_ray", "Enable X-Ray at Mesh Creation")
        row.prop(self, "smooth_method", text="Smoothing Method")

        # Widget Settings
        row = layout.row()
        row.prop(self,"draw_widget", text="Display Widget")

        ## Debug Settings
        box = layout.box().column(align=False)
        row = box.row()
        row.label(text="Debug Settings")

        row = box.row()
        row.prop(self, "show_debug", text="Show Debug Settings")
        
        if self.show_debug:
            row = box.row()
            row.prop(self, "new_method")
            row.prop(self, "debug")
            
            
            row = box.row()
            row.prop(self, "vert_inds", text="Show Vertex Indices")
            row.prop(self, "simple_vert_inds", text="Show Simple Indices")

            row = box.row()
            row.prop(self, "show_verts", text="Show Raw Vertices")
            row.prop(self, "raw_vert_size")
            
            row = box.row()
            row.prop(self, "show_backbone", text="Show Backbone")
            row.prop(self, "show_nodes", text="Show Cut Nodes")
            row.prop(self, "show_ring_inds", text="Show Ring Indices")


class CGCOOKIE_OT_retopoflow_panel(bpy.types.Panel):
    '''RetopoFlow Tools'''
    bl_category = "Retopology"
    bl_label = "RetopoFlow"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'

    @classmethod
    def poll(cls, context):
        mode = bpy.context.mode
        obj = context.active_object
        return (obj and obj.type == 'MESH' and mode in ('OBJECT', 'EDIT_MESH'))

    def draw(self, context):
        layout = self.layout

        settings = common_utilities.get_settings()

        col = layout.column(align=True)

        if bversion > '002.074.004':
            icons = icon_collections["main"]

            contours_icon = icons.get("rf_contours_icon")
            col.operator("cgcookie.contours", icon_value=contours_icon.icon_id)
        else:
            col.operator("cgcookie.contours", icon='IPO_LINEAR')

        box = layout.box()
        row = box.row()

        row.prop(settings, "contour_panel_settings")

        if settings.contour_panel_settings:
            col = box.column()
            col.prop(settings, "vertex_count")

            col.label("Guide Mode:")
            col.prop(settings, "ring_count")

            col.label("Cache:")
            col.prop(settings, "recover", text="Recover")

            if settings.recover:
                col.prop(settings, "recover_clip")

            col.operator("cgcookie.contours_clear_cache", text = "Clear Cache", icon = 'CANCEL')

        col = layout.column(align=True)
        if bversion > '002.074.004':
            polystrips_icon = icons.get("rf_polystrips_icon")
            col.operator("cgcookie.polystrips", icon_value=polystrips_icon.icon_id)
        else:
            col.operator("cgcookie.polystrips", icon='IPO_BEZIER')



        box = layout.box()
        row = box.row()

        row.prop(settings, "polystrips_panel_settings")

        if settings.polystrips_panel_settings:
            col = box.column()
            col.prop(settings, "symmetry_plane", text ="Symmetry Plane")


class CGCOOKIE_OT_retopoflow_menu(bpy.types.Menu):  
    bl_label = "Retopology"
    bl_space_type = 'VIEW_3D'
    bl_idname = "object.retopology_menu"

    def draw(self, context):
        layout = self.layout

        layout.operator_context = 'INVOKE_DEFAULT'

        layout.operator("cgcookie.contours", icon="IPO_LINEAR")
        layout.operator("cgcookie.polystrips", icon="IPO_BEZIER")


################### Contours ###################

def object_validation(ob):
    me = ob.data

    # get object data to act as a hash
    counts = (len(me.vertices), len(me.edges), len(me.polygons), len(ob.modifiers))
    bbox   = (tuple(min(v.co for v in me.vertices)), tuple(max(v.co for v in me.vertices)))
    vsum   = tuple(sum((v.co for v in me.vertices), Vector((0,0,0))))

    return (ob.name, counts, bbox, vsum)


def is_object_valid(ob):
    global contour_mesh_cache
    if 'valid' not in contour_mesh_cache: return False
    return contour_mesh_cache['valid'] == object_validation(ob)


def write_mesh_cache(orig_ob,tmp_ob, bme):
    print('writing mesh cache')
    global contour_mesh_cache
    contour_mesh_cache['valid'] = object_validation(orig_ob)
    contour_mesh_cache['bme'] = bme
    contour_mesh_cache['tmp'] = tmp_ob


def clear_mesh_cache():
    print('clearing mesh cache')

    global contour_mesh_cache

    if 'valid' in contour_mesh_cache and contour_mesh_cache['valid']:
        del contour_mesh_cache['valid']

    if 'bme' in contour_mesh_cache and contour_mesh_cache['bme']:
        bme_old = contour_mesh_cache['bme']
        bme_old.free()
        del contour_mesh_cache['bme']

    if 'tmp' in contour_mesh_cache and contour_mesh_cache['tmp']:
        old_obj = contour_mesh_cache['tmp']
        #context.scene.objects.unlink(self.tmp_ob)
        old_me = old_obj.data
        old_obj.user_clear()
        if old_obj and old_obj.name in bpy.data.objects:
            bpy.data.objects.remove(old_obj)
        if old_me and old_me.name in bpy.data.meshes:
            bpy.data.meshes.remove(old_me)
        del contour_mesh_cache['tmp']


class CGCOOKIE_OT_contours_cache_clear(bpy.types.Operator):
    '''Removes the temporary object and mesh data from the cache. Do this if you have altered your original form in any way'''
    bl_idname = "cgcookie.contours_clear_cache"
    bl_label = "Clear Contour Cache" 

    def execute(self,context):

        clear_mesh_cache()

        return {'FINISHED'}



  
class CGCOOKIE_OT_contours(bpy.types.Operator):
    '''Draw Strokes Perpindicular to Cylindrical Forms to Retopologize Them'''
    bl_idname = "cgcookie.contours"
    bl_label = "Contours"
    
    @classmethod
    def poll(cls,context):
        if context.mode not in {'EDIT_MESH','OBJECT'}:
            return False
        
        if context.active_object:
            if context.mode == 'EDIT_MESH':
                if len(context.selected_objects) > 1:
                    return True
                else:
                    return False
            else:
                return context.object.type == 'MESH'
        else:
            return False
    
    #####drawing#######
    def draw_callback(self,context):

        settings = common_utilities.get_settings()
        r3d = context.space_data.region_3d
        if context.space_data.use_occlude_geometry:
            new_matrix = [v for l in r3d.view_matrix for v in l]
            if new_matrix != self.last_matrix:
                for path in self.cut_paths:
                    path.update_visibility(context, self.original_form)
                    for cut_line in path.cuts:
                        cut_line.update_visibility(context, self.original_form)
                            
            self.post_update = False
            self.last_matrix = new_matrix
            
    
        for i, c_cut in enumerate(self.cut_lines):
            if self.widget_interaction and self.drag_target == c_cut:
                interact = True
            else:
                interact = False
            
            c_cut.draw(context, settings)#,three_dimensional = self.navigating, interacting = interact)
    
            if c_cut.verts_simple != [] and settings.show_cut_indices:
                loc = location_3d_to_region_2d(context.region, context.space_data.region_3d, c_cut.verts_simple[0])
                blf.position(0, loc[0], loc[1], 0)
                blf.draw(0, str(i))
    
    
        if self.cut_line_widget and settings.draw_widget:
            self.cut_line_widget.draw(context)
            
        if len(self.sketch):
            common_drawing.draw_polyline_from_points(context, self.sketch, self.snap_color, 2, "GL_LINE_SMOOTH")
            
        if len(self.cut_paths):
            for path in self.cut_paths:
                path.draw(context, path = False, nodes = settings.show_nodes, rings = True, follows = True, backbone = settings.show_backbone    )
                
        if len(self.snap_circle):
            common_drawing.draw_polyline_from_points(context, self.snap_circle, self.snap_color, 2, "GL_LINE_SMOOTH")

        if settings.show_help:
            self.help_box.draw()
    ####Blender Mesh Data Management####
    
    def new_destination_obj(self,context,name, mx):
        '''
        creates new object for mesh data to enter
        '''
        dest_me = bpy.data.meshes.new(name)
        dest_ob = bpy.data.objects.new(name,dest_me) #this is an empty currently
        dest_ob.matrix_world = mx
        dest_ob.update_tag()
        dest_bme = bmesh.new()
        dest_bme.from_mesh(dest_me)
        
        return dest_ob, dest_me, dest_bme
    
    def tmp_obj_and_triangulate(self,context, bme, ngons, mx):
        '''
        ob -  input object
        bme - bmesh extracted from input object <- this will be modified by triangulation
        ngons - list of bmesh faces that are ngons
        '''
        
        if len(ngons):
            new_geom = bmesh.ops.triangulate(bme, faces = ngons, quad_method=0, ngon_method=1)
            new_faces = new_geom['faces']

        new_me = bpy.data.meshes.new('tmp_recontour_mesh')
        bme.to_mesh(new_me)
        new_me.update()
        tmp_ob = bpy.data.objects.new('ContourTMP', new_me)
        
        #ob must be linked to scene for ray casting?
        context.scene.objects.link(tmp_ob)
        tmp_ob.update_tag()
        context.scene.update()
        #however it can be unlinked to prevent user from seeing it?
        context.scene.objects.unlink(tmp_ob)
        tmp_ob.matrix_world = mx
        
        return tmp_ob
    
    def mesh_data_gather_object_mode(self,context):
        '''
        get references to object and object data
        '''
        
        self.sel_edge = None
        self.sel_verts = None
        self.existing_cut = None
        ob = context.object
        tmp_ob = None
        
        name = ob.name + '_recontour'
        self.dest_ob, self.dest_me, self.dest_bme = self.new_destination_obj(context, name, ob.matrix_world)
        
        
        is_valid = is_object_valid(context.object)
        has_tmp = 'ContourTMP' in bpy.data.objects and bpy.data.objects['ContourTMP'].data
        
        if is_valid and has_tmp:
            self.bme = contour_mesh_cache['bme']            
            tmp_ob = contour_mesh_cache['tmp']
            
        else:
            clear_mesh_cache()
            
            me = ob.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
            
            self.bme = bmesh.new()
            self.bme.from_mesh(me)
            ngons = [f for f in self.bme.faces if len(f.verts) > 4]
            if len(ngons) or len(ob.modifiers) > 0:
                tmp_ob= self.tmp_obj_and_triangulate(context, self.bme, ngons, ob.matrix_world)
                
        if tmp_ob:
            self.original_form = tmp_ob
        else:
            self.original_form = ob
        
        if self.settings.recover and is_valid:
            print('loading cache!')
            self.undo_action()
            return
        else:
            print('no recover or not valid or something')
            global contour_undo_cache
            contour_undo_cache = []
            
        write_mesh_cache(ob,tmp_ob, self.bme)
        
    def mesh_data_gather_edit_mode(self,context):
        '''
        get references to object and object data
        '''
        
        self.dest_ob = context.object        
        self.dest_me = self.dest_ob.data
        self.dest_bme = bmesh.from_edit_mesh(self.dest_me)
        
        ob = [obj for obj in context.selected_objects if obj.name != context.object.name][0]
        is_valid = is_object_valid(ob)
        tmp_ob = None
        
        
        if is_valid:
            self.bme = contour_mesh_cache['bme']            
            tmp_ob = contour_mesh_cache['tmp']
        else:
            clear_mesh_cache()
            me = ob.to_mesh(scene=context.scene, apply_modifiers=True, settings='PREVIEW')
            me.update()
            
            self.bme = bmesh.new()
            self.bme.from_mesh(me)
            ngons = [f for f in self.bme.faces if len(f.verts) > 4]
            if len(ngons) or len(ob.modifiers) > 0:
                tmp_ob = self.tmp_obj_and_triangulate(context, self.bme, ngons, ob.matrix_world)
        
        if tmp_ob:
            print('Load form cache tmp obj, original form set')
            self.original_form = tmp_ob
        else:
            print('Load new obj, original form set')
            self.original_form = ob
        
        self.tmp_ob = tmp_ob
        
        if self.settings.recover and is_valid:
            print('loading cache!')
            self.undo_action()
            return
        
        else:
            global contour_undo_cache
            contour_undo_cache = []
            
            
        #count and collect the selected edges if any
        ed_inds = [ed.index for ed in self.dest_bme.edges if ed.select and len(ed.link_faces) < 2]
        
        self.existing_loops = []
        if len(ed_inds):
            vert_loops = contour_utilities.edge_loops_from_bmedges(self.dest_bme, ed_inds)

            if len(vert_loops) > 1:
                self.report({'WARNING'}, 'Only one edge loop will be used for extension')
            print('there are %i edge loops selected' % len(vert_loops))
            
            #for loop in vert_loops:
            #until multi loops are supported, do this    
            loop = vert_loops[0]
            if loop[-1] != loop[0] and len(list(set(loop))) != len(loop):
                self.report({'WARNING'},'Edge loop selection has extra parts!  Excluding this loop')
                
            else:
                lverts = [self.dest_bme.verts[i] for i in loop]
                
                existing_loop =ExistingVertList(context,
                                                lverts, 
                                                loop, 
                                                self.dest_ob.matrix_world,
                                                key_type = 'INDS')
                
                #make a blank path with just an existing head
                path = ContourCutSeries(context, [],
                                cull_factor = self.settings.cull_factor, 
                                smooth_factor = self.settings.smooth_factor,
                                feature_factor = self.settings.feature_factor)
            
                
                path.existing_head = existing_loop
                path.seg_lock = False
                path.ring_lock = True
                path.ring_segments = len(existing_loop.verts_simple)
                path.connect_cuts_to_make_mesh(ob)
                path.update_visibility(context, ob)
            
                #path.update_visibility(context, self.original_form)
                
                self.cut_paths.append(path)
                self.existing_loops.append(existing_loop)
        
        write_mesh_cache(ob,tmp_ob, self.bme)        
            
    def finish_mesh(self, context):
        back_to_edit = (context.mode == 'EDIT_MESH')
                    
        #This is where all the magic happens
        print('pushing data into bmesh')
        for path in self.cut_paths:
            path.push_data_into_bmesh(context, self.dest_ob, self.dest_bme, self.original_form, self.dest_me)
        
        if back_to_edit:
            print('updating edit mesh')
            bmesh.update_edit_mesh(self.dest_me, tessface=False, destructive=True)
        
        else:
            #write the data into the object
            print('write data into the object')
            self.dest_bme.to_mesh(self.dest_me)
        
            #remember we created a new object
            print('link destination object')
            context.scene.objects.link(self.dest_ob)
            
            print('select and make active')
            self.dest_ob.select = True
            context.scene.objects.active = self.dest_ob
            
            if context.space_data.local_view:
                view_loc = context.space_data.region_3d.view_location.copy()
                view_rot = context.space_data.region_3d.view_rotation.copy()
                view_dist = context.space_data.region_3d.view_distance
                bpy.ops.view3d.localview()
                bpy.ops.view3d.localview()
                #context.space_data.region_3d.view_matrix = mx_copy
                context.space_data.region_3d.view_location = view_loc
                context.space_data.region_3d.view_rotation = view_rot
                context.space_data.region_3d.view_distance = view_dist
                context.space_data.region_3d.update()
    
        return
    
    ####User Interface and Feedback functions####
    
    def get_event_details(self, context, event):
        event_ctrl    = 'CTRL+'  if event.ctrl  else ''
        event_shift   = 'SHIFT+' if event.shift else ''
        event_alt     = 'ALT+'   if event.alt   else ''
        event_ftype   = event_ctrl + event_shift + event_alt + event.type
        
        
        return {
            'context':  context,
            'region':   context.region,
            'r3d':      context.space_data.region_3d,
            
            'ctrl':     event.ctrl,
            'shift':    event.shift,
            'alt':      event.alt,
            'value':    event.value,
            'type':     event.type,
            'ftype':    event_ftype,
            'press':    event_ftype if event.value=='PRESS'   else None,
            'release':  event_ftype if event.value=='RELEASE' else None,
            
            'mouse':    (float(event.mouse_region_x), float(event.mouse_region_y)),
            'pressure': 1 if not hasattr(event, 'pressure') else event.pressure
            }
    
    
    def temporary_message_start(self,context, message):
        self.msg_start_time = time.time()
        if not self._timer:
            self._timer = context.window_manager.event_timer_add(0.1, context.window)
        
        context.area.header_text_set(text = message)  
        return
    
    def check_message(self,context):
        
        now = time.time()
        if now - self.msg_start_time > self.msg_duration:
            self.kill_timer(context)
            
            if self.mode in {'main guide', 'sketch'}:
                context.area.header_text_set(text = self.guide_msg)
            else:
                context.area.header_text_set(text = self.loop_msg)
    ####UNDO/Operator Data management####
        
    def create_undo_snapshot(self, action):
        '''
        saves data and operator state snapshot
        for undoing
        
        TODO:  perhaps pop/append are not fastest way
        deque?
        prepare a list and keep track of which entity to
        replace?
        '''
        
        repeated_actions = {'LOOP_SHIFT', 'PATH_SHIFT', 'PATH_SEGMENTS', 'LOOP_SEGMENTS'}
        
        if action in repeated_actions:
            if action == contour_undo_cache[-1][2]:
                print('repeatable...dont take snapshot')
                return
        
        print('undo: ' + action)    
        cut_data = copy.deepcopy(self.cut_paths)
        #perhaps I don't even need to copy this?
        state = copy.deepcopy(ContourStatePreserver(self))
        contour_undo_cache.append((cut_data, state, action))
            
        if len(contour_undo_cache) > self.settings.undo_depth:
            contour_undo_cache.pop(0)
            
    def undo_action(self):
        if len(contour_undo_cache) > 0:
            cut_data, op_state, action = contour_undo_cache.pop()
            
            self.cut_paths = cut_data
            op_state.push_state(self)
            
    def kill_timer(self, context):
        if not self._timer: return
        context.window_manager.event_timer_remove(self._timer)
        self._timer = None

    ####Strokes and Cutting####
    
    def new_path_from_draw(self,context,settings):
        '''
        package all the steps needed to make a new path
        TODO: What if errors?
        '''
        path = ContourCutSeries(context, self.sketch,
                                    segments = settings.ring_count,
                                    ring_segments = settings.vertex_count,
                                    cull_factor = settings.cull_factor, 
                                    smooth_factor = settings.smooth_factor,
                                    feature_factor = settings.feature_factor)
        
        
        path.ray_cast_path(context, self.original_form)
        if len(path.raw_world) == 0:
            print('NO RAW PATH')
            return None
        
        self.create_undo_snapshot('NEW_PATH')
        path.find_knots()
        
        if self.snap != [] and not self.force_new:
            merge_series = self.snap[0]
            merge_ring = self.snap[1]
            
            path.snap_merge_into_other(merge_series, merge_ring, context, self.original_form, self.bme)
            
            return merge_series

        path.smooth_path(context, ob = self.original_form)
        path.create_cut_nodes(context)
        path.snap_to_object(self.original_form, raw = False, world = False, cuts = True)
        path.cuts_on_path(context, self.original_form, self.bme)
        path.connect_cuts_to_make_mesh(self.original_form)
        path.backbone_from_cuts(context, self.original_form, self.bme)
        path.update_visibility(context, self.original_form)
        if path.cuts:
            # TODO: should this ever be empty?
            path.cuts[-1].do_select(settings)
        
        self.cut_paths.append(path)
        

        return path

    def sketch_confirm(self,context):
        #make sure we meant it
        if len(self.sketch) < 10:
            print('too short!')
            return
        
        for path in self.cut_paths:
            path.deselect(self.settings)
        
        print('attempt a new path')                    
        self.sel_path  = self.new_path_from_draw(context, self.settings)
        if self.sel_path:
            print('a new path was made')
            self.sel_path.do_select(self.settings)
            if self.sel_path.cuts:
                self.sel_cut = self.sel_path.cuts[-1]
            else:
                self.sel_cut = None
            if self.sel_cut:
                self.sel_cut.do_select(self.settings)
        self.force_new = False
        print('we deselected everyting')
        self.sketch = []
 
    def click_new_cut(self,context, settings, x,y):
        self.create_undo_snapshot('NEW')
        stroke_color = settings.theme_colors_active[settings.theme]
        mesh_color = settings.theme_colors_mesh[settings.theme]

        new_cut = ContourCutLine(x, y)
        
        for path in self.cut_paths:
            for cut in path.cuts:
                cut.deselect(settings)
                
        new_cut.do_select(settings)
        self.cut_lines.append(new_cut)
        
        return new_cut
           
    def release_place_cut(self,context,settings, x, y):

        self.sel_loop.tail.x = x
        self.sel_loop.tail.y = y

        width = Vector((self.sel_loop.head.x, self.sel_loop.head.y)) - Vector((x,y))

        #prevent small errant strokes
        if width.length in range(5, 20): #TODO: Setting for minimum pixel width
            self.cut_lines.remove(self.sel_loop)
            self.sel_loop = None
            showErrorMessage('The drawn cut must be more than 20 pixels')
            return

        elif width.length < 5:
            self.cut_lines.remove(self.sel_loop)
            # self.sel_loop = None
            return
        else: 
            #hit the mesh for the first time
            hit = self.sel_loop.hit_object(context, self.original_form, method = 'VIEW')

            if not hit:
                self.cut_lines.remove(self.sel_loop)
                self.sel_loop = None
                showErrorMessage('The middle of the cut must be over the object!')

                return

            self.sel_loop.cut_object(context, self.original_form, self.bme)
            self.sel_loop.simplify_cross(self.segments)
            self.sel_loop.update_com()
            self.sel_loop.update_screen_coords(context)
            self.sel_loop.head = None
            self.sel_loop.tail = None

            if not len(self.sel_loop.verts) or not len(self.sel_loop.verts_simple):
                self.sel_loop = None
                showErrorMessage('The cut failed for some reason, most likely topology, try again and report bug')
                return


            if settings.debug > 1:
                print('release_place_cut')
                print('len(self.cut_paths) = %d' % len(self.cut_paths))
                print('self.force_new = ' + str(self.force_new))

            if self.cut_paths != [] and not self.force_new:
                for path in self.cut_paths:
                    if path.insert_new_cut(context, self.original_form, self.bme, self.sel_loop, search = settings.search_factor):
                        #the cut belongs to the series now
                        path.connect_cuts_to_make_mesh(self.original_form)
                        path.update_visibility(context, self.original_form)
                        path.seg_lock = True
                        path.do_select(settings)
                        path.unhighlight(settings)
                        self.sel_path = path
                        self.cut_lines.remove(self.sel_loop)
                        for other_path in self.cut_paths:
                            if other_path != self.sel_path:
                                other_path.deselect(settings)
                        # no need to search for more paths
                        return

            #create a blank segment
            path = ContourCutSeries(context, [],
                            cull_factor = settings.cull_factor,
                            smooth_factor = settings.smooth_factor,
                            feature_factor = settings.feature_factor)

            path.insert_new_cut(context, self.original_form, self.bme, self.sel_loop, search = settings.search_factor)
            path.seg_lock = False  #not locked yet...not until a 2nd cut is added in loop mode
            path.segments = 1
            path.ring_segments = len(self.sel_loop.verts_simple)
            path.connect_cuts_to_make_mesh(self.original_form)
            path.update_visibility(context, self.original_form)

            for other_path in self.cut_paths:
                other_path.deselect(settings)

            self.cut_paths.append(path)
            self.sel_path = path
            path.do_select(settings)

            self.cut_lines.remove(self.sel_loop)
            self.force_new = False

            return

    
    ####Hover and Selection####
    
    def hover_guide_mode(self,context, settings, x, y):
        '''
        handles mouse selection, hovering, highlighting
        and snapping when the mouse moves in guide
        mode
        '''
        
        handle_color = settings.theme_colors_active[settings.theme]

        self.help_box.hover(x,y)
        #identify hover target for highlighting
        if self.cut_paths != []:
            target_at_all = False
            breakout = False
            for path in self.cut_paths:
                if not path.select:
                    path.unhighlight(settings)
                for c_cut in path.cuts:                    
                    h_target = c_cut.active_element(context,x,y)
                    if h_target:
                        path.highlight(settings)
                        target_at_all = True
                        self.hover_target = path
                        breakout = True
                        break
                
                if breakout:
                    break
                                  
            if not target_at_all:
                self.hover_target = None
        
        #assess snap points
        if self.cut_paths != [] and not self.force_new:
            rv3d = context.space_data.region_3d
            breakout = False
            snapped = False
            for path in self.cut_paths:
                
                end_cuts = []
                if not path.existing_head and len(path.cuts):
                    end_cuts.append(path.cuts[0])
                if not path.existing_tail and len(path.cuts):
                    end_cuts.append(path.cuts[-1])
                    
                if path.existing_head and not len(path.cuts):
                    end_cuts.append(path.existing_head)
                    
                for n, end_cut in enumerate(end_cuts):
                    
                    #potential verts to snap to
                    snaps = [v for i, v in enumerate(end_cut.verts_simple) if end_cut.verts_simple_visible[i]]
                    #the screen versions os those
                    screen_snaps = [location_3d_to_region_2d(context.region,rv3d,snap) for snap in snaps]
                    
                    mouse = Vector((x,y))
                    dists = [(mouse - snap).length for snap in screen_snaps]
                    
                    if len(dists):
                        best = min(dists)
                        if best < 2 * settings.extend_radius and best > 4: #TODO unify selection mouse pixel radius.

                            best_vert = screen_snaps[dists.index(best)]
                            view_z = rv3d.view_rotation * Vector((0,0,1))
                            if view_z.dot(end_cut.plane_no) > -.75 and view_z.dot(end_cut.plane_no) < .75:

                                imx = rv3d.view_matrix.inverted()
                                normal_3d = imx.transposed() * end_cut.plane_no
                                if n == 1 or len(end_cuts) == 1:
                                    normal_3d = -1 * normal_3d
                                screen_no = Vector((normal_3d[0],normal_3d[1]))
                                angle = math.atan2(screen_no[1],screen_no[0]) - 1/2 * math.pi
                                left = angle + math.pi
                                right =  angle
                                self.snap = [path, end_cut]
                                
                                if end_cut.desc == 'CUT_LINE' and len(path.cuts) > 1:
    
                                    self.snap_circle = contour_utilities.pi_slice(best_vert[0],best_vert[1],settings.extend_radius,.1 * settings.extend_radius, left,right, 20,t_fan = True)
                                    self.snap_circle.append(self.snap_circle[0])
                                else:
                                    self.snap_circle = contour_utilities.simple_circle(best_vert[0], best_vert[1], settings.extend_radius, 20)
                                    self.snap_circle.append(self.snap_circle[0])
                                    
                                breakout = True
                                if best < settings.extend_radius:
                                    snapped = True
                                    self.snap_color = (handle_color[0], handle_color[1], handle_color[2], 1.00)
                                    
                                else:
                                    alpha = 1 - best/(2*settings.extend_radius)
                                    self.snap_color = (handle_color[0], handle_color[1], handle_color[2], 0.50)
                                    
                                break
                        
                    if breakout:
                        break
                    
            if not breakout:
                self.snap = []
                self.snap_circle = []
                
    def hover_loop_mode(self,context, settings, x,y):
        '''
        Handles mouse selection and hovering
        '''
        self.help_box.hover(x,y)
        #identify hover target for highlighting
        if self.cut_paths != []:
            new_target = False
            target_at_all = False
            
            for path in self.cut_paths:
                for c_cut in path.cuts:
                    if not c_cut.select:
                        c_cut.unhighlight(settings) 
                    
                    h_target = c_cut.active_element(context,x,y)
                    if h_target:
                        c_cut.highlight(settings)
                        target_at_all = True
                         
                        if (h_target != self.hover_target) or (h_target.select and not self.cut_line_widget):
                            
                            self.hover_target = h_target
                            if self.hover_target.desc == 'CUT_LINE':

                                if self.hover_target.select:
                                    for possible_parent in self.cut_paths:
                                        if self.hover_target in possible_parent.cuts:
                                            parent_path = possible_parent
                                            break
                                    
                                    #spawn a new widget        
                                    self.cut_line_widget = CutLineManipulatorWidget(context, 
                                                                                    settings,
                                                                                    self.original_form, self.bme,
                                                                                    self.hover_target,
                                                                                    parent_path,
                                                                                    x,
                                                                                    y)
                                    self.cut_line_widget.derive_screen(context)
                                
                                else:
                                    self.cut_line_widget = None
                            
                        else:
                            if self.cut_line_widget:
                                self.cut_line_widget.x = x
                                self.cut_line_widget.y = y
                                self.cut_line_widget.derive_screen(context)
                    #elif not c_cut.select:
                        #c_cut.geom_color = (settings.geom_rgb[0],settings.geom_rgb[1],settings.geom_rgb[2],1)          
            if not target_at_all:
                self.hover_target = None
                self.cut_line_widget = None
    
    
    ####Non Interactive/Non Data Operators###
    def mode_set_guide(self,context):
        
        self.mode = 'main guide'
        self.sel_loop = None  #because loop may not exist after path level operations like changing n_rings
        if self.sel_path:
            self.sel_path.highlight(self.settings)
                    
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
            
        context.area.header_text_set(text = self.guide_msg)    
    
    def mode_set_loop(self):
        for path in self.cut_paths:
            for cut in path.cuts:
                cut.deselect(self.settings)
        if self.sel_path and len(self.sel_path.cuts):
            self.sel_loop = self.sel_path.cuts[-1]
            self.sel_path.cuts[-1].do_select(self.settings)
        
    #### Segment Operators####
    
    def segment_shift(self,context, up = True, s = 0.05):
        self.create_undo_snapshot('PATH_SHIFT')     
        for cut in self.sel_path.cuts:
            cut.shift += (-1 + 2 * up) * s
            cut.simplify_cross(self.sel_path.ring_segments)
                                
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.update_visibility(context, self.original_form)
        
    def segment_n_loops(self,context, path, n):
        if n < 3: return
        if not path.seg_lock:
            self.create_undo_snapshot('PATH_SEGMENTS')
            path.segments = n
            path.create_cut_nodes(context)
            path.snap_to_object(self.original_form, raw = False, world = False, cuts = True)
            path.cuts_on_path(context, self.original_form, self.bme)
            path.connect_cuts_to_make_mesh(self.original_form)
            path.update_visibility(context, self.original_form)
            path.backbone_from_cuts(context, self.original_form, self.bme)
    
    def segment_smooth(self,context, settings):
        method = settings.smooth_method
        if method not in {'PATH_NORMAL','CENTER_MASS','ENDPOINT'}: return
        
        self.create_undo_snapshot('SMOOTH')
        if method == 'PATH_NORMAL':
            #path.smooth_normals
            self.sel_path.average_normals(context, self.original_form, self.bme)
            self.temporary_message_start(context, 'Smooth normals based on drawn path')
            
        elif method == 'CENTER_MASS':
            #smooth CoM path
            self.temporary_message_start(context, 'Smooth normals based on CoM path')
            self.sel_path.smooth_normals_com(context, self.original_form, self.bme, iterations = 2)
        
        elif method == 'ENDPOINT':
            #path.interpolate_endpoints
            self.temporary_message_start(context, 'Smoothly interpolate normals between the endpoints')
            self.sel_path.interpolate_endpoints(context, self.original_form, self.bme)
       
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.backbone_from_cuts(context, self.original_form, self.bme) 
                   
    def cursor_to_segment(self, context):
        half = math.floor(len(self.sel_path.cuts)/2)
                            
        if math.fmod(len(self.sel_path.cuts), 2):  #5 segments is 6 rings
            loc = 0.5 * (self.sel_path.cuts[half].plane_com + self.sel_path.cuts[half+1].plane_com)
        else:
            loc = self.sel_path.cuts[half].plane_com
                            
        context.scene.cursor_location = loc
    
    #### Loop/Cut  Operators####
    def loop_select(self,context,eventd):
        
        if self.hover_target and self.hover_target != self.sel_loop:
                        
            self.sel_loop = self.hover_target    
            if not eventd['shift']:
                for path in self.cut_paths:
                    for cut in path.cuts:
                        cut.deselect(self.settings)  
                    if self.sel_loop in path.cuts and path != self.sel_path:
                            path.do_select(self.settings)
                            path.unhighlight(self.settings) #TODO, don't highlight in loop mode
                            self.sel_path = path
                    else:
                        path.deselect(self.settings)
                          
            #select the ring
            self.hover_target.do_select(self.settings)
            
            return True
        else:
            return False
                                        
    def loop_shift(self,context,eventd, shift = 0.05, up = True, undo = True):    
        if undo:
            self.create_undo_snapshot('LOOP_SHIFT')
            
        self.sel_loop.shift += shift * (-1 + 2 * up)
        self.sel_loop.simplify_cross(self.sel_path.ring_segments)
        
        for path in self.cut_paths:
            if self.sel_loop in path.cuts:
                path.connect_cuts_to_make_mesh(self.original_form)
                path.update_backbone(context, self.original_form, self.bme, self.sel_loop, insert = False)
                path.update_visibility(context, self.original_form)

               
    def loop_nverts_change(self, context, eventd, n):
        if n < 3:
            n = 3
            
        self.create_undo_snapshot('RING_SEGMENTS')  
        
        for path in self.cut_paths:
            if self.sel_loop in path.cuts:
                if not path.ring_lock:
                    old_segments = path.ring_segments
                    path.ring_segments = n
                        
                    for cut in path.cuts:
                        new_bulk_shift = round(cut.shift * old_segments/path.ring_segments)
                        new_fine_shift = old_segments/path.ring_segments * cut.shift - new_bulk_shift
                        
                        
                        new_shift =  path.ring_segments/old_segments * cut.shift
                        
                        print(new_shift - new_bulk_shift - new_fine_shift)
                        cut.shift = new_shift
                        cut.simplify_cross(path.ring_segments)
                    
                    path.backbone_from_cuts(context, self.original_form, self.bme)    
                    path.connect_cuts_to_make_mesh(self.original_form)
                    path.update_visibility(context, self.original_form)
                    
                    self.temporary_message_start(context, 'RING SEGMENTS %i' %path.ring_segments)
                    self.msg_start_time = time.time()
                else:
                    self.temporary_message_start(context, 'RING SEGMENTS: Can not be changed.  Path Locked')
        
    def loop_align(self,context, eventd, undo = True):
        
        if undo:
            self.create_undo_snapshot('ALIGN')
        #if not event.ctrl and not event.shift:
        act = 'BETWEEN'
        #act = 'FORWARD'
        #act = 'BACKWARD'
            
        self.sel_path.align_cut(self.sel_loop, mode = act, fine_grain = True)
        self.sel_loop.simplify_cross(self.sel_path.ring_segments)
        
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.update_backbone(context, self.original_form, self.bme, self.sel_loop, insert = False)
        self.sel_path.update_visibility(context, self.original_form)
        
    
    def loops_delete(self,context,loops, undo = True):
        '''
        removes a cut from a path
        if it's the only cut, removes the whole path
        ready for multipl selected cuts: TODO test
        '''
        if undo:
            self.create_undo_snapshot('DELETE')
        
        #Identify the paths
        update_paths = set()
        remove_paths = set()
        for loop in loops:
            for path in self.cut_paths:
                if loop in path.cuts:
                    if len(path.cuts) > 1 or len(path.cuts) == 1 and path.existing_head:
                        path.remove_cut(context, self.original_form, self.bme, loop)
                        if path not in update_paths:
                            update_paths.add(path)
                            
                        
                        
                    else:
                        if path not in remove_paths:
                            remove_paths.add(path)
        for u_path in update_paths - remove_paths:
            u_path.connect_cuts_to_make_mesh(self.original_form)
            u_path.update_visibility(context, self.original_form)
            u_path.backbone_from_cuts(context, self.original_form, self.bme)                
        
        
        for r_path in remove_paths:
            
            self.cut_paths.remove(r_path)
            
        self.sel_path = None
        self.sel_loop = None
    
    
    ####Interactive/Modal Operators
    
    def prepare_rotate(self,context, eventd, undo = True):
        '''
        TODO path from selected loop
        '''
        if undo:
            self.create_undo_snapshot('ROTATE')
        
        #TODO...if CoM is off screen, then what?
        x,y = eventd['mouse']
        screen_pivot = location_3d_to_region_2d(context.region,context.space_data.region_3d,self.sel_loop.plane_com)
        self.cut_line_widget = CutLineManipulatorWidget(context, self.settings, 
                                                        self.original_form, self.bme,
                                                        self.sel_loop,
                                                        self.sel_path,
                                                        screen_pivot[0],screen_pivot[1],
                                                        hotkey = True)
        self.cut_line_widget.transform_mode = 'ROTATE_VIEW'
        self.cut_line_widget.initial_x = x
        self.cut_line_widget.initial_y = y
        self.cut_line_widget.derive_screen(context)
        
    def prepare_translate(self,context, eventd, undo = True):
        '''
        TODO path from selected loop
        '''
        if undo:
            self.create_undo_snapshot('EDGE_SLIDE')
        
        x,y = eventd['mouse']
        self.cut_line_widget = CutLineManipulatorWidget(context, self.settings, 
                                                        self.original_form, self.bme,
                                                        self.sel_loop,
                                                        self.sel_path,
                                                        x,y,
                                                        hotkey = True)
        self.cut_line_widget.transform_mode = 'EDGE_SLIDE'    
        self.cut_line_widget.initial_x = x
        self.cut_line_widget.initial_y = y
        self.cut_line_widget.derive_screen(context)
    
    def prepare_widget(self, eventd):
        '''
        widget already exists
        '''
        self.create_undo_snapshot('WIDGET_TRANSFORM')
        self.cut_line_widget.derive_screen(eventd['context'])
        
    def widget_transform(self,context,settings, eventd):
        
        x,y = eventd['mouse']
        shft = eventd['shift']
        self.cut_line_widget.user_interaction(context, x, y, shift = shft)
        
        self.sel_loop.cut_object(context, self.original_form, self.bme)
        self.sel_loop.simplify_cross(self.sel_path.ring_segments)
        self.sel_loop.update_com()
        self.sel_path.align_cut(self.sel_loop, mode = 'BETWEEN', fine_grain = True)
        
        self.sel_path.connect_cuts_to_make_mesh(self.original_form)
        self.sel_path.update_visibility(context, self.original_form)
        
        self.temporary_message_start(context, 'WIDGET_TRANSFORM: ' + str(self.cut_line_widget.transform_mode))    

    ########################
    #### modal functions####
    
    def modal_nav(self, eventd):
        events_nav = self.keymap['navigate']
        handle_nav = False
        handle_nav |= eventd['ftype'] in events_nav
        
        if handle_nav: return 'nav'
            
        return ''
         
    def modal_loop(self, eventd): 
        self.footer = 'Loop Mode'
        
        #############################################
        # general navigation
        nmode = self.modal_nav(eventd)
        if nmode:
            return nmode  #stop here and tell parent modal to 'PASS_THROUGH'
        
        ########################################
        # accept / cancel hard coded
        if eventd['press'] in self.keymap['help']:
            if  self.help_box.is_collapsed:
                self.help_box.uncollapse()
            else:
                self.help_box.collapse()
            self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
        
        if eventd['press'] in self.keymap['confirm']:
            self.finish_mesh(eventd['context'])
            eventd['context'].area.header_text_set()
            return 'finish'
        
        if eventd['press'] in self.keymap['cancel']:
            eventd['context'].area.header_text_set()
            return 'cancel'
        
        #####################################
        # general, non modal commands
        if eventd['press'] in self.keymap['undo']:
            print('undo it!')
            self.undo_action()
            self.temporary_message_start(eventd['context'], "UNDO: %i steps in undo_cache" % len(contour_undo_cache))
            return ''
        
        if eventd['press'] in self.keymap['mode']:
            self.footer = 'Guide Mode'
            self.mode_set_guide(eventd['context'])
            return 'main guide'
     
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering widget
            x,y = eventd['mouse']
            self.hover_loop_mode(eventd['context'], self.settings, x,y)
            return ''
        
        if eventd['press'] in selection_mouse(): #self.keymap['select']: # selection
            ret = self.loop_select(eventd['context'], eventd)
            if ret:
                return ''
        
   
        if eventd['press'] in self.keymap['action']:   # cutting and widget hard coded to LMB
            if self.help_box.is_hovered:
                if  self.help_box.is_collapsed:
                    self.help_box.uncollapse()
                else:
                    self.help_box.collapse()
                self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
            
                return ''
            
            if self.cut_line_widget:
                self.prepare_widget(eventd)
                
                return 'widget'
            
            else:
                self.footer = 'Cutting'
                x,y = eventd['mouse']
                self.sel_loop = self.click_new_cut(eventd['context'], self.settings, x,y)    
                return 'cutting'
        
        if eventd['press'] in self.keymap['new']:
            self.force_new = self.force_new != True
            return ''
        ###################################
        # selected contour loop commands
        
        if self.sel_loop:
            if eventd['press'] in self.keymap['delete']:
                
                self.loops_delete(eventd['context'], [self.sel_loop])
                self.temporary_message_start(eventd['context'], 'DELETE')
                return ''
            

            if eventd['press'] in self.keymap['rotate']:
                self.prepare_rotate(eventd['context'],eventd)
                #header text handled during rotation
                return 'widget'
            
            if eventd['press'] in self.keymap['translate']:
                self.prepare_translate(eventd['context'], eventd)
                #header text handled during translation
                return 'widget'
            
            if eventd['press'] in self.keymap['align']:
                self.loop_align(eventd['context'], eventd)
                self.temporary_message_start(eventd['context'], 'ALIGN LOOP')
                return ''
            
            if eventd['press'] in self.keymap['up shift']:
                self.loop_shift(eventd['context'], eventd, up = True)
                self.temporary_message_start(eventd['context'], 'SHIFT: ' + str(self.sel_loop.shift))
                return ''
            
            if eventd['press'] in self.keymap['dn shift']:
                self.loop_shift(eventd['context'], eventd, up = False)
                self.temporary_message_start(eventd['context'], 'SHIFT: ' + str(self.sel_loop.shift))
                return ''
            
            if eventd['press'] in self.keymap['up count']:
                n = len(self.sel_loop.verts_simple)
                self.loop_nverts_change(eventd['context'], eventd, n+1)
                #message handled within op
                return ''
            
            if eventd['press'] in self.keymap['dn count']:
                n = len(self.sel_loop.verts_simple)
                self.loop_nverts_change(eventd['context'], eventd, n-1)
                #message handled within op
                return ''
            
            if eventd['press'] in self.keymap['snap cursor']:
                eventd['context'].scene.cursor_location = self.sel_loop.plane_com
                self.temporary_message_start(eventd['context'], "Cursor to loop")
                return ''
            
            if eventd['press'] in self.keymap['view cursor']:
                bpy.ops.view3d.view_center_cursor()
                self.temporary_message_start(eventd['context'], "View to cursor")
                return ''
                
        return ''
       
    def modal_guide(self, eventd):
        self.footer = 'Guide Mode'
        #############################################
        # general navigation
         
        nmode = self.modal_nav(eventd)
        if nmode:
            self.mode_last = 'main guide'
            return nmode
         
        ########################################
        #help
        if eventd['press'] in self.keymap['help']:
            if  self.help_box.is_collapsed:
                self.help_box.uncollapse()
            else:
                self.help_box.collapse()
            self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
            
        # accept / cancel 
        if eventd['press'] in self.keymap['confirm']:
            self.finish_mesh(eventd['context'])
            eventd['context'].area.header_text_set()
            return 'finish'
         
        if eventd['press'] in self.keymap['cancel']:
            eventd['context'].area.header_text_set()
            return 'cancel'
         
         
        if eventd['press'] in self.keymap['mode']:
            self.mode_set_loop()
            return 'main loop'
         
        if eventd['press'] in self.keymap['new']:
            self.force_new = self.force_new != True
            return '' 
        
        if eventd['press'] in self.keymap['undo']:
            self.undo_action()
            self.temporary_message_start(eventd['context'], "UNDO: %i steps remain in undo_cache" % len(contour_undo_cache))
            return ''
        
        #####################################
        # general, non modal commands
         
        if eventd['type'] == 'MOUSEMOVE':  #mouse movement/hovering widget
            x,y = eventd['mouse']
            self.hover_guide_mode(eventd['context'], self.settings, x, y)
            return ''
        
        if eventd['press'] in selection_mouse(): #self.keymap['select']: # selection
            if self.hover_target and self.hover_target.desc == 'CUT SERIES':
                self.hover_target.do_select(self.settings)
                self.sel_path = self.hover_target
                
                for path in self.cut_paths:
                    if path != self.hover_target:
                        path.deselect(self.settings) 
                
                return ''
         
        if eventd['press'] in self.keymap['action']: #LMB hard code for sketching
            
            if self.help_box.is_hovered:
                if  self.help_box.is_collapsed:
                    self.help_box.uncollapse()
                else:
                    self.help_box.collapse()
                self.help_box.snap_to_corner(eventd['context'],corner = [1,1])
                return ''

            self.footer = 'sketching'
            x,y = eventd['mouse']
            self.sketch = [(x,y)] 
            return 'sketch'
        ###################################
        # selected contour segment commands
         
        if self.sel_path:
            if eventd['press'] in self.keymap['delete']:
                self.create_undo_snapshot('DELETE')
                self.cut_paths.remove(self.sel_path)
                self.sel_path = None
                self.temporary_message_start(eventd['context'], 'DELETED PATH')
                        
                return ''
            
            if eventd['press'] in self.keymap['up shift']:
                self.segment_shift(eventd['context'], up = True)
                self.temporary_message_start(eventd['context'], 'SHIFT: ' + str(round(self.sel_path.cuts[0].shift,3)))
                return ''
            
            if eventd['press'] in self.keymap['dn shift']:
                self.segment_shift(eventd['context'], up = False)
                self.temporary_message_start(eventd['context'], 'SHIFT: ' + str(round(self.sel_path.cuts[0].shift,3)))
                return 
            
            if eventd['press'] in self.keymap['up count']:
                n = self.sel_path.segments + 1
                if self.sel_path.seg_lock:
                    self.temporary_message_start(eventd['context'], 'PATH SEGMENTS: Path is locked, cannot adjust segments')
                else:
                    self.segment_n_loops(eventd['context'], self.sel_path, n)    
                    self.temporary_message_start(eventd['context'], 'PATH SEGMENTS: %i' % n)
                return ''
            
            if eventd['press'] in self.keymap['dn count']:
                n = self.sel_path.segments - 1
                if self.sel_path.seg_lock:
                    self.temporary_message_start(eventd['context'], 'PATH SEGMENTS: Path is locked, cannot adjust segments')
                elif n < 3:
                    self.temporary_message_start(eventd['context'], 'PATH SEGMENTS: You want more segments than that!')
                else:
                    self.segment_n_loops(eventd['context'], self.sel_path, n)    
                    self.temporary_message_start(eventd['context'], 'PATH SEGMENTS: %i' % n)
                return ''
            
            if eventd['press'] in self.keymap['smooth']:
                
                self.segment_smooth(eventd['context'], self.settings)
                #messaging handled in operator
                return ''
            
            if eventd['press'] in self.keymap['snap cursor']:
                self.cursor_to_segment(eventd['context'])
                self.temporary_message_start(eventd['context'], 'Cursor to Segment')
                return ''
             
             
            if eventd['press'] in self.keymap['view cursor']:
                bpy.ops.view3d.view_center_cursor()
                return ''
                 
        return ''
    
    def modal_cut(self, eventd):
        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            p = eventd['pressure']
            self.sel_loop.tail.x = x
            self.sel_loop.tail.y = y      
            return ''
        
        if eventd['release'] in self.keymap['action']: #LMB hard code for cut
            print('new cut made')
            x,y = eventd['mouse']
            self.release_place_cut(eventd['context'], self.settings, x, y)
            return 'main loop'
        
    def modal_sketching(self, eventd):

        if eventd['type'] == 'MOUSEMOVE':
            x,y = eventd['mouse']
            self.sketch_curpos = (x,y)
            
            if not len(self.sketch):
                #somehow we got into sketching w/o sketching
                return 'main guide'
            
            (lx, ly) = self.sketch[-1]
            #on the fly, backwards facing, smoothing
            ss0,ss1 = self.stroke_smoothing,1-self.stroke_smoothing
            self.sketch += [(lx*ss0+x*ss1, ly*ss0+y*ss1)] #vs append?
                        
            return ''
        
        elif eventd['release'] in self.keymap['action']:
            print('released....trying to make a new path')
            self.sketch_confirm(eventd['context'])
                
            return 'main guide'
        
        return ''
    
    def modal_widget_tool(self,eventd):
        context = eventd['context']

        if eventd['type'] == 'MOUSEMOVE':
            self.widget_transform(context, self.settings, eventd)
            return ''
        
        elif eventd['release'] in self.keymap['action'] | self.keymap['modal confirm']:
            self.cut_line_widget = None
            self.sel_path.update_backbone(context, self.original_form, self.bme, self.sel_loop, insert = False)
            return 'main loop'
        
        elif eventd['press'] in self.keymap['modal cancel']:
            self.cut_line_widget.cancel_transform()
            self.sel_loop.cut_object(context, self.original_form, self.bme)
            self.sel_loop.simplify_cross(self.sel_path.ring_segments)
            self.sel_loop.update_com()
            
            self.sel_path.connect_cuts_to_make_mesh(self.original_form)
            self.sel_path.update_visibility(context, self.original_form)
        
            return 'main loop'    
                    
    def modal(self, context, event):
        context.area.tag_redraw()
        settings = common_utilities.get_settings()
        eventd = self.get_event_details(context, event)
        #if eventd['type'] != 'TIMER':
            #print((eventd['type'], eventd['value']))
            
        if event.type == 'TIMER':
            self.check_message(context)
            return {'RUNNING_MODAL'}
        
        FSM = {}
        FSM['main loop']    = self.modal_loop
        FSM['main guide']   = self.modal_guide
        FSM['nav']          = self.modal_nav
        FSM['cutting']      = self.modal_cut
        FSM['sketch']       = self.modal_sketching
        FSM['widget']       = self.modal_widget_tool
        
        self.cur_pos = eventd['mouse']
        nmode = FSM[self.mode](eventd)
        self.mode_pos = eventd['mouse']
        
        
        
        #self.is_navigating = (nmode == 'nav')
        if nmode == 'nav': return {'PASS_THROUGH'}
        
        if nmode in {'finish','cancel'}:
            common_utilities.callback_cleanup(self, context)
            self.kill_timer(context)
            return {'FINISHED'} if nmode == 'finish' else {'CANCELLED'}
        
        if nmode: self.mode = nmode
        
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        #HINT you are in contours code
        #TODO Settings harmon CODE REVIEW
        settings = common_utilities.get_settings()
        self.settings = settings
        self.keymap = key_maps.rtflow_default_keymap_generate()
        
        my_dir = os.path.split(os.path.abspath(__file__))[0]
        filename = os.path.join(my_dir, "help/help_contours.txt")
        if os.path.isfile(filename):
            help_txt = open(filename, mode='r').read()
        else:
            help_txt = "No Help File found, please reinstall!"

        self.help_box = TextBox(context,500,500,300,200,10,20,help_txt)
        if not settings.help_def:
            self.help_box.collapse()
        self.help_box.snap_to_corner(context, corner = [1,1])
        
        if context.space_data.viewport_shade in {'WIREFRAME','BOUNDBOX'}:
            showErrorMessage('Viewport shading must be at least SOLID')
            return {'CANCELLED'}
        elif context.mode == 'EDIT_MESH' and len(context.selected_objects) != 2:
            showErrorMessage('Must select exactly two objects')
            return {'CANCELLED'}
        elif context.mode == 'OBJECT' and len(context.selected_objects) != 1:
            showErrorMessage('Must select only one object')
            return {'CANCELLED'}
        
        self.mode = 'main loop'
        self.mode_last = 'main loop'
        
        self.is_navigating = False
        self.force_new = False
        self.post_update = True
        self.last_matrix = None
        
        self.mode_pos      = (0,0)
        self.cur_pos       = (0,0)
        self.mode_radius   = 0
        self.action_center = (0,0)
        self.action_radius = 0
        self.sketch_curpos = (0,0)
        self.sketch_pressure = 1
        self.sketch = []
        
        self.footer = ''
        self.footer_last = ''
        
        
        
        self._timer = context.window_manager.event_timer_add(0.1, context.window)
        
        self.stroke_smoothing = 0.5          # 0: no smoothing. 1: no change
        self.segments = settings.vertex_count
        self.guide_cuts = settings.ring_count
         
        #here is where we will cache verts edges and faces
        #unti lthe user confirms and we output a real mesh.
        self.verts = []
        self.edges = []
        self.faces = []
        
        self.cut_lines = []
        self.cut_paths = []
        self.draw_cache = []

        #what is the mouse over top of currently
        self.hover_target = None
        #keep track of selected cut_line and path
        self.sel_loop = None   #TODO: Change this to selected_loop
        
        if context.mode == 'OBJECT':
            #self.bme, self.dest_bme, self.dest_ob, self.original_form etc are all defined inside
            self.mesh_data_gather_object_mode(context)
        elif 'EDIT' in context.mode:
            self.mesh_data_gather_edit_mode(context)       
        if settings.use_x_ray:
            self.orig_x_ray = self.dest_ob.show_x_ray
            self.dest_ob.show_x_ray = True     
            
        #potential item for snapping in 
        self.snap = []
        self.snap_circle = []

        handle_color = settings.theme_colors_active[settings.theme]
        self.snap_color = (handle_color[0], handle_color[1], handle_color[2], 1.00)

        if len(self.cut_paths) == 0:
            self.sel_path = None   #TODO: change this to selected_segment
        else:
            print('there is a selected_path')
            self.sel_path = self.cut_paths[-1] #this would be an existing path from selected geom in editmode
        
        self.cut_line_widget = None  #An object of Class "CutLineManipulator" or None
        self.widget_interaction = False  #Being in the state of interacting with a widget o
        self.hot_key = None  #Keep track of which hotkey was pressed
        self.draw = False  #Being in the state of drawing a guide stroke
        
        self.loop_msg = 'LOOP MODE:  Sel, Trans, Rotate follow Blender, LMB: Cut, SHIFT+WHEEL, +/-:increase/decrease segments, CTRL/SHIFT+A: Align, X: Delete, SHIFT+S: Cursor to Stroke, C: View to Cursor, N: Force New Segment, TAB: toggle Guide mode'
        self.guide_msg = 'GUIDE MODE: Sel follows Blender, LMB to Sketch, CTRL+S: smooth, SHIFT+WHEEL, +/-: increase/decrease segments, <-,-> to Shift,TAB: toggle Loop mode'
        context.area.header_text_set(self.loop_msg)
            
        #timer for temporary messages
        self._timer = None
        self.msg_start_time = time.time()
        self.msg_duration = .75
        
        
        # switch to modal
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self.draw_callback, (context, ), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
        


################### Polystrips ###################


# Used to store keymaps for addon
addon_keymaps = []
icon_collections = {}

def register():
    bpy.utils.register_class(CGCOOKIE_OT_polystrips)

    if bversion > '002.074.004':
        rf_icons = bpy.utils.previews.new()

        icons_dir = os.path.join(os.path.dirname(__file__), "icons")

        rf_icons.load(
            "rf_contours_icon",
            os.path.join(icons_dir, "contours_32.png"),
            'IMAGE')
        rf_icons.load(
            "rf_polystrips_icon",
            os.path.join(icons_dir, "polystrips_32.png"),
            'IMAGE')

        icon_collections["main"] = rf_icons

    bpy.utils.register_class(RetopoFlowPreferences)
    bpy.utils.register_class(CGCOOKIE_OT_retopoflow_panel)
    bpy.utils.register_class(CGCOOKIE_OT_contours_cache_clear)
    bpy.utils.register_class(CGCOOKIE_OT_contours)
    bpy.utils.register_class(CGCOOKIE_OT_retopoflow_menu)

    # Create the addon hotkeys
    kc = bpy.context.window_manager.keyconfigs.addon
   
    # create the mode switch menu hotkey
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new('wm.call_menu', 'V', 'PRESS', ctrl=True, shift=True)
    kmi.properties.name = 'object.retopology_menu' 
    kmi.active = True
    addon_keymaps.append((km, kmi))


def unregister():
    bpy.utils.unregister_class(CGCOOKIE_OT_polystrips)

    clear_mesh_cache()
    bpy.utils.unregister_class(CGCOOKIE_OT_contours)
    bpy.utils.unregister_class(CGCOOKIE_OT_contours_cache_clear)
    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow_panel)
    bpy.utils.unregister_class(CGCOOKIE_OT_retopoflow_menu)
    bpy.utils.unregister_class(RetopoFlowPreferences)

    if bversion > '002.074.004':
        for icon in icon_collections.values():
            bpy.utils.previews.remove(icon)
        icon_collections.clear()

    # Remove addon hotkeys
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()

