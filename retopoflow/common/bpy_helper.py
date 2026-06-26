'''
Copyright (C) 2026 CG Cookie
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

import bpy
from typing import Protocol, Literal
from collections.abc import Callable
from types import ModuleType

class BpyOperatorCallable(Protocol):
    def __call__(
        self,
        /,
        execution_context : Literal[
            "INVOKE_DEFAULT",
            "INVOKE_REGION_WIN",
            "INVOKE_REGION_CHANNELS",
            "INVOKE_REGION_PREVIEW",
            "INVOKE_AREA",
            "INVOKE_SCREEN",
            "EXEC_DEFAULT",
            "EXEC_REGION_WIN",
            "EXEC_REGION_CHANNELS",
            "EXEC_REGION_PREVIEW",
            "EXEC_AREA",
            "EXEC_SCREEN",
        ] = 'EXEC_DEFAULT',
        *args : ..., # pyright:ignore[reportAny]
        **kwargs : ..., # pyright:ignore[reportAny]
    ) -> None:
        pass

def get_bpy_op(category_name : str, operator_name : str) -> BpyOperatorCallable:
    category : ModuleType | None = getattr(bpy.ops, category_name, None)
    assert category, f'Could not find bpy.ops.{category_name}'
    operator = getattr(category, operator_name, None)
    assert operator, f'Could not find bpy.ops.{category_name}.{operator_name}'
    return operator # pyright:ignore[reportAny]

def call_bpy_op(
    category_name : str, operator_name : str,
    /,
    execution_context : str = 'EXEC_DEFAULT',
    *args : ...,  # pyright:ignore[reportAny]
    **kwargs : ..., # pyright:ignore[reportAny]
) -> None:
    op = get_bpy_op(category_name, operator_name)
    op(execution_context, *args, **kwargs)

def bpy_ops_retopoflow(
    operator_name : str,
    /,
    execution_context : str = 'EXEC_DEFAULT',
    *args : ..., # pyright:ignore[reportAny]
    **kwargs : ..., # pyright:ignore[reportAny]
) -> None:
    call_bpy_op('retopoflow', operator_name, execution_context, *args, **kwargs)


# TimerCallback should actually take no args, but pyright complains
# about "Expected 0 positional arguments" for some reason...
# TimerCallback = Callable[[], float|None]
TimerCallback = Callable[..., float|None]

class BPY_Timers:
    @staticmethod
    def register(
        fn : TimerCallback | None = None,
        first_interval : float = 0.0,
        persistent : bool = False,
    ) -> TimerCallback | Callable[[TimerCallback], TimerCallback]:
        def decorator(fn : TimerCallback) -> TimerCallback:
            bpy.app.timers.register(
                fn,
                first_interval=first_interval,
                persistent=persistent,
            )
            return fn
        return decorator if fn is None else decorator(fn)

    # @staticmethod
    # def register(fn : Callable[[], float | None], *, first_interval : float = 0, persistent : bool = False):
    #     bpy.app.timers.register(fn, first_interval=first_interval, persistent=persistent)

    @staticmethod
    def is_registered(fn : Callable[[], float | None]) -> bool:
        return bpy.app.timers.is_registered(fn)

    @staticmethod
    def unregister(fn : Callable[[], float | None]):
        bpy.app.timers.unregister(fn)
