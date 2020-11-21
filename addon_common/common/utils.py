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
import sys
import glob
import inspect
import operator
import itertools
import importlib

import bpy
from mathutils import Vector, Matrix

from .blender import get_preferences
from .profiler import profiler
from .debug import dprint, debugger
from .maths import (
    Point, Direction, Normal, Frame,
    Point2D, Vec2D, Direction2D,
    Ray, XForm, BBox, Plane
)


##################################################


# find functions of object that has key attribute
# returns list of (attribute value, fn)
def find_fns(obj, key):
    cls = type(obj)
    fn_type = type(find_fns)
    members = [getattr(cls, k) for k in dir(cls)]
    methods = [member for member in members if type(member) == fn_type]
    return [
        (getattr(method, key), method)
        for method in methods
        if hasattr(method, key)
    ]



##################################################

StructRNA = bpy.types.bpy_struct
def still_registered(self, oplist):
    if getattr(still_registered, 'is_broken', False): return False
    def is_registered():
        cur = bpy.ops
        for n in oplist:
            if not hasattr(cur, n): return False
            cur = getattr(cur, n)
        try: StructRNA.path_resolve(self, "properties")
        except:
            print('no properties!')
            return False
        return True
    if is_registered(): return True
    still_registered.is_broken = True
    print('bpy.ops.%s is no longer registered!' % '.'.join(oplist))
    return False

registered_objects = {}
def registered_object_add(self):
    global registered_objects
    opid = self.operator_id
    print('Registering bpy.ops.%s' % opid)
    registered_objects[opid] = (self, opid.split('.'))

def registered_check():
    global registered_objects
    return all(still_registered(s, o) for (s, o) in registered_objects.values())


#################################################


def find_and_import_all_subclasses(cls, root_path=None):
    here_path = os.path.realpath(os.path.dirname(__file__))
    if root_path is None:
        root_path = os.path.realpath(os.path.join(here_path, '..'))

    touched_paths = set()
    found_subclasses = set()

    def search(root):
        nonlocal touched_paths, found_subclasses, here_path

        root = os.path.realpath(root)
        if root in touched_paths: return
        touched_paths.add(root)

        relpath = os.path.relpath(root, here_path)
        #print('  relpath: %s' % relpath)

        for path in glob.glob(os.path.join(root, '*')):
            if os.path.isdir(path):
                if not path.endswith('__pycache__'):
                    search(path)
                continue
            if os.path.splitext(path)[1] != '.py':
                continue

            try:
                pyfile = os.path.splitext(os.path.basename(path))[0]
                if pyfile == '__init__': continue
                pyfile = os.path.join(relpath, pyfile)
                pyfile = re.sub(r'\\', '/', pyfile)
                if pyfile.startswith('./'): pyfile = pyfile[2:]
                level = pyfile.count('..')
                pyfile = re.sub(r'^(\.\./)*', '', pyfile)
                pyfile = re.sub('/', '.', pyfile)
                #print('    Searching: %s (%d, %s)' % (pyfile, level, path))
                try:
                    tmp = importlib.__import__(pyfile, globals(), locals(), [], level=level+1)
                except Exception as e:
                    print('Caught exception while attempting to search for classes')
                    print('  cls: %s' % str(cls))
                    print('  pyfile: %s' % pyfile)
                    print('  %s' % str(e))
                    #print('      Could not import')
                    continue
                for tk in dir(tmp):
                    m = getattr(tmp, tk)
                    if not inspect.ismodule(m): continue
                    for k in dir(m):
                        v = getattr(m, k)
                        if not inspect.isclass(v): continue
                        if v is cls: continue
                        if not issubclass(v, cls): continue
                        # v is a subclass of cls, so add it to the global namespace
                        #print('      Found %s in %s' % (str(v), pyfile))
                        globals()[k] = v
                        found_subclasses.add(v)
            except Exception as e:
                print('Exception occurred while searching %s' % path)
                debugger.print_exception()

    #print('Searching for class %s' % str(cls))
    #print('  cwd: %s' % os.getcwd())
    #print('  Root: %s' % root_path)
    search(root_path)
    return found_subclasses


