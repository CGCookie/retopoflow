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

from __future__ import annotations
from typing import Self, ClassVar, Protocol, Any, cast, ParamSpec, TypeVar
from collections.abc import Sequence, Callable
from inspect import signature

import bpy
from bpy.types import Context, Event, Area, Window, Operator, KeyMapItem, WindowManager, Timer, SpaceView3D, bpy_struct, Property
from bpy.props import EnumProperty, StringProperty, IntProperty, FloatProperty

from ..rfglobals import RFGlobals
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import Debugger
from ...addon_common.common.useractions import event_match_blenderop
from ...addon_common.terminal import term_printer


dev_env = 'vscode_development' in __file__

def poll_retopoflow(context : Context) -> bool:
    if not context.edit_object: return False
    if context.edit_object.type != 'MESH': return False
    return True


class RFRegisterClass:
    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass

    _subclasses : list[type[RFRegisterClass]] = []

    def __init_subclass__(cls, **kwargs : Any): # pyright: ignore[reportExplicitAny, reportAny]
        RFRegisterClass._subclasses.append(cls)
        super().__init_subclass__(**kwargs)

    @staticmethod
    def get_all_classes() -> list[type[RFRegisterClass]]:
        return RFRegisterClass._subclasses
        # return RFRegisterClass.__subclasses__()  # this only works if the subclass is still in scope!!!!!
    @staticmethod
    def register_all():
        for op in RFRegisterClass.get_all_classes():
            bpy.utils.register_class(op) # pyright: ignore[reportArgumentType]
            op.register()
        print(f'RF registered {len(RFRegisterClass.get_all_classes())} RFRegisterClasses')
    @staticmethod
    def unregister_all():
        for op in reversed(RFRegisterClass.get_all_classes()):
            op.unregister()
            bpy.utils.unregister_class(op) # pyright: ignore[reportArgumentType]


RFKeyMap = tuple[
    str,
    dict[str, str | int | float | bool],
    dict[str, str | tuple[str,...] | Callable[[Context], bool]] | None,
]
RFKeyMaps = list[RFKeyMap]
BLKeyMaps = tuple[RFKeyMap, ...]

class RFOperator_Base(Operator):
    _subclasses : list[type[RFOperator_Base]] = []
    # bl_idname : ClassVar[str]
    rf_idname : ClassVar[str]
    rf_keymaps : RFKeyMaps = []

    def __init_subclass__(cls, *args : ..., **kwargs : dict[..., ...]): # pyright: ignore[reportAny]
        if not hasattr(cls, 'bl_idname'):
            # RFOperator and RFOperator_Execute should not go on _subclasses list.
            # they will not have bl_idname specified, but all subclasses should, so
            # we will use that to determine whether we skip registering that subclass.
            return

        cls.rf_idname = cls.bl_idname
        RFOperator_Base._subclasses.append(cls)
        super().__init_subclass__(*args, **kwargs)

    @staticmethod
    def get_all_RFOperators() -> list[type[RFOperator_Base]]:
        return RFOperator_Base._subclasses
        # return RFOperator.__subclasses__()  # this only works if the subclass is still in scope!!!!!

    @staticmethod
    def register_all():
        for op in RFOperator_Base.get_all_RFOperators():
            bpy.utils.register_class(op)
            op.register()
        print(f'RF registered {len(RFOperator_Base.get_all_RFOperators())} RFOperators')
    @staticmethod
    def unregister_all():
        exceptions : list[tuple[str, str, Exception]] = []
        for op in reversed(RFOperator_Base.get_all_RFOperators()):
            try:
                op.unregister()
            except Exception as e:
                exceptions.append((op.rf_idname, 'op.unregister', e))
            try:
                bpy.utils.unregister_class(op)
            except Exception as e:
                exceptions.append((op.rf_idname, 'bpy.utils.unregister_class', e))
        if not exceptions: return

        print()
        term_printer.boxed(
            *[ f'{rf_idname}, {action}: {e}\n' for (rf_idname, action, e) in exceptions ],
            title='Warning: caught exceptions while trying to unregister RFOperators'
        )
        print()

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass




