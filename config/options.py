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
import re
import copy
import json
import time
import shelve
import platform
import tempfile
from datetime import datetime
from contextlib import contextmanager
from collections.abc import Iterable

import bpy

from ..addon_common.common import gpustate
from ..addon_common.common.blender import get_path_from_addon_root
from ..addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString
from ..addon_common.common.debug import Debugger, dprint
from ..addon_common.common.decorators import run
from ..addon_common.common.drawing import Drawing
from ..addon_common.common.logger import Logger
from ..addon_common.common.maths import Color
from ..addon_common.common.profiler import Profiler
from ..addon_common.common.ui_document import UI_Document
from ..addon_common.common.utils import normalize_triplequote
from ..addon_common.hive.hive import Hive


###########################################
# RetopoFlow Configurations

# important: update Makefile and root/__init__.py, too!
# TODO: make Makefile pull version from here or some other file?
# TODO: make __init__.py pull version from here or some other file?
retopoflow_product = {
    # all the values are filled in by code below...
    'hive':           None, # based on `hive.json` contents
    'version':        None, # based on hive above
    'version tuple':  None, # based on hive above
    'git version':    None, # looks for `.git` folder
    'cgcookie built': None, # looks for `.cgcookie` file
    'github':         None, # depends on `.cgcookie` contents
    'blender market': None, # depends on `.cgcookie` contents
}

retopoflow_urls = {
    'blender market':   'https://blendermarket.com/products/retopoflow',
    'github issues':    'https://github.com/CGCookie/retopoflow/issues',
    'new github issue': 'https://github.com/CGCookie/retopoflow/issues/new',
    'help docs':        'https://docs.retopoflow.com',
    'help doc':         lambda fn: f'https://docs.retopoflow.com/{fn}.html',
    'tip':              'https://paypal.me/gfxcoder/',  # TODO: REPLACE WITH COOKIE-RELATED ACCOUNT!! :)
                                                        # note: can add number to URL to set a default, ex: https://paypal.me/retopoflow/5
}

# files created by retopoflow, all located at the root of RetopoFlow add-on
retopoflow_files = {
    'options filename':     'RetopoFlow_options.json',
    'screenshot filename':  'RetopoFlow_screenshot.png',
    'instrument filename':  'RetopoFlow_instrument.txt',
    'log filename':         'RetopoFlow_log.txt',
    # 'debug filename':       'RetopoFlow_debug.txt',     # hard-coded in __init__.py
    'backup filename':      'RetopoFlow_backup.blend',    # if working on unsaved blend file
    'profiler filename':    'RetopoFlow_profiler.txt',
    'keymaps filename':     'RetopoFlow_keymaps.json',
}

# objects / blender data created by retopoflow
retopoflow_datablocks = {
    'rotate object': 'RetopoFlow_Rotate',           # name of rotate object used for setting view
    'blender state': 'RetopoFlow Session Data',     # name of text block that contains data about blender state
}


# the following enables / disables profiler code, overriding the options['profiler']
# TODO: make this False before shipping!
# TODO: make Makefile check this value!
retopoflow_profiler = False


# convert version string to tuple
@run
def set_version_info():
    global retopoflow_product
    release_short = {
        'alpha':    'α',
        'beta':     'β',
        'official': '',
    }
    retopoflow_product['hive'] = Hive()
    version = retopoflow_product['hive']['version']
    release = retopoflow_product['hive']['release']
    retopoflow_product['version'] = f'{version}{release_short[release]}'
    retopoflow_product['version tuple'] = tuple(int(i) for i in version.split('.'))

@run
def set_git_info():
    global retopoflow_product
    try:
        path_git = get_path_from_addon_root('.git')
        git_head_path = os.path.join(path_git, 'HEAD')
        if not os.path.exists(git_head_path): return
        git_ref_path = open(git_head_path).read().split()[1]
        assert git_ref_path.startswith('refs/heads/')
        git_ref_path = git_ref_path[len('refs/heads/'):]
        git_ref_fullpath = os.path.join(path_git, 'logs', 'refs', 'heads', git_ref_path)
        if not os.path.exists(git_ref_fullpath): return
        log = open(git_ref_fullpath).read().splitlines()
        commit = log[-1].split()[1]
        retopoflow_product['git version'] = f'{git_ref_path} {commit}'
    except Exception as e:
        print('An exception occurred while checking git info')
        print(e)

