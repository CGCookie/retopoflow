'''
Copyright (C) 2025 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

from __future__ import annotations
from bpy.types import Context
from ..retopoflow.rfglobals import RFGlobals

class Theme:
    default : dict[str, list[float]] = {
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
    common : dict[str,list[float]] = {
        'editmesh_active':  [1, 1, 1, 0.2],
        'wire_edit':        [0, 0, 0],
        'vertex':           [0, 0, 0],
    }
    blue : dict[str,list[float]] = {
        'vertex_select':    [0.5, 0.85, 1],
        'edge_select':      [0, 0.7, 1],
        'edge_mode_select': [0, 0.7, 1],
        'face_select':      [0, 0.5, 1, 0.5],
        'face_mode_select': [0, 0.5, 1, 0.5],
        'face_retopology':  [0.25, 0.45, 0.65, 0.5],
    }
    green : dict[str,list[float]] = {
        'vertex_select':    [0.2, 1, 0.25],
        'edge_select':      [0, 0.9, 0],
        'edge_mode_select': [0, 0.9, 0],
        'face_select':      [0, 0.8, 0.3, 0.5],
        'face_mode_select': [0, 0.8, 0.3, 0.5],
        'face_retopology':  [0.175, 0.5, 0.25, 0.5],
    }
    orange : dict[str,list[float]] = {
        'vertex_select':    [1, 0.85, 0.25],
        'edge_select':      [0.9, 0.65, 0],
        'edge_mode_select': [0.9, 0.65, 0],
        'face_select':      [1, 0.5, 0, 0.5],
        'face_mode_select': [1, 0.5, 0, 0.5],
        'face_retopology':  [0.5, 0.4, 0.3, 0.5],
    }
    pink : dict[str,list[float]] = {
        'vertex_select':    [1, 0.7, 1],
        'edge_select':      [0.85, 0.55, 0.85],
        'edge_mode_select': [0.85, 0.55, 0.85],
        'face_select':      [1, 0, 0.75, 0.5],
        'face_mode_select': [1, 0, 0.75, 0.5],
        'face_retopology':  [0.6, 0.3, 0.6, 0.5],
    }
    purple : dict[str,list[float]] = {
        'vertex_select':    [0.75, 0.65, 1],
        'edge_select':      [0.825, 0.55, 1],
        'edge_mode_select': [0.825, 0.55, 1],
        'face_select':      [0.65, 0.25, 1, 0.5],
        'face_mode_select': [0.65, 0.25, 1, 0.5],
        'face_retopology':  [0.4, 0, 0.5, 0.5],
    }

    @staticmethod
    def store_default(context : Context):
        user_theme = context.preferences.themes[0].view_3d
        for pref in Theme.default:
            color = list(getattr(user_theme, pref))
            Theme.default[pref] = color

    @staticmethod
    def set_theme(context : Context, theme_name : str):
        RFCore = RFGlobals.RFCore_None
        # Don't change the theme from preferences when Retopoflow is not running
        if not RFCore or not RFCore.is_running: return
        if not hasattr(context.space_data, 'overlay'): return

        def apply(settings):
            user_theme = context.preferences.themes[0].view_3d
            for pref, color in settings.items():
                setattr(user_theme, pref, color)

        if theme_name == 'none':
            apply(Theme.default)
        else:
            theme = getattr(Theme, theme_name, Theme.blue)
            apply(Theme.common)
            apply(theme)