class RFOperator_KeymapContext:
    def update_km_context(self, _context : Context):
        # technically, self is a bpy_struct type that "wraps" RFOperator_KeymapContext

        RFCore = RFGlobals.RFCore_None
        if not RFCore: return

        if self.km_context == 'OVERRIDE':
            # NOTE: 'km_status_override' is set by caller ('set_statusbar_override')
            # NOTE: 'km_context' is not reset as we need is as a fallback when we exit the override
            pass
        else:
            # print(f'RFOperator_KeymapContext._update_km_context {RFCore.km_context=} -> {km_context=}')
            RFCore.km_status_override = None
            RFCore.km_context = self.km_context if self.km_context else None

    km_context: StringProperty( # pyright: ignore[reportUninitializedInstanceVariable]
        name='Keymap Context',
        description='Context for the tool keymap',
        # cast update_km_context so type hinting matches (looks like blender abuses type system)
        update=cast(Callable[[bpy_struct, Context], None], update_km_context),
    )

    def set_statusbar_override(self, status: str | Sequence[str] | None):
        RFCore = RFGlobals.RFCore_None
        if not RFCore: return

        if status is None:
            # print(f'RFOperator_KeymapContext:: reset_override {RFOperator.RFCore.km_context=}')
            self.km_context = RFCore.km_context if RFCore.km_context is not None else ''
            return
        # print(f'RFOperator_KeymapContext:: set_statusbar_override. {status=}')
        RFCore.km_status_override = status
        self.km_context = 'OVERRIDE'  # IMPORTANT: updating a property triggers statusbar update!




class RFAssetShelf(bpy.types.AssetShelf):
    bl_space_type = 'VIEW_3D'
    asset_library_reference = 'CUSTOM'

    _subclasses = []
    def __init_subclass__(cls, **kwargs):
        RFAssetShelf._subclasses.append(cls)
        cls.rf_idname = cls.bl_idname
        super().__init_subclass__(**kwargs)
    @staticmethod
    def get_all_RFOperators():
        return RFAssetShelf._subclasses
        # return RFOperator.__subclasses__()  # this only works if the subclass is still in scope!!!!!
    @staticmethod
    def register_all():
        for op in RFAssetShelf.get_all_RFOperators():
            bpy.utils.register_class(op)
            op.register()
        print(f'RF registered {len(RFAssetShelf.get_all_RFOperators())} RFAssetShelves')
    @staticmethod
    def unregister_all():
        for op in reversed(RFAssetShelf.get_all_RFOperators()):
            op.unregister()
            bpy.utils.unregister_class(op)

    @classmethod
    def poll(cls, context : Context) -> bool:
        RFCore = RFGlobals.RFCore_None
        # make sure RFCore is running
        if not RFCore or not RFCore.is_running: return False

        if not context.edit_object: return False
        if context.edit_object.type != 'MESH': return False

        # make sure RFOperator has only one running instance!
        if getattr(cls, '_is_running', False): return False

        if not cls.can_start(context):
            # print(f'{cls}.poll: {cls.can_start(context)=}')
            return False

        return True

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass
    @classmethod
    def can_start(cls, _context : Context) -> bool: return True


class RFOperator_Execute(RFOperator_Base, RFOperator_KeymapContext, bpy.types.Operator):
    @classmethod
    def poll(cls, context : Context) -> bool:
        return poll_retopoflow(context)



class TickledCallback(Protocol):
    def __call__(self): pass

