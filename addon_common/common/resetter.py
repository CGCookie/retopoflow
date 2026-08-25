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
from collections import ChainMap
from bpy.types import bpy_prop_array
from mathutils import Color

Key = str | tuple[object, str]
PathPart = str | int                             # attribute name or subscript index
Stored = tuple[object, object, list[PathPart]]   # previous value, root object, path from root

def simple_representation(v : object) -> object:
    match v:
        case bpy_prop_array():
            return list(v) # pyright: ignore[reportUnknownVariableType]
        case Color():
            return list(v)
        case _:
            return v

# matches one path segment: an attribute name (with optional leading dot) or an integer subscript
re_path_part = re.compile(r'\.?(\w+)|\[(\d+)\]')

def parse_path(path : str) -> list[PathPart]:
    # 'context.preferences.themes[0].view_3d' -> ['context', 'preferences', 'themes', 0, 'view_3d']
    parts : list[PathPart] = []
    pos = 0
    assert not path.startswith('.'), f'Cannot parse path "{path}"'
    for m in re_path_part.finditer(path):
        assert m.start() == pos, f'Cannot parse path "{path}" at position {pos}'
        parts.append(m[1] if m[1] is not None else int(m[2]))
        pos = m.end()
    assert pos == len(path) and parts, f'Cannot parse path "{path}"'
    return parts

def resolve_path(o : object, parts : list[PathPart]) -> object:
    for part in parts:
        o = o[part] if type(part) is int else getattr(o, part) # pyright: ignore[reportIndexIssue, reportArgumentType]
    return o

class Resetter:
    _label    : str | None
    _previous : dict[Key, Stored]
    _backup   : dict[Key, Stored]

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

        match key:
            case str():
                # root name (ex: context, space) is looked up in the caller's scope
                root_name, *parts = parse_path(key)
                assert type(root_name) is str, f'Path "{key}" must start with a name'
                frame = inspect.currentframe()
                for _ in range(depth):
                    assert frame
                    frame = frame.f_back
                assert frame
                root = ChainMap(frame.f_locals, frame.f_globals)[root_name]
            case (root, attr_path):
                parts = parse_path(attr_path)
            case _: # pyright: ignore[reportUnnecessaryComparison]
                assert False, f'Unhandled type {type(key)} ({key})' # pyright: ignore[reportUnreachable]

        assert parts and type(parts[-1]) is str, f'Path in "{key}" must end with an attribute'
        pvalue = resolve_path(root, parts)

        # print(f'Resetter {self._label}: store {key} = {pvalue} ({type(pvalue)})')
        self._previous[key] = (simple_representation(pvalue), root, parts)

    def _setter(self, key : Key, value : object):
        _, root, parts = self._previous[key]

        try:
            owner = resolve_path(root, parts[:-1])
        except (AttributeError, ReferenceError):
            # a None partway along the path (ex: context.scene is None while Blender is shutting down),
            # or a reference to a since-freed StructRNA (ex: a closed Space)
            return
        if owner is None:
            # the property's owner is gone, so there is nothing left to restore
            return

        try:
            setattr(owner, parts[-1], value) # pyright: ignore[reportArgumentType]
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
        value, _, _ = self._previous[key]
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
