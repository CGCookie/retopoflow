'''
Copyright (C) 2022 CG Cookie
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
import bpy
import inspect
from collections import namedtuple

import bpy.utils.previews

from .decorators import blender_version_wrapper, only_in_blender_version, add_cache


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



class Temp:
    _store = {}

    @classmethod
    def assign(cls, var, val):
        frame = inspect.currentframe().f_back
        f_globals, f_locals = frame.f_globals, frame.f_locals
        if var not in cls._store:
            cls._store[var] = {
                'val': eval(var, globals=f_globals, locals=f_locals),
                'globals': f_globals,
                'locals': f_locals,
            }
        exec(f'{var} = {val}', globals=f_globals, locals=f_locals)

    @classmethod
    def restore_all(cls):
        for var, data in cls._store.items():
            exec(f'{var} = {data["val"]}', globals=data['globals'], locals=data['locals'])
        cls._store.clear()

    @classmethod
    def restore(cls, var):
        val, f_globals, f_locals = cls._store[var]
        exec(f'{var} = {data["val"]}', globals=f_globals, locals=f_locals)
        del cls._store[var]

    @classmethod
    def discard(cls, var):
        if var in cls._store[var]:
            del cls._store[var]


class TempBPYData:
    '''
    wrapper for bpy.data that allows the changing of settings while
    storing original settings for later restoration.

    This is _different_ than pre-storing the settings, in that we don't
    need to know beforehand what should be stored/restored.
    '''

    _always_store = True
    _store = {}

    is_bpy_type = lambda o: any(isinstance(o, t) for t in {
        bpy.types.bpy_func,
        bpy.types.bpy_prop,
        bpy.types.bpy_prop_array,
        bpy.types.bpy_struct,
        bpy.types.bpy_struct_meta_idprop,
    })

    is_stop_type = lambda o: any(isinstance(o, t) for t in {
        bpy.types.Object,
    })

    class WKey:
        @classmethod
        def Attr(cls, key): return cls(key, True)
        @classmethod
        def Item(cls, key): return cls(key, False)

        def __init__(self, key, is_attr):
            self._key = key
            self._is_attr = is_attr

        def __str__(self):
            return f'.{self._key}' if self._is_attr else f'[{self._key}]'

        @property
        def key(self):     return self._key
        @property
        def is_attr(self): return self._is_attr
        @property
        def is_item(self): return not self._is_attr

        def get(self, data):
            return getattr(data, self._key) if self._is_attr else data[self._key]
        def set(self, data, val):
            if self._is_attr: setattr(data, self._key, val)
            else: data[self._key] = val

    class Walker:
        def __init__(self, *keys, from_walker=None):
            if from_walker:
                assert from_walker.in_struct
                full_keys = from_walker.keys
                data = from_walker.data
                path = from_walker.path
            else:
                full_keys = tuple()
                data = bpy.data
                path = 'bpy.data'
            pre_data = None
            for key in keys:
                data, pre_data, path = key.get(data), data
                path = f'{path}{key}'
                full_keys += key

            self.__dict__['_data'] = {
                'path':      path,
                'keys':      full_keys,
                'data':      data,
                'prev':      (pre_data, keys[-1]),
                'in_struct': TempBPYData.is_bpy_type(data),
                'is_stop':   TempBPYData.is_stop_type(data),
            }

        def __repr__(self):                  return f'<Walker {self.path} = {self.data}>'
        def __iter__(self):                  return iter(self.data)
        def __call__(self, *args, **kwargs): return self.data(*args, **kwargs)
        def __getattr__(self, key):          return self.get(key, True)
        def __setattr__(self, key, val):     return self.set(key, True, val)
        def __getitem__(self, key):          return self.get(key, False)
        def __setitem__(self, key, val):     return self.set(key, False, val)

        @classmethod
        def unwrap(cls, val): return val.data if isinstance(val, cls) else val

        @property
        def path(self):       return self.__dict__['_data']['path']
        @property
        def keys(self): return self.__dict__['_data']['keys']
        @property
        def data(self):       return self.__dict__['_data']['data']
        @property
        def prev(self):       return self.__dict__['_data']['prev']
        @property
        def in_struct(self):  return self.__dict__['_data']['in_struct']
        @property
        def is_struct(self):  return self.__dict__['_data']['is_stop']

        def get(self, key, attr):
            if self.is_stop:
                return getattr(self.data, key) if attr else self.data[key]
            wk = TempBPYData.WKey(key, attr)
            w = TempBPYData.Walker(wk, from_walker=self)
            return w if w.in_struct else w.data
        def set(self, key, attr, val):
            assert self.in_struct
            TempBPYData.store(list(self.keys) + [(key, attr)])
            val = self.unwrap(val)
            if attr: setattr(self.data, key, val)
            else:    self.data[key] = val
        # def ignore(self)

    @classmethod
    def debug_print_store(cls):
        print(f'TempBPYData.store = {{')
        for keys_attrs, val in cls._store.items():
            print(f'  {cls.keys_attrs_to_path(keys_attrs)}: {val}')
        print(f'}}')

    @classmethod
    def get_from_keys_attrs(cls, keys_attrs):
        data = bpy.data
        for (key, attr) in keys_attrs:
            data = cls.get_from_key(data, key)
        return data
    @classmethod
    def get_from_key(cls, data, key):
        return getattr(data, key[1:]) if key.startswith('.') else data[key][1:-1]
    @classmethod
    def set_from_key_attr(cls, data, key, attr, val):
        if attr: setattr(data, key, val)
        else:    data[key] = val

    @classmethod
    def keys_to_path(cls, keys_attrs):
        path = 'bpy.data'
        for (key, attr) in keys_attrs:
            path += f'.{key}' if attr else f'[{key}]'
        return path

    @classmethod
    def store(cls, keys_attrs):
        store_key = tuple(keys_attrs)
        store_val = cls.get_from_keys_attrs(keys_attrs)
        if cls._always_store or not cls.is_bpy_type(store_val):
            # only remember previous values if keys points to a non bpy_type.
            # an example of keys that point to a bpy_type that we would wish to assign
            # bpy.data.window_managers[0].windows[0].view_layer.objects.active
            cls._store.setdefault(store_key, store_val)

    @classmethod
    def clear(cls):
        cls._store.clear()

    @classmethod
    def discard(cls, keys_attrs):
        if type(keys_attrs) is cls.Walker:
            keys_attrs = keys_attrs.key_attrs
        if keys_attrs in cls._store:
            del cls._store[keys_attrs]

    @classmethod
    def restore_all(cls, *, clear=True):
        for (keys_attrs, val) in cls._store.items():
            data = bpy.data
            for (key, attr) in keys_attrs[:-1]:
                data = cls.get_from_key(data, key)
            (key, attr) = keys_attrs[-1]
            cls.set_from_key_attr(data, key, attr, val)
        if clear:
            cls.clear()

    @classmethod
    def is_bpy_type(cls, o):
        if any(isinstance(o, t) for t in cls._stop_at_types):
            return False
        return any(isinstance(o, t) for t in cls._bpy_types)

    @classmethod
    def __getattr__(cls, key): return cls.Walker(cls.WKey(key, True))
    @classmethod
    def __getitem__(cls, key): return cls.Walker(cls.WKey(key, False))

    def __init__(self): pass

bpy_data = TempBPYData()

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



def get_preferences(ctx=None):
    return (ctx if ctx else bpy.context).preferences

###############################################################
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
    fn_path = lambda filename: os.path.realpath(os.path.dirname(filename))
    path_here = fn_path(__file__)
    if path_here not in get_path_from_addon_root.root:
        import addon_utils
        # NOTE: append '/' to end to prevent matching subfolders that have appended stuff
        modules = [mod for mod in addon_utils.modules() if path_here.startswith(fn_path(mod.__file__) + '/')]
        assert len(modules) == 1, f'Could not find root for add-on containing {path_here}: {modules}'
        get_path_from_addon_root.root[path_here] = fn_path(modules[0].__file__)
    return os.path.join(get_path_from_addon_root.root[path_here], *path_join)

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

@blender_version_wrapper('<', '2.80')
def matrix_vector_mult(mat, vec): return mat * vec
@blender_version_wrapper('>=', '2.80')
def matrix_vector_mult(mat, vec): return mat @ vec

@blender_version_wrapper('<', '2.80')
def quat_vector_mult(quat, vec): return quat * vec
@blender_version_wrapper('>=', '2.80')
def quat_vector_mult(quat, vec): return quat @ vec

#############################################################
# TODO: generalize these functions to be add_object, etc.

@blender_version_wrapper('<=','2.79')
def set_object_layers(o): o.layers = list(bpy.context.scene.layers)
@blender_version_wrapper('>=','2.80')
def set_object_layers(o): print('unhandled: set_object_layers')

@blender_version_wrapper('<=','2.79')
def set_object_selection(o, sel): o.select = sel
@blender_version_wrapper('>=','2.80')
def set_object_selection(o, sel): o.select_set(sel)

@blender_version_wrapper('<=','2.79')
def link_object(o): bpy.context.scene.objects.link(o)
@blender_version_wrapper('>=','2.80')
def link_object(o): bpy.context.scene.collection.objects.link(o)

@blender_version_wrapper('<=','2.79')
def set_active_object(o): bpy.context.scene.objects.active = o
@blender_version_wrapper('>=','2.80')
def set_active_object(o): bpy.context.view_layer.objects.active = o

# use this, because bpy.context might not Screen context!
# see https://docs.blender.org/api/current/bpy.context.html
def get_active_object(): return bpy.context.view_layer.objects.active

def get_from_dict_or_object(o, k): return o[k] if type(o) is dict else getattr(o, k)
def toggle_property(o, k): setattr(o, k, not getattr(o, k))

@only_in_blender_version('<= 2.79')
def toggle_screen_header(ctx): bpy.ops.screen.header(ctx)
@only_in_blender_version('>= 2.80')
def toggle_screen_header(ctx):
    # print(f'Addon Common Warning: Cannot toggle header visibility (addon_common/common/blender.py: toggle_screen_header)')
    # print(f'  Skipping while bug exists in Blender 3.0+, see: https://developer.blender.org/T93410')
    toggle_property(get_from_dict_or_object(ctx, 'space_data'), 'show_region_header')

@only_in_blender_version('< 3.00')
def toggle_screen_tool_header(ctx): pass
@only_in_blender_version('>= 3.00')
def toggle_screen_tool_header(ctx):
    toggle_property(get_from_dict_or_object(ctx, 'space_data'), 'show_region_tool_header')

@blender_version_wrapper('<=', '2.79')
def toggle_screen_toolbar(ctx):
    bpy.ops.view3d.toolshelf(ctx)
@blender_version_wrapper('>=', '2.80')
def toggle_screen_toolbar(ctx):
    toggle_property(get_from_dict_or_object(ctx, 'space_data'), 'show_region_toolbar')

@blender_version_wrapper('<=', '2.79')
def toggle_screen_properties(ctx):
    bpy.ops.view3d.properties(ctx)
@blender_version_wrapper('>=', '2.80')
def toggle_screen_properties(ctx):
    toggle_property(get_from_dict_or_object(ctx, 'space_data'), 'show_region_ui')

@blender_version_wrapper('<=', '2.79')
def toggle_screen_lastop(ctx):
    # Blender 2.79 does not have a last operation region
    pass
@blender_version_wrapper('>=', '2.80')
def toggle_screen_lastop(ctx):
    toggle_property(get_from_dict_or_object(ctx, 'space_data'), 'show_region_hud')



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
    tagged_redraw_all = True
    tag_reasons.add(reason)
    if not only_tag: perform_redraw_all()
def perform_redraw_all(only_area=None):
    global tagged_redraw_all, tag_reasons
    if not tagged_redraw_all: return
    # print('Redrawing:', tag_reasons)
    tag_reasons.clear()
    tagged_redraw_all = False
    if only_area:
        only_area.tag_redraw()
    else:
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for ar in win.screen.areas:
                    ar.tag_redraw()




def show_blender_popup(message, title="Message", icon="INFO", wrap=80):
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
    lines = message.splitlines()
    if wrap > 0:
        nlines = []
        for line in lines:
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
            self.layout.label(line)
    bpy.context.window_manager.popup_menu(draw, title=title, icon=icon)
    return

def show_error_message(message, title="Error", wrap=80):
    show_blender_popup(message, title, "ERROR", wrap)

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
