# Change List

This document contains details about what has changed in Retopoflow in version 4.

### 4.2.0

- Added low poly sharp edge and edge mark snapping to Tweak and Relax
- Added standalone operator for Relax that can even be used outside of Retopoflow
- All Retopoflow tools now respect Blender's Alt+B clipping region
    - Useful for isolating areas while working
- Tools statusbar now shows the result of Blender operations such as Merge by Distance

### 4.1.8

- Fixed issue with Relax brush with mirror boundary clipping
- Improved stability of Relax near mirror boundaries

### 4.1.7

- Improved Relax at extreme scales
- Improved Relax Equalize Faces
- Fixed crease and sharp sliding in Tweak and Relax

### 4.1.6

- Significantly improved Relax performance
- Added option to slide along seams, creases, and sharp edges in Tweak and Relax
- Added vertex and edge sliding when pressing G during transforms
    - Clamping is off by default for boundary edges so you can easily slide outwards
- Added Tweak Loops option to PolyPen, Strokes, and Contours
    - This will select and slide loops when clicking and dragging from an edge instead of grabbing the edge
    - It is per-tool and on by default in Contours
- Improved auto picking projection method during transforms
    - If a lot of vertices are selected or any of their normals are not pointing towards the view, Face Nearest is used. Otherwise, Face Project.
- Added option to specify specific objects or collections as snapping sources
- Added option to disable auto picking projection method
- Added option to disable loop cutting feature in PolyPen's knife
- Added option to disable transforms correcting face normals
- Minor UI cleanup
- Increased default Face Nearest snapping steps
- Fixed PolyPen attempting to loop cut when it should bridge
- Fixed several PolyPen knife issues
- Fixed transforms flipping normals on thin curved surfaces
- Fixed snapping to self during loop cut and slide
- Fixed some Blender settings not being returned to previous values when exiting
- Fixed double click to loop select in Blender 5.1+
- Fixed crash when disabling the Retopoflow add-on while using it


### 4.1.5

- Added new Edit Mode Auto-Save feature for backing up modeling sessions
    - Blender's Auto-Save does not work in Edit Mode, so this fills that gap
    - It uses the same location and time increment as Blender's Auto-Save
    - You can recover using the usual File -> Recover menu
    - You can disable this feature if you already use another auto-save add-on for Edit Mode
- Added new vertex smoothing algorithm option for Relax
    - This is enabled by default and should make most cases significantly more stable
    - It uses a Laplacian method and behaves similar to Blender's smooth brush in sculpt mode
- Relax's Straighten Edges option can now work without spreading out the vertices
    - This helps fix issues when working with non-square rectangles
- A new Relax option, Equalize Faces, combines the previous face options while additionally averaging the area of each face
- Added a new Auto mode to Relax for automatically setting the number of substeps in the simulation
    - This makes it more stable at low vertex counts and faster at high vertex counts
- Improved Relax behavior at extreme scales
- Fixed issue with creases when jumping straight to object mode
- Fixed theme preferences being incorrectly saved in Blender 5.1 if exiting Blender while Retopoflow is active
- Fixed silent error in console when using Relax on geometry without faces
- Fixed issues with PolyPen attempting to knife when it should create a triangle


### 4.1.4

- Fixed PolyPen knife sometimes trying to insert loops when it should not

### 4.1.3

- Fixed issue with PolyPen freezing when operating on loose edges
- Fixed issue with faces flipping when using proportional editing


### 4.1.2

- Added option to constrain new knife cuts to the UI
- The status bar hotkeys now correctly show customized hotkeys
- Added hotkeys, `Shift P` and `Alt P`, for pinning and unpinning
- Pinned verts are now skipped by default by the clean up operator
- Fixed issue with verts interpolated from pins unable to be unpinned


### 4.1.1

- Masking and pinning options are now shared between Tweak and Relax
- The pie menu, documentation, and report issue hotkeys are now customizable
- The default hotkey for reporting an issue is now `Alt F1`
- Fixed issue with starting Retopoflow 4.1 in Blender 4.5
- Fixed issue with starting Retopoflow 4.1 in Blender 4.2


### 4.1.0

New:
- Significantly improved knifing in PolyPen
  - You can now make cuts across multiple faces
  - PolyPen can now automatically adds quad junctions when cutting between adjacent edges on a quad
  - You can now add any number of cuts into the middle of a face and it will split when you connect to the other side
  - New knife points on edges are now correctly constrained to the edge
  - You can now start a cut from a selected edge without needing to fist insert a point