class RFOperator(RFOperator_Base, RFOperator_KeymapContext, Operator):
    active_operators : list[Self] = []

    tickled : TickledCallback | None = None

    _is_running : ClassVar[bool]

    working_area : Area | None
    working_window : Window | None
    last_op : Operator | None
    _stop : bool
    fullscreen_keymaps : set[KeyMapItem]
    _draw_postpixel_overlay : object | None


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        type(self)._is_running = False
        self.working_area = None
        self.working_window = None
        self.last_op = None
        self._stop = False
        self.fullscreen_keymaps = set()
        self._draw_postpixel_overlay = None

    @staticmethod
    def handle_tickle():
        tickled = RFOperator.tickled
        if not tickled: return
        tickled()

    @staticmethod
    def active_operator() -> RFOperator | None:
        return RFOperator.active_operators[-1] if RFOperator.active_operators else None
    @classmethod
    def is_active(cls) -> bool:
        return type(RFOperator.active_operator()) is cls
    @staticmethod
    def is_active_static(op_cls : type) -> bool:
        return type(RFOperator.active_operator()) is op_cls

    @classmethod
    def is_running(cls) -> bool:
        return any(cls is type(op) for op in RFOperator.active_operators)


    @classmethod
    def poll(cls, context : Context) -> bool:
        RFCore = RFGlobals.RFCore_None
        # make sure RFCore is running
        if not RFCore or not RFCore.is_running: return False

        if not context.edit_object: return False
        if context.edit_object.type != 'MESH': return False

        # make sure RFOperator has only one running instance!
        if getattr(cls, '_is_running', False): return False

        if not cls.can_start(context):
            # print(f'{cls}.poll: {cls.can_start(context)=}')
            return False

        return True

    def invoke(self, context : Context, event : Event) -> set[str]:
        if not self.can_init(context, event): return {'CANCELLED'}
        type(self)._is_running = True
        RFOperator.active_operators.append(self)
        _ = context.window_manager.modal_handler_add(self) # pyright: ignore[reportAny]
        self.last_op = None
        self.working_area = context.area # pyright: ignore[reportAny]
        self.working_window = context.window # pyright: ignore[reportAny]
        self._stop = False

        keymap_items = context.window_manager.keyconfigs.user.keymaps['Screen'].keymap_items # pyright: ignore[reportAny]
        self.fullscreen_keymaps = {
            km
            for km in keymap_items # pyright: ignore[reportAny]
            if km.idname == 'screen.screen_full_area' # pyright: ignore[reportAny]
        }

        if self.draw_postpixel_overlay.__func__ != RFOperator.draw_postpixel_overlay:
            self._draw_postpixel_overlay = SpaceView3D.draw_handler_add(
                self.draw_postpixel_overlay, (), 'WINDOW', 'POST_PIXEL'
            )
        else:
            self._draw_postpixel_overlay = None

        RFGlobals.InvalidationManager.prevent_invalidation()

        try:
            self.init(context, event)
        except Exception as e:
            print(f'Caught Exception in operator init: {e}')
            _ = Debugger.print_exception()
            if self in RFOperator.active_operators: RFOperator.active_operators.remove(self)
            type(self)._is_running = False
            return {'CANCELLED'}
        context.area.tag_redraw() # pyright: ignore[reportAny]
        return {'RUNNING_MODAL'}

    def stop(self):
        print(f'stopping {self=} {self._stop=}')

        if self._stop: return
        self._stop = True

        brush = getattr(self, 'rf_brush', None)
        if brush:
            print(f'  stopping brush {brush=}')
            try:
                brush.stop()
            except ReferenceError as re:
                print(f'Caught ReferenceError while trying to stop operator')
                print(f'  {re}')

        if self._draw_postpixel_overlay:
            SpaceView3D.draw_handler_remove(self._draw_postpixel_overlay, 'WINDOW')
            self._draw_postpixel_overlay = None
        bpy.context.workspace.status_text_set(None)

        if self in RFOperator.active_operators: RFOperator.active_operators.remove(self)
        type(self)._is_running = False

    def modal(self, context : Context, event : Event) -> set[str]:
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_running or self._stop:
            ret = {'CANCELLED'}
        else:
            RFCore.is_controlling = True

            # if we were tickled by another RF operator (ex: Translate finished when using PolyPen),
            # handle tickle event (which will remove tickle timer / handler)
            RFOperator.handle_tickle()

            RFCore.event_mouse = (event.mouse_x, event.mouse_y)

            last_op = ops[-1] if (ops := context.window_manager.operators) else None
            if self.last_op != last_op:
                self.reset()
                self.last_op = last_op
                context.area.tag_redraw()

            if not context.area:
                # this can happen if an area is fullscreened :(
                ret = {'CANCELLED'}
            elif context.mode != 'EDIT_MESH':
                # this can happen if undoing back into OBJECT mode
                ret = {'CANCELLED'}
            else:
                try:
                    ret = self.update(context, event)
                except KeyboardInterrupt as e:
                    print(f'RFOperator.modal: Caught KeyboardInterrupt Exception in self.update: {e}')
                    ret = {'CANCELLED'}
                except Exception as e:
                    print(f'RFOperator.modal: Unhandled Exception Caught in self.update: {e}')
                    _ = Debugger.print_exception()
                    ret = {'CANCELLED'}

        if ret & {'FINISHED', 'CANCELLED'}:
            try:
                self.finish(context)
            except Exception as e:
                print(f'RFOperator.modal: Unhandled Exception Caught in self.finish: {e}')
                Debugger.print_exception()
                ret = {'CANCELLED'}
            if self._draw_postpixel_overlay:
                wm, space = bpy.types.WindowManager, bpy.types.SpaceView3D
                space.draw_handler_remove(self._draw_postpixel_overlay, 'WINDOW')
                self._draw_postpixel_overlay = None
            if RFOperator.active_operator() != self:
                # print(f'RFOperator: currently finishing operator is not top??')
                # print(self)
                # print(RFOperator.active_operators)
                pass
            if self in RFOperator.active_operators: RFOperator.active_operators.remove(self)
            for area in context.screen.areas: area.tag_redraw()
            Cursors.restore()
            if RFOperator.active_operators:
                # other RF operators on stack, so tickle them so they can see the changes
                RFOperator.tickle(context)
            RFGlobals.InvalidationManager.resume_invalidation()
            type(self)._is_running = False
            return ret

        if 'PASS_THROUGH' in ret:
            # check if passing event through might trigger something incompatible with RF
            if event_match_blenderop(event, 'Screen | screen.screen_full_area'):
                # attempting to full screen the area!
                print('ATTEMPTING TO FULLSCREEN')
                # this causes some machines to crash
                # the RFOperator_MaximizeWatcher will catch, block, and message about this
                # See issue #1615
                return {'PASS_THROUGH'}

                # ctx = { k: getattr(context,k) for k in ['window', 'area', 'region', 'screen'] }
                # props = get_kmi_properties(kmi)
                # def tickle():
                #     RFOperator.tickle(bpy.context)
                # def go_full_now():
                #     with bpy.context.temp_override(**ctx):
                #         bpy.ops.screen.screen_full_area(**props)
                # self.stop()
                # # RFCore.switch_to_tool('builtin.move')
                # # RFCore.quick_switch_with_call(tickle, go_full_now, self.rf_idname, delay=0.125)
                # RFCore.quick_switch_with_call(go_full_now, self.rf_idname, delay=0.125)
                # return {'FINISHED'}

        return ret

    @staticmethod
    def tickle(context : Context):
        # tickle RF operator by temporarily setting a timer that will self-remove (causes modal / update to be called)
        # sadly, cannot use context.window.event_simulate, because this requires `--enable-event-simulate` Blender commandline argument
        # ex: context.window.event_simulate('TIMER', 'NOTHING')
        # bpy.app.timer also does not work, as it doesn't trigger an event
        RFOperator.handle_tickle()
        wm : WindowManager = context.window_manager # pyright: ignore[reportAny]
        win : Window = context.window # pyright: ignore[reportAny]
        timer : Timer = wm.event_timer_add(0.01, window=win)
        def tickled():
            RFCore = RFGlobals.RFCore_None
            if not RFCore: return
            try:
                wm.event_timer_remove(timer)
                RFOperator.tickled = None
                RFCore.tag_redraw_areas()
            except Exception as e:
                print('Ignoring uncaught Exception while trying to remove event timer')
                print(f'  Exception: {e}')
        RFOperator.tickled = tickled

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass

    @classmethod
    def can_start(cls, _context : Context) -> bool: return True
    def can_init(self, _context : Context, _event : Event) -> bool: return True
    def init(self, _context : Context, _event : Event): pass
    def reset(self): pass
    def update(self, _context : Context, _event : Event) -> set[str]: return {'FINISHED'}
    def finish(self, _context : Context): pass
    def draw_postpixel_overlay(self, _context : Context): pass
    def draw_preview(self, _context : Context): pass
    def draw_postview(self, _context : Context): pass
    def draw_postpixel(self, _context : Context): pass
    @classmethod
    def depsgraph_update(cls): pass


