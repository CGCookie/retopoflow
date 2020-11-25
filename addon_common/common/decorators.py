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
import json
import time
import inspect

import bpy


debug_run_test_calls = False
def debug_test_call(*args, **kwargs):
    def wrapper(fn):
        if debug_run_test_calls:
            ret = str(fn(*args,*kwargs))
            print('TEST: %s()' % fn.__name__)
            if args:
                print('  arg:', args)
            if kwargs:
                print('  kwa:', kwargs)
            print('  ret:', ret)
        return fn
    return wrapper



def stats_wrapper(fn):
    return fn

    if not hasattr(stats_report, 'stats'):
        stats_report.stats = dict()
    frame = inspect.currentframe().f_back
    f_locals = frame.f_locals

    filename = os.path.basename(frame.f_code.co_filename)
    clsname = f_locals['__qualname__'] if '__qualname__' in f_locals else ''
    linenum = frame.f_lineno
    fnname = fn.__name__
    key = '%s%s (%s:%d)' % (
        clsname + ('.' if clsname else ''),
        fnname, filename, linenum
    )
    stats = stats_report.stats
    stats[key] = {
        'filename': filename,
        'clsname': clsname,
        'linenum': linenum,
        'fileline': '%s:%d' % (filename, linenum),
        'fnname': fnname,
        'count': 0,
        'total time': 0,
        'average time': 0,
    }

    def wrapped(*args, **kwargs):
        time_beg = time.time()
        ret = fn(*args, **kwargs)
        time_end = time.time()
        time_delta = time_end - time_beg
        d = stats[key]
        d['count'] += 1
        d['total time'] += time_delta
        d['average time'] = d['total time'] / d['count']
        return ret
    return wrapped


def stats_report():
    return

    stats = stats_report.stats if hasattr(stats_report, 'stats') else dict()
    l = max(len(k) for k in stats)

    def fmt(s):
        return s + ' ' * (l - len(s))

    print()
    print('Call Statistics Report')

    cols = [
        ('class', 'clsname', '%s'),
        ('func', 'fnname', '%s'),
        ('location', 'fileline', '%s'),
        # ('line','linenum','% 10d'),
        ('count', 'count', '% 8d'),
        ('total (sec)', 'total time', '% 10.4f'),
        ('avg (sec)', 'average time', '% 10.6f'),
    ]
    data = [stats[k] for k in sorted(stats)]
    data = [[h] + [f % row[c] for row in data] for (h, c, f) in cols]
    colwidths = [max(len(d) for d in col) for col in data]
    totwidth = sum(colwidths) + len(colwidths) - 1

    def rpad(s, l):
        return '%s%s' % (s, ' ' * (l - len(s)))

    def printrow(i_row):
        row = [col[i_row] for col in data]
        print(' '.join(rpad(d, w) for (d, w) in zip(row, colwidths)))

    printrow(0)
    print('-' * totwidth)
    for i in range(1, len(data[0])):
        printrow(i)



def add_cache(attr, default):
    def wrapper(fn):
        setattr(fn, attr, default)
        return fn
    return wrapper


class LimitRecursion:
    def __init__(self, count, def_ret):
        self.count = count
        self.def_ret = def_ret
        self.calls = 0

    def __call__(self, fn):
        def wrapped(*args, **kwargs):
            ret = self.def_ret
            if self.calls < self.count:
                try:
                    self.calls += 1
                    ret = fn(*args, **kwargs)
                finally:
                    self.calls -= 1
            return ret
        return wrapped


def timed_call(label):
    def wrapper(fn):
        def wrapped(*args, **kwargs):
            time_beg = time.time()
            ret = fn(*args, **kwargs)
            time_end = time.time()
            time_delta = time_end - time_beg
            print('Timing: %0.4fs, %s' % (time_delta, label))
            return ret
        return wrapped
    return wrapper


