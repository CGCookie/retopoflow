class Theme:
    default = {
        'editmesh_active':  [1, 1, 1, 0.2],
        'wire_edit':        [0, 0, 0],
        'vertex':           [0, 0, 0],
        'face_retopology':  [0.314, 0.784, 1, 0.059],
        'vertex_select':    [1, 0.5, 0],
        'edge_select':      [1, 0.6, 0],
        'edge_mode_select': [1, 0.85, 0],
        'face_select':      [1, 0.64, 0, 0.2],
        'face_mode_select': [1, 0.72, 0, 0.2],
    }
    common = {
        'editmesh_active':  [1, 1, 1, 0.2],
        'wire_edit':        [0, 0, 0],
        'vertex':           [0, 0, 0],
    }
    blue = {
        'vertex_select':    [0.5, 0.85, 1],
        'edge_select':      [0, 0.7, 1],
        'edge_mode_select': [0, 0.7, 1],
        'face_select':      [0, 0.5, 1, 0.5],
        'face_mode_select': [0, 0.5, 1, 0.5],
        'face_retopology':  [0.25, 0.45, 0.65, 0.5],
    }
    green = {
        'vertex_select':    [0.2, 1, 0.25],
        'edge_select':      [0, 0.9, 0],
        'edge_mode_select': [0, 0.9, 0],
        'face_select':      [0, 0.8, 0.3, 0.5],
        'face_mode_select': [0, 0.8, 0.3, 0.5],
        'face_retopology':  [0.175, 0.5, 0.25, 0.5],
    }
    orange = {
        'vertex_select':    [1, 0.85, 0.25],
        'edge_select':      [0.9, 0.65, 0],
        'edge_mode_select': [0.9, 0.65, 0],
        'face_select':      [1, 0.5, 0, 0.5],
        'face_mode_select': [1, 0.5, 0, 0.5],
        'face_retopology':  [0.5, 0.4, 0.3, 0.5],
    }
    pink = {
        'vertex_select':    [1, 0.7, 1],
        'edge_select':      [0.85, 0.55, 0.85],
        'edge_mode_select': [0.85, 0.55, 0.85],
        'face_select':      [1, 0, 0.75, 0.5],
        'face_mode_select': [1, 0, 0.75, 0.5],
        'face_retopology':  [0.5, 0.3, 0.5, 0.5],
    }

    def store_default(context):
        user_theme = context.preferences.themes[0].view_3d
        for pref in Theme.default.keys():
            Theme.default[pref] =  [x for x in getattr(user_theme, pref)]


    def set_theme(context, theme):
        # Don't change the theme from preferences when Retopoflow is not running
        if not hasattr(context.space_data, 'overlay'):
            from ..retopoflow.rfcore import RFCore
            if not RFCore.is_running:
                return

        if theme == 'none':
            settings = Theme.default
        else:
            settings = Theme.common | getattr(Theme, theme)

        for pref in settings.keys():
            setattr(context.preferences.themes[0].view_3d, pref, settings[pref])
