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

import bpy
import re

from ...addon_common.common.blender_cursors import Cursors
from ...addon_common.common.debug import Debugger
from ...addon_common.common.useractions import event_match_blenderop, get_kmi_properties

re_status_entry = re.compile(r'((?P<icon>LMB|MMB|RMB): *)?(?P<text>.*)')
map_icons = {
    'LMB': 'MOUSE_LMB',
    'MMB': 'MOUSE_MMB',
    'RMB': 'MOUSE_RMB',
}


def poll_retopoflow(context):
    if not context.edit_object: return False
    if context.edit_object.type != 'MESH': return False
    return True


class RFRegisterClass:
    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass

    _subclasses = []
    def __init_subclass__(cls, **kwargs):
        RFRegisterClass._subclasses.append(cls)
        super().__init_subclass__(**kwargs)

    @staticmethod
    def get_all_classes():
        return RFRegisterClass._subclasses
        # return RFRegisterClass.__subclasses__()  # this only works if the subclass is still in scope!!!!!
    @staticmethod
    def register_all():
        for op in RFRegisterClass.get_all_classes():
            bpy.utils.register_class(op)
            op.register()
    @staticmethod
    def unregister_all():
        for op in reversed(RFRegisterClass.get_all_classes()):
            op.unregister()
            bpy.utils.unregister_class(op)

def chain_rf_keymaps(*classes, extra=[]):
    return tuple( [keymap for cls in classes for keymap in cls.rf_keymaps] + extra )

class RFOperator_Execute(bpy.types.Operator):
    _subclasses = []
    def __init_subclass__(cls, **kwargs):
        RFOperator._subclasses.append(cls)
        super().__init_subclass__(**kwargs)

    @staticmethod
    def get_all_RFOperators():
        return RFOperator_Execute._subclasses
        # return RFOperator.__subclasses__()  # this only works if the subclass is still in scope!!!!!
    @staticmethod
    def register_all():
        for op in RFOperator_Execute.get_all_RFOperators():
            bpy.utils.register_class(op)
            op.register()
    @staticmethod
    def unregister_all():
        for op in reversed(RFOperator_Execute.get_all_RFOperators()):
            op.unregister()
            bpy.utils.unregister_class(op)

    @classmethod
    def poll(cls, context):
        return poll_retopoflow(context)

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass


class RFOperator(bpy.types.Operator):
    active_operators = []
    RFCore = None
    InvalidationManager = None
    tickled = None

    _subclasses = []
    def __init_subclass__(cls, **kwargs):
        RFOperator._subclasses.append(cls)
        cls.rf_idname = cls.bl_idname
        super().__init_subclass__(**kwargs)

    @staticmethod
    def active_operator():
        return RFOperator.active_operators[-1] if RFOperator.active_operators else None
    @classmethod
    def is_active(cls):
        return type(RFOperator.active_operator()) is cls

    @classmethod
    def is_running(cls):
        return any(cls is type(op) for op in RFOperator.active_operators)

    @staticmethod
    def get_all_RFOperators():
        return RFOperator._subclasses
        # return RFOperator.__subclasses__()  # this only works if the subclass is still in scope!!!!!
    @staticmethod
    def register_all():
        for op in RFOperator.get_all_RFOperators():
            bpy.utils.register_class(op)
            op.register()
    @staticmethod
    def unregister_all():
        for op in reversed(RFOperator.get_all_RFOperators()):
            op.unregister()
            bpy.utils.unregister_class(op)

    @classmethod
    def poll(cls, context):
        # make sure RFCore is running
        if not RFOperator.RFCore.is_running: return False

        if not context.edit_object: return False
        if context.edit_object.type != 'MESH': return False

        # make sure RFOperator has only one running instance!
        if getattr(cls, '_is_running', False): return False

        if not cls.can_start(context):
            # print(f'{cls}.poll: {cls.can_start(context)=}')
            return False

        return True

    def invoke(self, context, event):
        if self.can_init(context, event) == False: return {'CANCELLED'}
        type(self)._is_running = True
        RFOperator.active_operators.append(self)
        context.window_manager.modal_handler_add(self)
        def status(header, context):
            try:
                self.status(header, context)
            except Exception as e:
                print(f'Caught exception while trying to set status {e}')
                context.workspace.status_text_set(None)
        context.workspace.status_text_set(status)
        self.last_op = None
        self.working_area = context.area
        self.working_window = context.window
        self._stop = False

        if hasattr(self, 'draw_postpixel_overlay'):
            wm, space = bpy.types.WindowManager, bpy.types.SpaceView3D
            self._draw_postpixel_overlay = space.draw_handler_add(self.draw_postpixel_overlay, (), 'WINDOW', 'POST_PIXEL')
        else:
            self._draw_postpixel_overlay = None

        self.InvalidationManager.prevent_invalidation()

        self.init(context, event)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def stop(self):
        print(f'stopping {self=}')
        if self._stop: return
        self._stop = True
        if self._draw_postpixel_overlay:
            wm, space = bpy.types.WindowManager, bpy.types.SpaceView3D
            space.draw_handler_remove(self._draw_postpixel_overlay, 'WINDOW')
            self._draw_postpixel_overlay = None
        bpy.context.workspace.status_text_set(None)
        if self in RFOperator.active_operators: RFOperator.active_operators.remove(self)
        type(self)._is_running = False

    def modal(self, context, event):
        if not RFOperator.RFCore.is_running or self._stop:
            ret = {'CANCELLED'}
        else:
            RFOperator.RFCore.is_controlling = True
            if RFOperator.tickled:
                # we were tickled by another RF operator (ex: Translate finished when using PolyPen)
                # handle tickle event (which will remove tickle timer / handler)
                RFOperator.tickled()

            RFOperator.RFCore.event_mouse = (event.mouse_x, event.mouse_y)

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
                    Debugger.print_exception()
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
            context.workspace.status_text_set(None)
            for area in context.screen.areas: area.tag_redraw()
            Cursors.restore()
            if RFOperator.active_operators:
                # other RF operators on stack, so tickle them so they can see the changes
                RFOperator.tickle(context)
            self.InvalidationManager.resume_invalidation()
            type(self)._is_running = False
            return ret

        if 'PASS_THROUGH' in ret:
            # check if passing event through might trigger something incompatible with RF
            if kmi := event_match_blenderop(event, 'Screen | screen.screen_full_area'):
                # attempting to full screen the area!
                ctx = { k: getattr(context,k) for k in ['window', 'area', 'region', 'screen'] }
                props = get_kmi_properties(kmi)
                def fn():
                    with bpy.context.temp_override(**ctx):
                        bpy.ops.screen.screen_full_area(**props)
                self.stop()
                self.RFCore.quick_switch_with_call(fn, self.rf_idname)
                return {'FINISHED'}

        return ret

    @staticmethod
    def tickle(context):
        # tickle RF operator by temporarily setting a timer that will self-remove (causes modal / update to be called)
        # sadly, cannot use context.window.event_simulate, because this requires `--enable-event-simulate` Blender commandline argument
        # ex: context.window.event_simulate('TIMER', 'NOTHING')
        # bpy.app.timer also does not work, as it doesn't trigger an event
        if RFOperator.tickled: RFOperator.tickled()
        wm, win, area = context.window_manager, context.window, context.area
        timer = wm.event_timer_add(0.01, window=win)
        def tickled():
            try:
                wm.event_timer_remove(timer)
                RFOperator.tickled = None
                RFOperator.RFCore.tag_redraw_areas()
            except Exception as e:
                print(f'Ignoring uncaught Exception while trying to remove event timer')
                print(e)
        RFOperator.tickled = tickled


    def status(self, header, context):
        layout = header.layout
        row = layout.row()
        row.ui_units_x = 7
        row.label(text=self.bl_label)
        if hasattr(self, 'rf_status'):
            row = layout.row()
            row.ui_units_x = 10 * len(self.rf_status)
            for e in self.rf_status:
                m_entry = re_status_entry.match(e)
                icon = m_entry['icon'] or ''
                row.label(text=m_entry['text'], icon=map_icons.get(icon, icon))

    @classmethod
    def register(cls): pass
    @classmethod
    def unregister(cls): pass
    @classmethod
    def can_start(cls, context): return True
    def can_init(self, context, event): return True
    def init(self, context, event): pass
    def reset(self): pass
    def update(self, context, event): return {'FINISHED'}
    def finish(self, context): pass
    def draw_preview(self, context): pass
    def draw_postview(self, context): pass
    def draw_postpixel(self, context): pass
    @classmethod
    def depsgraph_update(cls): pass