@run
def set_build_info():
    global retopoflow_product
    try:
        cgcookie_built_path = get_path_from_addon_root('.cgcookie')
        cgcookie_built = (
            open(cgcookie_built_path, 'rt').read()
            if os.path.exists(cgcookie_built_path)
            else ''
        )
        retopoflow_product['cgcookie built'] = cgcookie_built != ''
        retopoflow_product['github']         = 'GitHub'         in cgcookie_built
        retopoflow_product['blender market'] = 'Blender Market' in cgcookie_built
    except Exception as e:
        print('An exception occurred while getting build info')
        print(e)

# @run(git=None, cgcookie_built=True, blendermarket=True)
def override_version_settings(**kwargs):
    # use kwargs defined below to override product info for testing purposes
    global retopoflow_product
    if 'git'            in kwargs: retopoflow_product['git version']    = kwargs['git']
    if 'cgcookie_built' in kwargs: retopoflow_product['cgcookie built'] = kwargs['cgcookie_built']
    if 'github'         in kwargs: retopoflow_product['github']         = kwargs['github']
    if 'blendermarket'  in kwargs: retopoflow_product['blender market'] = kwargs['blendermarket']

print(f'RetopoFlow git: {retopoflow_product["git version"]}')


###########################################
# Get system info

build_platform = bpy.app.build_platform.decode('utf-8')
(
    platform_system,
    platform_node,
    platform_release,
    platform_version,
    platform_machine,
    platform_processor,
) = platform.uname()
gpu_info = gpustate.gpu_info()



