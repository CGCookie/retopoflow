'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

import os
import math
import inspect
from inspect import ismethod, isfunction, signature
from collections import namedtuple
from contextlib import contextmanager

import bpy
import bpy.utils.previews

from .decorators import blender_version_wrapper, only_in_blender_version, add_cache, ignore_exceptions
from .functools import find_fns, self_wrapper
from .blender_cursors import Cursors
from ..terminal import term_printer



def iter_all_view3d_areas(*, screen=None):
    if screen:
        yield from (a for a in screen.areas if a.type == 'VIEW_3D')
        return

    yield from (
        a
        for wm in bpy.data.window_managers.values()
        for win in wm.windows
        for a in win.screen.areas
        if a.type == 'VIEW_3D'
    )

def iter_all_view3d_spaces():
    yield from (
        s
        for a in iter_all_view3d_areas()
        for s in a.spaces
        if s.type == 'VIEW_3D'
    )


def get_view3d_area(context=None):
    # assuming: context.screen is correct, and a SINGLE VIEW_3D area!
    if not context: context = bpy.context
    if context.area and context.area.type == 'VIEW_3D': return context.area
    return next((a for a in context.screen.areas if a.type == 'VIEW_3D'), None)

def get_view3d_region(context=None):
    if not context: context = bpy.context
    if context.region and context.region.type == 'WINDOW': return context.region
    area = get_view3d_area(context=context)
    return next((r for r in area.regions if r.type == 'WINDOW'),  None) if area else None

def get_view3d_space(context=None):
    if not context: context = bpy.context
    if context.space_data and context.space_data.type == 'VIEW_3D': return context.space_data
    area = get_view3d_area(context=context)
    return next((s for s in area.spaces  if s.type == 'VIEW_3D'), None) if area else None


class StoreRestore:
    def __init__(self, *, init_storage=None):
        self._bindings = {}
        self._bind_order = []
        self._storage = {}
        self._restoring = False
        self._callbacks = []
        self._delay = False
        self._delayed = False
        if init_storage: self.init_storage(init_storage)

    def init_storage(self, storage, *, update_only=False):
        if update_only:
            for k in storage:
                self._storage[k] = storage[k]
        else:
            self._storage = storage

    def bind(self, key, fn_get, fn_set, fn_restore=None):
        def fn_set_wrapper():
            def wrapped(*args, **kwargs):
                # print(f'SETTING {key} {args} {kwargs} {self._restoring} {fn_set} {fn_restore}')
                if self._restoring and fn_restore:
                    return fn_restore(*args, **kwargs)
                return fn_set(*args, **kwargs)
            return wrapped
        self._bindings[key] = (fn_get, fn_set_wrapper())
        self._bind_order.append(key)
    def bind_all(self, iter_key_get_set_optrestore):
        for (key, *fns) in iter_key_get_set_optrestore:
            self.bind(key, *fns)

    def clear_storage_change_callbacks(self):
        self._callbacks.clear()
    def register_storage_change_callback(self, fn):
        if fn in self._callbacks: return
        self._callbacks.append(fn)
        self.call_storage_change_callback()
    @contextmanager
    def delay_storage_change_callback(self):
        try:
            self._delay = True
            self._delayed = False
            yield None
        finally:
            # print(f'$$ {self._delayed=}')
            self._delay = False
            if self._delayed:
                self.call_storage_change_callback()
    def call_storage_change_callback(self):
        if not self._callbacks: return
        if self._delay:
            self._delayed = True
        else:
            for fn in self._callbacks:
                fn(self._storage)

    def __setitem__(self, k, v): self.set(k, v)
    def set(self, k, v):
        self.store(k, only_new=True)
        _, fn_set = self._bindings[k]
        fn_set(v)
    def __getitem__(self, k): return self.get(k)
    def get(self, k):
        fn_get, _ = self._bindings[k]
        return fn_get()

    def store(self, k, *, only_new=True):
        if only_new and k in self._storage: return
        fn_get, _ = self._bindings[k]
        nv = fn_get()
        if k in self._storage:
            # print(f'>> {k=} {self._storage[k]=} {nv=}')
            if self._storage[k] == nv: return
        else:
            # print(f'++ {k=} {nv=}')
            pass
        self._storage[k] = nv
        self.call_storage_change_callback()
    def store_all(self, *, only_new=True):
        with self.delay_storage_change_callback():
            for k in self._bindings:
                self.store(k, only_new=only_new)

    def discard(self, k):
        # print(f'-- discard({k=})')
        self._storage.discard(k)
        self.call_storage_change_callback()
    def remove(self, k):
        # print(f'-- remove({k=})')
        self._storage.remove(k)
        self.call_storage_change_callback()

    def restore(self, k, *, discard=False):
        if k not in self._storage: return
        if k not in self._bindings:
            print(f'Addon Common: Could not find setter for {k}')
        else:
            # print(f'Addon Common: Restoring {k} = {self._storage[k]}')
            _, fn_set = self._bindings[k]
            try:
                self._restoring = True
                fn_set(self._storage[k])
            finally:
                self._restoring = False
        if discard: self.discard(k)
    def restore_all(self, *, ignore=None, discard=False):
        ignore = ignore or set()
        with self.delay_storage_change_callback():
            for k in self._bind_order:
                if k not in self._storage or k in ignore: continue
                self.restore(k, discard=discard)


