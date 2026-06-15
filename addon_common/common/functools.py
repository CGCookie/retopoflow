'''
Copyright (C) 2023 CG Cookie
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

from functools import wraps
from inspect import signature, getmodule, getfile, currentframe, getframeinfo
from types import FrameType
from typing import ParamSpec, TypeVar
from collections.abc import Callable

##################################################

Param = ParamSpec('Param')
RetType = TypeVar('RetType')

def wrap_function(
    fn_original : Callable[Param, RetType],
    *,
    fn_pre : Callable[Param, None] | None = None,
    fn_post : Callable[Param, None] | None = None,
) -> Callable[[], None]:
    mod_original = getmodule(fn_original)

    # gather debug info
    f_current : FrameType | None = currentframe()
    assert f_current
    f_calling : FrameType | None = f_current.f_back
    assert f_calling
    info = getframeinfo(f_calling)

    def call_and_report_exception(
        label : str,
        fn : Callable[Param, RetType|None] | None,
        args : ..., kwargs : ... # pyright: ignore[reportAny]
    ) -> RetType | None:
        if not fn:
            return None
    
        try:
            ret = fn(*args, **kwargs) # pyright: ignore[reportCallIssue, reportAny]
        except Exception as e:
            print(f'Caught Exceptions while calling {label} on wrapped {fn_original.__name__}')
            print(f'  *args: {args}')
            print(f'  **kwargs: {kwargs}')
            print(f'  wrapped from: {info.filename}:{info.lineno} in {info.function}')
            print(f'  fn_original file: {getfile(fn_original)}')
            print(f'  Exception: {e}')
            raise
        return ret

    @wraps(fn_original)
    def wrapped(*args : ..., **kwargs : ...) -> RetType: # pyright: ignore[reportAny]
        _   = call_and_report_exception('pre',      fn_pre,      args, kwargs)
        ret = call_and_report_exception('original', fn_original, args, kwargs)
        _   = call_and_report_exception('post',     fn_post,     args, kwargs)
        return ret # pyright: ignore[reportReturnType]

    def unwrap():
        # print(f'unwrapping')
        setattr(mod_original, fn_original.__name__, fn_original)

    setattr(mod_original, fn_original.__name__, wrapped)
    return unwrap









##################################################


# find functions of object that has key attribute
# returns list of (attribute value, fn)
def find_fns(obj, key, *, full_search=False):
    classes = type(obj).__mro__ if full_search else [type(obj)]
    members = [getattr(cls, k) for cls in classes for k in dir(cls) if hasattr(cls, k)]
    # test if type is fn_type rather than isfunction() because bpy has problems!
    # methods = [member for member in members if isfunction(member)]
    fn_type = type(find_fns)
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
