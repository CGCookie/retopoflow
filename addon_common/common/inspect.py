'''
Copyright (C) 2023 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning

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

import inspect

from collections.abc import MutableMapping


class ScopeBuilder(MutableMapping):
    """
    A dictionary-like object that mimics frame.f_locals
    - builds up a custom locals mapping based on current f_locals
    - names can be transformed (ex: a local x can be referred using y in nonlocal)
    - value getting is lazy (no need to capture after variable has been assigned to)
    """

    @staticmethod
    def get_frame(frame_depth):
        frame = inspect.currentframe()
        for i in range(frame_depth):
            frame = frame.f_back
        return frame

    def __init__(self, *args, frame_depth=1, **kwargs):
        self.__store = dict()

        frame = self.get_frame(frame_depth + 1)
        for nonlocalname in args:
            localname = nonlocalname
            self.__store[nonlocalname] = (frame, localname)
        for nonlocalname, localname in kwargs.items():
            self.__store[nonlocalname] = (frame, localname)

    def items(self):
        return { nonlocalname: self[nonlocalname] for nonlocalname in self }

    def __getitem__(self, nonlocalname):
        (frame, localname) = self.__store[nonlocalname]
        if localname in frame.f_locals: return frame.f_locals[localname]
        if localname in frame.f_globals: return frame.f_globals[localname]
        assert False, f'Could not find {localname} in locals or globals of {frame}'

    def __setitem__(self, nonlocalname, localname):
        frame = self.get_frame(2)
        self.__store[nonlocalname] = (frame, localname)

    def __delitem__(self, nonlocalname):
        del self.__store[nonlocalname]

    def keys(self):
        return self.__store.keys()

    def __iter__(self):
        return iter(self.__store)

    def __len__(self):
        return len(self.__store)

    def _keytransform(self, key):
        return key

    def capture_fn(self, arg, *, frame_depth=1):
        frame = self.get_frame(frame_depth + 1)
        if inspect.isfunction(arg):
            fn = arg
            nonlocalname = fn.__name__
            localname = fn.__name__
            self.__store[nonlocalname] = (frame, localname)
            return fn

        nonlocalname = arg
        def cb(fn):
            localname = fn.__name__
            self.__store[nonlocalname] = (frame, localname)
            return fn
        return cb

    def capture_var(self, nonlocalname, /, localname=None, *, frame_depth=1):
        frame = self.get_frame(frame_depth + 1)
        self.__store[nonlocalname] = (frame, localname or nonlocalname)


# class CaptureLocals(dict):
#     def __init__(self, *args, frame_depth=1, **kwargs):
#         self.__frame = inspect.currentframe()
#         for i in range(frame_depth):
#             self.__frame = self.__frame.f_back
#         for arg in args: self.capture(arg)
#         for k, v in kwargs.items(): self.capture(v, k)

#     def capture(self, var, as_var=None):
#         self[as_var or var] = self.__frame.f_locals[var]

#     def capture_fn(self, fn):
#         self[fn.__name__] = fn
#         return fn

def capture_locals(*args, frame_depth=1, **kwargs):
    frame = inspect.currentframe()
    for i in range(frame_depth): frame = frame.f_back
    f_locals = {}
    for arg in args:
        f_locals[arg] = frame.f_locals[arg]
    for k, v in kwargs.items():
        f_locals[k] = frame.f_locals[v]
    return f_locals
