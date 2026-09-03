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
from functools import singledispatch
from typing import Self, ClassVar, Protocol, Any, cast, Literal, ParamSpec, TypeVar, TypeAlias, TYPE_CHECKING
from collections.abc import Sequence, Callable, Iterable
from inspect import signature

if TYPE_CHECKING: from ..rftool_statusbar import SharedStatusbarKeymap # Only used for type definition, avoids circular import

import bpy
from bpy.types import (
    Context, Event,
    Area, Window, WindowManager, SpaceView3D,
    Operator,
    KeyMapItem,
    Timer,
    bpy_struct,
    Property,
    AssetShelf,
)
from bpy.props import EnumProperty, StringProperty, IntProperty, FloatProperty

from ..rfglobals import RFGlobals
from ..rfoverlay_base import RFOverlay_Base
from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import Debugger
from ...addon_common.common.useractions import event_match_blenderop
from ...addon_common.terminal import term_printer


dev_env = 'vscode_development' in __file__

def poll_retopoflow(context : Context) -> bool:
    if not context.edit_object:
        return False
    if context.edit_object.type != 'MESH':
        return False
    return True


def rf_is_running() -> bool:
    ''' True while an RF tool is active.  Operators that also run outside RF branch on this. '''
    RFCore = RFGlobals.RFCore_None
    return bool(RFCore and RFCore.is_running)


def hotkey_owns_context(context : Context, tool_context_attr : str) -> bool:
    ''' Whether a standalone hotkey belongs here, decided by the user's preferences '''
    if context.mode != 'EDIT_MESH': return False
    from ..preferences import RF_Prefs   # deferred: preferences.py imports from this module
    prefs = RF_Prefs.get_prefs(context)
    if getattr(prefs, tool_context_attr) == 'ANY_TOOL': return True
    tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
    return tool is not None and tool.idname.split('.')[0] == 'retopoflow'


class RFRegisterClass:
    _subclasses : ClassVar[list[type[RFRegisterClass]]] = []
    _registered_classes : ClassVar[set[type[RFRegisterClass]]] = set()

    def __init_subclass__(cls, *args : ..., **kwargs : ...): # pyright: ignore[reportAny]
        RFRegisterClass._subclasses.append(cls)
        super().__init_subclass__(*args, **kwargs)

    @staticmethod
    def get_all_classes() -> list[type[RFRegisterClass]]:
        return RFRegisterClass._subclasses
        # return RFRegisterClass.__subclasses__()  # this only works if the subclass is still in scope!!!!!

    @classmethod
    def is_registered(cls) -> bool:
        return cls in RFRegisterClass._registered_classes

    @staticmethod
    def register_all():
        for op in RFRegisterClass._subclasses:
            bpy.utils.register_class(op) # pyright: ignore[reportArgumentType]
            RFRegisterClass._registered_classes.add(op)
            op.register()
        print(f'RF registered {len(RFRegisterClass.get_all_classes())} RFRegisterClasses')

    @staticmethod
    def unregister_all():
        for op in reversed(RFRegisterClass.get_all_classes()):
            op.unregister()
            RFRegisterClass._registered_classes.discard(op)
            bpy.utils.unregister_class(op) # pyright: ignore[reportArgumentType]

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass


RFKeyMap : TypeAlias = tuple[
    str,
    dict[str, str | int | float | bool],
    dict[str, str | tuple[str,...] | Callable[[Context], bool] | Callable[[Context], str]] | None,
]
RFKeyMaps : TypeAlias = list[RFKeyMap]
BLKeyMaps : TypeAlias = tuple[RFKeyMap, ...]



DEBUG_PRINT = False