class BlenderSettings:

    #########################################
    # Workspace and Scene

    @staticmethod
    def workspace_get(): return bpy.context.window.workspace.name
    @staticmethod
    def workspace_set(name): bpy.context.window.workspace = bpy.data.workspaces[name]

    @staticmethod
    def scene_get(): return bpy.context.window.scene.name
    @staticmethod
    def scene_set(name): bpy.context.window.scene = bpy.data.scenes[name]

    @staticmethod
    def scene_scale_get(): return bpy.context.scene.unit_settings.scale_length
    @staticmethod
    def scene_scale_set(v): bpy.context.scene.unit_settings.scale_length = v


    #########################################
    # Objects
    # NOTE: select, active, and visible properties are stored in scene!

    @staticmethod
    def objects_selected_get():
        return [ o.name for o in bpy.data.objects if o.select_get() ]
    @staticmethod
    def objects_selected_restore(names):
        BlenderSettings.objects_selected_set(names, only=True)
    @staticmethod
    def objects_selected_set(names, *, only=False):
        names = set(names)
        for o in bpy.data.objects:
            if only: o.select_set(o.name in names)
            elif o.name in names: o.select_set(True)

    @staticmethod
    def objects_visible_get():
        return [ o.name for o in bpy.data.objects if not o.hide_viewport ] #hide_get() ]
    @staticmethod
    def objects_visible_restore(names):
        BlenderSettings.objects_visible_set(names, only=True)
    @staticmethod
    def objects_visible_set(names, *, only=False):
        names = set(names)
        for o in bpy.data.objects:
            if only: o.hide_viewport = (o.name not in names) #hide_set(o.name not in names)
            elif o.name in names: o.hide_viewport = False # hide_set(False)

    @staticmethod
    def object_active_get():
        return bpy.context.view_layer.objects.active.name if bpy.context.view_layer.objects.active else None
    @staticmethod
    def object_active_set(name):
        if not name: return
        obj = bpy.data.objects[name]
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj


    #########################################
    # Header, Status Bar, Cursor

    @staticmethod
    def header_text_set(s=None): get_view3d_area().header_text_set(text=s)
    @staticmethod
    def header_text_restore(): BlenderSettings.header_text_set()

    @staticmethod
    def statusbar_text_set(s=None, *, internal=False):
        if not internal: bpy.context.workspace.status_text_set(text=s)
        else:            bpy.context.workspace.status_text_set_internal(text=s)
    @staticmethod
    def statusbar_text_restore():
        BlenderSettings.statusbar_text_set()

    @staticmethod
    def cursor_set(cursor): Cursors.set(cursor)
    @staticmethod
    def cursor_restore(): Cursors.restore()


    #########################################
    # Region Panels

    @staticmethod
    def _get_region(*, label=None, type=None):
        if label: type = region_label_to_data[label].type
        area = get_view3d_area()
        return next((r for r in area.regions if r.type == type), None)
    @staticmethod
    def _get_regions():
        return { label: BlenderSettings._get_region(label=label) for label in region_label_to_data }

    @staticmethod
    def panels_get():
        rgns = BlenderSettings._get_regions()
        return {
            label: (rgns[label].width > 1 and rgns[label].height > 1) if rgns[label] else False
            for label in region_label_to_data
        }
    @staticmethod
    def panels_set(state):
        ctx = create_simple_context(bpy.context)
        current = BlenderSettings.panels_get()
        for label, val in state.items():
            if val == current[label]: continue
            fn_toggle = region_label_to_data[label].fn_toggle
            if fn_toggle: fn_toggle(ctx)
    @staticmethod
    def panels_hide(*, ignore=None):
        ignore = ignore or set()
        BlenderSettings.panels_set({
            label: False for label in region_label_to_data if label not in ignore
        })



    #########################################
    # Viewport Shading and Settings

    @staticmethod
    def shading_type_get(): return get_view3d_space().shading.type
    @staticmethod
    def shading_type_set(v): get_view3d_space().shading.type = v

    @staticmethod
    def shading_light_get(): return get_view3d_space().shading.light
    @staticmethod
    def shading_light_set(v): get_view3d_space().shading.light = v

    @staticmethod
    def shading_matcap_get(): return get_view3d_space().shading.studio_light
    @staticmethod
    @ignore_exceptions(TypeError)  # ignore type error (enum value doesn't exist in this context)
    def shading_matcap_set(v): get_view3d_space().shading.studio_light = v

    @staticmethod
    def shading_colortype_get(): return get_view3d_space().shading.color_type
    @staticmethod
    @ignore_exceptions(TypeError)  # ignore type error (enum value doesn't exist in this context)
    def shading_colortype_set(v): get_view3d_space().shading.color_type = v

    @staticmethod
    def shading_color_get(): return get_view3d_space().shading.single_color
    @staticmethod
    def shading_color_set(v): get_view3d_space().shading.single_color = v

    @staticmethod
    def shading_backface_get(): return get_view3d_space().shading.show_backface_culling
    @staticmethod
    def shading_backface_set(v): get_view3d_space().shading.show_backface_culling = v

    @staticmethod
    def shading_shadows_get(): return get_view3d_space().shading.show_shadows
    @staticmethod
    def shading_shadows_set(v): get_view3d_space().shading.show_shadows = v

    @staticmethod
    def shading_xray_get(): return get_view3d_space().shading.show_xray
    @staticmethod
    def shading_xray_set(v): get_view3d_space().shading.show_xray = v

    @staticmethod
    def shading_cavity_get(): return get_view3d_space().shading.show_cavity
    @staticmethod
    def shading_cavity_set(v): get_view3d_space().shading.show_cavity = v

    @staticmethod
    def shading_outline_get(): return get_view3d_space().shading.show_object_outline
    @staticmethod
    def shading_outline_set(v): get_view3d_space().shading.show_object_outline = v

    @staticmethod
    def shading_restore():
        for k in ['type','light','matcap','colortype','color','backface','shadows','xray','cavity','outline']:
            BlenderSettings._storerestore.restore(f'shading {k}')

    @staticmethod
    def quadview_get(): return bool(get_view3d_space().region_quadviews)
    @staticmethod
    def quadview_toggle():
        bpy.ops.screen.region_quadview({'area': get_view3d_area(), 'region': BlenderSettings._get_region(label='window')})
    @staticmethod
    def quadview_set(v):
        if BlenderSettings.quadview_get() != v: BlenderSettings.quadview_toggle()
    @staticmethod
    def quadview_hide(): BlenderSettings.quadview_set(False)
    @staticmethod
    def quadview_show(): BlenderSettings.quadview_set(True)

    @staticmethod
    def viewaa_get(): return bpy.context.preferences.system.viewport_aa
    @staticmethod
    def viewaa_set(v): bpy.context.preferences.system.viewport_aa = v
    @staticmethod
    def viewaa_simplify():
        BlenderSettings.viewaa_set('FXAA' if BlenderSettings.viewaa_get() != 'OFF' else 'OFF')

    @staticmethod
    def clip_distances_get():
        spc = get_view3d_space()
        return (spc.clip_start, spc.clip_end)
    @staticmethod
    def clip_distances_set(v):
        spc = get_view3d_space()
        spc.clip_start, spc.clip_end = v


    #########################################
    # Overlays

    @staticmethod
    def overlays_get(): return get_view3d_space().overlay.show_overlays
    @staticmethod
    def overlays_set(v): get_view3d_space().overlay.show_overlays = v
    @staticmethod
    def overlays_hide(): BlenderSettings.overlays_set(False)
    @staticmethod
    def overlays_show(): BlenderSettings.overlays_set(True)

    @staticmethod
    def overlays_restore(): BlenderSettings._storerestore.restore('overlays')


    #########################################
    # Gizmo

    @staticmethod
    def gizmo_get():
        # return bpy.context.space_data.show_gizmo
        spc = get_view3d_space()
        settings = { k:getattr(spc, k) for k in dir(spc) if k.startswith('show_gizmo') }
        # print('manipulator_settings:', settings)
        return settings
    @staticmethod
    def gizmo_set(v):
        # bpy.context.space_data.show_gizmo = v
        spc = get_view3d_space()
        if type(v) is bool:
            for k in dir(spc):
                # DO NOT CHANGE `show_gizmo` VALUE
                if not k.startswith('show_gizmo_'): continue
                setattr(spc, k, v)
        else:
            for k,v_ in v.items():
                setattr(spc, k, v_)
    @staticmethod
    def gizmo_hide(): BlenderSettings.gizmo_set(False)
    @staticmethod
    def gizmo_show(): BlenderSettings.gizmo_set(True)


    #########################################
    # StoreRestore instance

    @staticmethod
    def storerestore_init(*, init_storage=None, clear_callbacks=True):
        cls = BlenderSettings
        cls._storerestore = StoreRestore(init_storage=init_storage)
        cls._storerestore.bind_all([
            # ('workspace', cls.workspace_get, cls.workspace_set),
            # ('scene', cls.scene_get, cls.scene_set),
            # IMPORTANT: visible must be _before_ selected, because object must be visible before it can be selected
            ('objects visible',   cls.objects_visible_get,   cls.objects_visible_set,  cls.objects_visible_restore),
            ('objects selected',  cls.objects_selected_get,  cls.objects_selected_set, cls.objects_selected_restore),
            ('object active',     cls.object_active_get,     cls.object_active_set),
            ('scene scale',       cls.scene_scale_get,       cls.scene_scale_set),
            ('panels',            cls.panels_get,            cls.panels_set),
            ('shading type',      cls.shading_type_get,      cls.shading_type_set),
            ('shading light',     cls.shading_light_get,     cls.shading_light_set),
            ('shading matcap',    cls.shading_matcap_get,    cls.shading_matcap_set),
            ('shading colortype', cls.shading_colortype_get, cls.shading_colortype_set),
            ('shading color',     cls.shading_color_get,     cls.shading_color_set),
            ('shading backface',  cls.shading_backface_get,  cls.shading_backface_set),
            ('shading shadows',   cls.shading_shadows_get,   cls.shading_shadows_set),
            ('shading xray',      cls.shading_xray_get,      cls.shading_xray_set),
            ('shading cavity',    cls.shading_cavity_get,    cls.shading_cavity_set),
            ('shading outline',   cls.shading_outline_get,   cls.shading_outline_set),
            ('quadview',          cls.quadview_get,          cls.quadview_set),
            ('overlays',          cls.overlays_get,          cls.overlays_set),
            ('gizmo',             cls.gizmo_get,             cls.gizmo_set),
            ('viewaa',            cls.viewaa_get,            cls.viewaa_set),
            ('clip distances',    cls.clip_distances_get,    cls.clip_distances_set),
        ])
        if clear_callbacks:
            cls._storerestore.clear_storage_change_callbacks()

    def __init__(self, **kwargs):
        self.storerestore_init(**kwargs)

    @staticmethod
    def init_storage(*args, **kwargs):
        BlenderSettings._storerestore.init_storage(*args, **kwargs)
    @staticmethod
    def restore_all(*args, **kwargs):
        BlenderSettings._storerestore.restore_all(*args, **kwargs)