# corrected bug in previous version of blender_version fn wrapper
# https://github.com/CGCookie/retopoflow/commit/135746c7b4ee0052ad0c1842084b9ab983726b33#diff-d4260a97dcac93f76328dfaeb5c87688
def blender_version_wrapper(op, ver):
    self = blender_version_wrapper
    if not hasattr(self, 'fns'):
        major, minor, rev = bpy.app.version
        self.blenderver = '%d.%02d' % (major, minor)
        self.fns = fns = {}
        self.ops = {
            '<':  lambda v: self.blenderver <  v,
            '>':  lambda v: self.blenderver >  v,
            '<=': lambda v: self.blenderver <= v,
            '==': lambda v: self.blenderver == v,
            '>=': lambda v: self.blenderver >= v,
            '!=': lambda v: self.blenderver != v,
        }

    update_fn = self.ops[op](ver)
    def wrapit(fn):
        nonlocal self, update_fn
        fn_name = fn.__name__
        fns = self.fns
        error_msg = "Could not find appropriate function named %s for version Blender %s" % (fn_name, self.blenderver)

        if update_fn: fns[fn_name] = fn

        def callit(*args, **kwargs):
            nonlocal fns, fn_name, error_msg
            fn = fns.get(fn_name, None)
            assert fn, error_msg
            ret = fn(*args, **kwargs)
            return ret

        return callit
    return wrapit

class PersistentOptions:
    class WrappedDict:
        def __init__(self, cls, filename, version, defaults, update_external):
            self._dirty = False
            self._last_save = time.time()
            self._write_delay = 2.0
            self._defaults = defaults
            self._update_external = update_external
            self._defaults['persistent options version'] = version
            self._dict = {}
            if filename:
                src = inspect.getsourcefile(cls)
                path = os.path.split(os.path.abspath(src))[0]
                self._fndb = os.path.join(path, filename)
            else:
                self._fndb = None
            self.read()
            if self._dict.get('persistent options version', None) != version:
                self.reset()
            self.update_external()
        def update_external(self):
            upd = self._update_external
            if upd:
                upd()
        def dirty(self):
            self._dirty = True
            self.update_external()
        def clean(self, force=False):
            if not force:
                if not self._dirty:
                    return
                if time.time() < self._last_save + self._write_delay:
                    return
            if self._fndb:
                json.dump(self._dict, open(self._fndb, 'wt'), indent=2, sort_keys=True)
            self._dirty = False
            self._last_save = time.time()
        def read(self):
            self._dict = {}
            if self._fndb and os.path.exists(self._fndb):
                try:
                    self._dict = json.load(open(self._fndb, 'rt'))
                except Exception as e:
                    print('Exception caught while trying to read options from "%s"' % self._fndb)
                    print(str(e))
                for k in set(self._dict.keys()) - set(self._defaults.keys()):
                    print('Deleting extraneous key "%s" from options' % k)
                    del self._dict[k]
            self.update_external()
            self._dirty = False
        def keys(self):
            return self._defaults.keys()
        def reset(self):
            keys = list(self._dict.keys())
            for k in keys:
                del self._dict[k]
            self._dict['persistent options version'] = self['persistent options version']
            self.dirty()
            self.clean()
        def __getitem__(self, key):
            return self._dict[key] if key in self._dict else self._defaults[key]
        def __setitem__(self, key, val):
            assert key in self._defaults, 'Attempting to write "%s":"%s" to options, but key does not exist in defaults' % (str(key), str(val))
            if self[key] == val: return
            self._dict[key] = val
            self.dirty()
            self.clean()
        def gettersetter(self, key, fn_get_wrap=None, fn_set_wrap=None):
            if not fn_get_wrap: fn_get_wrap = lambda v: v
            if not fn_set_wrap: fn_set_wrap = lambda v: v
            oself = self
            class GetSet:
                def get(self):
                    return fn_get_wrap(oself[key])
                def set(self, v):
                    v = fn_set_wrap(v)
                    if oself[key] != v:
                        oself[key] = v
            return GetSet()

    def __init__(self, filename=None, version=None):
        self._filename = filename
        self._version = version
        self._db = None

    def __call__(self, cls):
        upd = getattr(cls, 'update', None)
        if upd:
            u = upd
            def wrap():
                def upd_wrap(*args, **kwargs):
                    u(None)
                return upd_wrap
            upd = wrap()
        self._db = PersistentOptions.WrappedDict(cls, self._filename, self._version, cls.defaults, upd)
        db = self._db
        class WrappedClass:
            def __init__(self, *args, **kwargs):
                self._db = db
                self._def = cls.defaults
            def __getitem__(self, key):
                return self._db[key]
            def __setitem__(self, key, val):
                self._db[key] = val
            def keys(self):
                return self._db.keys()
            def reset(self):
                self._db.reset()
            def clean(self):
                self._db.clean()
            def gettersetter(self, key, fn_get_wrap=None, fn_set_wrap=None):
                return self._db.gettersetter(key, fn_get_wrap=fn_get_wrap, fn_set_wrap=fn_set_wrap)
        return WrappedClass