#########################################################

def delay_exec(action, f_globals=None, f_locals=None):
    if f_globals is None or f_locals is None:
        frame = inspect.currentframe().f_back               # get frame   of calling function
        if f_globals is None: f_globals = frame.f_globals   # get globals of calling function
        if f_locals  is None: f_locals  = frame.f_locals    # get locals  of calling function
    def run_it(*args, **kwargs):
        # args are ignored!?
        d = dict(f_locals)
        d.update(kwargs)
        try:
            return exec(action, f_globals, f_locals)
        except Exception as e:
            print('Caught exception while trying to run a delay_exec')
            print('  action:', action)
            print('  except:', e)
            raise e
    return run_it

#########################################################


def git_info(start_at_caller=True):
    if start_at_caller:
        path_root = os.path.abspath(inspect.stack()[1][1])
    else:
        path_root = os.path.abspath(os.path.dirname(__file__))
    try:
        path_git_head = None
        while path_root:
            path_test = os.path.join(path_root, '.git', 'HEAD')
            if os.path.exists(path_test):
                # found it!
                path_git_head = path_test
                break
            if os.path.split(path_root)[1] == 'addons':
                break
            path_root = os.path.dirname(path_root)  # try next level up
        if not path_git_head:
            # could not find .git folder
            return None
        path_git_ref = open(path_git_head).read().split()[1]
        if not path_git_ref.startswith('refs/heads/'):
            print('git detected, but HEAD uses unexpected format')
            return None
        path_git_ref = path_git_ref[len('refs/heads/'):]
        git_ref_fullpath = os.path.join(path_root, '.git', 'logs', 'refs', 'heads', path_git_ref)
        if not os.path.exists(git_ref_fullpath):
            print('git detected, but could not find ref file %s' % git_ref_fullpath)
            return None
        log = open(git_ref_fullpath).read().splitlines()
        commit = log[-1].split()[1]
        return ('%s %s' % (path_git_ref, commit))
    except Exception as e:
        print('An exception occurred while checking git info')
        print(e)
    return None




#########################################################




def kwargopts(kwargs, defvals=None, **mykwargs):
    opts = defvals.copy() if defvals else {}
    opts.update(mykwargs)
    opts.update(kwargs)
    if 'opts' in kwargs: opts.update(opts['opts'])
    def factory():
        class Opts():
            ''' pretend to be a dictionary, but also add . access fns '''
            def __init__(self):
                self.touched = set()
            def __getattr__(self, opt):
                self.touched.add(opt)
                return opts[opt]
            def __getitem__(self, opt):
                self.touched.add(opt)
                return opts[opt]
            def __len__(self): return len(opts)
            def has_key(self, opt): return opt in opts
            def keys(self): return opts.keys()
            def values(self): return opts.values()
            def items(self): return opts.items()
            def __contains__(self, opt): return opt in opts
            def __iter__(self): return iter(opts)
            def print_untouched(self):
                print('untouched: %s' % str(set(opts.keys()) - self.touched))
            def pass_through(self, *args):
                return {key:self[key] for key in args}
        return Opts()
    return factory()



def kwargs_translate(key_from, key_to, kwargs):
    if key_from in kwargs:
        kwargs[key_to] = kwargs[key_from]
        del kwargs[key_from]

def kwargs_splitter(keys, kwargs):
    if type(keys) is str: keys = [keys]
    kw = {k:v for (k,v) in kwargs.items() if k in keys}
    for k in keys:
        if k in kwargs: del kwargs[k]
    return kw


def any_args(*args):
    return any(bool(a) for a in args)



#################################################


def accumulate_last(iterable, *args, **kwargs):
    # returns last result when accumulating
    # https://docs.python.org/3.7/library/itertools.html#itertools.accumulate
    final = None
    for step in itertools.accumulate(iterable, *args, **kwargs):
        final = step
    return final

def selection_mouse():
    select_type = get_preferences().inputs.select_mouse
    return ['%sMOUSE' % select_type, 'SHIFT+%sMOUSE' % select_type]

