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

re_status_entry = re.compile(r'((?P<icon>LMB|MMB|RMB): *)?(?P<text>.*)')
map_icons = {
    'LMB': 'MOUSE_LMB',
    'MMB': 'MOUSE_MMB',
    'RMB': 'MOUSE_RMB',
}


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

def chain_rf_keymaps(*classes):
    return tuple( keymap for cls in classes for keymap in cls.rf_keymaps )

class RFOperator(bpy.types.Operator):
    active_operators = []
    RFCore = None
    tickled = None

    _subclasses = []
    def __init_subclass__(cls, **kwargs):
        RFOperator._subclasses.append(cls)
        super().__init_subclass__(**kwargs)

    @staticmethod
    def active_operator():
        return RFOperator.active_operators[-1] if RFOperator.active_operators else None
    @classmethod
    def is_active(cls):
        return type(RFOperator.active_operator()) is cls

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
        if not context.edit_object: return False
        if context.edit_object.type != 'MESH': return False
        return True

    def invoke(self, context, event):
        if self.can_init(context, event) == False: return {'CANCELLED'}
        RFOperator.active_operators.append(self)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(lambda header, context: self.status(header, context))
        self.last_op = None
        self.working_area = context.area
        self.working_window = context.window
        self.init(context, event)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        self.RFCore.is_controlling = True
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
                print(f'Caught KeyboardInterrupt Exception: {e}')
                ret = {'CANCELLED'}
            except Exception as e:
                print(f'Unhandled Exception Caught: {e}')
                Debugger.print_exception()
                ret = {'CANCELLED'}

        if ret & {'FINISHED', 'CANCELLED'}:
            if RFOperator.active_operator() != self:
                print(f'RFOperator: currently finishing operator is not top??')
                print(self)
                print(RFOperator.active_operators)
            RFOperator.active_operators.remove(self)
            context.workspace.status_text_set(None)
            for area in context.screen.areas: area.tag_redraw()
            Cursors.restore()
            if RFOperator.active_operators:
                # other RF operators on stack, so tickle them so they can see the changes
                RFOperator.tickle(context)

        return ret

    @staticmethod
    def tickle(context):
        # tickle RF operator by temporarily setting a timer that will self-remove (causes modal / update to be called)
        # sadly, cannot use context.window.event_simulate, because this requires `--enable-event-simulate` Blender commandline argument
        # ex: context.window.event_simulate('TIMER', 'NOTHING')
        wm  = context.window_manager
        timer = wm.event_timer_add(0.01, window=context.window)
        def tickled():
            wm.event_timer_remove(timer)
            RFOperator.tickled = None
            context.area.tag_redraw()
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
    def can_init(self, context, event): return True
    def init(self, context, event): pass
    def reset(self): pass
    def update(self, context, event): return {'FINISHED'}
    def draw_preview(self, context): pass
    def draw_postview(self, context): pass
    def draw_postpixel(self, context): pass



def create_operator(name, idname, label, *, fn_poll=None, fn_invoke=None, fn_exec=None, fn_modal=None):
    class RFOp(RFOperator):
        bl_idname = f"retopoflow.{idname}"
        bl_label = label
        bl_space_type = "VIEW_3D"
        bl_region_type = "TOOLS"
        bl_options = set()

        @classmethod
        def poll(cls, context):
            return fn_poll(context) if fn_poll else True
        def invoke(self, context, event):
            ret = fn_invoke(context, event) if fn_invoke else self.execute(context)
            return ret if ret is not None else {'FINISHED'}
        def execute(self, context):
            ret = fn_exec(context) if fn_exec else {'CANCELLED'}
            return ret if ret is not None else {'FINISHED'}
        def modal(self, context, event):
            ret = fn_modal(context, event) if fn_modal else {'FINISHED'}
            return ret if ret is not None else {'FINISHED'}

    RFOp.__name__ = f'RETOPOFLOW_OT_{name}'
    return RFOp


def invoke_operator(name, label):
    idname = name.lower()
    def get(fn):
        create_operator(name, idname, label, fn_invoke=fn)
        fn.bl_idname = f'retopoflow.{idname}'
        return fn
    return get

def execute_operator(name, label):
    idname = name.lower()
    def get(fn):
        create_operator(name, idname, label, fn_exec=fn)
        fn.bl_idname = f'retopoflow.{idname}'
        return fn
    return get

def modal_operator(name, label):
    idname = name.lower()
    def get(fn):
        create_operator(name, idname, label, fn_exec=fn)
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