def workspace_duplicate(*, context=None, name=None, use=True):
    # unfortunately, there isn't an elegant way to get a newly created workspace.
    # but, each workspace has a unique name, so we can use their names to determine
    # which workspace is new.
    context = context or bpy.context
    cur_name = context.window.workspace.name
    prev_workspaces = {workspace.name for workspace in bpy.data.workspaces}
    bpy.ops.workspace.duplicate()
    new_workspace = next((workspace for workspace in bpy.data.workspaces if workspace.name not in prev_workspaces))
    if name: new_workspace.name = name
    context.window.workspace = new_workspace if use else bpy.data.workspaces[cur_name]
    return new_workspace

def scene_duplicate(*, context=None, type='LINK_COPY', name=None, use=True):
    # unfortunately, there isn't an elegant way to get a newly created scene.
    # but, each scene has a unique name, so we can use their names to determine
    # which scene is new.
    context = context or bpy.context
    cur_name = context.window.scene.name
    prev_scenes = {scene.name for scene in bpy.data.scenes}
    bpy.ops.scene.new(type=type)
    new_scene = next((scene for scene in bpy.data.scenes if scene.name not in prev_scenes))
    if name: new_scene.name = name
    context.window.scene = new_scene if use else bpy.data.scenes[cur_name]
    return new_scene



