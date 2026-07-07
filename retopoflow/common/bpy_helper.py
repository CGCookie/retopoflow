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
from bpy.types import Object
from typing import Protocol, Literal, cast, TypeAlias
from collections.abc import Callable
from types import ModuleType

BPY_OP_RETURN : TypeAlias = set[
    Literal[
        'RUNNING_MODAL',
        'CANCELLED',
        'FINISHED',
        'PASS_THROUGH'
    ]
]

# see : https://docs.blender.org/api/current/bpy.ops.html#execution-context
BPY_OP_EXECUTION_CONTEXT : TypeAlias = Literal[
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
]

BL_SPACE_TYPES : TypeAlias = Literal[
    "EMPTY",
    "VIEW_3D",
    "IMAGE_EDITOR",
    "NODE_EDITOR",
    "SEQUENCE_EDITOR",
    "CLIP_EDITOR",
    "DOPESHEET_EDITOR",
    "GRAPH_EDITOR",
    "NLA_EDITOR",
    "TEXT_EDITOR",
    "CONSOLE",
    "INFO",
    "TOPBAR",
    "STATUSBAR",
    "OUTLINER",
    "PROPERTIES",
    "FILE_BROWSER",
    "SPREADSHEET",
    "PREFERENCES",
]

BL_REGION_TYPES : TypeAlias = Literal[
    "WINDOW",
    "HEADER",
    "CHANNELS",
    "TEMPORARY",
    "UI",
    "TOOLS",
    "TOOL_PROPS",
    "ASSET_SHELF",
    "ASSET_SHELF_HEADER",
    "PREVIEW",
    "HUD",
    "NAVIGATION_BAR",
    "EXECUTE",
    "FOOTER",
    "TOOL_HEADER",
    "XR",
]

# see: https://docs.blender.org/api/current/bpy_types_enum_items/operator_type_flag_items.html#rna-enum-operator-type-flag-items
BL_OPTIONS : TypeAlias = set[Literal[
    'REGISTER',             # Display in the info window and support the redo toolbar panel
    'UNDO',                 # Push an undo event when the operator returns `FINISHED` (needed for operator redo, mandatory if the operator modifies Blender data).
    'UNDO_GROUPED',         # Push a single undo event for repeated instances of this operator.
    'BLOCKING',             # Block anything else from using the cursor.
    'MACRO',                # Use to check if an operator is a macro.
    'GRAB_CURSOR',          # Use so the operator grabs the mouse focus, enables wrapping when continuous grab is enabled.
    'GRAB_CURSOR_X',        # Grab, only warping the X axis.
    'GRAB_CURSOR_Y',        # Grab, only warping the Y axis.
    'DEPENDS_ON_CURSOR',    # The initial cursor location is used, when running from a menus or buttons the user is prompted to place the cursor before beginning the operation.
    'PRESET',               # Display a preset button with the operators settings.
    'INTERNAL',             # Removes the operator from search results
    'MODAL_PRIORITY',       # Handle events before other modal operators without this option. Use with caution, do not modify data that other modal operators assume is unchanged during their operation.
]]

class BpyOperatorCallable(Protocol):
    def __call__(
        self,
        /,
        execution_context : BPY_OP_EXECUTION_CONTEXT = 'EXEC_DEFAULT',
        *args : ..., # pyright:ignore[reportAny]
        **kwargs : ..., # pyright:ignore[reportAny]
    ) -> BPY_OP_RETURN:
        return set()

def get_bpy_op(category_name : str, operator_name : str) -> BpyOperatorCallable:
    category : ModuleType | None = getattr(bpy.ops, category_name, None)
    assert category, f'Could not find bpy.ops.{category_name}'
    operator = getattr(category, operator_name, None)
    assert operator, f'Could not find bpy.ops.{category_name}.{operator_name}'
    return operator # pyright:ignore[reportAny]

def call_bpy_op(
    category_name : str, operator_name : str,
    /,
    execution_context : BPY_OP_EXECUTION_CONTEXT = 'EXEC_DEFAULT',
    *args : ...,  # pyright:ignore[reportAny]
    **kwargs : ..., # pyright:ignore[reportAny]
) -> BPY_OP_RETURN:
    op = get_bpy_op(category_name, operator_name)
    return op(execution_context, *args, **kwargs)

def bpy_ops_retopoflow(
    operator_name : str,
    /,
    execution_context : BPY_OP_EXECUTION_CONTEXT = 'EXEC_DEFAULT',
    *args : ..., # pyright:ignore[reportAny]
    **kwargs : ..., # pyright:ignore[reportAny]
) -> BPY_OP_RETURN:
    return call_bpy_op('retopoflow', operator_name, execution_context, *args, **kwargs)


# TimerCallback should actually take no args, but pyright complains
# about "Expected 0 positional arguments" for some reason...
# TimerCallback = Callable[[], float|None]
TimerCallback : TypeAlias = Callable[..., float|None]

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


class LibraryData:
    """
    Helper "type" for the generator returned by bpy.data.libraries.load().
    Note...
    - When _inside_ the generator, the types of following attributes are lists of strings.
      This is similar to, but different from, bpy.data.
    - Once _outside_, though, the types change to lists of objects.
      This is much closer to bpy.data, but still different from.
    """

    objects : list[str | Object] = []


def bpy_data_libraries_load_object(
    blend_path : str,
    object_name : str,
    *,
    link : bool = False,
    pack : bool = False,
    relative : bool = False,
    set_fake : bool = False,
    recursive : bool = False,
    reuse_local_id : bool = False,
    assets_only : bool = False,
    clear_asset_data : bool = False,
    create_liboverrides : bool = False,
    reuse_liboverrides : bool = False,
    create_liboverrides_runtime : bool = False,
) -> Object | None:
    '''
    Wrapper function for bpy.data.libraries.load() that better handles type hinting.
    see: https://docs.blender.org/api/current/bpy.types.BlendDataLibraries.html#bpy.types.BlendDataLibraries.load
    '''

    with bpy.data.libraries.load(
        blend_path,
        link=link,
        pack=pack,
        relative=relative,
        set_fake=set_fake,
        recursive=recursive,
        reuse_local_id=reuse_local_id,
        assets_only=assets_only,
        clear_asset_data=clear_asset_data,
        create_liboverrides=create_liboverrides,
        reuse_liboverrides=reuse_liboverrides,
        create_liboverrides_runtime=create_liboverrides_runtime,
    ) as (data_from, data_to): # pyright: ignore[reportUnknownVariableType]
        data_from = cast(LibraryData, data_from)
        data_to = cast(LibraryData, data_to)

        if object_name not in data_from.objects:
            return None

        data_to.objects = [ object_name ]

    return cast(Object, data_to.objects[0]) # the type of data_to changes outside load() generator
