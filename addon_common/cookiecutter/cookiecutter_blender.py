'''
Copyright (C) 2021 CG Cookie

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

import math

import bpy
import bgl

from ..common.decorators import blender_version_wrapper
from ..common.debug import debugger
from ..common.drawing import Drawing
from ..common.utils import iter_head
from ..common.blender import toggle_screen_header, toggle_screen_toolbar, toggle_screen_properties, toggle_screen_lastop


class CookieCutter_Blender:
    def _cc_blenderui_init(self):
        self._scene = self.context.scene
        self._area = self.context.area
        self._space = self.context.space_data
        self._window = self.context.window
        self._screen = self.context.screen
        self._region = self.context.region
        self._rgn3d = self.context.space_data.region_3d
        self.scene_scale_store()
        self.viewaa_store()
        self.manipulator_store()
        self.panels_store()
        self.overlays_store()
        self.statusbar_stats_store()
        self.quadview_store()
        self.shading_store()

    def _cc_blenderui_end(self, ignore_panels=False):
        self.shading_restore()
        self.quadview_restore()
        self.overlays_restore()
        if not ignore_panels: self.panels_restore()
        self.statusbar_stats_restore()
        self.manipulator_restore()
        self.viewaa_restore()
        self.cursor_modal_restore()
        self.header_text_restore()
        self.scene_scale_restore()


    #########################################
    # Header

    @blender_version_wrapper("<=", "2.79")
    def header_text_set(self, s=None):
        if s is None:
            self._area.header_text_set()
        else:
            self._area.header_text_set(s)
    @blender_version_wrapper(">=", "2.80")
    def header_text_set(self, s=None):
        self._area.header_text_set(s)

    def header_text_restore(self):
        self.header_text_set()


    #########################################
    # Cursor

    def cursor_modal_set(self, v):
        self._window.cursor_modal_set(v)

    def cursor_modal_restore(self):
        self._window.cursor_modal_restore()


    #########################################
    # Panels

    def _cc_panels_get_details(self):
        # regions for 3D View:
        #     279: [ HEADER, TOOLS, TOOL_PROPS, UI,  WINDOW ]
        #     280: [ HEADER, TOOLS, UI,         HUD, WINDOW ]
        #            0       1      2           3   4
        # could hard code the indices, but these magic numbers might change.
        # will stick to magic (but also way more descriptive) types
        rgn_header = iter_head(r for r in self._area.regions if r.type == 'HEADER')
        rgn_toolshelf = iter_head(r for r in self._area.regions if r.type == 'TOOLS')
        rgn_properties = iter_head(r for r in self._area.regions if r.type == 'UI')
        rgn_hud = iter_head(r for r in self._area.regions if r.type == 'HUD')
        return (rgn_header, rgn_toolshelf, rgn_properties, rgn_hud)

    def panels_store(self):
        rgn_header,rgn_toolshelf,rgn_properties,rgn_hud = self._cc_panels_get_details()
        show_header,show_toolshelf,show_properties = rgn_header.height>1, rgn_toolshelf.width>1, rgn_properties.width>1
        show_hud = rgn_hud.width>1 if rgn_hud else False
        self._show_header = show_header
        self._show_toolshelf = show_toolshelf
        self._show_properties = show_properties
        self._show_hud = show_hud

    def panels_restore(self):
        rgn_header,rgn_toolshelf,rgn_properties,rgn_hud = self._cc_panels_get_details()
        show_header,show_toolshelf,show_properties = rgn_header.height>1, rgn_toolshelf.width>1, rgn_properties.width>1
        show_hud = rgn_hud.width>1 if rgn_hud else False
        ctx = {
            'area': self._area,
            'space_data': self._space,
            'window': self._window,
            'screen': self._screen,
            'region': self._region,
        }
        if self._show_header and not show_header: toggle_screen_header(ctx)
        if self._show_toolshelf and not show_toolshelf: toggle_screen_toolbar(ctx)
        if self._show_properties and not show_properties: toggle_screen_properties(ctx)
        if self._show_hud and not show_hud: toggle_screen_lastop(ctx)

    def panels_hide(self):
        rgn_header,rgn_toolshelf,rgn_properties,rgn_hud = self._cc_panels_get_details()
        show_header,show_toolshelf,show_properties = rgn_header.height>1, rgn_toolshelf.width>1, rgn_properties.width>1
        show_hud = rgn_hud.width>1 if rgn_hud else False
        ctx = {
            'area': self._area,
            'space_data': self._space,
            'window': self._window,
            'screen': self._screen,
            'region': self._region,
        }
        if show_header: toggle_screen_header(ctx)
        if show_toolshelf: toggle_screen_toolbar(ctx)
        if show_properties: toggle_screen_properties(ctx)
        if show_hud: toggle_screen_lastop(ctx)


    #########################################
    # Viewport Shading

    def shading_type_get(self): return self._space.shading.type
    def shading_type_set(self, v): self._space.shading.type = v

    def shading_light_get(self): return self._space.shading.light
    def shading_light_set(self, v): self._space.shading.light = v

    def shading_matcap_get(self): return self._space.shading.studio_light
    def shading_matcap_set(self, v): self._space.shading.studio_light = v

    def shading_colortype_get(self): return self._space.shading.color_type
    def shading_colortype_set(self, v): self._space.shading.color_type = v

    def shading_color_get(self): return self._space.shading.single_color
    def shading_color_set(self, v): self._space.shading.single_color = v

    def shading_backface_get(self): return self._space.shading.show_backface_culling
    def shading_backface_set(self, v): self._space.shading.show_backface_culling = v

    def shading_shadows_get(self): return self._space.shading.show_shadows
    def shading_shadows_set(self, v): self._space.shading.show_shadows = v

    def shading_xray_get(self): return self._space.shading.show_xray
    def shading_xray_set(self, v): self._space.shading.show_xray = v

    def shading_cavity_get(self): return self._space.shading.show_cavity
    def shading_cavity_set(self, v): self._space.shading.show_cavity = v

    def shading_outline_get(self): return self._space.shading.show_object_outline
    def shading_outline_set(self, v): self._space.shading.show_object_outline = v

    def shading_store(self):
        self._shading = {
            'type': self.shading_type_get(),
            'light': self.shading_light_get(),
            'matcap': self.shading_matcap_get(),
            'colortype': self.shading_colortype_get(),
            'color': self.shading_color_get(),
            'backface': self.shading_backface_get(),
            'shadows': self.shading_shadows_get(),
            'xray': self.shading_xray_get(),
            'cavity': self.shading_cavity_get(),
            'outline': self.shading_outline_get(),
        }
    def shading_restore(self):
        if self._shading['type'] == 'WIREFRAME':
            self.shading_type_set(self._shading['type'])
            self.shading_xray_set(self._shading['xray'])
            self.shading_outline_set(self._shading['outline'])
        else:
            self.shading_type_set(self._shading['type'])
            self.shading_light_set(self._shading['light'])
            self.shading_matcap_set(self._shading['matcap'])
            self.shading_colortype_set(self._shading['colortype'])
            self.shading_color_set(self._shading['color'])
            self.shading_backface_set(self._shading['backface'])
            self.shading_shadows_set(self._shading['shadows'])
            self.shading_xray_set(self._shading['xray'])
            self.shading_cavity_set(self._shading['cavity'])
            self.shading_outline_set(self._shading['outline'])


    #########################################
    # Overlays and Manipulators/Gizmos

    @blender_version_wrapper("<=", "2.79")
    def overlays_get(self): return None
    @blender_version_wrapper("<=", "2.79")
    def overlays_set(self, v): pass

    @blender_version_wrapper(">=", "2.80")
    def overlays_get(self): return self._space.overlay.show_overlays
    @blender_version_wrapper(">=", "2.80")
    def overlays_set(self, v): self._space.overlay.show_overlays = v

    @blender_version_wrapper("<=", "2.79")
    def manipulator_get(self): return self._space.show_manipulator
    @blender_version_wrapper("<=", "2.79")
    def manipulator_set(self, v): self._space.show_manipulator = v

    def shading_type_get(self): return self._space.shading.type
    def shading_type_set(self, v): self._space.shading.type = v

    def scene_scale_get(self): return self._scene.unit_settings.scale_length
    def scene_scale_set(self, v): self._scene.unit_settings.scale_length = v

    @blender_version_wrapper(">=", "2.80")
    def manipulator_get(self):
        # return self._space.show_gizmo
        spc = self._space
        settings = { k:getattr(spc, k) for k in dir(spc) if k.startswith('show_gizmo') }
        # print('manipulator_settings:', settings)
        return settings
    @blender_version_wrapper(">=", "2.80")
    def manipulator_set(self, v):
        # self._space.show_gizmo = v
        spc = self._space
        if type(v) is bool:
            for k in dir(spc):
                # DO NOT CHANGE `show_gizmo` VALUE
                if not k.startswith('show_gizmo_'): continue
                setattr(spc, k, v)
        else:
            for k,v_ in v.items():
                setattr(spc, k, v_)

    @blender_version_wrapper('<=', '2.83')
    def statusbar_stats_get(self): return None
    @blender_version_wrapper('<=', '2.83')
    def statusbar_stats_set(self, v): pass
    @blender_version_wrapper('>', '2.83')
    def statusbar_stats_get(self): return self.context.preferences.view.show_statusbar_stats
    @blender_version_wrapper('>', '2.83')
    def statusbar_stats_set(self, v): self.context.preferences.view.show_statusbar_stats = v

    def overlays_store(self):   self._overlays = self.overlays_get()
    def overlays_restore(self): self.overlays_set(self._overlays)
    def overlays_hide(self):    self.overlays_set(False)
    def overlays_show(self):    self.overlays_set(True)

    def quadview_get(self):     return bool(self._space.region_quadviews)
    def quadview_toggle(self):  bpy.ops.screen.region_quadview({'area': self._area, 'region': self._area.regions[5]})
    def quadview_set(self, v):
        if self.quadview_get() != v: self.quadview_toggle()
    def quadview_store(self):   self._quadview = bool(self._space.region_quadviews)
    def quadview_restore(self): self.quadview_set(self._quadview)
    def quadview_hide(self):    self.quadview_set(False)
    def quadview_show(self):    self.quadview_set(True)

    def scene_scale_store(self):   self._scene_scale = self.scene_scale_get()
    def scene_scale_restore(self): self.scene_scale_set(self._scene_scale)

    def manipulator_store(self):   self._manipulator = self.manipulator_get()
    def manipulator_restore(self): self.manipulator_set(self._manipulator)
    def manipulator_hide(self):    self.manipulator_set(False)
    def manipulator_show(self):    self.manipulator_set(True)

    def statusbar_stats_store(self):   self._statusbar_stats = self.statusbar_stats_get()
    def statusbar_stats_restore(self): self.statusbar_stats_set(self._statusbar_stats)
    def statusbar_stats_hide(self):    self.statusbar_stats_set(False)
    def statusbar_stats_show(self):    self.statusbar_stats_set(True)

    def gizmo_store(self):         self._manipulator = self.manipulator_get()
    def gizmo_restore(self):       self.manipulator_set(self._manipulator)
    def gizmo_hide(self):          self.manipulator_set(False)
    def gizmo_show(self):          self.manipulator_set(True)

    def viewaa_store(self):         self._viewaa = self.context.preferences.system.viewport_aa
    def viewaa_restore(self):       self.context.preferences.system.viewport_aa = self._viewaa
    def viewaa_set(self, v):        self.context.preferences.system.viewport_aa = v
    def viewaa_simplify(self):
        if self._viewaa == 'OFF': return
        self.viewaa_set('FXAA')