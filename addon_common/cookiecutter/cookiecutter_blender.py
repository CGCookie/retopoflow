'''
Copyright (C) 2022 CG Cookie

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

from ..common.blender import region_label_to_data, create_simple_context
from ..common.decorators import blender_version_wrapper
from ..common.debug import debugger
from ..common.drawing import Drawing, Cursors
from ..common.utils import iter_head


class StoreRestore:
    def __init__(self):
        self._storage = {}
        self._bindings = {}
    def bind(self, k, fn_get, fn_set):
        self._bindings[k] = (fn_get, fn_set)
    def store(self, k):
        fn_get, _ = self._bindings[k]
        self._storage[k] = fn_get()
    def store_all(self):
        for k in self._bindings:
            self.store(k)
    def get(self, k):
        return self._storage[k]
    def discard(self, k):
        del self._storage[k]
    def restore(self, k, *, discard=False):
        _, fn_set = self._bindings[k]
        fn_set(self._storage[k])
        if discard: self.discard(k)
    def restore_all(self, *, ignore=None, clear=False):
        touched = set()
        for k in self._storage:
            if ignore and k in ignore: continue
            self.restore(k)
            touched.add(k)
        if clear:
            for k in touched:
                del self._storage[k]


class CookieCutter_Blender:
    def _cc_blenderui_init(self):
        self._storerestore = StoreRestore()
        bind = self._storerestore.bind
        # self._storerestore.bind('workspace', self.workspace_get, self.workspace_set)
        # self._storerestore.bind('scene', self.scene_get, self.scene_set)
        bind('objects selected',  self.objects_selected_get,  self.objects_selected_set)
        bind('objects visible',   self.objects_visible_get,   self.objects_visible_set)
        bind('object active',     self.object_active_get,     self.object_active_set)
        bind('scene scale',       self.scene_scale_get,       self.scene_scale_set)
        bind('panels',            self.panels_get,            self.panels_set)
        bind('shading type',      self.shading_type_get,      self.shading_type_set)
        bind('shading light',     self.shading_light_get,     self.shading_light_set)
        bind('shading matcap',    self.shading_matcap_get,    self.shading_matcap_set)
        bind('shading colortype', self.shading_colortype_get, self.shading_colortype_set)
        bind('shading color',     self.shading_color_get,     self.shading_color_set)
        bind('shading backface',  self.shading_backface_get,  self.shading_backface_set)
        bind('shading shadows',   self.shading_shadows_get,   self.shading_shadows_set)
        bind('shading xray',      self.shading_xray_get,      self.shading_xray_set)
        bind('shading cavity',    self.shading_cavity_get,    self.shading_cavity_set)
        bind('shading outline',   self.shading_outline_get,   self.shading_outline_set)
        bind('quadview',          self.quadview_get,          self.quadview_set)
        bind('overlays',          self.overlays_get,          self.overlays_set)
        bind('gizmo',             self.gizmo_get,             self.gizmo_set)
        bind('viewaa',            self.viewaa_get,            self.viewaa_set)
        self._storerestore.store_all()


    def _cc_blenderui_end(self, ignore=None):
        self._storerestore.restore_all(ignore=ignore)

        self.header_text_restore()
        self.statusbar_text_restore()
        self.cursor_restore()


    #########################################
    # Workspace and Scene

    def workspace_set(self, name):  self.context.window.workspace = bpy.data.workspaces[name]
    def workspace_get(self): return self.context.window.workspace.name

    def scene_set(self, name):  self.context.window.scene = bpy.data.scenes[name]
    def scene_get(self): return self.context.window.scene.name

    def scene_scale_get(self):     return self.context.scene.unit_settings.scale_length
    def scene_scale_set(self, v):  self.context.scene.unit_settings.scale_length = v


    #########################################
    # Objects
    # NOTE: select, active, and visible properties are stored in scene!

    def objects_selected_get(self): return { o.name for o in bpy.data.objects if o.select_get() }
    def objects_selected_set(self, names, *, only=False):
        for o in bpy.data.objects:
            if only: o.select_set(o.name in names)
            elif o.name in names: o.select_set(True)

    def objects_visible_get(self): return { o.name for o in bpy.data.objects if not o.hide_get() }
    def objects_visible_set(self, names, *, only=False):
        for o in bpy.data.objects:
            if only: o.hide_set(o.name not in names)
            elif o.name in names: o.hide_set(False)

    def object_active_get(self): return self.context.view_layer.objects.active.name if self.context.view_layer.objects.active else None
    def object_active_set(self, name):
        if not name: return
        obj = bpy.data.objects[name]
        obj.select_set(True)
        self.context.view_layer.objects.active = obj


    #########################################
    # Header, Status Bar, Cursor

    def header_text_set(self, s=None): self.context.area.header_text_set(text=s)
    def header_text_restore(self):     self.header_text_set()

    def statusbar_text_set(self, s=None, *, internal=False):
        if not internal: self.context.workspace.status_text_set(text=s)
        else:            self.context.workspace.status_text_set_internal(text=s)
    def statusbar_text_restore(self):     self.statusbar_text_set()

    def cursor_set(self, cursor): Cursors.set(cursor)
    def cursor_restore(self):     Cursors.restore()


    #########################################
    # Region Panels

    def _get_region(self, *, label=None, type=None):
        if label: type = region_label_to_data[label].type
        return next((r for r in self.context.area.regions if r.type == type), None)
    def _get_regions(self):
        return { label: self._get_region(label=label) for label in region_label_to_data }

    def panels_get(self):
        rgns = self._get_regions()
        return {
            label: (rgns[label].width > 1 and rgns[label].height > 1) if rgns[label] else False
            for label in region_label_to_data
        }
    def panels_set(self, state):
        ctx = create_simple_context(self.context)
        current = self.panels_get()
        for label, val in state.items():
            if val == current[label]: continue
            fn_toggle = region_label_to_data[label].fn_toggle
            if fn_toggle: fn_toggle(ctx)
    def panels_hide(self, *, ignore=None):
        if not ignore: ignore = set()
        self.panels_set({ label: False for label in region_label_to_data if label not in ignore })


    #########################################
    # Viewport Shading and Settings

    def shading_type_get(self): return self.context.space_data.shading.type
    def shading_type_set(self, v): self.context.space_data.shading.type = v

    def shading_light_get(self): return self.context.space_data.shading.light
    def shading_light_set(self, v): self.context.space_data.shading.light = v

    def shading_matcap_get(self): return self.context.space_data.shading.studio_light
    def shading_matcap_set(self, v): self.context.space_data.shading.studio_light = v

    def shading_colortype_get(self): return self.context.space_data.shading.color_type
    def shading_colortype_set(self, v): self.context.space_data.shading.color_type = v

    def shading_color_get(self): return self.context.space_data.shading.single_color
    def shading_color_set(self, v): self.context.space_data.shading.single_color = v

    def shading_backface_get(self): return self.context.space_data.shading.show_backface_culling
    def shading_backface_set(self, v): self.context.space_data.shading.show_backface_culling = v

    def shading_shadows_get(self): return self.context.space_data.shading.show_shadows
    def shading_shadows_set(self, v): self.context.space_data.shading.show_shadows = v

    def shading_xray_get(self): return self.context.space_data.shading.show_xray
    def shading_xray_set(self, v): self.context.space_data.shading.show_xray = v

    def shading_cavity_get(self): return self.context.space_data.shading.show_cavity
    def shading_cavity_set(self, v): self.context.space_data.shading.show_cavity = v

    def shading_outline_get(self): return self.context.space_data.shading.show_object_outline
    def shading_outline_set(self, v): self.context.space_data.shading.show_object_outline = v

    def quadview_get(self):     return bool(self.context.space_data.region_quadviews)
    def quadview_toggle(self):  bpy.ops.screen.region_quadview({'area': self.context.area, 'region': self._get_region(label='window')})
    def quadview_set(self, v):
                                if self.quadview_get() != v: self.quadview_toggle()
    def quadview_hide(self):    self.quadview_set(False)
    def quadview_show(self):    self.quadview_set(True)

    def viewaa_get(self):       return self.context.preferences.system.viewport_aa
    def viewaa_set(self, v):    self.context.preferences.system.viewport_aa = v
    def viewaa_simplify(self):  self.viewaa_set('FXAA' if self.viewaa_get() != 'OFF' else 'OFF')


    #########################################
    # Overlays

    def overlays_get(self):     return self.context.space_data.overlay.show_overlays
    def overlays_set(self, v):  self.context.space_data.overlay.show_overlays = v
    def overlays_hide(self):    self.overlays_set(False)
    def overlays_show(self):    self.overlays_set(True)
    def overlays_restore(self): self._storerestore.restore('overlays')


    #########################################
    # Gizmo

    def gizmo_get(self):
        # return self.context.space_data.show_gizmo
        spc = self.context.space_data
        settings = { k:getattr(spc, k) for k in dir(spc) if k.startswith('show_gizmo') }
        # print('manipulator_settings:', settings)
        return settings
    def gizmo_set(self, v):
        # self.context.space_data.show_gizmo = v
        spc = self.context.space_data
        if type(v) is bool:
            for k in dir(spc):
                # DO NOT CHANGE `show_gizmo` VALUE
                if not k.startswith('show_gizmo_'): continue
                setattr(spc, k, v)
        else:
            for k,v_ in v.items():
                setattr(spc, k, v_)
    def gizmo_hide(self):       self.gizmo_set(False)
    def gizmo_show(self):       self.gizmo_set(True)