class Options:
    default_options = {                 # all the default settings for unset or reset

        'rf version':           None,   # if versions differ, flush stored options
        'version update':       False,

        # WARNING THRESHOLDS
        'warning max target':   '20k',  # can specify as 20000, 20_000, '20k', '20000', see convert_numstr_num() in addon_common.common.maths
        'warning max sources':  '1m',
        'warning normal check': True,

        'show experimental':    False,  # should show experimental tools?

        'preload help images':  False,
        'async mesh loading':   True,   # True: load source meshes asynchronously
        'async image loading':  True,

        # AUTO SAVE
        'last auto save path':  '',     # file path of last auto save (used for recover)

        # STARTUP
        'check auto save':      True,       # give warning about disabled auto save at start
        'check unsaved':        True,       # give warning about unsaved blend file at start
        'welcome':              True,       # show welcome message?
        'starting tool':        'PolyPen',  # which tool to start with when clicking diamond

        # BLENDER PANEL
        'expand advanced panel': False,
        'expand help panel':     True,

        # BLENDER UI
        'hide panels no overlap':   True,   # hide panels even when region overlap is disabled
        'hide header panel':        True,   # hide header panel (where RF menu shows)

        # DIALOGS
        'show main window':     True,   # True: show main window; False: show tiny
        'show options window':  True,   # show options window
        'show geometry window': True,   # show geometry counts window
        'tools autohide':       True,   # should tool's options auto-hide/-show when switching tools?

        # DEBUG, PROFILE, INSTRUMENT SETTINGS
        'profiler':             False,  # enable profiler?
        'instrument':           False,  # enable instrumentation?
        'debug level':          0,      # debug level, 0--5 (for printing to console). 0=no print; 5=print all
        'debug actions':        False,  # print actions (except MOUSEMOVE) to console

        # UNDO SETTINGS
        'undo change tool':     False,  # should undo change the selected tool?
        'undo depth':           100,    # size of undo stack

        'select dist':              10,         # pixels away to select
        'action dist':              20,         # pixels away to allow action
        'move dist':                10,         # pixels away until mousedrag grabs
        'remove doubles dist':      0.001,
        'push and snap distance':   0.1,        # distance to push vertices out along normal before snapping back to source surface

        # VISIBILITY TEST TUNING PARAMETERS
        'visible bbox factor':      0.01,       # rf_sources.visibility_preset_*
        'visible dist offset':      0.1,        # rf_sources.visibility_preset_*
        'selection occlusion test': True,       # True: do not select occluded geometry
        'selection backface test':  True,       # True: do not select geometry that is facing away

        'accel recompute delay':    0.125,      # seconds to wait to prevent recomputing accel structs too quickly after navigation
        'view change delay':        0.250,      # seconds to wait before calling view change callbacks (> accel recompute delay)
        'target change delay':      0.010,      # seconds to wait before calling target change callbacks

        'move rotate object if no selection': True,

        ####################################################
        # VISUALIZATION SETTINGS

        # UX SETTINGS
        'show tooltips':                True,
        'tooltip delay':                0.75,
        'escape to quit':               False,  # True:ESC is action for quitting
        'confirm tab quit':             True,   # True:pressing TAB to quit is confirmed (prevents accidentally leaving when pie menu was intended)
        'hide cursor on tweak':         True,   # True: cursor is hidden when tweaking geometry
        'hide overlays':                True,       # hide overlays (wireframe, grid, axes, etc.)
        'override shading':             'dark',    # light, dark, or off. Sets optimal values for backface culling, xray, shadows, cavity, outline, and matcap
        'shading view':                 'SOLID',
        'shading light':                'MATCAP',
        'shading matcap light':         'retopoflow_light.exr', # found under matcaps/
        'shading matcap dark':          'retopoflow_dark.exr',  # found under matcaps/
        'shading colortype':            'SINGLE',
        'shading color light':          [1.0, 1.0, 1.0],
        'shading color dark':           [1.0, 1.0, 1.0],
        'shading backface culling':     True,
        'shading xray':                 False,
        'shading shadows':              False,
        'shading cavity':               False,
        'shading outline':              False,
        'color theme':                  'Green',
        'symmetry view':                'Edge',
        'symmetry effect':              0.5,
        'symmetry mirror input':        False,       # True: input is mirrored to correct side of symmetry.  False: input is clamped
        'normal offset multiplier':     1.0,
        'constrain offset':             False,      # when False, symmetry viz looks good.  do we still need this???
        'ui scale':                     1.0,
        'clip auto adjust':             True,       # True: clip settings are automatically adjusted based on view distance and source bbox
        'clip auto start mult':         0.0010,     # factor for clip_start
        'clip auto start min':          0.0010,     # absolute minimum for clip_start
        'clip auto end mult':           100.00,     # factor for clip_end
        'clip auto end max':            500.0,      # absolute maximum for clip_end
        'clip override':                True,       # True: override with below values; False: scale by unit scale factor
        'clip start override':          0.0500,
        'clip end override':            200.00,

        # TARGET VISUALIZATION SETTINGS
        # 'pin enabled' and 'pin seam' are in TARGET PINNING SETTINGS
        'warn non-manifold':               True,       # visualize non-manifold warnings
        'show pinned':                     True,       # visualize pinned geometry
        'show seam':                       True,

        'target vert size':                4.0,
        'target edge size':                1.0,
        'target alpha':                    1.00,
        'target hidden alpha':             0.2,
        'target alpha backface':           0.1,
        'target cull backfaces':           False,

        'target alpha poly':                  0.65,
        'target alpha poly selected':         0.75,
        'target alpha poly warning':          0.25,
        'target alpha poly pinned':           0.75,
        'target alpha poly seam':             0.75,
        'target alpha poly mirror':           0.25,
        'target alpha poly mirror selected':  0.25,
        'target alpha poly mirror warning':   0.15,
        'target alpha poly mirror pinned':    0.25,
        'target alpha poly mirror seam':      0.25,

        'target alpha line':                  0.10,
        'target alpha line selected':         1.00,
        'target alpha line warning':          0.75,
        'target alpha line pinned':           0.75,
        'target alpha line seam':             0.75,
        'target alpha line mirror':           0.10,
        'target alpha line mirror selected':  0.50,
        'target alpha line mirror warning':   0.15,
        'target alpha line mirror pinned':    0.15,
        'target alpha line mirror seam':      0.15,

        'target alpha point':                 0.25,
        'target alpha point selected':        1.00,
        'target alpha point warning':         0.75,
        'target alpha point pinned':          0.95,
        'target alpha point seam':            0.95,
        'target alpha point mirror':          0.00,
        'target alpha point mirror selected': 0.50,
        'target alpha point mirror warning':  0.15,
        'target alpha point mirror pinned':   0.15,
        'target alpha point mirror seam':     0.15,
        'target alpha point highlight':       1.00,

        'target alpha mirror':                1.00,

        # TARGET PINNING SETTINGS
        # 'show pinned' and 'show seam' are in TARGET VISUALIZATION SETTINGS
        'pin enabled':  True,
        'pin seam':     True,

        # ADDON UPDATER SETTINGS
        'updater auto check update':    True,
        'updater interval months':      0,
        'updater interval days':        1,
        'updater interval hours':       0,
        'updater interval minutes':     0,


        #######################################
        # GENERAL SETTINGS

        'smooth edge flow iterations':  10,
        'automerge':                    True,
        'merge dist':                   10,     # pixels away to merge

        #######################################
        # TOOL SETTINGS

        'contours count':               16,
        'contours uniform':             True,   # should new cuts be made uniformly about circumference?
        'contours non-manifold check':  True,

        'polystrips radius':            40,
        'polystrips below alpha':       0.6,
        'polystrips scale falloff':     0.93,
        'polystrips draw curve':        False,
        'polystrips max strips':        10,     # PS will not show handles if knot count is above max
        'polystrips arrows':            False,
        'polystrips handle inner size': 15,
        'polystrips handle outer size': 20,
        'polystrips handle border':     3,

        'strokes radius':               40,
        'strokes below alpha':          0.6,
        'strokes span insert mode':    'Brush Size',
        'strokes span count':           1,
        'strokes snap stroke':          True,       # should stroke snap to unselected geometry?
        'strokes snap dist':            10,         # pixels away to snap
        'strokes automerge':            True,
        'strokes merge dist':           10,         # pixels away to merge

        'knife automerge':              True,
        'knife merge dist':             10,         # pixels away to merge
        'knife snap dist':              5,          # pixels away to snap

        'polypen automerge':            True,
        'polypen merge dist':           10,         # pixels away to merge
        'polypen insert dist':          15,         # pixels away for inserting new vertex in existing geo
        'polypen insert mode':          'Tri/Quad',

        'brush min alpha':              0.10,
        'brush max alpha':              0.70,

        'relax radius':                 50,
        'relax falloff':                1.5,
        'relax strength':               0.5,
        'relax below alpha':            0.6,
        'relax algorithm':              '3D',
        'relax mask boundary':          'include',
        'relax mask symmetry':          'maintain',
        'relax mask occluded':          'exclude',
        'relax mask selected':          'all',
        'relax steps':                  2,
        'relax force multiplier':       1.5,
        'relax edge length':            True,
        'relax face radius':            True,
        'relax face sides':             False,
        'relax face angles':            True,
        'relax correct flipped faces':  False,
        'relax straight edges':         True,
        'relax preset 1 name':         'Preset 1',
        'relax preset 1 radius':        50,
        'relax preset 1 falloff':       1.5,
        'relax preset 1 strength':      0.5,
        'relax preset 2 name':         'Preset 2',
        'relax preset 2 radius':        50,
        'relax preset 2 falloff':       1.5,
        'relax preset 2 strength':      0.5,
        'relax preset 3 name':         'Preset 3',
        'relax preset 3 radius':        50,
        'relax preset 3 falloff':       1.5,
        'relax preset 3 strength':      0.5,
        'relax preset 4 name':         'Preset 4',
        'relax preset 4 radius':        50,
        'relax preset 4 falloff':       1.5,
        'relax preset 4 strength':      0.5,

        'tweak mode':                   'raycast',  # mode to move tweaked vert back to surface of source: snap or raycast
        'tweak radius':                 50,
        'tweak falloff':                1.5,
        'tweak strength':               0.5,
        'tweak below alpha':            0.6,
        'tweak mask boundary':          'include',
        'tweak mask symmetry':          'maintain',
        'tweak mask occluded':          'exclude',
        'tweak mask selected':          'all',
        'tweak preset 1 name':         'Preset 1',
        'tweak preset 1 radius':        50,
        'tweak preset 1 falloff':       1.5,
        'tweak preset 1 strength':      0.5,
        'tweak preset 2 name':         'Preset 2',
        'tweak preset 2 radius':        50,
        'tweak preset 2 falloff':       1.5,
        'tweak preset 2 strength':      0.5,
        'tweak preset 3 name':         'Preset 3',
        'tweak preset 3 radius':        50,
        'tweak preset 3 falloff':       1.5,
        'tweak preset 3 strength':      0.5,
        'tweak preset 4 name':         'Preset 4',
        'tweak preset 4 radius':        50,
        'tweak preset 4 falloff':       1.5,
        'tweak preset 4 strength':      0.5,

        'patches angle':                120,

        'select geometry':              'Verts',
        'select merge dist':           10,         # pixels away to merge
        'select automerge':            True,
    }

    db = None           # current options dict
    fndb = None         # name of file in which to store db (set up in __init__)
    is_dirty = False    # does the internal db differ from db stored in file? (need writing)
    last_change = 0     # when did we last changed an option?
    write_delay = 1.0   # seconds to wait before writing db to file
    write_error = False # True when we failed to write options to file

    def __init__(self):
        self._callbacks = []
        self._calling = False
        if not Options.fndb:
            Options.fndb = get_path_from_addon_root(retopoflow_files['options filename'])
            # Options.fndb = self.get_path('options filename')
            print(f'RetopoFlow options path: {Options.fndb}')
            self.read()
            self['version update'] = (self['rf version'] != retopoflow_product['version'])
            self['rf version'] = retopoflow_product['version']
        self.update_external_vars()

    def __getitem__(self, key):
        return Options.db[key] if key in Options.db else Options.default_options[key]

    def __setitem__(self, key, val):
        assert key in Options.default_options, f'Attempting to write "{key}":"{val}" to options, but key does not exist'
        assert not self._calling, f'Attempting to change option "{key}" to "{val}" while calling callbacks'
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
        return get_path_from_addon_root(retopoflow_files[key])

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
        Logger.set_log_filename(retopoflow_files['log filename'])
        # Profiler.set_profiler_enabled(self['profiler'] and retopoflow_profiler)
        Profiler.set_profiler_filename(self.get_path('profiler filename'))
        Drawing.set_custom_dpi_mult(self['ui scale'])
        UI_Document.show_tooltips = self['show tooltips']
        UI_Document.tooltip_delay = self['tooltip delay']
        self.call_callbacks()

    def dirty(self):
        Options.is_dirty = True
        Options.last_change = time.time()
        self.update_external_vars()

    def clean(self, force=False, raise_exception=True, retry=True):
        if not Options.is_dirty:
            # nothing has changed
            return
        if not force and time.time() < Options.last_change + Options.write_delay:
            # we haven't waited long enough before storing db
            if retry: bpy.app.timers.register(self.clean, first_interval=Options.write_delay)
            return
        dprint('Writing options:', Options.db)
        try:
            json.dump(
                Options.db,
                open(Options.fndb, 'wt'),
                indent=2,
                sort_keys=True,
            )
            Options.is_dirty = False
        except PermissionError as e:
            self.write_error = True
            if raise_exception: raise e
        except Exception as e:
            self.write_error = True
            if raise_exception: raise e

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
                print(f'Deleting key "{k}" from options')
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
            if key in Options.db:
                del Options.db[key]
        if version:
            Options.db['rf version'] = retopoflow_product['version']
        self.dirty()
        self.clean()

    def set_default(self, key, val):
        # does not dirty nor invoke write!
        assert key in Options.default_options, f'Attempting to write "{key}":"{val}" to options, but key does not exist'
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

    def get_auto_save_filepath(self, *, suffix=None, emergency=False):
        suffix = f'_{suffix}' if suffix else ''

        if emergency or not getattr(bpy.data, 'filepath', None):
            # not working on a saved .blend file, yet!
            path = os.path.expanduser('~')
            # path = bpy.context.preferences.filepaths.temporary_directory
            # if not path: path = tempfile.gettempdir()
            filename = retopoflow_files['backup filename']
        else:
            fullpath = os.path.abspath(bpy.data.filepath)
            path, filename = os.path.split(fullpath)
            suffix = f'_RetopoFlow_AutoSave{suffix}'

        base, ext = os.path.splitext(filename)
        return os.path.join(path, f'{base}{suffix}{ext}')