class RFOperator_Base(Operator):
    _subclasses : list[type[RFOperator_Base]] = []
    # bl_idname : ClassVar[str]
    rf_idname : ClassVar[str]
    rf_keymaps : RFKeyMaps = []

    def __init_subclass__(cls, *args : ..., **kwargs : ...): # pyright: ignore[reportAny]
        if not hasattr(cls, 'bl_idname'):
            # RFOperator and RFOperator_Execute should not go on _subclasses list.
            # they will not have bl_idname specified, but all subclasses should, so
            # we will use that to determine whether we skip registering that subclass.
            return

        cls.rf_idname = cls.bl_idname
        if DEBUG_PRINT:
            print('RFOperator_Base.__init_subclass__:')
            print(f'  - {cls.__name__=} {cls.__qualname__=}')
            print(f'  - {cls.__mro__=}')
            print(f'  - {cls.rf_idname=} {cls.bl_idname=}')
        RFOperator_Base._subclasses.append(cls)
        super().__init_subclass__(*args, **kwargs)

    @staticmethod
    def get_all_RFOperators() -> list[type[RFOperator_Base]]:
        return RFOperator_Base._subclasses
        # return RFOperator.__subclasses__()  # this only works if the subclass is still in scope!!!!!

    @staticmethod
    def register_all():
        if DEBUG_PRINT:
            print('RFOperator_Base.register_all:')
        for op in RFOperator_Base.get_all_RFOperators():
            if DEBUG_PRINT:
                print(f'  - {op.rf_idname=}, {op.bl_idname=}')
                print('    - bpy.utils.register_class(op)')
            try:
                bpy.utils.register_class(op)
            except Exception as e:
                assert False, f'caught Exception {e} while trying to register class'
            if DEBUG_PRINT:
                print('    - op.register()')
            op.register()
            if DEBUG_PRINT:
                print('    - done')
        print(f'RF registered {len(RFOperator_Base.get_all_RFOperators())} RFOperators')

    @staticmethod
    def unregister_all():
        exceptions : list[tuple[str, str, Exception]] = []
        if DEBUG_PRINT:
            print('RFOperator_Base.unregister_all:')
        for op in reversed(RFOperator_Base.get_all_RFOperators()):
            if DEBUG_PRINT:
                print(f'  - {op.rf_idname=}, {op.bl_idname=}')
            try:
                op.unregister()
            except Exception as e:
                exceptions.append((op.rf_idname, 'op.unregister', e))
            try:
                bpy.utils.unregister_class(op)
            except Exception as e:
                exceptions.append((op.rf_idname, 'bpy.utils.unregister_class', e))
        if not exceptions:
            return

        # Exceptions were thrown and caught!
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





class RFOperator_KeymapContext_Helper:
    @staticmethod
    def update_km_context(props : bpy_struct, _context : Context):
        # technically, self is a bpy_struct type that "wraps" RFOperator_KeymapContext
        RFCore = RFGlobals.RFCore_None
        if not RFCore:
            return
        if not hasattr(props, 'km_context'):
            return

        km_context = str(getattr(props, 'km_context')) # pyright: ignore[reportAny]

        if km_context == 'OVERRIDE':
            # NOTE: 'km_status_override' is set by caller ('set_statusbar_override')
            # NOTE: 'km_context' is not reset as we need is as a fallback when we exit the override
            pass
        else:
            # print(f'RFOperator_KeymapContext._update_km_context {RFCore.km_context=} -> {km_context=}')
            RFCore.km_status_override = None
            RFCore.km_context = km_context if km_context else None

class RFOperator_KeymapContext(RFOperator_KeymapContext_Helper, RFOperator_Base):
    km_context: StringProperty( # pyright: ignore[reportUninitializedInstanceVariable]
        name='Keymap Context',
        description='Context for the tool keymap',
        update=RFOperator_KeymapContext_Helper.update_km_context,
    )

    def set_statusbar_override(
        self,
        status: str | SharedStatusbarKeymap | Sequence[str | SharedStatusbarKeymap] | None,
    ):
        RFCore = RFGlobals.RFCore_None
        if not RFCore:
            return

        if status is None:
            # print(f'RFOperator_KeymapContext:: reset_override {RFOperator.RFCore.km_context=}')
            self.km_context = RFCore.km_context if RFCore.km_context is not None else ''
            return

        # print(f'RFOperator_KeymapContext:: set_statusbar_override. {status=}')
        RFCore.km_status_override = status
        self.km_context = 'OVERRIDE'  # IMPORTANT: updating a property triggers statusbar update!



