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

'''
This code helps prevent circular importing.
Each of the main common objects are referenced here.
'''

class GlobalsMeta(type):
    # allows for `Globals.drawing` instead of `Globals.get('drawing')`
    def __setattr__(self, name, value):
        self.set(value, objtype=name)
    def __getattr__(self, objtype):
        return self.get(objtype)

class Globals(metaclass=GlobalsMeta):
    __vars = {}

    @staticmethod
    def set(obj, objtype=None):
        Globals.__vars[objtype or type(obj).__name__.lower()] = obj
        return obj

    @staticmethod
    def is_set(objtype):
        return Globals.__vars.get(objtype, None) is not None

    @staticmethod
    def get(objtype):
        return Globals.__vars.get(objtype, None)

    @staticmethod
    def __getattr__(objtype):
        return Globals.get(objtype)
