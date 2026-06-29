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

import re
import inspect
from bpy.types import bpy_prop_array
from mathutils import Color

Key = str | tuple[object, str]
Scopes = list[dict[str, object]]

def simple_representation(v : object) -> object:
    match v:
        case bpy_prop_array():
            return list(v) # pyright: ignore[reportUnknownVariableType]
        case Color():
            return list(v)
        case _:
            return v

def object_to_key(o : object) -> str:
    s = str(o)

    # sanitize string by replacing any double quotes, newlines, or CRs with underscores
    s = re.sub(r'["\n\r]', '', s)

    # remove anything that looks like a memory address
    s = re.sub(r'0x[0-9a-fA-F]+', '', s)

    # print(f'object_to_key({o}) = "{s}"')
    return s

def create_variable(o : object, f_locals : dict[str, object]) -> str:
    if '__o' not in f_locals:
        f_locals['__o'] = {}
    k = object_to_key(o)
    f_locals['__o'][k] = o
    return k

class Resetter:
    _label : str | None
    _previous : dict[Key, tuple[object, Scopes]]
    _backup   : dict[Key, tuple[object, Scopes]]

    def __init__(self, label : str | None = None):
        self._label = label
        self._previous = {}
        self._backup = {}
        # print(f'Resetter: new {self._label}')

    def __del__(self):
        self.reset()

    def store(self, key : Key, *, depth : int = 1):
        if key in self._previous:
            return

        frame = inspect.currentframe()
        for _ in range(depth):
            assert frame
            frame = frame.f_back
        assert frame
        f_globals, f_locals = dict(frame.f_globals), dict(frame.f_locals)
        scopes = [f_globals, f_locals]

        match key:
            case str():
                cmd = f'{key}'
            case (o, a):
                var = create_variable(o, f_locals)
                cmd = f'__o["{var}"].{a}'
            case _: # pyright: ignore[reportUnnecessaryComparison]
                assert False, f'Unhandled type {type(key)} ({key})' # pyright: ignore[reportUnreachable]

        pvalue : object = eval(cmd, *scopes) # pyright: ignore[reportAny]

        # print(f'Resetter {self._label}: set {key} = {pvalue} ({type(pvalue)}) -> {value} ({type(value)})')
        self._previous[key] = (
            simple_representation(pvalue),
            [f_globals, f_locals],
        )

    def _setter(self, key : Key, value : object):
        _, scopes = self._previous[key]
        if type(value) is str:
            value = f'"{value}"'

        match key:
            case str():
                cmd = f'{key} = {value}'
            case (o, a):
                var = object_to_key(o)
                cmd = f'__o["{var}"].{a} = {value}'
            case _: # pyright: ignore[reportUnnecessaryComparison]
                assert False, f'Unhandled type {type(key)} ({key})' # pyright: ignore[reportUnreachable]

        try:
            exec(cmd, *scopes)
        except Exception as _exception:
            print(f'Resetter: Exception caught and ignored while trying to set {key} = {value}')
            print(f'  Exception: {_exception}')

    def __setitem__(self, key : Key, value : object):
        try:
            self.store(key, depth=2)
            self._setter(key, value)
        except Exception as e:
            print(f'Resetter: Exception caught while trying to set {key} = {value}')
            print(f'  Exception: {e}')
            raise e

    def __delitem__(self, key : Key):
        value, _ = self._previous[key]
        # print(f'Resetter {self._label}: reset {key} <- {value} ({type(value)})')
        self._setter(key, value)
        del self._previous[key]

    def reset(self):
        keys = list(self._previous.keys())
        for key in keys:
            del self[key]
        # print(f'Resetter: reset {self._label} {keys}')

    def clear(self):
        self._backup = self._previous
        self._previous = {}

    def restore(self):
        self._previous = self._backup
