import os
import bpy
from bpy.props import EnumProperty, StringProperty, BoolProperty, IntProperty, FloatVectorProperty, FloatProperty
from bpy.types import AddonPreferences
from . import addon_updater_ops

class RetopoFlowPreferences(AddonPreferences):
    #bl_idname = 'retopoFlow'
    bl_idname = os.path.basename(os.path.dirname(os.path.abspath(__file__)))
    
    def update_theme(self, context):
        print('theme updated to ' + str(theme))


    # source and target object
    source_object = StringProperty(
        name='Source Object',
        description='High resolution object to retopologize, defaults to Active if none set',
        default=''
        )

    target_object = StringProperty(
        name='Target Object',
        description='Low resolution object that holds the retopologized mesh',
        default=''
        )
    
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
    retopoflow_panel_settings = BoolProperty(
        name="Show Settings",
        description = "Show the RetopoFlow settings",
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


    # addon updater preferences

    auto_check_update = BoolProperty(
        name = "Auto-check for Update",
        description = "If enabled, auto-check for updates using an interval",
        default = False,
        )
    
    updater_intrval_months = IntProperty(
        name='Months',
        description = "Number of months between checking for updates",
        default=0,
        min=0
        )
    updater_intrval_days = IntProperty(
        name='Days',
        description = "Number of days between checking for updates",
        default=14,
        min=0,
        )
    updater_intrval_hours = IntProperty(
        name='Hours',
        description = "Number of hours between checking for updates",
        default=0,
        min=0,
        max=23
        )
    updater_intrval_minutes = IntProperty(
        name='Minutes',
        description = "Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59
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

        # updater draw function
        addon_updater_ops.update_settings_ui(self,context)