class RFAssetShelf(AssetShelf):
    bl_space_type : Literal[
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
    ] = 'VIEW_3D'
    asset_library_reference : Literal["ALL", "LOCAL", "ESSENTIALS", "CUSTOM"] = 'CUSTOM'

    rf_idname : ClassVar[str]

    _subclasses : list[type[RFAssetShelf]] = []
    def __init_subclass__(cls, **kwargs : dict[str, ...]):
        RFAssetShelf._subclasses.append(cls)
        cls.rf_idname = cls.bl_idname
        super().__init_subclass__(**kwargs)

    @staticmethod
    def get_all_RFOperators() -> list[type[RFAssetShelf]]:
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
        if not RFCore or not RFCore.is_running:
            return False

        if not context.edit_object:
            return False

        if context.edit_object.type != 'MESH':
            return False

        # make sure RFOperator has only one running instance!
        if getattr(cls, '_is_running', False):
            return False

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



class RFOperator_Execute(RFOperator_KeymapContext):
    """
    This class is more decorative and descriptive than anything else.
    This class is far less built-up than the RFOperator class below.
    """

    @classmethod
    def poll(cls, context : Context) -> bool:
        return poll_retopoflow(context)

class RFOperator_Invoke(RFOperator_KeymapContext):
    """
    Operators here run via invoke(), inside or outside of RF, with modal specific protections.
    """

    rf_was_controlling : bool | None = None
    rf_prevented_invalidation : bool = False   # guarantees prevent/resume stay paired

    def __init_subclass__(cls, *args : ..., **kwargs : ...): # pyright: ignore[reportAny]
        super().__init_subclass__(*args, **kwargs)

        # wrap invoke / modal / cancel so the guards follow the operator's own return values:
        # engage on RUNNING_MODAL, release when modal ends, cancel runs, or modal raises.
        # NOTE: bpy.utils.register_class checks the exact parameter count of invoke / modal /
        # cancel (defaults included), so every wrapper must mirror the original's signature.

        WRAPPED = '_rf_control_wrapped'

        def fresh(name : str):
            # only functions this subclass defines itself; anything inherited from another
            # RFOperator_Invoke subclass was wrapped when that subclass was created
            fn = cls.__dict__.get(name)
            return None if fn is None or getattr(fn, WRAPPED, False) else fn

        if fn_invoke := fresh('invoke'):
            def invoke(self, context, event): # pyright: ignore[reportMissingParameterType]
                ret = fn_invoke(self, context, event)
                if ret and 'RUNNING_MODAL' in ret:
                    self.guard_modal()
                return ret
            setattr(invoke, WRAPPED, True)
            cls.invoke = invoke

        if fn_modal := fresh('modal'):
            def modal(self, context, event): # pyright: ignore[reportMissingParameterType]
                try:
                    ret = fn_modal(self, context, event)
                except Exception:
                    self.unguard_modal()
                    raise
                if ret and (ret & {'FINISHED', 'CANCELLED'}):
                    self.unguard_modal()
                return ret
            setattr(modal, WRAPPED, True)
            cls.modal = modal

        if fn_cancel := fresh('cancel'):
            def cancel(self, context): # pyright: ignore[reportMissingParameterType]
                try:
                    return fn_cancel(self, context)
                finally:
                    self.unguard_modal()
            setattr(cancel, WRAPPED, True)
            cls.cancel = cancel
        elif 'modal' in cls.__dict__ and not getattr(getattr(cls, 'cancel', None), WRAPPED, False):
            # a modal subclass with no cancel of its own must still not leak the guards when
            # Blender force-ends it (ex: the window closes)
            def cancel(self, context): # pyright: ignore[reportMissingParameterType]
                self.unguard_modal()
            setattr(cancel, WRAPPED, True)
            cls.cancel = cancel

    def guard_modal(self):
        ''' Everything that must hold while this operator sits on top as a modal. '''
        self.take_rf_control()
        self.prevent_invalidation()

    def unguard_modal(self):
        self.return_rf_control()
        self.resume_invalidation()

    def take_rf_control(self):
        # is_controlling means "RFCore is the top modal operator", which we now are.
        # RFCore notices lost control but that check is its own modal, frozen while we are on top.
        # Left set, RFCore keeps dispatching the underlying tool's draw callbacks with stale state;
        # if the mesh changed, a ReferenceError there makes RFCore.stop() tear down the whole session.
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_running: return
        self.rf_was_controlling = RFCore.is_controlling
        RFCore.is_controlling = False

    def return_rf_control(self):
        if self.rf_was_controlling is None: return  # never taken, nothing to put back
        RFCore = RFGlobals.RFCore_None
        if RFCore and RFCore.is_running:
            RFCore.is_controlling = self.rf_was_controlling
        self.rf_was_controlling = None

    def prevent_invalidation(self):
        # Guards the held bmesh against other add-ons' depsgraph handlers, not against RF
        InvalidationManager = RFGlobals.InvalidationManager_None
        if not InvalidationManager or self.rf_prevented_invalidation: return
        InvalidationManager.prevent_invalidation()
        self.rf_prevented_invalidation = True

    def resume_invalidation(self):
        if not self.rf_prevented_invalidation: return  # never prevented, nothing to resume
        self.rf_prevented_invalidation = False
        InvalidationManager = RFGlobals.InvalidationManager_None
        if InvalidationManager:
            InvalidationManager.resume_invalidation()

    @classmethod
    def poll(cls, context : Context) -> bool:
        return poll_retopoflow(context)



