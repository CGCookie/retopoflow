'''
Copyright (C) 2019 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import os

import bpy
import bmesh
from bpy.types import WorkSpaceTool

from ..addon_common.common.globals import Globals
from ..addon_common.common import drawing
from ..addon_common.common.drawing import ScissorStack
from ..addon_common.cookiecutter.cookiecutter import CookieCutter
from ..addon_common.common import ui

class VIEW3D_OT_RetopoFlow(CookieCutter):
    """Tooltip"""
    bl_idname = "cgcookie.retopoflow"
    bl_label = "RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    default_keymap = {
        'commit': {'RET',},
        'cancel': {'ESC',},
    }

    @classmethod
    def can_start(cls, context):
        # check that the context is correct
        if not context.region or context.region.type != 'WINDOW': return False
        if not context.space_data or context.space_data.type != 'VIEW_3D': return False
        # check we are in mesh editmode
        if context.mode != 'EDIT_MESH': return False
        # make sure we are editing a mesh object
        ob = context.active_object
        if not ob or ob.type != 'MESH': return False
        # all seems good!
        return True

    def start(self):
        self.target = bpy.context.active_object
        self.sources = [o for o in bpy.data.objects if o != self.target and o.type == "MESH" and o.visible_get()]
        print('sources: %s' % ', '.join(o.name for o in self.sources))
        print('target: %s' % self.target.name)
        self.manipulator_hide()
        self.panels_hide()
        self.overlays_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')
        self.target.hide_viewport = True

        path = os.path.join(os.path.dirname(__file__), '..', 'config', 'ui.css')
        try:
            Globals.ui_draw.load_stylesheet(path)
        except AssertionError as e:
            # TODO: show proper dialog to user here!!
            print('could not load stylesheet "%s"' % path)
            print(e)

        self.ui_elem = ui.button(label="Push Me!")
        c = 0
        def mouseclick(e):
            nonlocal c
            c += 1
            self.ui_elem.innerText = "You've clicked me %d times.\nNew lines act like spaces here, but there is text wrapping!" % c
        def mousedown(e):
            self.ui_elem.innerText = "mouse is down!"
        def mouseup(e):
            self.ui_elem.innerText = "mouse is up!"
        self.ui_elem.add_eventListener('mouseclick', mouseclick)
        self.ui_elem.add_eventListener('mousedown', mousedown)
        self.ui_elem.add_eventListener('mouseup', mouseup)
        self.document.body.append_child(self.ui_elem)

        #win_tools = self.wm.create_window('RetopoFlow', {'pos':7, 'movable':True, 'bgcolor':(0.5,0.5,0.5,0.9)})

    def end(self):
        self.target.hide_viewport = False

    def update(self):
        # mx,my = self.actions.mouse if self.actions.mouse else (0,0)
        # if self.ui_elem.get_under_mouse(mx, my):
        #     self.ui_elem.add_pseudoclass('hover')
        #     if not self.ui_elem.is_active and self.actions.using('LEFTMOUSE'):
        #         self.ui_elem.add_pseudoclass('active')
        #         self.ui_elem.dispatch_event('mousedown')
        # elif self.ui_elem.is_hovered:
        #     self.ui_elem.del_pseudoclass('hover')
        # if not self.actions.using('LEFTMOUSE') and self.ui_elem.is_active:
        #     self.ui_elem.dispatch_event('mouseup')
        #     self.ui_elem.del_pseudoclass('active')
        #     if self.ui_elem.is_hovered: self.ui_elem.dispatch_event('mouseclick')
        pass

    @CookieCutter.Draw('post2d')
    def draw_stuff(self):
        # will be done by ui system
        # ScissorStack.start(self.context)
        # Globals.ui_draw.update()
        # self.ui_elem.clean()
        # self.ui_elem.position(500, self.ui_y, 200, 200)
        # self.ui_elem.draw()
        # ScissorStack.end()
        pass

    @CookieCutter.FSM_State('main')
    def modal_main(self):
        self.cursor_modal_set('CROSSHAIR')

        if self.actions.pressed('commit'):
            self.done()
            return

        if self.actions.pressed('cancel'):
            self.done(cancel=True)
            return





class VIEW3D_OT_RetopoFlow_Tool(WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'OBJECT'

    # The prefix of the idname should be your add-on name.
    bl_idname = "cgcookie.retopoflow"
    bl_label = "RetopoFlow"
    bl_description = "A suite of retopology tools for Blender through a unified retopology mode"
    bl_icon = "ops.mesh.polybuild_hover"
    bl_widget = None
    bl_keymap = (
        ("view3d.select_circle", {"type": 'LEFTMOUSE', "value": 'PRESS'},
         {"properties": [("wait_for_input", False)]}),
        ("view3d.select_circle", {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True},
         {"properties": [("mode", 'SUB'), ("wait_for_input", False)]}),
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties("view3d.select_circle")
        layout.prop(props, "mode")
        layout.prop(props, "radius")


# class MyOtherTool(WorkSpaceTool):
#     bl_space_type='VIEW_3D'
#     bl_context_mode='OBJECT'

#     bl_idname = "my_template.my_other_select"
#     bl_label = "My Lasso Tool Select"
#     bl_description = (
#         "This is a tooltip\n"
#         "with multiple lines"
#     )
#     bl_icon = "ops.generic.select_lasso"
#     bl_widget = None
#     bl_keymap = (
#         ("view3d.select_lasso", {"type": 'LEFTMOUSE', "value": 'PRESS'}, None),
#         ("view3d.select_lasso", {"type": 'LEFTMOUSE', "value": 'PRESS', "ctrl": True},
#          {"properties": [("mode", 'SUB')]}),
#     )

#     def draw_settings(context, layout, tool):
#         props = tool.operator_properties("view3d.select_lasso")
#         layout.prop(props, "mode")


# def register():
#     bpy.utils.register_tool(MyTool, after={"builtin.scale_cage"}, separator=True, group=True)
#     bpy.utils.register_tool(MyOtherTool, after={MyTool.bl_idname})

# def unregister():
#     bpy.utils.unregister_tool(MyTool)
#     bpy.utils.unregister_tool(MyOtherTool)

# if __name__ == "__main__":
#     register()