- Tweak and Relax are now sensitive to pen pressure
- Tweak and Relax now have a pinning system
  - You can either add pins yourself or use attributes like seams or sharp edges
- Added new Topo Rotate operator (`Alt R`) for rotating selected topology in place
- Loop selection in Retopoflow now ends at inner corners by default in Blender 5.1+
    - We added the option for this and other loop delimiters to Blender 5.1 thanks to your support!
- Fill Region is now disabled when picking shortest path (`Ctrl Shift LMB`) in Retopoflow
    - The Loop and Shortest Path default adjustments can be disabled in the Tool Switching preferences if needed
- Added preference for W pie menu to work from any tool or only Retopoflow tools
- Blender's Status Bar now displays full hotkey hints for all tools
- Added preset themes for the retopology overlay
  - The new default is Blue for improved accessibility (and vibes)
  - You can use any custom theme you have set in Blender by setting the theme to "Blender"
- Added ability to change vert and edge thickness while using Retopoflow
  - Thew new default is 4px for verts and 2px for edges for improved clarity
- Added warning for Windows tablet users if they are using WindowsInk drivers
  - WindowsInk can currently cause some lag spikes in recent Blender versions, even without Retopoflow

Improved:
- Relax initialization and acceleration structure building is now up to 5x faster
- Contours is now about 2x faster
- Added retopology overlay offset to tool header
- Added mirror modifier merge distance to Mirror panel
- Deleting faceless edges is now off by default in the Cleanup operator
- Unused outer Contours sample points are no longer shown when using Walk or Skip
- Fixed PolyPen and Strokes not being able to extrude from a line of symmetry
- Fixed Relax crash when a vertex has invalid coordinates
- Fixed Tweak and Relax not using masking settings when using the quick switch hotkeys
- Fixed Contours crash when cutting a singular face that is behind the source mesh
- Fixed Contours breaking with a vector subtraction error in rare situations
- Fixed Contours breaking with a matrix error in rare situations
- Fixed Contours getting twisted on certain shapes
- Fixed issue when cancelling a Contours cut with a right click
- Fixed issue with mirroring on the -Y and -Z axis in Polystrips
- Fixed crash when a source object is a curve with a geometry nodes modifier that has no output
- Fixed Fade Inactive not turning on when tool switching
- Fixed wireframe mirror display mode in Blender 5.0
- Fixed issue with enabling the add-on with certain graphics drivers
- Fixed small memory leak in custom overlays

### 4.0.2
- Added option to only snap to selected objects
- Added support for Blender 5.0

### 4.0.1
- Fixed issue with detecting user keymaps

### 4.0.0

Retopoflow 4 is officially released!

New:
- Added Shift hotkey for moving in small increments while tweaking
- Added preference to disable warning that shows when starting Retopoflow without a source

Improved:
- The `W` pie menu now works when a non-Retopoflow tool is selected
- Improved Relax strength factor
- Tweak and Relax now treat edges between visible and hidden faces as a boundary
- Improved drawing from the line of symmetry in PolyStrips
- Added preset support to Clean Up operator
- Added PolyStrips and Strokes mirroring options to Mirror panel
- Fixed PolyStrips width when the retopo object has non-uniform scale
- Fixed PolyStrips creating sharp angles when the stroke is smooth but the source has sharp angles
- Fixed issue when deleting source objects while Retopoflow is running
- Fixed Strokes and PolyPen being able to snap to hidden vertices
- Fullscreening an area is now blocked since it can cause a crash on some machines
    - We will restore this functionality once we find a full fix

### 4.0.0 beta 7

New:
- Retopoflow can now use non-mesh objects like curves and NURBS as sources as long as they have evaluated faces
- The existing faces are no longer selected after using PolyStrips to bridge
- Added RK4 as a new iteration method for Relax
    - RK4 is significantly more stable overall but may apply too much or too little strength in some cases
- Added preferences for disabling the help and pie menu hotkeys

Improved:
- Fixed random crashing in Strokes and PolyStrips in Blender 4.5
- Fixed occasional flipped normals in Contours
- Fixed several smaller issues

### 4.0.0 beta 6

