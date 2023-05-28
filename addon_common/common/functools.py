'''
Copyright (C) 2022 CG Cookie
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

from inspect import isfunction, signature


##################################################


# find functions of object that has key attribute
# returns list of (attribute value, fn)
def find_fns(obj, key):
    cls = type(obj)
    fn_type = type(find_fns)
    members = [getattr(cls, k) for k in dir(cls)]
    # test if type is fn_type rather than isfunction() because bpy has problems!
    # methods = [member for member in members if isfunction(member)]
    methods = [member for member in members if type(member) == fn_type]
    return [
        (getattr(method, key), method)
        for method in methods
        if hasattr(method, key)
    ]

def self_wrapper(self, fn):
    sig = signature(fn)
    params = list(sig.parameters.values())
    if params[0].name != 'self': return fn
    def wrapped(*args, **kwargs):
        return fn(self, *args, **kwargs)
    return wrapped