class RF_AssetShelfOperator:
    asset_library_type: EnumProperty( # pyright: ignore[reportUninitializedInstanceVariable]
        name="Asset Library Type",
        description="Asset Library Type",
        items=[
            # NOTE: BLENDER DOCS DO NOT DESCRIBE THE VALUES! :(
            # https://github.com/blender/blender/blob/main/source/blender/makesdna/DNA_asset_types.h#L27
            ("LOCAL", "Local", "Local", "", 1),
            ("ALL", "All", "All", "", 2),
            ("ESSENTIALS", "Essentials", "Essentials", "", 3),
            ("CUSTOM", "Custom", "Custom", "", 100),
        ],
    )
    asset_library_identifier: StringProperty() # pyright: ignore[reportUninitializedInstanceVariable]
    relative_asset_identifier: StringProperty() # pyright: ignore[reportUninitializedInstanceVariable]


def idname_to_retopoflow_bl_idname(idname : str) -> str:
    idname = idname.lower().removeprefix('retopoflow.')
    # idname = idname.replace(' ', '_')
    return f'retopoflow.{idname}'

# Blender 4.2 uses Python 3.11, so we cannot use modern (Python 3.12+) generic types with square brackets
Param = ParamSpec('Param')
RetType = TypeVar('RetType')

