'''
Copyright (C) 2014 Plasmasolutions
software@plasmasolutions.de

Created by Thomas Beck
Donated to CGCookie and the world

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

'''
Note: not all of the following code was provided by Plasmasolutions
TODO: split into separate files?
'''

import os
import sys
import time
import inspect
import itertools
import linecache
import traceback
from math import floor
from hashlib import md5
from datetime import datetime
from functools import wraps

from .blender import show_blender_popup
from .functools import find_fns
from .globals import Globals
from .hasher import Hasher


class Debugger:
    _error_level = 1
    _exception_count = 0

    def __init__(self):
        pass

    @staticmethod
    def set_error_level(l):
        Debugger._error_level = max(0, min(5, int(l)))

    @staticmethod
    def get_error_level():
        return Debugger._error_level

    @staticmethod
    def dprint(*objects, sep=' ', end='\n', file=sys.stdout, flush=True, l=2):
        if Debugger._error_level < l: return
        sobjects = sep.join(str(o) for o in objects)
        print(
            f'DEBUG({l}): {sobjects}',
            end=end, file=file, flush=flush
        )

    @staticmethod
    def dcallstack(l=2):
        ''' print out the calling stack, skipping the first (call to dcallstack) '''
        Debugger.dprint('Call Stack Dump:', l=l)
        for i, entry in enumerate(inspect.stack()):
            if i > 0:
                Debugger.dprint('  %s' % str(entry), l=l)

    @staticmethod
    def call_stack():
        return traceback.format_stack()


    # http://stackoverflow.com/questions/14519177/python-exception-handling-line-number
    @staticmethod
    def get_exception_info_and_hash():
        '''
        this function is a duplicate of the one above, but this will attempt
        to create a hash to make searching for duplicate bugs on github easier (?)
        '''

        exc_type, exc_obj, tb = sys.exc_info()
        pathabs, pathdir = os.path.abspath, os.path.dirname
        pathjoin, pathsplit = os.path.join, os.path.split
        base_path = pathabs(pathjoin(pathdir(__file__), '..'))

        hasher = Hasher()
        errormsg = ['EXCEPTION (%s): %s' % (exc_type, exc_obj)]
        hasher.add(errormsg[0])
        # errormsg += ['Base: %s' % base_path]

        etb = traceback.extract_tb(tb)
        pfilename = None
        for i,entry in enumerate(reversed(etb)):
            filename,lineno,funcname,line = entry
            if pfilename is None:
                # only hash in details of where the exception occurred
                hasher.add(os.path.split(filename)[1])
                # hasher.add(lineno)
                hasher.add(funcname)
                hasher.add(line.strip())
            if filename != pfilename:
                pfilename = filename
                if filename.startswith(base_path):
                    filename = '.../%s' % filename[len(base_path)+1:]
                errormsg += ['    %s' % (filename, )]
            errormsg += ['%03d %04d:%s() %s' % (i, lineno, funcname, line.strip())]

        return ('\n'.join(errormsg), hasher.get_hash())

    @staticmethod
    def print_exception():
        Debugger._exception_count += 1
        errormsg, errorhash = Debugger.get_exception_info_and_hash()
        message = []
        message += ['Exception Info']
        message += ['- Time: %s' % datetime.today().isoformat(' ')]
        message += ['- Count: %d' % Debugger._exception_count]
        message += ['- Hash: %s' % str(errorhash)]
        message += ['- Info:']
        message += ['  - %s' % s for s in errormsg.splitlines()]
        message = '\n'.join(message)
        print('%s\n%s\n%s' % ('_' * 100, message, '^' * 100))
        logger = Globals.logger
        if logger: logger.add(message)   # write error to log text object
        # if Debugger._exception_count < 10:
        #     show_blender_popup(
        #         message,
        #         title='Exception Info',
        #         icon='ERROR',
        #         wrap=240
        #     )
        return message

    # @staticmethod
    # def print_exception2():
    #     exc_type, exc_value, exc_traceback = sys.exc_info()
    #     print("*** print_tb:")
    #     traceback.print_tb(exc_traceback, limit=1, file=sys.stdout)
    #     print("*** print_exception:")
    #     traceback.print_exception(exc_type, exc_value, exc_traceback,
    #                               limit=2, file=sys.stdout)
    #     print("*** print_exc:")
    #     traceback.print_exc()
    #     print("*** format_exc, first and last line:")
    #     formatted_lines = traceback.format_exc().splitlines()
    #     print(formatted_lines[0])
    #     print(formatted_lines[-1])
    #     print("*** format_exception:")
    #     print(repr(traceback.format_exception(exc_type, exc_value,exc_traceback)))
    #     print("*** extract_tb:")
    #     print(repr(traceback.extract_tb(exc_traceback)))
    #     print("*** format_tb:")
    #     print(repr(traceback.format_tb(exc_traceback)))
    #     if exc_traceback:
    #         print("*** tb_lineno:", exc_traceback.tb_lineno)

    start_time = time.time()
    last_time = time.time()
    @staticmethod
    def tprint(*args):
        t = time.time()
        td = t - Debugger.last_time
        lbar = min(25, floor(td*20))
        bar = '%s%s' % ('X' * lbar, '_' * (25-lbar))
        print(bar, '%8.4f' % td, *args)
        sys.stdout.flush()
        Debugger.last_time = t


class ExceptionHandler:
    _universal = []

    @staticmethod
    def on_exception(fn):
        fn._exceptionhandler_on_exception = True
        return fn

    def __init__(self, obj=None, *, universal=False):
        # print(f'ExceptionHandler.__init__({self})')
        self._single = []
        self._um = []
        self._universal_only = universal
        self.collect_callbacks(obj)

    def __del__(self):
        # print(f'ExceptionHandler.__del__({self})')
        for fn in getattr(self, '_um', []):
            self.remove_universal_callback(fn)

    def collect_callbacks(self, obj):
        if not obj: return
        for (_, fn) in find_fns(obj, '_exceptionhandler_on_exception'):
            self.add_callback(fn)

    @staticmethod
    def add_universal_callback(fn):
        ExceptionHandler._universal += [fn]

    @staticmethod
    def remove_universal_callback(fn):
        if fn not in ExceptionHandler._universal: return
        ExceptionHandler._universal.remove(fn)

    @staticmethod
    def clear_universal_callbacks():
        ExceptionHandler._universal = []

    def add_callback(self, fn, universal=None):
        # print(f'ExceptionHandler.add_callback({self}, {fn}, {universal})')
        if getattr(fn, '_exceptionhandler_collected', False): return
        fn._exceptionhandler_collected = True
        if universal is None and self._universal_only: universal = True
        if universal:
            self._universal += [fn]
            self._um += [fn]
        else:
            self._single += [fn]

    def wrap(self, def_val, only=Exception):
        def wrapper(fn):
            def wrapped(*args, **kwargs):
                ret = def_val
                try:
                    ret = fn(*args, **kwargs)
                except only as e:
                    self.handle_exception(e)
                return ret
            return wrapped
        return wrapper

    def handle_exception(self, e):
        # print(f'ExceptionHandler: calling back these fns')
        # for fn in itertools.chain(self._universal, self._single):
        #     print(f'    {fn}')
        for fn in itertools.chain(self._universal, self._single):
            try:
                fn(e)
            except Exception as e2:
                print(f'ExceptionHandler: Caught exception while calling back exception callbacks: {fn.__name__}')
                print(f'    original:   {e}')
                print(f'    additional: {e2}')
                debugger.print_exception()


debugger = Debugger()
dprint = debugger.dprint
tprint = debugger.tprint
exceptionhandler = ExceptionHandler(universal=True)
Globals.set(debugger)
Globals.dprint = dprint
Globals.exceptionhandler = exceptionhandler