def get_settings():
    if not hasattr(get_settings, 'cache'):
        addons = get_preferences().addons
        folderpath = os.path.dirname(os.path.abspath(__file__))
        while folderpath:
            folderpath,foldername = os.path.split(folderpath)
            if foldername in {'lib','addons'}: continue
            if foldername in addons: break
        else:
            assert False, 'Could not find non-"lib" folder'
        if not addons[foldername].preferences: return None
        get_settings.cache = addons[foldername].preferences
    return get_settings.cache

def get_dpi():
    system_preferences = get_preferences().system
    factor = getattr(system_preferences, "pixel_size", 1)
    return int(system_preferences.dpi * factor)

def get_dpi_factor():
    return get_dpi() / 72

def blender_version():
    major,minor,rev = bpy.app.version
    # '%03d.%03d.%03d' % (major, minor, rev)
    return '%d.%02d' % (major,minor)


def iter_head(i, default=None):
    try:
        return next(iter(i))
    except StopIteration:
        return default

def iter_running_sum(lw):
    s = 0
    for w in lw:
        s += w
        yield (w,s)

def iter_pairs(items, wrap, repeat=False):
    if not items: return
    while True:
        for i0,i1 in zip(items[:-1],items[1:]): yield i0,i1
        if wrap: yield items[-1],items[0]
        if not repeat: return

def rotate_cycle(cycle, offset):
    l = len(cycle)
    return [cycle[(l + ((i - offset) % l)) % l] for i in range(l)]

def max_index(vals, key=None):
    if not key: return max(enumerate(vals), key=lambda ival:ival[1])[0]
    return max(enumerate(vals), key=lambda ival:key(ival[1]))[0]

def min_index(vals, key=None):
    if not key: return min(enumerate(vals), key=lambda ival:ival[1])[0]
    return min(enumerate(vals), key=lambda ival:key(ival[1]))[0]


def shorten_floats(s):
    # reduces number of digits (for float) found in a string
    # useful for reducing noise of printing out a Vector, Buffer, Matrix, etc.
    s = re.sub(r'(?P<neg>-?)(?P<d0>\d)\.(?P<d1>\d)\d\d+e-02', r'\g<neg>0.0\g<d0>\g<d1>', s)
    s = re.sub(r'(?P<neg>-?)(?P<d0>\d)\.\d\d\d+e-03', r'\g<neg>0.00\g<d0>', s)
    s = re.sub(r'-?\d\.\d\d\d+e-0[4-9]', r'0.000', s)
    s = re.sub(r'-?\d\.\d\d\d+e-[1-9]\d', r'0.000', s)
    s = re.sub(r'(?P<digs>\d\.\d\d\d)\d+', r'\g<digs>', s)
    return s


def get_matrices(ob):
    ''' obtain blender object matrices '''
    mx = ob.matrix_world
    imx = mx.inverted()
    return [mx, imx]


class AddonLocator(object):
    def __init__(self, f=None):
        self.fullInitPath = f if f else __file__
        self.FolderPath = os.path.dirname(self.fullInitPath)
        self.FolderName = os.path.basename(self.FolderPath)

    def AppendPath(self):
        sys.path.append(self.FolderPath)
        print("Addon path has been registered into system path for this session")



class UniqueCounter():
    __counter = 0
    @staticmethod
    def next():
        UniqueCounter.__counter += 1
        return UniqueCounter.__counter


class Dict():
    '''
    a fancy dictionary object
    '''
    def __init__(self, *args, **kwargs):
        self.__dict__['__d'] = {}
        self.set(*args, **kwargs)
    def __getitem__(self, k):
        return self.__dict__['__d'][k]
    def __setitem__(self, k, v):
        self.__dict__['__d'][k] = v
        return v
    def __delitem__(self, k):
        del self.__dict__['__d'][k]
    def __getattr__(self, k):
        return self.__dict__['__d'][k]
    def __setattr__(self, k, v):
        self.__dict__['__d'][k] = v
        return v
    def __delattr__(self, k):
        del self.__dict__['__d'][k]
    def set(self, d=None, **kwargs):
        if d:
            for k,v in d.items():
                self[k] = v
        for k,v in kwargs.items():
            self[k] = v