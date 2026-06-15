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
from typing import Protocol, Any
from types import ModuleType


class BpyOperatorCallable(Protocol):
    def __call__(
        self,
        /,
        km_context : str = 'EXEC_DEFAULT',
        *args : Any, **kwargs : Any # pyright:ignore[reportExplicitAny, reportAny]
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
    km_context : str = 'EXEC_DEFAULT',
    *args : Any, **kwargs : Any  # pyright:ignore[reportExplicitAny, reportAny]
) -> None:
    op = get_bpy_op(category_name, operator_name)
    op(km_context, *args, **kwargs)

def bpy_ops_retopoflow(
    operator_name : str,
    /,
    km_context : str = 'EXEC_DEFAULT',
    *args : Any, **kwargs : Any # pyright:ignore[reportExplicitAny, reportAny]
) -> None:
    call_bpy_op('retopoflow', operator_name, km_context, *args, **kwargs)