def create_simple_context(context=None):
    return {
        a: getattr(context or bpy.context, a)
        for a in ['area', 'space_data', 'window', 'screen', 'region']
    }



# class Temp:
#     _store = {}

#     @classmethod
#     def assign(cls, var, val):
#         frame = inspect.currentframe().f_back
#         f_globals, f_locals = frame.f_globals, frame.f_locals
#         if var not in cls._store:
#             cls._store[var] = {
#                 'val': eval(var, globals=f_globals, locals=f_locals),
#                 'globals': f_globals,
#                 'locals': f_locals,
#             }
#         exec(f'{var} = {val}', globals=f_globals, locals=f_locals)

#     @classmethod
#     def restore_all(cls):
#         for var, data in cls._store.items():
#             exec(f'{var} = {data["val"]}', globals=data['globals'], locals=data['locals'])
#         cls._store.clear()

#     @classmethod
#     def restore(cls, var):
#         val, f_globals, f_locals = cls._store[var]
#         exec(f'{var} = {data["val"]}', globals=f_globals, locals=f_locals)
#         del cls._store[var]

#     @classmethod
#     def discard(cls, var):
#         if var in cls._store[var]:
#             del cls._store[var]


# class TempBPYData:
#     '''
#     wrapper for bpy.data that allows the changing of settings while
#     storing original settings for later restoration.

#     This is _different_ than pre-storing the settings, in that we don't
#     need to know beforehand what should be stored/restored.
#     '''

#     _always_store = True
#     _store = {}

#     is_bpy_type = lambda o: any(isinstance(o, t) for t in {
#         bpy.types.bpy_func,
#         bpy.types.bpy_prop,
#         bpy.types.bpy_prop_array,
#         bpy.types.bpy_struct,
#         bpy.types.bpy_struct_meta_idprop,
#     })

#     is_stop_type = lambda o: any(isinstance(o, t) for t in {
#         bpy.types.Object,
#     })

#     class WKey:
#         @classmethod
#         def Attr(cls, key): return cls(key, True)
#         @classmethod
#         def Item(cls, key): return cls(key, False)

#         def __init__(self, key, is_attr):
#             self._key = key
#             self._is_attr = is_attr

#         def __str__(self):
#             return f'.{self._key}' if self._is_attr else f'[{self._key}]'

#         @property
#         def key(self):     return self._key
#         @property
#         def is_attr(self): return self._is_attr
#         @property
#         def is_item(self): return not self._is_attr

