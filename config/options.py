'''
Copyright (C) 2020 CG Cookie
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
import re
import json
import time
import shelve
import platform
import tempfile

import bgl
import bpy

from ..addon_common.common.blender import get_preferences
from ..addon_common.common.debug import Debugger, dprint
from ..addon_common.common.drawing import Drawing
from ..addon_common.common.logger import Logger
from ..addon_common.common.maths import Color
from ..addon_common.common.profiler import Profiler
from ..addon_common.common.utils import git_info
from ..addon_common.common.ui_core import UI_Document
from ..addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat


###########################################
# RetopoFlow Configurations

# important: update Makefile and root/__init__.py, too!
# TODO: make Makefile pull version from here or some other file?
# TODO: make __init__.py pull version from here or some other file?
retopoflow_version = '3.0.0β2'
retopoflow_version_tuple = (3, 0, 0)

retopoflow_issues_url = "https://github.com/CGCookie/retopoflow/issues"

# TODO: REPLACE WITH COOKIE-RELATED ACCOUNT!! :)
# NOTE: can add number to url to start the amount off
# ex: https://paypal.me/retopoflow/5
retopoflow_tip_url    = "https://paypal.me/gfxcoder/"

# the following enables / disables profiler code, overriding the options['profiler']
# TODO: make this False before shipping!
# TODO: make Makefile check this value!
retopoflow_profiler = False

retopoflow_version_git = None
def get_git_info():
    global retopoflow_version_git
    try:
        git_head_path = os.path.join('.git', 'HEAD')
        if not os.path.exists(git_head_path): return
        git_ref_path = open(git_head_path).read().split()[1]
        assert git_ref_path.startswith('refs/heads/')
        git_ref_path = git_ref_path[len('refs/heads/'):]
        git_ref_fullpath = os.path.join('.git', 'logs', 'refs', 'heads', git_ref_path)
        if not os.path.exists(git_ref_fullpath): return
        log = open(git_ref_fullpath).read().splitlines()
        commit = log[-1].split()[1]
        print('git: %s %s' % (git_ref_path,commit))
        retopoflow_version_git = '%s %s' % (git_ref_path, commit)
    except Exception as e:
        print('An exception occurred while checking git info')
        print(e)
get_git_info()


###########################################
# Get system info

build_platform = bpy.app.build_platform.decode('utf-8')
retopoflow_git_version = git_info()
platform_system,platform_node,platform_release,platform_version,platform_machine,platform_processor = platform.uname()
# https://www.khronos.org/registry/OpenGL-Refpages/gl2.1/xhtml/glGetString.xml
gpu_vendor = bgl.glGetString(bgl.GL_VENDOR)
gpu_renderer = bgl.glGetString(bgl.GL_RENDERER)
gpu_version = bgl.glGetString(bgl.GL_VERSION)
gpu_shading = bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION)

print('RetopoFlow git: %s' % str(retopoflow_git_version))




class Options:
    path_root = None
    options_filename = 'RetopoFlow_options.json'    # the filename of the Shelve object
                                                    # will be located at root of RF plug-in

    default_options = {                 # all the default settings for unset or reset
        'rf version':           None,   # if versions differ, flush stored options

        'show experimental':    False,  # should show experimental tools?

        'welcome':              True,   # show welcome message?
        'tools_min':            False,  # minimize tools window?
        'profiler':             False,  # enable profiler?
        'instrument':           False,  # enable instrumentation?
        'debug level':          0,      # debug level, 0--5 (for printing to console). 0=no print; 5=print all
        'debug actions':        False,  # print actions (except MOUSEMOVE) to console

        'visualize counts':     True,   # visualize geometry counts

        'visualize fps':        False,  # visualize fps
        'low fps threshold':    5,      # threshold of a low fps
        'low fps warn':         True,   # warn user of low fps?
        'low fps time':         10,     # time (seconds) before warning user of low fps

        'show tooltips':        True,
        'tooltip delay':        0.75,
        'keyboard repeat delay': 0.25, # delay before repeating
        'keyboard repeat pause': 0.10, # pause between repeats
        'undo change tool':     False,  # should undo change the selected tool?
        'undo depth':           100,    # size of undo stack

        'github issues url':    'https://github.com/CGCookie/retopoflow/issues',
        'github new issue url': 'https://github.com/CGCookie/retopoflow/issues/new',
        'github low fps url':   'https://github.com/CGCookie/retopoflow/issues/448#new_comment_field',

        'tools pos':    7,
        'info pos':     1,
        'options pos':  9,

        'async mesh loading': True,

        'tools autohide': True,         # should tool's options auto-hide/-show when switching tools?
        'tools autocollapse': True,     # should tool's options auto-open/-collapse when switching tools?
        'background gradient': True,    # draw focus gradient

        'escape to quit': False,        # True:ESC is action for quitting

        # True=tool's options are visible
        'tool contours visible': True,
        'tool polystrips visible': True,
        'tool polypen visible': True,
        'tool relax visible': True,
        'tool tweak visible': True,
        'tool loops visible': True,
        'tool patches visible': True,
        'tool strokes visible': True,

        # True=tool's options are collapsed
        'tools general collapsed': False,       # is general tools collapsed
        'tools symmetry collapsed': True,       # is symmetry tools collapsed
        'tool contours collapsed': True,
        'tool polystrips collapsed': True,
        'tool polypen collapsed': True,
        'tool relax collapsed': True,
        'tool tweak collapsed': True,
        'tool loops collapsed': True,
        'tool patches collapsed': True,
        'tool strokes collapsed': True,

        'select dist':          10,             # pixels away to select
        'action dist':          20,             # pixels away to allow action
        'remove doubles dist':  0.001,

        # visibility test tuning parameters
        'visible bbox factor':  0.001,          # rf_sources.visibility_preset_*
        'visible dist offset':  0.0008,         # rf_sources.visibility_preset_*

        'color theme':              'Green',
        'symmetry view':            'Edge',
        'symmetry effect':          0.5,
        'normal offset multiplier': 1.0,
        'constrain offset':         True,
        'ui scale':                 1.0,

        # visualization settings
        'target vert size':         4.0,
        'target edge size':         1.0,
        'target alpha':             0.10,
        'target hidden alpha':      0.02,
        'target alpha backface':    0.2,
        'target cull backfaces':    False,

        # 'options filename':     'RetopoFlow_options.json',  # must get handled specially?
        'screenshot filename':  'RetopoFlow_screenshot.png',
        'instrument_filename':  'RetopoFlow_instrument',
        'log_filename':         'RetopoFlow_log',
        'backup_filename':      'RetopoFlow_backup',
        'quickstart_filename':  'RetopoFlow_quickstart',
        'profiler_filename':    'RetopoFlow_profiler.txt',

        'contours count':   16,
        'contours uniform': True,               # should new cuts be made uniformly about circumference?

        'polystrips scale falloff':     0.93,
        'polystrips draw curve':        False,
        'polystrips max strips':        10,     # PS will not show handles if knot count is above max
        'polystrips arrows':            False,
        'polystrips handle inner size': 15,
        'polystrips handle outer size': 20,
        'polystrips handle border':     3,

        'polypen merge dist':       10,         # pixels away to merge
        'polypen automerge':        True,
        'polypen triangle only':    False,

        'relax mask boundary':  'include',
        'relax mask symmetry':  'maintain',
        'relax mask hidden':    'exclude',
        'relax mask selected':  'all',
        'relax steps':          2,
        'relax edge length':    True,
        'relax face radius':    True,
        'relax face sides':     True,
        'relax face angles':    False,
        'relax force multiplier': 1.5,

        'tweak mask boundary':  False,
        'tweak mask symmetry':  True,
        'tweak mask hidden':    True,
        'tweak mask selected':  False,

        'patches angle':        120,

        # addon updater settings
        'updater auto check update': True,
        'updater interval months': 0,
        'updater interval days': 1,
        'updater interval hours': 0,
        'updater interval minutes': 0,
    }

    db = None           # current options dict
    fndb = None         # name of file in which to store db (set up in __init__)
    is_dirty = False    # does the internal db differ from db stored in file? (need writing)
    last_change = 0     # when did we last changed an option?
    write_delay = 1.0   # seconds to wait before writing db to file

    def __init__(self):
        self._callbacks = []
        self._calling = False
        if not Options.fndb:
            path = os.path.split(os.path.abspath(__file__))[0]
            Options.path_root = os.path.abspath(os.path.join(path, '..'))
            Options.fndb = os.path.join(Options.path_root, Options.options_filename)
            # Options.fndb = self.get_path('options filename')
            print('RetopoFlow options path: %s' % Options.fndb)
            self.read()
            if self['rf version'] != retopoflow_version:
                print('RetopoFlow version has changed.  Reseting options')
                self.reset()
        self.update_external_vars()

    def __getitem__(self, key):
        return Options.db[key] if key in Options.db else Options.default_options[key]

    def __setitem__(self, key, val):
        assert key in Options.default_options, 'Attempting to write "%s":"%s" to options, but key does not exist' % (str(key),str(val))
        assert not self._calling, 'Attempting to change option %s to %s while calling callbacks' % (str(key), str(val))
        if self[key] == val: return
        oldval = self[key]
        Options.db[key] = val
        self.dirty()
        self.clean()

    def add_callback(self, callback):
        self._callbacks += [callback]
    def remove_callback(self, callback):
        self._callbacks = [cb for cb in self._callbacks if cb != callback]
    def clear_callbacks(self):
        self._callbacks = []
    def call_callbacks(self):
        self._calling = True
        for callback in self._callbacks: callback()
        self._calling = False

    def get_path(self, key):
        return os.path.join(Options.path_root, self[key])

    def get_path_incremented(self, key):
        p = self.get_path(key)
        if os.path.exists(p):
            i = 0
            p0,p1 = os.path.splitext(p)
            while os.path.exists('%s.%03d.%s' % (p0, i, p1)): i += 1
            p = '%s.%03d.%s' % (p0, i, p1)
        return p

    def update_external_vars(self):
        Debugger.set_error_level(self['debug level'])
        Logger.set_log_filename(self['log_filename'])  #self.get_path('log_filename'))
        # Profiler.set_profiler_enabled(self['profiler'] and retopoflow_profiler)
        Profiler.set_profiler_filename(self.get_path('profiler_filename'))
        Drawing.set_custom_dpi_mult(self['ui scale'])
        UI_Document.key_repeat_delay = self['keyboard repeat delay']
        UI_Document.key_repeat_pause = self['keyboard repeat pause']
        UI_Document.show_tooltips = self['show tooltips']
        UI_Document.tooltip_delay = self['tooltip delay']
        self.call_callbacks()

    def dirty(self):
        Options.is_dirty = True
        Options.last_change = time.time()
        self.update_external_vars()

    def clean(self, force=False):
        if not Options.is_dirty:
            # nothing has changed
            return
        if not force and time.time() < Options.last_change + Options.write_delay:
            # we haven't waited long enough before storing db
            return
        dprint('Writing options:', Options.db)
        json.dump(Options.db, open(Options.fndb, 'wt'), indent=2, sort_keys=True)
        Options.is_dirty = False

    def read(self):
        Options.db = {}
        if os.path.exists(Options.fndb):
            try:
                Options.db = json.load(open(Options.fndb, 'rt'))
            except Exception as e:
                print('Exception caught while trying to read options from file')
                print(str(e))
            # remove options that are not in default options
            for k in set(Options.db.keys()) - set(Options.default_options.keys()):
                print('Deleting key "%s" from options' % k)
                del Options.db[k]
        else:
            print('No options file')
        self.update_external_vars()
        Options.is_dirty = False

    def keys(self):
        return Options.db.keys()

    def reset(self, keys=None, version=True):
        if keys is None:
            keys = list(Options.db.keys())
        for key in keys:
            del Options.db[key]
        if version:
            Options.db['rf version'] = retopoflow_version
        self.dirty()
        self.clean()

    def set_default(self, key, val):
        # does not dirty nor invoke write!
        assert key in Options.default_options, 'Attempting to write "%s":"%s" to options, but key does not exist' % (str(key),str(val))
        if key not in Options.db:
            Options.db[key] = val

    def set_defaults(self, d_key_vals):
        # does not dirty nor invoke write!
        for key in d_key_vals:
            self.set_default(key, d_key_vals[key])

    def getter(self, key, getwrap=None):
        if not getwrap: getwrap = lambda v: v
        def _getter(): return getwrap(options[key])
        return _getter

    def setter(self, key, setwrap=None, setcallback=None):
        if not setwrap: setwrap = lambda v: v
        if not setcallback:
            def nop(v): pass
            setcallback = nop
        def _setter(v):
            options[key] = setwrap(v)
            setcallback(options[key])
        return _setter

    def gettersetter(self, key, getwrap=None, setwrap=None, setcallback=None):
        return (self.getter(key, getwrap=getwrap), self.setter(key, setwrap=setwrap, setcallback=setcallback))

    def temp_filepath(self, ext):
        #tempdir = get_preferences().filepaths.temporary_directory
        tempdir = tempfile.gettempdir()
        return os.path.join(tempdir, '%s.%s' % (self['backup_filename'], ext))


def ints_to_Color(r, g, b, a=255): return Color((r/255.0, g/255.0, b/255.0, a/255.0))
class Themes:
    # fallback color for when specified key is not found
    error = ints_to_Color(255,  64, 255, 255)

    common = {
        'mesh':       ints_to_Color(255, 255, 255, 255),
        'warning':    ints_to_Color(182,  31,   0, 128),
        'stroke':     ints_to_Color( 40, 255,  40, 255),

        # RFTools
        'polystrips': ints_to_Color(128, 255, 255,  96),
        'strokes':    ints_to_Color( 64,  64,  64,  96),
        'tweak':      ints_to_Color(255, 128,  25, 255),
        'relax':      ints_to_Color(128, 255, 128, 255),
    }

    themes = {
        'Blue': {
            'select':  ints_to_Color( 26, 111, 255, 255),
            'new':     ints_to_Color( 40,  40, 255, 255),
            'active':  ints_to_Color( 26, 111, 255, 255),
        },
        'Green': {
            'select':  ints_to_Color( 78, 207,  81, 255),
            'new':     ints_to_Color( 40, 255,  40, 255),
            'active':  ints_to_Color( 78, 207,  81, 255),
        },
        'Orange': {
            'select':  ints_to_Color(207, 135,  78, 255),
            'new':     ints_to_Color(255, 128,  64, 255),
            'active':  ints_to_Color(207, 135,  78, 255),
        },
    }

    @property
    def theme(self):
        return self.themes[options['color theme']]
    def __getitem__(self, key):
        return self.theme.get(key, self.common.get(key, self.error))


class Visualization_Settings:
    def __init__(self):
        self._last = {}
        self.update_settings()

    def update_settings(self):
        watch = ['color theme', 'normal offset multiplier', 'constrain offset', 'target vert size', 'target edge size']
        if all(getattr(self._last, key, None) == options[key] for key in watch): return
        for key in watch: self._last[key] = options[key]

        color_mesh = themes['mesh']
        color_select = themes['select']
        normal_offset_multiplier = options['normal offset multiplier']
        constrain_offset = options['constrain offset']
        vert_size = options['target vert size']
        edge_size = options['target edge size']

        self._source_settings = {
            'poly color':     (0.0, 0.0, 0.0, 0.0),
            'poly offset':    0.000008,
            'poly dotoffset': 1.0,
            'line width':     0.0,
            'point size':     0.0,
            'load edges':     False,
            'load verts':     False,
            'no selection':   True,
            'no below':       True,
            'triangles only': True,     # source bmeshes are triangles only!
            'cull backfaces': True,

            'focus mult':       0.01,
            'normal offset':    0.0005 * normal_offset_multiplier,    # pushes vertices out along normal
            'constrain offset': constrain_offset,
        }

        self._target_settings = {
            'poly color':                  (*color_mesh[:3],   0.20),
            'poly color selected':         (*color_select[:3], 0.30),
            'poly offset':                 0.000010,
            'poly dotoffset':              1.0,
            'poly mirror color':           (*color_mesh[:3],   0.10),
            'poly mirror color selected':  (*color_select[:3], 0.10),
            'poly mirror offset':          0.000010,
            'poly mirror dotoffset':       1.0,

            'line color':                  (*color_mesh[:3],   1.00),
            'line color selected':         (*color_select[:3], 1.00),
            'line width':                  edge_size,
            'line offset':                 0.000012,
            'line dotoffset':              1.0,
            'line mirror stipple':         False,
            'line mirror color':           (*color_mesh[:3],   0.25),
            'line mirror color selected':  (*color_select[:3], 0.25),
            'line mirror width':           1.5,
            'line mirror offset':          0.000012,
            'line mirror dotoffset':       1.0,
            'line mirror stipple':         False,

            'point color':                 (*color_mesh[:3],   1.00),
            'point color selected':        (*color_select[:3], 1.00),
            'point color highlight':       (1.0, 1.0, 0.1, 1.0),
            'point size':                  vert_size,
            'point size highlight':        10.0,
            'point offset':                0.000015,
            'point dotoffset':             1.0,
            'point mirror color':          (*color_mesh[:3],   0.25),
            'point mirror color selected': (*color_select[:3], 0.25),
            'point mirror size':           3.0,
            'point mirror offset':         0.000015,
            'point mirror dotoffset':      1.0,

            'focus mult':                  1.0,
            'normal offset':               0.001 * normal_offset_multiplier,    # pushes vertices out along normal
            'constrain offset':            constrain_offset,
        }

    def get_source_settings(self):
        self.update_settings()
        return self._source_settings

    def get_target_settings(self):
        self.update_settings()
        return self._target_settings

    def source(self, key):
        self.update_settings()
        return self._source_settings[key]

    def target(self, key):
        self.update_settings()
        return self._target_settings[key]

    def __getitem__(self, key):
        return self.target(key)

    def __setitem__(self, key, val):
        assert key in Options.default_options, 'Attempting to write "%s":"%s" to options, but key does not exist' % (str(key),str(val))
        if self[key] == val: return
        Options.db[key] = val
        self.dirty()
        self.clean()


# set all the default values!
options = Options()
themes = Themes()
visualization = Visualization_Settings()
