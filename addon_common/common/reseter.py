'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

from bpy.types import bpy_prop_array
import inspect

class Reseter:
    def __init__(self, *, label=None):
        self._label = label
        self._previous = {}

    def __del__(self):
        self.reset()

    def _setter(self, key, value):
        _, f_globals, f_locals = self._previous[key]
        if type(value) is str: value = f'"{value}"'

        tkey = type(key)
        if tkey is str:
            exec(f'{key} = {value}', f_globals, f_locals)
        elif tkey is tuple:
            _, a = key
            exec(f'__o.{a} = {value}', f_globals, f_locals)

    def __setitem__(self, key, value):
        if key not in self._previous:
            frame = inspect.currentframe().f_back
            f_globals, f_locals = dict(frame.f_globals), dict(frame.f_locals)

            tkey = type(key)
            if tkey is str:
                pvalue = eval(f'{key}', f_globals, f_locals)
            elif tkey is tuple:
                o, a = key
                f_locals['__o'] = o
                pvalue = eval(f'__o.{a}', f_globals, f_locals)

            if type(pvalue) is bpy_prop_array:
                pvalue = list(pvalue)

            # print(f'Reseter {self._label}: set {key} = {pvalue} ({type(pvalue)}) -> {value} ({type(value)})')
            self._previous[key] = ( pvalue, f_globals, f_locals )

        self._setter(key, value)

    def __delitem__(self, key):
        value, _, _ = self._previous[key]
        # print(f'Reseter {self._label}: reset {key} <- {value} ({type(value)})')
        self._setter(key, value)
        del self._previous[key]

    def reset(self):
        keys = list(self._previous.keys())
        for key in keys:
            del self[key]