class TickledCallback(Protocol):
    def __call__(self): pass

class RFOperator(RFOperator_KeymapContext):
    active_operators : ClassVar[list[Self]] = []

    tickled : TickledCallback | None = None

    _is_running : ClassVar[bool] = False

    working_area : Area | None = None
    working_window : Window | None = None
    last_op : Operator | None = None
    _stop : bool = False
    _foreign_modal_ran : bool = False
    fullscreen_keymaps : list[KeyMapItem] = []
    _draw_postpixel_overlay : object | None = None

    had_init : bool = False
    prevented_invalidation : bool = False
    had_teardown : bool = False

    @staticmethod
    def handle_tickle():
        tickled = RFOperator.tickled
        if not tickled:
            return
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

    def operators_above(self) -> list[RFOperator]:
        ''' RF operators that started after this one and are still running. '''
        ops = RFOperator.active_operators
        if self not in ops: return []
        return ops[ops.index(self) + 1:]

    def is_waiting_on_operator(self) -> bool:
        ''' True while a RF operator that started above this one is still working.
        Used so an operator that wants to tear down can hold off until it is safe. '''
        # Overlays ignored because they are always running on top
        return any(not isinstance(op, RFOverlay_Base) for op in self.operators_above())


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

    def teardown(self, context : Context) -> bool:
        '''
        Single teardown for every way this operator can end:
            - modal() returning FINISHED or CANCELLED
            - stop() from RFCore
            - cancel() from Blender
            - invoke() failing

        Returns False only when self.finish() raised.
        '''
        if self.had_teardown: return True
        self.had_teardown = True

        ok = True
        if self.had_init:
            self.had_init = False
            try:
                self.finish(context)
            except Exception as e:
                print(f'RFOperator.teardown: Unhandled Exception Caught in self.finish: {e}')
                _ = Debugger.print_exception()
                ok = False

        if self._draw_postpixel_overlay:
            try:
                SpaceView3D.draw_handler_remove(self._draw_postpixel_overlay, 'WINDOW')
            except Exception as e:
                print(f'RFOperator.teardown: could not remove draw handler: {e}')
            self._draw_postpixel_overlay = None

        if self in RFOperator.active_operators:
            RFOperator.active_operators.remove(self)
        type(self)._is_running = False

        if self.prevented_invalidation:
            # Only resume if there was a matching prevent, otherwise the count goes negative
            self.prevented_invalidation = False
            RFGlobals.InvalidationManager.resume_invalidation()

        return ok

    def cancel(self, context : Context):
        ''' Blender calls this when it ends the modal operator itself. '''
        _ = self.teardown(context)

    def invoke(self, context : Context, event : Event) -> set[str]:
        if not self.can_init(context, event):
            return {'CANCELLED'}
        self.had_init = False
        self.prevented_invalidation = False
        self.had_teardown = False
        type(self)._is_running = True
        RFOperator.active_operators.append(self)
        # From here on, _is_running is set, and only teardown clears it.
        # Try / Except used so that we can still teardown if there is an issue,
        # otherwise poll() refuses to start it again for the rest of the session.
        try:
            if not context.window_manager.modal_handler_add(self):
                # Without a modal handler, modal() never runs, so nothing would clear _is_running
                _ = self.teardown(context)
                return {'CANCELLED'}
            self.last_op = None
            self.working_area = context.area
            self.working_window = context.window
            self._stop = False
            self._foreign_modal_ran = False

            user_keyconfigs = context.window_manager.keyconfigs.user
            if not user_keyconfigs:
                # bailing out after registering above. Otherwise the operator would stay
                # in active_operators with _is_running set, and poll() refuses to start it again
                _ = self.teardown(context)
                return {'CANCELLED'}
            keymap_items = user_keyconfigs.keymaps['Screen'].keymap_items
            self.fullscreen_keymaps = [
                km
                for km in keymap_items
                if km.idname == 'screen.screen_full_area'
            ]

            if self.draw_postpixel_overlay.__func__ != RFOperator.draw_postpixel_overlay:
                def draw_postpixel_overlay_safe():
                    # Don't touch tool state during or after outside modals that modify the bmesh
                    # until this operator's modal reset has rebuilt its state
                    RFCore = RFGlobals.RFCore_None
                    if RFCore and RFCore.is_foreign_modal_running(bpy.context):
                        self._foreign_modal_ran = True
                        return
                    if self._foreign_modal_ran: return
                    self.draw_postpixel_overlay()
                self._draw_postpixel_overlay = SpaceView3D.draw_handler_add(
                    draw_postpixel_overlay_safe, (), 'WINDOW', 'POST_PIXEL'
                )
            else:
                self._draw_postpixel_overlay = None

            RFGlobals.InvalidationManager.prevent_invalidation()
            self.prevented_invalidation = True

            self.had_init = True
            self.init(context, event)
        except Exception as e:
            print(f'RFOperator.invoke: Unhandled Exception caught while starting operator: {e}')
            _ = Debugger.print_exception()
            _ = self.teardown(context)
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
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

        if bpy.context.workspace:
            bpy.context.workspace.status_text_set(None)

        _ = self.teardown(bpy.context)

    def modal(self, context : Context, event : Event) -> set[str]:
        RFCore = RFGlobals.RFCore_None
        if not RFCore or not RFCore.is_running or self._stop:
            ret = {'CANCELLED'}
        else:
            # if we were tickled by another RF operator (ex: Translate finished when using PolyPen),
            # handle tickle event (which will remove tickle timer / handler)
            RFOperator.handle_tickle()

            if RFCore.is_foreign_modal_running(context):
                # A foreign modal that can edit the mesh is running on top.
                # An event that leaks through it must not touch tool state.
                self._foreign_modal_ran = True
                return {'PASS_THROUGH'}

            RFCore.is_controlling = True
            RFCore.event_mouse = (event.mouse_x, event.mouse_y)

            last_op = ops[-1] if (ops := context.window_manager.operators) else None
            if self._foreign_modal_ran or self.last_op != last_op:
                # reset when the operator history changes, and also right after a foreign modal ends.
                # A cancelled one (e.g. RMB out of a bevel) reverts the mesh without pushing history,
                # so the last_op comparison alone would miss it
                self._foreign_modal_ran = False
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
            if RFOperator.active_operator() != self:
                # print(f'RFOperator: currently finishing operator is not top??')
                # print(self)
                # print(RFOperator.active_operators)
                pass
            if not self.teardown(context):
                ret = {'CANCELLED'}
            for area in context.screen.areas:
                area.tag_redraw()
            Cursors.restore()
            if RFOperator.active_operators:
                # other RF operators on stack, so tickle them so they can see the changes
                RFOperator.tickle(context)
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
        wm : WindowManager = context.window_manager
        win : Window = context.window
        timer : Timer = wm.event_timer_add(0.01, window=win)
        def tickled():
            RFCore = RFGlobals.RFCore_None
            if not RFCore:
                return
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
    def draw_always(self) -> bool: return False
    def draw_postpixel_overlay(self): pass
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

