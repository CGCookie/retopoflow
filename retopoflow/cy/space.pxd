# distutils: language=c++
# cython: language_level=3

from .vector cimport rctf, rcti, BoundBox


cdef struct ListBase:
    void* first
    void* last


cdef struct View2D:
    # Tot - area that data can be drawn in; cur - region of tot that is visible in viewport
    rctf tot, cur
    # Vert - vertical scroll-bar region; hor - horizontal scroll-bar region
    rcti vert, hor
    # Mask - region (in screen-space) within which 'cur' can be viewed
    rcti mask

    # Min/max sizes of 'cur' rect (only when keepzoom not set)
    float[2] min
    float[2] max
    # Allowable zoom factor range (only when (keepzoom & V2D_LIMITZOOM)) is set
    float minzoom, maxzoom

    # Scroll - scroll-bars to display (bit-flag)
    short scroll
    # Scroll_ui - temp settings used for UI drawing of scrollers
    short scroll_ui

    # Keeptot - 'cur' rect cannot move outside the 'tot' rect?
    short keeptot
    # Keepzoom - axes that zooming cannot occur on, and also clamp within zoom-limits
    short keepzoom
    # Keepofs - axes that translation is not allowed to occur on
    short keepofs

    # Settings
    short flag
    # Alignment of content in totrect
    short align

    # Storage of current winx/winy values, set in UI_view2d_size_update
    short winx, winy
    # Storage of previous winx/winy values encountered by UI_view2d_curRect_validate(), for keep-aspect
    short oldwinx, oldwiny

    # Pivot point for transforms (rotate and scale)
    short around

    # Usually set externally (as in, not in view2d files)
    # Alpha of vertical and horizontal scroll-bars (range is [0, 255])
    char alpha_vert, alpha_hor
    char[2] _pad

    # When set (not 0), determines how many pixels to scroll when scrolling an entire page
    # Otherwise the height of View2D.mask is used
    float page_size_y

    # Animated smooth view
    void* sms                # struct SmoothView2DStore*
    void* smooth_timer      # struct wmTimer*


cdef struct ARegion:
    ARegion* next
    ARegion* prev
    View2D v2d
    rcti winrct
    short winx, winy
    int category_scroll
    short regiontype
    short alignment
    short flag
    short sizex, sizey
    short overlap
    short flagfullscreen
    char[2] _pad
    ListBase panels
    ListBase panels_category_active
    ListBase ui_lists
    ListBase ui_previews
    ListBase view_states
    void* regiondata
    void* runtime  # ARegionRuntimeHandle -> ARegionRuntime


cdef struct RegionView3D:
    # GL_PROJECTION matrix.
    float[4][4] winmat
    # GL_MODELVIEW matrix.
    float[4][4] viewmat
    # Inverse of viewmat.
    float[4][4] viewinv
    # Viewmat*winmat.
    float[4][4] persmat
    # Inverse of persmat.
    float[4][4] persinv
    # Offset/scale for camera GLSL texture-coordinates.
    float[4] viewcamtexcofac

    # viewmat/persmat multiplied with object matrix, while drawing and selection.
    float[4][4] viewmatob
    float[4][4] persmatob

    # User defined clipping planes.
    float[6][4] clip
    
    # Clip in object space
    float[6][4] clip_local
    BoundBox* clipbb                  # struct BoundBox*

    # Allocated backup of itself while in local-view
    RegionView3D* localvd
    void* view_render            # struct ViewRender*
    
    # Animated smooth view
    void* sms                    # struct SmoothView3DStore*
    void* smooth_timer          # struct wmTimer*
    
    # Transform gizmo matrix
    float[4][4] twmat
    # min/max dot product on twmat XYZ axis
    float[3] tw_axis_min
    float[3] tw_axis_max
    float[3][3] tw_axis_matrix

    float gridview               # DNA_DEPRECATED

    # View rotation, must be kept normalized
    float[4] viewquat
    # Distance from 'ofs' along -viewinv[2] vector, where result is negative as is 'ofs'.
    float dist
    # Camera view offsets, 1.0 = viewplane moves entire width/height.
    float camdx
    float camdy
    # Runtime only
    float pixsize
    # View center & orbit pivot, negative of world-space location,
    # also matches `-viewinv[3][0:3]` in orthographic mode.
    float[3] ofs
    # Viewport zoom on the camera frame, see BKE_screen_view3d_zoom_to_fac.
    float camzoom

    # Check if persp/ortho view, since 'persp' can't be used for this since
    # it can have cameras assigned as well. (only set in #view3d_winmatrix_set)
    char is_persp  # is perspective view ?
    char persp  # likely view type... 0: ORTHO, 1: PERSP, 2: CAMERA.
    char view  # is_orthographic_side_view
    char view_axis_roll
    char viewlock # Should usually be accessed with RV3D_LOCK_FLAGS()
    # Options for runtime only locking (cleared on file read)
    char runtime_viewlock # Should usually be accessed with RV3D_LOCK_FLAGS()
    # Options for quadview (store while out of quad view).
    char viewlock_quad
    char _pad

    # Normalized offset for locked view: (-1, -1) bottom left, (1, 1) upper right.
    float[2] ofs_lock

    short twdrawflag
    short rflag
    
    # Last view (use when switching out of camera view).
    float[4] lviewquat
    char lpersp
    char lview
    char lview_axis_roll
    char _pad8
    
    # Active rotation from NDOF or elsewhere.
    float rot_angle
    float[3] rot_axis