def create_operator(
    name   : str,
    idname : str,
    label  : str,
    *,
    description : str | None = None,
    fn_poll     : Callable[[Context], bool] | None = None,
    fn_invoke   : Callable[[Operator, Context, Event], set[str] | None] | Callable[[Context, Event], set[str] | None] | None = None,
    fn_exec     : Callable[[Operator, Context],        set[str] | None] | Callable[[Context],        set[str] | None] | None = None,
    fn_modal    : Callable[[Operator, Context, Event], set[str] | None] | Callable[[Context, Event], set[str] | None] | None = None,
    options     : set[str] | None = None,
    asset_shelf : bool = False,
) -> RFOperator:

    if fn_invoke:
        sig = signature(fn_invoke)
        params = list(sig.parameters.values())
        assert params, 'Expected invoke function to have 2 or 3 arguments, but saw none'
        if params[0].name != 'self':
            fn_invoke_orig : Callable[[Context, Event], set[str] | None] = cast(Callable[[Context, Event], set[str] | None], fn_invoke)
            def invoke_wrap(_self : Operator, context : Context, event : Event) -> set[str] | None:
                return fn_invoke_orig(context, event)
            fn_invoke_self = invoke_wrap
        else:
            fn_invoke_self = cast(Callable[[Operator, Context, Event], set[str] | None], fn_invoke)
    else:
        def invoke_default(self : Operator, context : Context, _event: Event) -> set[str] | None:
            return self.execute(context)
        fn_invoke_self = invoke_default

    if fn_exec:
        sig = signature(fn_exec)
        params = list(sig.parameters.values())
        assert params, 'Expected exec function to have 1 or 2 arguments, but saw none'
        if params[0].name != 'self':
            fn_exec_orig : Callable[[Context], set[str] | None] = cast(Callable[[Context], set[str] | None], fn_exec)
            def exec_wrap(_self : Operator, context : Context) -> set[str] | None:
                return fn_exec_orig(context)
            fn_exec_self = exec_wrap
        else:
            fn_exec_self = cast(Callable[[Operator, Context], set[str] | None], fn_exec)
    else:
        def exec_default(_self : Operator, _context: Context) -> set[str] | None:
            return {'CANCELLED'}
        fn_exec_self = exec_default

    if fn_modal:
        sig = signature(fn_modal)
        params = list(sig.parameters.values())
        assert params, 'Expected modal function to have 2 or 3 arguments, but saw none'
        if params[0].name != 'self':
            fn_modal_orig : Callable[[Context, Event], set[str] | None] = cast(Callable[[Context, Event], set[str] | None], fn_modal)
            def modal_wrap(_self : Operator, context : Context, event : Event) -> set[str] | None:
                return fn_modal_orig(context, event)
            fn_modal_self = modal_wrap
        else:
            fn_modal_self = cast(Callable[[Operator, Context, Event], set[str] | None], fn_modal)
    else:
        def modal_default(_self : Operator, _context : Context, _event : Event) -> set[str] | None:
            return {'FINISHED'}
        fn_modal_self = modal_default

    class RFOp:
        bl_idname      : str = idname_to_retopoflow_bl_idname(idname)
        bl_label       : str = label
        bl_description : str = description if description is not None else label
        bl_space_type  : str = "VIEW_3D"
        bl_region_type : str = "TOOLS"
        bl_options : set[str] = options or set()

        @classmethod
        def poll(cls, context : Context) -> bool:
            return fn_poll(context) if fn_poll else True

        def invoke(self : Operator, context : Context, event : Event) -> set[str]: # pyright: ignore[reportGeneralTypeIssues]
            ret = fn_invoke_self(self, context, event)
            return ret if ret is not None else {'FINISHED'}

        def execute(self : Operator, context : Context) -> set[str]: # pyright: ignore[reportGeneralTypeIssues]
            ret = fn_exec_self(self, context)
            return ret if ret is not None else {'FINISHED'}

        def modal(self : Operator, context : Context, event : Event) -> set[str]: # pyright: ignore[reportGeneralTypeIssues]
            ret =  fn_modal_self(self, context, event)
            return ret if ret is not None else {'FINISHED'}

    opname = f'RETOPOFLOW_OT_{name}'

    return type(opname, (RFOp, RF_AssetShelfOperator, RFOperator), {}) # pyright: ignore[reportReturnType]


