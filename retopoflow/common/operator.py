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

class RFOperator(bpy.types.Operator):
    active_operators = []
    RFCore = None

    @staticmethod
    def active_operator():
        return RFOperator.active_operators[-1] if RFOperator.active_operators else None

    @staticmethod
    def get_all_RFOperators():
        return RFOperator.__subclasses__()
    @staticmethod
    def register_all():
        for op in RFOperator.get_all_RFOperators():
            bpy.utils.register_class(op)
    @staticmethod
    def unregister_all():
        for op in reversed(RFOperator.get_all_RFOperators()):
            bpy.utils.unregister_class(op)

    @classmethod
    def poll(cls, context):
        if not context.edit_object: return False
        if context.edit_object.type != 'MESH': return False
        return True

    def invoke(self, context, event):
        RFOperator.active_operators.append(self)
        context.window_manager.modal_handler_add(self)
        context.workspace.status_text_set(lambda header, context: self.status(header, context))
        self.last_op = None
        self.init(context, event)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        RFOperator.RFCore.event_mouse = (event.mouse_x, event.mouse_y)

        last_op = ops[-1] if (ops := context.window_manager.operators) else None
        if self.last_op != last_op:
            self.reset()
            self.last_op = last_op
            context.area.tag_redraw()

        if not context.area:
            # this can happen if an area is fullscreened :(
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
        return ret

    def status(self, header, context):
        layout = header.layout
        row = layout.row()
        row.ui_units_x = 7
        row.label(text=self.bl_label)
        row = layout.row()
        row.ui_units_x = 10 * len(self.rf_status)
        for e in self.rf_status:
            m_entry = re_status_entry.match(e)
            icon = m_entry['icon'] or ''
            row.label(text=m_entry['text'], icon=map_icons.get(icon, icon))

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


