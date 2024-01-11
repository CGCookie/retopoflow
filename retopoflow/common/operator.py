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


operators = []

def create_operator(name, idname, label, *, fn_poll=None, fn_invoke=None, fn_exec=None, fn_modal=None):
    class RFOp(bpy.types.Operator):
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
    operators.append(RFOp)
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


def register():
    for op in operators:
        bpy.utils.register_class(op)

def unregister():
    for op in reversed(operators):
        bpy.utils.unregister_class(op)
