'''
Copyright (C) 2018 CG Cookie
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
import shelve
import platform

import bgl
import bpy

from .common.debug import Debugger, dprint
from .common.logger import Logger
from .common.profiler import Profiler


retopoflow_version = '2.0.0'

# the following enables / disables profiler code, overriding the options['profiler']
# TODO: make this False before shipping!
retopoflow_profiler = True

build_platform = bpy.app.build_platform.decode('utf-8')

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

platform_system,platform_node,platform_release,platform_version,platform_machine,platform_processor = platform.uname()

# https://www.khronos.org/registry/OpenGL-Refpages/gl2.1/xhtml/glGetString.xml
gpu_vendor = bgl.glGetString(bgl.GL_VENDOR)
gpu_renderer = bgl.glGetString(bgl.GL_RENDERER)
gpu_version = bgl.glGetString(bgl.GL_VERSION)
gpu_shading = bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION)

retopoflow_issues_url = "https://github.com/CGCookie/retopoflow/issues"

# TODO: REPLACE WITH COOKIE-RELATED ACCOUNT!! :)
# NOTE: can add number to url to start the amount off
# ex: https://paypal.me/retopoflow/5
retopoflow_tip_url    = "https://paypal.me/gfxcoder/"



class Options:
    options_filename = 'RetopoFlow_options.json'    # the filename of the Shelve object
                                                    # will be located at root of RF plug-in

    default_options = {                 # all the default settings for unset or reset
        'rf version':           None,   # if versions differ, flush stored options

        'show experimental':    False,  # should show experimental tools?

        'welcome':              True,   # show welcome message?
        'tools_min':            False,  # minimize tools window?
        'profiler':             False,  # enable profiler?
        'instrument':           False,  # enable instrumentation?
        'debug level':          0,      # debug level, 0--5 (for printing to console)
        'debug actions':        False,  # print actions (except MOUSEMOVE) to console

        'visualize fps':        False,  # visualize fps
        'low fps threshold':    5,      # threshold of a low fps
        'low fps warn':         True,   # warn user of low fps?
        'low fps time':         10,     # time (seconds) before warning user of low fps

        'show tooltips':        True,
        'undo change tool':     False,  # should undo change the selected tool?

        'github issues url':    'https://github.com/CGCookie/retopoflow/issues',
        'github new issue url': 'https://github.com/CGCookie/retopoflow/issues/new',
        'github low fps url':   'https://github.com/CGCookie/retopoflow/issues/448#new_comment_field',

        'tools pos':    7,
        'info pos':     1,
        'options pos':  9,

        'async mesh loading': True,

        'tools autocollapse': True,             # should tool's options auto-open/-collapse when switching tools?
        'background gradient': True,

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

        'color theme':          'Green',
        'symmetry view':        'Edge',
        'symmetry effect':      0.5,

        'target alpha':             1.0,
        'target hidden alpha':      0.1,
        'target alpha backface':    0.2,
        'target cull backfaces':    False,

        'screenshot filename':  'RetopoFlow_screenshot.png',
        'instrument_filename':  'RetopoFlow_instrument',
        'log_filename':         'RetopoFlow_log',
        'backup_filename':      'RetopoFlow_backup',
        'quickstart_filename':  'RetopoFlow_quickstart',
        'profiler_filename':    'RetopoFlow_profiler.txt',

        'contours count':   16,
        'contours uniform': True,               # should new cuts be made uniformly about circumference?

        'polystrips scale falloff':     -1,
        'polystrips draw curve':        False,
        'polystrips max strips':        10,     # PS will not show handles if knot count is above max
        'polystrips arrows':            False,
        'polystrips handle inner size': 15,
        'polystrips handle outer size': 20,
        'polystrips handle border':     2,

        'polypen automerge': True,

        'relax mask boundary':  True,
        'relax mask hidden':    True,
        'relax mask selected':  False,
        'relax steps':          2,
        'relax edge length':    True,
        'relax face radius':    True,
        'relax face sides':     True,
        'relax face angles':    False,
        'relax force multiplier': 1.5,

        'tweak mask boundary':  False,
        'tweak mask hidden':    True,
        'tweak mask selected':  False,

        'patches angle':        120,
    }

    db = None                           # current options dict
    fndb = None

    def __init__(self):
        if not Options.fndb:
            path = os.path.split(os.path.abspath(__file__))[0]
            Options.fndb = os.path.join(path, Options.options_filename)
            print('RetopoFlow Options path: %s' % Options.fndb)
            self.read()
            if self['rf version'] != retopoflow_version:
                print('RetopoFlow version has changed.  Reseting options')
                self.reset()
        self.update_external_vars()
    def __del__(self):
        #self.write()
        pass
    def __getitem__(self, key):
        return Options.db[key] if key in Options.db else Options.default_options[key]
    def __setitem__(self, key, val):
        assert key in Options.default_options, 'Attempting to write "%s":"%s" to options, but key does not exist' % (str(key),str(val))
        if self[key] == val: return
        Options.db[key] = val
        self.write()
    def update_external_vars(self):
        # print('Updating:')
        # print('- Debugger: %d' % self['debug level'])
        # print('- Logger: %s' % self['log_filename'])
        # print('- Profiler: %s %s' % (str(self['profiler'] and retopoflow_profiler), self['profiler_filename']))
        Debugger.set_error_level(self['debug level'])
        Logger.set_log_filename(self['log_filename'])
        Profiler.set_profiler_enabled(self['profiler'] and retopoflow_profiler)
        Profiler.set_profiler_filename(self['profiler_filename'])
    def write(self):
        dprint('Writing options:', Options.db)
        json.dump(Options.db, open(Options.fndb, 'wt'))
        self.update_external_vars()
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
    def keys(self): return Options.db.keys()
    def reset(self):
        keys = list(Options.db.keys())
        for key in keys:
            del Options.db[key]
        Options.db['rf version'] = retopoflow_version
        self.write()
    def set_default(self, key, val):
        assert key in Options.default_options, 'Attempting to write "%s":"%s" to options, but key does not exist' % (str(key),str(val))
        if key not in Options.db: Options.db[key] = val
    def set_defaults(self, d_key_vals):
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
        tempdir = bpy.context.user_preferences.filepaths.temporary_directory
        return os.path.join(tempdir, '%s.%s' % (self['backup_filename'], ext))

def rgba_to_float(r, g, b, a): return (r/255.0, g/255.0, b/255.0, a/255.0)
class Themes:
    themes = {
        'Blue': {
            'mesh':    rgba_to_float( 78, 207,  81, 255),
            'frozen':  rgba_to_float(255, 255, 255, 255),
            'new':     rgba_to_float( 40, 255,  40, 255),
            'select':  rgba_to_float( 26, 111, 255, 255),
            'active':  rgba_to_float( 26, 111, 255, 255),
            'warning': rgba_to_float(182,  31,   0, 125),

            'stroke':  rgba_to_float( 40, 255,  40, 255),
        },
        'Green': {
            'mesh':    rgba_to_float( 26, 111, 255, 255),
            'frozen':  rgba_to_float(255, 255, 255, 255),
            'new':     rgba_to_float( 40, 255,  40, 255),
            'select':  rgba_to_float( 78, 207,  81, 255),
            'active':  rgba_to_float( 78, 207,  81, 255),
            'warning': rgba_to_float(182,  31,   0, 125),

            'stroke':  rgba_to_float( 40, 255,  40, 255),
        },
        'Orange': {
            'mesh':    rgba_to_float( 26, 111, 255, 255),
            'frozen':  rgba_to_float(255, 255, 255, 255),
            'new':     rgba_to_float( 40, 255,  40, 255),
            'select':  rgba_to_float(207, 135,  78, 255),
            'active':  rgba_to_float(207, 135,  78, 255),
            'warning': rgba_to_float(182,  31,   0, 125),

            'stroke':  rgba_to_float( 40, 255,  40, 255),
        },
    }

    def __getitem__(self, key): return self.themes[options['color theme']][key]


# set all the default values!
options = Options()
themes = Themes()