Operator_Poll_Function    = Callable[[Context], bool]
Operator_Invoke_Function  = Callable[[Operator, Context, Event], set[str] | None] | Callable[[Context, Event], set[str] | None]
Operator_Execute_Function = Callable[[Operator, Context],        set[str] | None] | Callable[[Context],        set[str] | None]
Operator_Modal_Function   = Callable[[Operator, Context, Event], set[str] | None] | Callable[[Context, Event], set[str] | None]

def create_operator(
    name   : str,
    idname : str,
    label  : str,
    *,
    description : str | None = None,
    fn_poll     : Operator_Poll_Function | None = None,
    fn_invoke   : Operator_Invoke_Function | None = None,
    fn_exec     : Operator_Execute_Function | None = None,
    fn_modal    : Operator_Modal_Function | None = None,
    options     : set[str] | None = None,
    keymaps     : RFKeyMaps | None = None,
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
        rf_keymaps : RFKeyMaps = keymaps or list()

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
    *,
    description : str | None = None,
    options     : set[str] | None = None,
    fn_poll     : Operator_Poll_Function    | None = None,
    fn_exec     : Operator_Execute_Function | None = None,
    fn_modal    : Operator_Modal_Function   | None = None,
    keymaps     : RFKeyMaps | None = None,
) -> Callable[[Operator_Invoke_Function], Operator_Invoke_Function]:
    idname = name.lower().removeprefix('retpoflow.')
    def get(fn : Operator_Invoke_Function) -> Operator_Invoke_Function:
        _ = create_operator(
            name,
            idname,
            label,
            fn_invoke=fn,
            description=description,
            fn_poll=fn_poll,
            fn_exec=fn_exec,
            fn_modal=fn_modal,
            options=options,
            keymaps=keymaps,
        )
        # add bl_idname attribute to function
        setattr(fn, 'bl_idname', idname_to_retopoflow_bl_idname(idname))
        setattr(fn, 'rf_keymaps', keymaps)
        return fn
    return get