#         def get(self, data):
#             return getattr(data, self._key) if self._is_attr else data[self._key]
#         def set(self, data, val):
#             if self._is_attr: setattr(data, self._key, val)
#             else: data[self._key] = val

#     class Walker:
#         def __init__(self, *keys, from_walker=None):
#             if from_walker:
#                 assert from_walker.in_struct
#                 full_keys = from_walker.keys
#                 data = from_walker.data
#                 path = from_walker.path
#             else:
#                 full_keys = tuple()
#                 data = bpy.data
#                 path = 'bpy.data'
#             pre_data = None
#             for key in keys:
#                 data, pre_data, path = key.get(data), data
#                 path = f'{path}{key}'
#                 full_keys += key

#             self.__dict__['_data'] = {
#                 'path':      path,
#                 'keys':      full_keys,
#                 'data':      data,
#                 'prev':      (pre_data, keys[-1]),
#                 'in_struct': TempBPYData.is_bpy_type(data),
#                 'is_stop':   TempBPYData.is_stop_type(data),
#             }

#         def __repr__(self):                  return f'<Walker {self.path} = {self.data}>'
#         def __iter__(self):                  return iter(self.data)
#         def __call__(self, *args, **kwargs): return self.data(*args, **kwargs)
#         def __getattr__(self, key):          return self.get(key, True)
#         def __setattr__(self, key, val):     return self.set(key, True, val)
#         def __getitem__(self, key):          return self.get(key, False)
#         def __setitem__(self, key, val):     return self.set(key, False, val)

#         @classmethod
#         def unwrap(cls, val): return val.data if isinstance(val, cls) else val

#         @property
#         def path(self):       return self.__dict__['_data']['path']
#         @property
#         def keys(self): return self.__dict__['_data']['keys']
#         @property
#         def data(self):       return self.__dict__['_data']['data']
#         @property
#         def prev(self):       return self.__dict__['_data']['prev']
#         @property
#         def in_struct(self):  return self.__dict__['_data']['in_struct']
#         @property
#         def is_struct(self):  return self.__dict__['_data']['is_stop']

#         def get(self, key, attr):
#             if self.is_stop:
#                 return getattr(self.data, key) if attr else self.data[key]
#             wk = TempBPYData.WKey(key, attr)
#             w = TempBPYData.Walker(wk, from_walker=self)
#             return w if w.in_struct else w.data
#         def set(self, key, attr, val):
#             assert self.in_struct
#             TempBPYData.store(list(self.keys) + [(key, attr)])
#             val = self.unwrap(val)
#             if attr: setattr(self.data, key, val)
#             else:    self.data[key] = val
#         # def ignore(self)

#     @classmethod
#     def debug_print_store(cls):
#         print(f'TempBPYData.store = {{')
#         for keys_attrs, val in cls._store.items():
#             print(f'  {cls.keys_attrs_to_path(keys_attrs)}: {val}')
#         print(f'}}')

#     @classmethod
#     def get_from_keys_attrs(cls, keys_attrs):
#         data = bpy.data
#         for (key, attr) in keys_attrs:
#             data = cls.get_from_key(data, key)
#         return data
#     @classmethod
#     def get_from_key(cls, data, key):
#         return getattr(data, key[1:]) if key.startswith('.') else data[key][1:-1]
#     @classmethod
#     def set_from_key_attr(cls, data, key, attr, val):
#         if attr: setattr(data, key, val)
#         else:    data[key] = val

#     @classmethod
#     def keys_to_path(cls, keys_attrs):
#         path = 'bpy.data'
#         for (key, attr) in keys_attrs:
#             path += f'.{key}' if attr else f'[{key}]'
#         return path

#     @classmethod
#     def store(cls, keys_attrs):
#         store_key = tuple(keys_attrs)
#         store_val = cls.get_from_keys_attrs(keys_attrs)
#         if cls._always_store or not cls.is_bpy_type(store_val):
#             # only remember previous values if keys points to a non bpy_type.
#             # an example of keys that point to a bpy_type that we would wish to assign
#             # bpy.data.window_managers[0].windows[0].view_layer.objects.active
#             cls._store.setdefault(store_key, store_val)

#     @classmethod
#     def clear(cls):
#         cls._store.clear()

#     @classmethod
#     def discard(cls, keys_attrs):
#         if type(keys_attrs) is cls.Walker:
#             keys_attrs = keys_attrs.key_attrs
#         if keys_attrs in cls._store:
#             del cls._store[keys_attrs]

#     @classmethod
#     def restore_all(cls, *, clear=True):
#         for (keys_attrs, val) in cls._store.items():
#             data = bpy.data
#             for (key, attr) in keys_attrs[:-1]:
#                 data = cls.get_from_key(data, key)
#             (key, attr) = keys_attrs[-1]
#             cls.set_from_key_attr(data, key, attr, val)
#         if clear:
#             cls.clear()

#     @classmethod
#     def is_bpy_type(cls, o):
#         if any(isinstance(o, t) for t in cls._stop_at_types):
#             return False
#         return any(isinstance(o, t) for t in cls._bpy_types)