def invoke_operator(
    name : str,
    label : str,
    **kwargs : Any # pyright: ignore[reportExplicitAny, reportAny]
) -> Callable[[Callable[Param, RetType]], Callable[Param, RetType]]:
    idname = name.lower().removeprefix('retpoflow.')
    def get(fn : Callable[Param, RetType]) -> Callable[Param,RetType]:
        _op = create_operator(
            name,
            idname,
            label,
            fn_invoke=fn, # pyright: ignore[reportArgumentType]
            **kwargs # pyright: ignore[reportAny]
        )
        # add bl_idname attribute to function
        fn.bl_idname = idname_to_retopoflow_bl_idname(idname) # pyright: ignore[reportFunctionMemberAccess]
        return fn
    return get

def execute_operator(
    name : str,
    label : str,
    **kwargs : Any # pyright: ignore[reportExplicitAny, reportAny]
) -> Callable[[Callable[Param, RetType]], Callable[Param, RetType]]:
    idname = name.lower().removeprefix('retopoflow.')
    def get(fn : Callable[Param, RetType]) -> Callable[Param, RetType]:
        _op = create_operator(
            name,
            idname,
            label,
            fn_exec=fn, # pyright: ignore[reportArgumentType]
            **kwargs # pyright: ignore[reportAny]
        )
        # add bl_idname attribute to function
        fn.bl_idname = idname_to_retopoflow_bl_idname(idname) # pyright: ignore[reportFunctionMemberAccess]
        return fn
    return get

def modal_operator(
    name : str,
    label : str,
    **kwargs : Any # pyright: ignore[reportExplicitAny, reportAny]
) -> Callable[[Callable[Param,RetType]], Callable[Param,RetType]]:
    idname = name.lower().removeprefix('retopoflow.')
    def fn_execute(self : Operator, context : Context) -> set[str]:
        wm : WindowManager = context.window_manager # pyright: ignore[reportAny]
        _ = wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def get(fn : Callable[Param,RetType]) -> Callable[Param,RetType]:
        _op = create_operator(
            name,
            idname,
            label,
            fn_exec=fn_execute,
            fn_modal=fn, # pyright: ignore[reportArgumentType]
            **kwargs # pyright: ignore[reportAny]
        )
        # add bl_idname attribute to function
        fn.bl_idname = idname_to_retopoflow_bl_idname(idname) # pyright: ignore[reportFunctionMemberAccess]
        return fn
    return get

PropTypes : dict[str | Property, Property] = { # pyright: ignore[reportAssignmentType]
    'int':   IntProperty,
    'float': FloatProperty,
    'enum':  EnumProperty,
    IntProperty:   IntProperty,
    FloatProperty: FloatProperty,
    EnumProperty:  EnumProperty,
}

def wrap_property(
    cls : type,
    propname : str,
    proptype : str | Property,
    **kwargs: Any # pyright: ignore[reportExplicitAny, reportAny]
) -> Property:
    def getter(_ : Any) -> Any: # pyright: ignore[reportExplicitAny, reportAny]
        return getattr(cls, propname) # pyright: ignore[reportAny]

    def setter(_ : Any, v : Any): # pyright: ignore[reportExplicitAny, reportAny]
        setattr(cls, propname, v)

    assert proptype in PropTypes, f'Unhandled property type {proptype} for {cls}.{propname}'
    Prop = PropTypes[proptype]

    return Prop(get=getter, set=setter, **kwargs) # pyright: ignore[reportCallIssue, reportUnknownVariableType]


def chain_rf_keymaps(*classes : type[RFOperator_Base], extra : RFKeyMaps | None = None) -> BLKeyMaps:
    keymaps = [
        keymap for cls in classes for keymap in cls.rf_keymaps
    ]

    if extra:
        keymaps.extend(extra)

    return tuple(keymaps)