def execute_operator(
    name : str,
    label : str,
    *,
    description : str | None = None,
    options     : set[str] | None = None,
    fn_poll     : Operator_Poll_Function | None = None,
    fn_invoke   : Operator_Invoke_Function | None = None,
    fn_modal    : Operator_Modal_Function | None = None,
    keymaps     : RFKeyMaps | None = None,
) -> Callable[[Operator_Execute_Function], Operator_Execute_Function]:
    idname = name.lower().removeprefix('retopoflow.')
    def get(fn : Operator_Execute_Function) -> Operator_Execute_Function:
        _op = create_operator(
            name,
            idname,
            label,
            fn_exec=fn,
            description=description,
            fn_poll=fn_poll,
            fn_invoke=fn_invoke,
            fn_modal=fn_modal,
            options=options,
            keymaps=keymaps,
        )
        # add bl_idname attribute to function
        setattr(fn, 'bl_idname', idname_to_retopoflow_bl_idname(idname))
        setattr(fn, 'rf_keymaps', keymaps)
        return fn
    return get

def modal_operator(
    name : str,
    label : str,
    *,
    description : str | None = None,
    options     : set[str] | None = None,
    fn_poll     : Operator_Poll_Function | None = None,
    fn_invoke   : Operator_Invoke_Function | None = None,
    keymaps     : RFKeyMaps | None = None,
) -> Callable[[Operator_Modal_Function], Operator_Modal_Function]:
    idname = name.lower().removeprefix('retopoflow.')
    def fn_execute(self : Operator, context : Context) -> set[str]:
        wm : WindowManager = context.window_manager
        _ = wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def get(fn : Operator_Modal_Function) -> Operator_Modal_Function:
        _op = create_operator(
            name,
            idname,
            label,
            fn_exec=fn_execute,
            fn_modal=fn,
            description=description,
            fn_poll=fn_poll,
            fn_invoke=fn_invoke,
            options=options,
            keymaps=keymaps,
        )
        # add bl_idname attribute to function
        setattr(fn, 'bl_idname', idname_to_retopoflow_bl_idname(idname))
        setattr(fn, 'rf_keymaps', keymaps)
        return fn
    return get