#     @classmethod
#     def __getattr__(cls, key): return cls.Walker(cls.WKey(key, True))
#     @classmethod
#     def __getitem__(cls, key): return cls.Walker(cls.WKey(key, False))

#     def __init__(self): pass

# bpy_data = TempBPYData()

# if True:
#     win = bpy_data.window_managers[0].windows[0]
#     vlobjs = win.view_layer.objects

#     print(vlobjs.active)

#     vlobjs.active = bpy_data.objects['Suzanne']
#     area = win.screen.areas[2]
#     space = area.spaces.active
#     space.show_region_ui = False

#     print([(o.name, o.select_get()) for o in vlobjs])

#     TempBPYData.discard(space.show_region_ui)

#     TempBPYData.debug_print_store()
#     TempBPYData.restore_all()





###########################################################
# Mode

def mode_translate(mode):
    return {
        'OBJECT':        'OBJECT',          # for some reason, we must
        'EDIT_MESH':     'EDIT',            # translate bpy.context.mode
        'SCULPT':        'SCULPT',          # to something that
        'PAINT_VERTEX':  'VERTEX_PAINT',    # bpy.ops.object.mode_set()
        'PAINT_WEIGHT':  'WEIGHT_PAINT',    # accepts...
        'PAINT_TEXTURE': 'TEXTURE_PAINT',
    }.get(mode, mode)                       # WHY DO YOU DO THIS, BLENDER!?!?!?

def mode_set(mode):
    bpy.ops.object.mode_set(mode_translate(mode))

#############################################################

def index_of_area_space(area, space):
    return next(iter(i for (i,s) in enumerate(area.spaces) if s == space))


#############################################################

@add_cache('root', {})
def get_path_from_addon_root(*path_join):
    path_here = os.path.realpath(os.path.dirname(__file__))
    path_addon_root = os.path.realpath(os.path.join(path_here, '..', '..'))
    return os.path.join(path_addon_root, *path_join)
    # fn_path = lambda filename: os.path.realpath(os.path.dirname(filename))
    # path_here = fn_path(__file__)
    # if path_here not in get_path_from_addon_root.root:
    #     import addon_utils
    #     # NOTE: append '/' to end to prevent matching subfolders that have appended stuff
    #     modules = [mod for mod in addon_utils.modules() if path_here.startswith(fn_path(mod.__file__) + '/')]
    #     assert len(modules) == 1, f'Could not find root for add-on containing {path_here}: {modules}'
    #     get_path_from_addon_root.root[path_here] = fn_path(modules[0].__file__)
    # return os.path.join(get_path_from_addon_root.root[path_here], *path_join)

def get_path_from_addon_common(*path_join):
    path_here = os.path.dirname(__file__)
    return os.path.realpath(os.path.join(path_here, '..', *path_join))

def get_path_shortened_from_addon_root(path):
    path_addon = get_path_from_addon_root()
    path_addons = os.path.dirname(path_addon)
    path = os.path.realpath(path)
    assert path.startswith(path_addons), f'Unexpected start of path:\n  {path=}\n  {path_addons=}'
    return path[len(path_addons)+1:]  # +1 to skip leading '/'

#############################################################

class BlenderIcon:
    blender_icons = bpy.utils.previews.new()
    path_icons = get_path_from_addon_root()   # default to add-on root

    @staticmethod
    def icon_id(file):
        if file not in BlenderIcon.blender_icons:
            BlenderIcon.blender_icons.load(
                file,
                os.path.join(BlenderIcon.path_icons, file),
                'IMAGE',
            )
        return BlenderIcon.blender_icons[file].icon_id


#############################################################