class Themes:
    # fallback color for when specified key is not found
    error = Color.from_ints(255,  64, 255, 255)

    common = {
        'mesh':       Color.from_ints(255, 255, 255, 255),
        'warning':    Color.from_ints(182,  31,   0, 128),

        'stroke':     Color.from_ints(255, 255,   0, 255),
        'highlight':  Color.from_ints(255, 255,  25, 255),
        'set select': Color.from_ints(255, 255, 255, 192),
        'add select': Color.from_ints(128, 255, 128, 192),
        'del select': Color.from_ints(255, 128, 128, 192),

        # RFTools
        'polystrips': Color.from_ints(  0, 100,  25, 150),
        'strokes':    Color.from_ints(  0, 100,  90, 150),
        'tweak':      Color.from_ints(229, 137,  26, 255), # Opacity is set by brush strength
        'relax':      Color.from_ints(  0, 135, 255, 255), # Opacity is set by brush strength

        # Target Geometry
        'warn':       Color((0.43, 0.072, 0.03)), #.from_ints(182,  31,   0),
        'seam':       Color((0.859, 0.145, 0.071)), #.from_ints(255, 160, 255),
        'pin':        Color.from_ints(217, 200, 18), #.from_ints(255,  41, 255),
    }

    themes = {
        'Green': {
            'select':  Color.from_ints( 78, 207,  81),
            'new':     Color.from_ints( 40, 255,  40),
        },
        'Blue': {
            'select':  Color.from_ints( 55, 160, 255),
            'new':     Color.from_ints( 40,  40, 255),
        },
        'Orange': {
            'select':  Color.from_ints(255, 135,  54),
            'new':     Color.from_ints(255, 128,  64),
        },
    }
    # themes['Blue'] = {
    #     key: color.rotated_hue((209 - 121) / 360) for (key, color) in themes['Green'].items()
    # }
    # themes['Orange'] = {
    #     key: color.rotated_hue((24 - 121) / 360) for (key, color) in themes['Green'].items()
    # }

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
        watch = [
            'color theme',
            'normal offset multiplier',
            'constrain offset',
            'target vert size',
            'target edge size',
            *[f'target alpha poly {p}'         for p in ['', 'selected', 'warning', 'pinned', 'seam']],
            *[f'target alpha poly mirror {p}'  for p in ['', 'selected', 'warning', 'pinned', 'seam']],
            *[f'target alpha line {p}'         for p in ['', 'selected', 'warning', 'pinned', 'seam']],
            *[f'target alpha line mirror {p}'  for p in ['', 'selected', 'warning', 'pinned', 'seam']],
            *[f'target alpha point {p}'        for p in ['', 'selected', 'warning', 'pinned', 'seam']],
            *[f'target alpha point mirror {p}' for p in ['', 'selected', 'warning', 'pinned', 'seam']],
            'target alpha point highlight',
            'target alpha mirror',
        ]
        watch = [w.strip() for w in watch]  # strip watched properties to remove trailing spaces
        if all(getattr(self._last, key, None) == options[key] for key in watch): return
        for key in watch: self._last[key] = options[key]

        color_mesh = themes['mesh']
        color_select = themes['select']
        color_warn = themes['warn']
        color_pin = themes['pin']
        color_seam = themes['seam']
        color_hilight = themes['highlight']
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
            'no warning':     True,
            'no pinned':      True,
            'no seam':        True,
            'no below':       True,
            'triangles only': True,     # source bmeshes are triangles only!
            'cull backfaces': True,

            'focus mult':       0.01,
            'normal offset':    0.0005 * normal_offset_multiplier,    # pushes vertices out along normal
            'constrain offset': constrain_offset,
        }

        mirror_alpha_factor = options['target alpha mirror']
        self._target_settings = {
            'poly color':                  (*color_mesh[:3],   options['target alpha poly']),
            'poly color selected':         (*color_select[:3], options['target alpha poly selected']),
            'poly color warning':          (*color_warn[:3],   options['target alpha poly warning']),
            'poly color pinned':           (*color_pin[:3],    options['target alpha poly pinned']),
            'poly color seam':             (*color_seam[:3],   options['target alpha poly seam']),
            'poly offset':                 0.000010,
            'poly dotoffset':              1.0,
            'poly mirror color':           (*color_mesh[:3],   options['target alpha poly mirror'] * mirror_alpha_factor),
            'poly mirror color selected':  (*color_select[:3], options['target alpha poly mirror selected'] * mirror_alpha_factor),
            'poly mirror color warning':   (*color_warn[:3],   options['target alpha poly mirror warning'] * mirror_alpha_factor),
            'poly mirror color pinned':    (*color_pin[:3],    options['target alpha poly mirror pinned'] * mirror_alpha_factor),
            'poly mirror color seam':      (*color_seam[:3],   options['target alpha poly mirror seam'] * mirror_alpha_factor),
            'poly mirror offset':          0.000010,
            'poly mirror dotoffset':       1.0,

            'line color':                  (*color_mesh[:3],   options['target alpha line']),
            'line color selected':         (*color_select[:3], options['target alpha line selected']),
            'line color warning':          (*color_warn[:3],   options['target alpha line warning']),
            'line color pinned':           (*color_pin[:3],    options['target alpha line pinned']),
            'line color seam':             (*color_seam[:3],   options['target alpha line seam']),
            'line width':                  edge_size,
            'line offset':                 0.000012,
            'line dotoffset':              1.0,
            'line mirror color':           (*color_mesh[:3],   options['target alpha line mirror'] * mirror_alpha_factor),
            'line mirror color selected':  (*color_select[:3], options['target alpha line mirror selected'] * mirror_alpha_factor),
            'line mirror color warning':   (*color_warn[:3],   options['target alpha line mirror warning'] * mirror_alpha_factor),
            'line mirror color pinned':    (*color_pin[:3],    options['target alpha line mirror pinned'] * mirror_alpha_factor),
            'line mirror color seam':      (*color_seam[:3],   options['target alpha line mirror seam'] * mirror_alpha_factor),
            'line mirror width':           1.5,
            'line mirror offset':          0.000012,
            'line mirror dotoffset':       1.0,

            'point color':                 (*color_mesh[:3],   options['target alpha point']),
            'point color selected':        (*color_select[:3], options['target alpha point selected']),
            'point color warning':         (*color_warn[:3],   options['target alpha point warning']),
            'point color pinned':          (*color_pin[:3],    options['target alpha point pinned']),
            'point color seam':            (*color_seam[:3],   options['target alpha point seam']),
            'point color highlight':       (*color_hilight[:3],options['target alpha point highlight']),
            'point size':                  vert_size,
            'point size highlight':        10.0,
            'point offset':                0.000015,
            'point dotoffset':             1.0,
            'point mirror color':          (*color_mesh[:3],   options['target alpha point mirror'] * mirror_alpha_factor),
            'point mirror color selected': (*color_select[:3], options['target alpha point mirror selected'] * mirror_alpha_factor),
            'point mirror color warning':  (*color_warn[:3],   options['target alpha point mirror warning'] * mirror_alpha_factor),
            'point mirror color pinned':   (*color_pin[:3],    options['target alpha point mirror pinned'] * mirror_alpha_factor),
            'point mirror color seam':     (*color_seam[:3],   options['target alpha point mirror seam'] * mirror_alpha_factor),
            'point mirror size':           3.0,
            'point mirror offset':         0.000015,
            'point mirror dotoffset':      1.0,

            'focus mult':                  0.0, #1.0,
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




class SessionOptions:
    '''
    options/settings that are specific to this particular .blend file.
    useful for storing current state and restoring in case of failure.
    data is stored in bpy.data.texts[textblockname]['data'].
    '''

    textblockname = retopoflow_datablocks['blender state']

    userfriendlytext = normalize_triplequote('''
        RetopoFlow customizes several aspects of Blender for optimal retopology
        experience by overriding viewport settings, rendering settings, mesh sizes,
        and so on.  This text block is used to store the previous options and settings
        that RetopoFlow overrides when it starts, so that they can be restored when
        RetopoFlow quits.

        Normally, this text block is never seen.  However, if Blender happens to crash or
        is closed before RetopoFlow was able to restore the Blender options and settings,
        these changes will remain in the last saved .blend file.  RetopoFlow will use
        this information to restore everything back to normal the next time the .blend
        file is opened.

        If you see this text block, RetopoFlow has not finished restoring the Blender
        settings.  In the 3D View, click RetopoFlow > Recover: Finish Auto Save Recovery.
    ''')

    default = {
        'retopoflow': {
            'version': retopoflow_product['version'],
            'timestamp': None, # automatically filled out when getting session data
            'target': None,    # automatically filled out when starting RF
        },

        'disabled': False,

        'normalize': {
            'unit scaling factor': None,
            'mesh scaling factor': 1.0,
            'view scaling factor': 1.0,
            'clip distances': {
                'start': None,
                'end': None,
            },
            'view': {
                'distance': None,
                'location': None,
            },
        },

        'blender': {
            # to be filled in by CookieCutter_Blender and RetopoFlow_Normalize
        },
    }

    @classmethod
    def _get_data_as_pydata(cls):
        if cls.textblockname not in bpy.data.texts: return None
        def convert(d):
            # print(f'{d=} {type(d)=}')
            if type(d) in {bool, int, float, str}:
                return d
            if hasattr(d, 'keys'):
                return { k: convert(d[k]) for k in d.keys() }
            # ASSUMING it is a list!
            return [ convert(v) for v in d ]
            assert False, f'Unknown type: {d} ({type(d)})'
        return convert(bpy.data.texts[cls.textblockname]['data'])

    @classmethod
    @contextmanager
    def temp_disable(cls):
        if not cls.has_session_data():
            yield None
            return
        cls.set('disabled', True)
        yield None
        cls.set('disabled', False)

    @classmethod
    def has_active_session_data(cls):
        if not cls.has_session_data(): return False
        data = bpy.data.texts[cls.textblockname]['data']
        return data['disabled'] if 'disabled' in data else True

    @classmethod
    def has_session_data(cls):
        if cls.textblockname not in bpy.data.texts: return False
        return True

    @classmethod
    def _get_data(cls):
        if not cls.has_session_data():
            # create text block for storing state
            textblock = bpy.data.texts.new(SessionOptions.textblockname)
            # set user-friendly message
            textblock.from_string(SessionOptions.userfriendlytext)
            textblock.cursor_set(0, character=0)
            # assignment below will create deep copy of default
            textblock['data'] = SessionOptions.default
            cls.set('retopoflow', 'timestamp', str(datetime.now()))
            #cls.set('retopoflow', 'timestamp', timestamp)
        else:
            textblock = bpy.data.texts[SessionOptions.textblockname]
        return textblock['data']

    class Walker:
        def __init__(self, *path):
            if len(path) == 1 and type(path[0]) is str:
                path = [path]
            self.__dict__['path'] = path

        @property
        def path(self):
            return self.__dict__['path']

        def __truediv__(self, key):
            return SessionOptions.Walker(*self.path, key)

        def __getattr__(self, key):
            return SessionOptions.get(*self.path, key)

        def __setattr__(self, key, value):
            SessionOptions.set(*self.path, key, val)
            return val

        @property
        def value(self):
            return SessionOptions.get(*self.path)
        @value.setter
        def value(self, val):
            SessionOptions.set(*self.path, val)

    @classmethod
    def __truediv__(cls, key):
        return SessionOptions.Walker([key])

    @classmethod
    @property
    def data(cls):
        return SessionOptions.Walker()

    @classmethod
    def get(cls, *keys):
        data = cls._get_data()
        if len(keys) == 1 and type(keys[0]) is not str:
            keys = keys[0]
        for key in keys: data = data[key]
        return data

    @classmethod
    def _get_default(cls, *keys):
        data = cls.default
        if len(keys) == 1 and type(keys[0]) is not str:
            keys = keys[0]
        for key in keys: data = data[key]
        return data

    @classmethod
    def set(cls, *args):
        if len(args) == 1:
            # `args` contains a dictionary
            dict_keys_vals = args[0]
            assert type(dict_keys_vals) is dict, f'SessionOptions.set expects dictionary ({dict_keys_vals=})'
            def s(*args):
                *path, dkv = args
                if type(dkv) is dict and type(cls._get_default(*path)) is dict:
                    for k,v in dkv.items():
                        s(*path, k, v)
                else:
                    cls.set(*path, dkv)
            s(dict_keys_vals)
        else:
            # `args` is a list, where all but last are keys into SessionOptions and last is the value to set
            keys_then_value = args
            assert len(keys_then_value) >= 2, f'SessionOptions.set expects at least 2 arguments ({keys_then_value=})'
            *keys, value = keys_then_value
            data = cls.get(keys[:-1])
            data[keys[-1]] = value

    def __getitem__(self, keys):
        if type(keys) is str: keys = (keys,)
        return self.get(*keys)

    def __setitem__(self, keys, value):
        if type(keys) is str: keys = (keys,)
        return self.set(*keys, value)

    @classmethod
    def clear(cls):
        if not cls.has_session_data(): return
        textblock = bpy.data.texts[cls.textblockname]
        bpy.data.texts.remove(textblock)


# set all the default values!
options = Options()
themes = Themes()
visualization = Visualization_Settings()
sessionoptions = SessionOptions()