def create_operator(name, idname, label, *, description=None, fn_poll=None, fn_invoke=None, fn_exec=None, fn_modal=None, options=set(), pass_self=False):
    if idname.startswith('retopoflow.'): idname = idname[len('retopoflow.'):]

    if fn_invoke:
        if not pass_self:
            fn_invoke_pre = fn_invoke
            fn_invoke = lambda self, context, event: fn_invoke_pre(context, event)
    else:
        fn_invoke = lambda self, context, event: self.execute(context)

    if fn_exec:
        if not pass_self:
            fn_exec_pre = fn_exec
            fn_exec = lambda self, context: fn_exec_pre(context)
    else:
        fn_exec = lambda self, context: {'CANCELLED'}

    if fn_modal:
        if not pass_self:
            fn_modal_pre = fn_modal
            fn_modal = lambda self, context, event: fn_modal_pre(context, event)
    else:
        fn_modal = lambda self, context, event: {'FINISHED'}

    class RFOp:
        bl_idname = f"retopoflow.{idname}"
        bl_label = label
        bl_description = description if description is not None else label
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = options

        @classmethod
        def poll(cls, context):
            return fn_poll(context) if fn_poll else True
        def invoke(self, context, event):
            ret = fn_invoke(self, context, event)
            return ret if ret is not None else {'FINISHED'}
        def execute(self, context):
            ret = fn_exec(self, context)
            return ret if ret is not None else {'FINISHED'}
        def modal(self, context, event):
            ret = fn_modal(self, context, event)
            return ret if ret is not None else {'FINISHED'}

    opname = f'RETOPOFLOW_OT_{name}'

    return type(opname, (RFOp, RFOperator), {})


def invoke_operator(name, label, **kwargs):
    idname = name.lower()
    if idname.startswith('retopoflow.'): idname = idname[len('retopoflow.'):]
    def get(fn):
        create_operator(name, idname, label, fn_invoke=fn, **kwargs)
        fn.bl_idname = f'retopoflow.{idname}'
        return fn
    return get

def execute_operator(name, label, **kwargs):
    idname = name.lower()
    if idname.startswith('retopoflow.'): idname = idname[len('retopoflow.'):]
    def get(fn):
        create_operator(name, idname, label, fn_exec=fn, **kwargs)
        fn.bl_idname = f'retopoflow.{idname}'
        return fn
    return get

def modal_operator(name, label, **kwargs):
    idname = name.lower()
    if idname.startswith('retopoflow.'): idname = idname[len('retopoflow.'):]
    def fn_execute(self, context):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}
    def get(fn):
        create_operator(name, idname, label, fn_exec=fn_execute, fn_modal=fn, pass_self=True, **kwargs)
        fn.bl_idname = f'retopoflow.{idname}'
        return fn
    return get

def wrap_property(cls, propname, proptype, **kwargs):
    def getter(_): return getattr(cls, propname)
    def setter(_, v): setattr(cls, propname, v)
    match proptype:
        case 'int':
            return bpy.props.IntProperty(get=getter, set=setter, **kwargs)
        case 'float':
            return bpy.props.FloatProperty(get=getter, set=setter, **kwargs)
        case 'enum':
            return bpy.props.EnumProperty(get=getter, set=setter, **kwargs)
        case _:
            assert False, f'Unhandled property type {proptype} for {cls}.{propname}'