New:
- Added preferences for what to name newly created retopology objects
- Added limits to how far Relax can move geometry as a percent of the brush radius
- Added option to apply retopology settings to non-Retopoflow tools
- Added option to revert retopology settings if they were applied to non-Retopoflow tools
- Added option to reset all Retopoflow tool settings

Improved:
- Improved drawing PolyStrips across and along the line of symmetry
- Increased default vertex selection distance in response to feedback
- Fixed PolyPen crash when closest edge has zero length
- Fixed PolyStrips crash when bridging two faces that share a vertex
- Fixed info menu icon missing in Blender 4.2
- Fixed twisting in Relax when rotation was not applied
- Re-enabled Face Angles and Face Radius in Relax by default
- Fixed crash when toggling maximize area
- Fixed issue when switching workspaces into Retopoflow
- Fixed retopology overlay not being enabled in all 3D Views in the workspace
- Fixed issue when packaging Retopoflow using Blender's extension build command


### 4.0.0 beta 5

New:
- You can now draw across the symmetry line in PolyPen, Contours, and PolyStrips

Improved:
- Fixed issue with Blender 4.5 on Mac

### 4.0.0 beta 4

New:
- Added quick hotkeys for Tweak and Relax
    - Shift drag for Relax
    - Ctrl Shift drag for Tweak
- Added option to use Blender's native transform to the Tweaking panel
    - Allows snapping to the edges and verts of the source object
    - Allows all bonus features like edge slide and constraints
    - Great for low poly or hard surface objects but not for high poly organic sculpts
- Strokes now takes into account the line of symmetry when a mirror is enabled
    - New options for behavior at the line of symmetry and determining which side is being mirrored
- PolyStrips has a new stroke preview that shows the width of the resulting strip.

Improved:
- Fixed issue with Tweak and Relax not working when the retopo object scale was extreme
- Fixed issue with transforms not working when the retopo object was not at world origin
- Fixed crash when restoring factory defaults while Retopoflow is enabled


### 4.0.0 beta 3

New:
- A Mirroring panel with quick actions was added to the tool settings
- There is now a warning if entering Retopoflow when no sources are detected
- You can now control the merge distance of the Strokes brush

Improved:
- All tools now use Face Nearest snapping by default
- Masking corners in Tweak and Relax now respects concave corners
- The Tweak and Relax brush falloff control is now much more user friendly
- Strokes bridges can now be untwisted in edge cases where they are twisted
- Improved visualization for proportional editing
- Fixed several issues with mirror modifier clipping
- Fixed conflict with keymaps that use Ctrl LMB Drag as box or lasso select
- Fixed case where Relax would mangle n-gons if they had multiple sides on a boundary
- Fixed case where Relax would affect vertices outside of the brush
- Fixed Strokes merge circle sometimes highlighting when the result would not be merged
- Fixed Retopoflow exiting when maximizing the 3D View

### 4.0.0 beta 2

New:
- Contours can now extend from the correct boundary regardless of which loop is selected
- Improved Relax performance
- Disabled Relax Face Radius and Face Angles options by default since they are not always stable
- Renamed Stroke Smoothing to Stabilize to match Blender's term
- Added Stabilize control to Strokes
- F1 now opens documentation and F2 reports an issue

Fixed:
- Fixed crash when a conflicting add-on listens for mesh changes and frees bmesh while we're using it
- Fixed issue with flipped normals when the retopology object's origin is far away

### 4.0.0 beta 1

Retopoflow 4 is a complete rewrite of Retopoflow that massively improves performance and integrates the tools directly into Blender's Edit Mode.

Some key changes include:
- General
    - The tools are now in the Edit Mode toolbar
    - Ctrl scroll is now used instead of Shift scroll for adjusting insert count
- Contours
    - A new Fast method was added, which can improve performance on dense meshes and work in some cases where the mesh is split
- PolyStrips
    - Proportional Editing can now be used for smoothly affecting the surrounding geometry while adjusting existing strips
    - The angle at which new strips are split to create sharp corners can now be specified
    - Strip spacing is now calculated in world space
- Strokes
    - Several new stroke shapes are now supported so drawing new geometry feels more natural
    - Extrudes can now match the curvature of the original geometry if the method is set to Adapt
    - A smoothing control has been added for naturally blending between strokes created at different angles
    - The new default insert count, Average, always creates perfectly even quads when extruding