class ModifierWrapper_Mirror:
    '''
    normalize the mirror modifier API across 2.79 and 2.80
    '''
    @staticmethod
    def create_new(obj):
        bpy.ops.object.modifier_add(type='MIRROR')
        mod = ModifierWrapper_Mirror(obj, obj.modifiers[-1])
        mod.set_defaults()
        return mod

    @staticmethod
    def get_from_object(obj):
        for mod in obj.modifiers:
            if mod.type != 'MIRROR': continue
            return ModifierWrapper_Mirror(obj, mod)
        return None

    def __init__(self, obj, modifier):
        self._reading = True
        self.obj = obj
        self.mod = modifier
        self.read()

    @property
    def x(self):
        return 'x' in self._symmetry
    @x.setter
    def x(self, v):
        if v: self._symmetry.add('x')
        else: self._symmetry.discard('x')
        self.write()

    @property
    def y(self):
        return 'y' in self._symmetry
    @y.setter
    def y(self, v):
        if v: self._symmetry.add('y')
        else: self._symmetry.discard('y')
        self.write()

    @property
    def z(self):
        return 'z' in self._symmetry
    @z.setter
    def z(self, v):
        if v: self._symmetry.add('z')
        else: self._symmetry.discard('z')
        self.write()

    @property
    def use_clip(self):
        return self.mod.use_clip
    @use_clip.setter
    def use_clip(self, v):
        self.mod.use_clip = v

    @property
    def xyz(self):
        return set(self._symmetry)

    @property
    def symmetry_threshold(self):
        return self._symmetry_threshold
    @symmetry_threshold.setter
    def symmetry_threshold(self, v):
        self._symmetry_threshold = max(0, float(v))
        self.write()


    def enable_axis(self, axis):
        self._symmetry.add(axis)
        self.write()
    def disable_axis(self, axis):
        self._symmetry.discard(axis)
        self.write()
    def disable_all(self):
        self._symmetry.clear()
        self.write()
    def is_enabled_axis(self, axis):
        return axis in self._symmetry

    def set_defaults(self):
        self.mod.merge_threshold = 0.001
        self.mod.show_expanded = False
        self.mod.show_on_cage = True
        self.mod.use_mirror_merge = True
        self.mod.show_viewport = True
        self.disable_all()

    @blender_version_wrapper('<', '2.80')
    def read(self):
        self._reading = True
        self._symmetry = set()
        if self.mod.use_x: self._symmetry.add('x')
        if self.mod.use_y: self._symmetry.add('y')
        if self.mod.use_z: self._symmetry.add('z')
        self._symmetry_threshold = self.mod.merge_threshold
        self.show_viewport = self.mod.show_viewport
        self._reading = False
    @blender_version_wrapper('>=', '2.80')
    def read(self):
        self._reading = True
        self._symmetry = set()
        if self.mod.use_axis[0]: self._symmetry.add('x')
        if self.mod.use_axis[1]: self._symmetry.add('y')
        if self.mod.use_axis[2]: self._symmetry.add('z')
        self._symmetry_threshold = self.mod.merge_threshold
        self.show_viewport = self.mod.show_viewport
        self._reading = False

    @blender_version_wrapper('<', '2.80')
    def write(self):
        if self._reading: return
        self.mod.use_x = self.x
        self.mod.use_y = self.y
        self.mod.use_z = self.z
        self.mod.merge_threshold = self._symmetry_threshold
        self.mod.show_viewport = self.show_viewport
    @blender_version_wrapper('>=', '2.80')
    def write(self):
        if self._reading: return
        self.mod.use_axis[0] = self.x
        self.mod.use_axis[1] = self.y
        self.mod.use_axis[2] = self.z
        self.mod.merge_threshold = self._symmetry_threshold
        self.mod.show_viewport = self.show_viewport




#############################################################
# TODO: generalize these functions to be add_object, etc.

def set_object_selection(o, sel): o.select_set(sel)
def link_object(o):       bpy.context.scene.collection.objects.link(o)
def set_active_object(o): bpy.context.view_layer.objects.active = o

# use this, because bpy.context might not Screen context!
# see https://docs.blender.org/api/current/bpy.context.html
def get_active_object(): return bpy.context.view_layer.objects.active

def get_from_dict_or_object(o, k): return o[k] if type(o) is dict else getattr(o, k)
def toggle_property(o, k): setattr(o, k, not getattr(o, k))

def toggle_screen_header(ctx):
    # print(f'Addon Common Warning: Cannot toggle header visibility (addon_common/common/blender.py: toggle_screen_header)')
    # print(f'  Skipping while bug exists in Blender 3.0+, see: https://developer.blender.org/T93410')
    space = ctx['space_data'] if type(ctx) is dict else get_view3d_space(ctx)
    toggle_property(space, 'show_region_header')

def toggle_screen_tool_header(ctx):
    space = ctx['space_data'] if type(ctx) is dict else get_view3d_space(ctx)
    toggle_property(space, 'show_region_tool_header')

def toggle_screen_toolbar(ctx):
    space = ctx['space_data'] if type(ctx) is dict else get_view3d_space(ctx)
    toggle_property(space, 'show_region_toolbar')

def toggle_screen_properties(ctx):
    space = ctx['space_data'] if type(ctx) is dict else get_view3d_space(ctx)
    toggle_property(space, 'show_region_ui')

def toggle_screen_lastop(ctx):
    space = ctx['space_data'] if type(ctx) is dict else get_view3d_space(ctx)
    toggle_property(space, 'show_region_hud')



# regions for 3D View:
#            0       1            2           3    4       5
#     279: [ HEADER, TOOLS,       TOOL_PROPS, UI,  WINDOW         ]
#     280: [ HEADER, TOOLS,       UI,         HUD, WINDOW         ]
#     300: [ HEADER, TOOL_HEADER, TOOLS,      UI,  HUD,    WINDOW ]
# could hard code the indices, but these magic numbers might change.
# will stick to magic (but also way more descriptive) types
RegionData = namedtuple('RegionData', 'type fn_toggle')
region_label_to_data = {
    'header':      RegionData('HEADER',      toggle_screen_header),
    'tool header': RegionData('TOOL_HEADER', toggle_screen_tool_header),
    'tool shelf':  RegionData('TOOLS',       toggle_screen_toolbar),
    'properties':  RegionData('UI',          toggle_screen_properties),
    'hud':         RegionData('HUD',         toggle_screen_lastop),
    'window':      RegionData('WINDOW',      None),
}