EnumPropertyItem = (
      tuple[str, str, str]
    | tuple[str, str, str, int]
    | tuple[str, str, str, str | int, int]
    | None
)
EnumPropertyItems = (
      Iterable[EnumPropertyItem]
    | Callable[[bpy_struct, Context | None], Iterable[EnumPropertyItem]]
)

class OperatorPropertyWrapper:
    @staticmethod
    def int(
        wrap_cls : type,
        propname : str,
        **kwargs : ... # pyright: ignore[reportAny]
    ) -> Property:
        def getter(_self : bpy_struct) -> int:
            return int(getattr(wrap_cls, propname)) # pyright: ignore[reportAny]
        def setter(_self : bpy_struct, v : int):
            setattr(wrap_cls, propname, v)
        return IntProperty(
            get=getter,
            set=setter,
            **kwargs # pyright: ignore[reportAny]
        )

    @staticmethod
    def float(
        wrap_cls : type,
        propname : str,
        **kwargs : ... # pyright: ignore[reportAny]
    ) -> Property:
        def getter(_self : bpy_struct) -> float:
            return float(getattr(wrap_cls, propname)) # pyright: ignore[reportAny]
        def setter(_self : bpy_struct, v : float):
            setattr(wrap_cls, propname, v)
        return FloatProperty(
            get=getter,
            set=setter,
            **kwargs # pyright: ignore[reportAny]
        )

    @staticmethod
    def enum(
        wrap_cls : type,
        propname : str,
        *,
        items: EnumPropertyItems,
        **kwargs : ... # pyright: ignore[reportAny]
    ) -> Property:
        def getter(_self : bpy_struct) -> int:
            return int(getattr(wrap_cls, propname)) # pyright: ignore[reportAny]
        def setter(_self : bpy_struct, v : int):
            setattr(wrap_cls, propname, v)
        return EnumProperty(
            items=items,
            get=getter,
            set=setter,
            **kwargs # pyright: ignore[reportAny]
        )


RFOperator_Type : TypeAlias = type[RFOperator_Base]

Chainable_Keymaps : TypeAlias = (
    RFOperator_Type
    | RFKeyMap | RFKeyMaps
    | Operator_Invoke_Function | Operator_Execute_Function | Operator_Modal_Function
    | None
)

def chain_rf_keymaps(
    *classes_or_keymaps : Chainable_Keymaps,
    extra : RFKeyMaps | None = None,
) -> BLKeyMaps:
    def rf_keymaps(class_keymaps : Chainable_Keymaps) -> RFKeyMaps:
        match class_keymaps:
            case None:
                return []
            case tuple():  # RFKeyMap
                return [ class_keymaps ]
            case list():  # RFKeyMaps
                return class_keymaps
            case type():  # RFOperator_Type
                return class_keymaps.rf_keymaps
            case fn if callable(fn):  # Operator_XXX_Function
                return cast(RFKeyMaps, getattr(fn, 'rf_keymaps'))
            case _:
                assert False, f'Unhandled type {type(class_keymaps)} ({class_keymaps})'

    keymaps = [
        keymap
        for ck in classes_or_keymaps
        for keymap in rf_keymaps(ck)
    ]

    if extra:
        keymaps.extend(extra)

    return tuple(keymaps)
