'''
Copyright (C) 2018 CG Cookie

https://github.com/CGCookie/retopoflow

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

import bpy

class CookieCutter_Utils:
    def find_fns(self, key):
        c = type(self)
        objs = [getattr(c,k) for k in dir(c)]
        fns = [fn for fn in objs if inspect.isfunction(fn)]
        return [(getattr(fn,key),fn) for fn in fns if hasattr(fn,key)]