tagged_redraw_all = False
tag_reasons = set()
def tag_redraw_all(reason, only_tag=True):
    global tagged_redraw_all, tag_reasons
    if False: term_printer.sprint(f'tagging redraw all: already={1 if tagged_redraw_all else 0} only_tag={1 if only_tag else 0}')
    tagged_redraw_all = True
    tag_reasons.add(reason)
    if not only_tag: perform_redraw_all()
def perform_redraw_all(only_area=None):
    global tagged_redraw_all, tag_reasons
    if not tagged_redraw_all: return
    if False: term_printer.sprint('Redrawing:', tag_reasons)
    tag_reasons.clear()
    tagged_redraw_all = False
    if only_area:
        only_area.tag_redraw()
    else:
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for ar in win.screen.areas:
                    ar.tag_redraw()



class BlenderPopupOperator:
    def __init__(self, idname, **kwargs):
        self.idname = idname
        self.kwargs = kwargs
    def draw(self, layout):
        layout.operator(self.idname, **self.kwargs)

def show_blender_popup(message, *, title="Message", icon="INFO", wrap=80):
    '''
    icons: NONE, QUESTION, ERROR, CANCEL,
           TRIA_RIGHT, TRIA_DOWN, TRIA_LEFT, TRIA_UP,
           ARROW_LEFTRIGHT, PLUS,
           DISCLOSURE_TRI_DOWN, DISCLOSURE_TRI_RIGHT,
           RADIOBUT_OFF, RADIOBUT_ON,
           MENU_PANEL, BLENDER, GRIP, DOT, COLLAPSEMENU, X,
           GO_LEFT, PLUG, UI, NODE, NODE_SEL,
           FULLSCREEN, SPLITSCREEN, RIGHTARROW_THIN, BORDERMOVE,
           VIEWZOOM, ZOOMIN, ZOOMOUT, ...
    see: https://git.blender.org/gitweb/gitweb.cgi/blender.git/blob/HEAD:/source/blender/editors/include/UI_icons.h
    '''  # noqa

    if not message: return
    if type(message) is list:
        lines = message
    else:
        lines = message.splitlines()
    if wrap > 0:
        nlines = []
        for line in lines:
            if type(line) is str:
                spc = len(line) - len(line.lstrip())
                while len(line) > wrap:
                    i = line.rfind(' ',0,wrap)
                    if i == -1:
                        nlines += [line[:wrap]]
                        line = line[wrap:]
                    else:
                        nlines += [line[:i]]
                        line = line[i+1:]
                    if line:
                        line = ' '*spc + line
            nlines += [line]
        lines = nlines
    def draw(self,context):
        for line in lines:
            if type(line) is str:
                self.layout.label(text=line)
            elif type(line) is BlenderPopupOperator:
                line.draw(self.layout)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)
    return

def show_error_message(message, **kwargs):
    kwargs.setdefault('title', 'Error')
    kwargs.setdefault('icon', 'ERROR')
    show_blender_popup(message, **kwargs)

def get_text_block(name, create=True, error_on_fail=True):
    name = str(name)
    if name in bpy.data.texts: return bpy.data.texts[name]
    if not create: return None
    old = { t.name for t in bpy.data.texts }
    bpy.ops.text.new()
    new = { t.name for t in bpy.data.texts if t.name not in old }
    if error_on_fail:
        assert len(new) != 0, f'Could not create new text block ({name=})'
        assert len(new) == 1, f'Creating new text block added two text blocks? ({name=})'
    elif len(new) != 1:
        return None
    textblock = bpy.data.texts[new.pop()]
    textblock.name = name
    return textblock

def show_blender_text(textblock_name, hide_header=True, goto_top=True):
    if textblock_name not in bpy.data.texts:
        # no textblock to show
        return

    txt = bpy.data.texts[textblock_name]
    if goto_top:
        txt.current_line_index = 0
        txt.select_end_line_index = 0

    # duplicate the current area then change it to a text editor
    area_dupli = bpy.ops.screen.area_dupli('INVOKE_DEFAULT')
    win = bpy.context.window_manager.windows[-1]
    area = win.screen.areas[-1]
    area.type = 'TEXT_EDITOR'

    # load the text file into the correct space
    for space in area.spaces:
        if space.type == 'TEXT_EDITOR':
            space.text = txt
            space.show_word_wrap = True
            space.show_syntax_highlight = False
            space.top = 0
            if hide_header and area.regions[0].height != 1:
                # hide header
                toggle_screen_header({'window':win, 'region':area.regions[2], 'area':area, 'space_data':space})

def bversion(short=True):
    major,minor,rev = bpy.app.version
    bver_long = '%03d.%03d.%03d' % (major,minor,rev)
    bver_short = '%d.%02d' % (major, minor)
    return bver_short if short else bver_long


def event_modifier_check(event, *, ctrl=None, shift=None, alt=None, oskey=None):
    if ctrl  is not None and event.ctrl  != ctrl:  return False
    if shift is not None and event.shift != shift: return False
    if alt   is not None and event.alt   != alt:   return False
    if oskey is not None and event.oskey != oskey: return False
    return True

