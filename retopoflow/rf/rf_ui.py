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

from ..help import retopoflow_version, help_welcome

from ...addon_common.common.utils import delay_exec
from ...addon_common.common.globals import Globals
from ...addon_common.common import ui
from ...addon_common.common.ui_styling import load_defaultstylings
from ...addon_common.common.profiler import profiler

def reload_stylings():
    load_defaultstylings()
    path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'ui.css')
    try:
        Globals.ui_draw.load_stylesheet(path)
    except AssertionError as e:
        # TODO: show proper dialog to user here!!
        print('could not load stylesheet "%s"' % path)
        print(e)
    Globals.ui_document.body.dirty('Reloaded stylings', children=True)
    Globals.ui_document.body.dirty_styling()
    Globals.ui_document.body.dirty_flow()

class RetopoFlow_UI:
    def open_welcome(self):
        ui_welcome = ui.framed_dialog(label='Welcome!!', id='welcomedialog', parent=self.document.body)
        ui.markdown(mdown=help_welcome, parent=ui_welcome)
        ui.button(label='Close', parent=ui_welcome, on_mouseclick=delay_exec("self.document.body.delete_child(ui_welcome)"))

    def alert_user(self, title=None, message=None, level=None, msghash=None):
        print(title, message, level, msghash)

    def setup_ui(self):
        self.manipulator_hide()
        self.panels_hide()
        self.overlays_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')

        # load ui.css
        reload_stylings()

        def setup_main_ui():
            self.ui_main = ui.framed_dialog(label='RetopoFlow %s' % retopoflow_version, id="maindialog", parent=self.document.body)

            # tools
            ui_tools = ui.div(id="tools", parent=self.ui_main)
            def add_tool(rftool):
                # must be a fn so that local vars are unique and correctly captured
                lbl, img = rftool.name, rftool.icon
                if hasattr(self, 'rf_starting_tool'):
                    checked = rftool.name == self.rf_starting_tool
                else:
                    checked = not hasattr(add_tool, 'notfirst')
                if checked: self.select_rftool(rftool)
                radio = ui.input_radio(id='tool-%s'%lbl.lower(), value=lbl.lower(), name="tool", classes="tool", checked=checked, parent=ui_tools)
                radio.add_eventListener('on_input', delay_exec('''if radio.checked: self.select_rftool(rftool)'''))
                ui.img(src=img, parent=radio)
                ui.label(innerText=lbl, parent=radio)
                add_tool.notfirst = True
            for rftool in self.rftools: add_tool(rftool)

            ui.button(label='Welcome!', parent=self.ui_main, on_mouseclick=self.open_welcome)
            ui.button(label='All Help', parent=self.ui_main)
            ui.button(label='General Help', parent=self.ui_main)
            ui.button(label='Tool Help', parent=self.ui_main)
            ui.button(label='Report Issue', parent=self.ui_main)
            ui.button(label='Exit', parent=self.ui_main, on_mouseclick=self.done)
            ui.button(label='Reload Styles', parent=self.ui_main, on_mouseclick=reload_stylings)
            def printout_profiler():
                profiler.printout()
                print("Children: %d" % self.document.body.count_children())
            ui.button(label='Profiler', parent=self.ui_main, on_mouseclick=printout_profiler)
            ui.button(label='Profiler Clear', parent=self.ui_main, on_mouseclick=profiler.reset)


        def setup_options():
            self.ui_options = ui.framed_dialog(label='Options', id='optionsdialog', right=0, parent=self.document.body)

            ui_general = ui.collapsible(label='General', id='generaloptions', parent=self.ui_options)
            ui.button(label='Maximize Area', parent=ui_general)

            ui_target_cleaning = ui.collapsible(label='Target Cleaning', id='targetcleaning', parent=ui_general)
            ui_target_snapverts = ui.collapsible(label='Snap Verts', id='snapverts', parent=ui_target_cleaning)
            ui.button(label="All", parent=ui_target_snapverts)
            ui.button(label="Selected", parent=ui_target_snapverts)
            ui_target_removedbls = ui.collapsible(label='Remove Doubles', id='removedoubles', parent=ui_target_cleaning)
            ui.labeled_input_text(label='Distance', value='0.001', parent=ui_target_removedbls)
            ui.button(label="All", parent=ui_target_removedbls)
            ui.button(label="Selected", parent=ui_target_removedbls)

            ui_target_rendering = ui.collapsible(label="Target Rendering", parent=ui_general)
            ui.labeled_input_text(label='Above', value='100', parent=ui_target_rendering)
            ui.labeled_input_text(label='Below', value='10', parent=ui_target_rendering)
            ui.labeled_input_text(label='Backface', value='20', parent=ui_target_rendering)
            ui.input_checkbox(label='Cull Backfaces', parent=ui_target_rendering)

            ui_symmetry = ui.collapsible(label='Symmetry', id='symmetryoptions', parent=self.ui_options)

            for rftool in self.rftools:
                for ui_elem in rftool._callback('ui setup'):
                    self.ui_options.append_child(ui_elem)

            #test
            ui.labeled_input_text(label='Above', value='100', parent=self.ui_options)
            ui.labeled_input_text(label='Below', value='10', parent=self.ui_options)
            ui.labeled_input_text(label='Backface', value='20', parent=self.ui_options)
            ui.input_text(value='foo bar', parent=self.ui_options)

        def setup_delete_ui():
            self.ui_delete = ui.framed_dialog(label='Delete/Dissolve', id='deletedialog', parent=self.document.body, resizable_x=False, hide_on_close=True)
            self.ui_delete.width = 200
            self.ui_delete.is_visible = False
            def hide_ui_delete():
                self.ui_delete.is_visible = False
            self.ui_delete.add_eventListener('on_focusout', hide_ui_delete)

            def act(opt):
                self.delete_dissolve_option(opt)
                self.ui_delete.is_visible = False

            ui_delete = ui.collection('Delete', parent=self.ui_delete)
            ui.button(label='Vertices', on_mouseclick=delay_exec('''act(('Delete','Vertices'))'''), parent=ui_delete)
            ui.button(label='Edges', on_mouseclick=delay_exec('''act(('Delete','Edges'))'''), parent=ui_delete)
            ui.button(label='Faces', on_mouseclick=delay_exec('''act(('Delete','Faces'))'''), parent=ui_delete)
            ui.button(label='Only Edges & Faces', on_mouseclick=delay_exec('''act(('Delete','Only Edges & Faces'))'''), parent=ui_delete)
            ui.button(label='Only Faces', on_mouseclick=delay_exec('''act(('Delete','Only Faces'))'''), parent=ui_delete)

            ui_dissolve = ui.collection('Dissolve', parent=self.ui_delete)
            ui.button(label='Vertices', on_mouseclick=delay_exec('''act(('Dissolve','Vertices'))'''), parent=ui_dissolve)
            ui.button(label='Edges', on_mouseclick=delay_exec('''act(('Dissolve','Edges'))'''), parent=ui_dissolve)
            ui.button(label='Faces', on_mouseclick=delay_exec('''act(('Dissolve','Faces'))'''), parent=ui_dissolve)
            ui.button(label='Loops', on_mouseclick=delay_exec('''act(('Dissolve','Loops'))'''), parent=ui_dissolve)

        def test():
            c = 0
            def mouseclick(e):
                nonlocal c
                c += 1
                e.target.innerText = "You've clicked me %d times.\nNew lines act like spaces here, but there is text wrapping!" % c
            def mousedblclick(e):
                e.target.innerText = "NO!!!!  You've double clicked me!!!!"
                e.target.add_pseudoclass('disabled')
            def mousedown(e):
                e.target.innerText = "mouse is down!"
            def mouseup(e):
                e.target.innerText = "mouse is up!"
            def reload_stylings(e):
                load_defaultstylings()
                self.document.body.dirty_styling()
            def width_increase(e):
                self.ui_main.width = self.ui_main.width_pixels + 50
            def width_decrease(e):
                self.ui_main.width = self.ui_main.width_pixels - 50
            self.ui_main.append_child(ui.img(src='contours_32.png'))
            # self.ui_main.append_child(ui.img(src='polystrips_32.png', style='width:26px; height:26px'))
            # self.ui_main.append_child(ui.button(label="Click on me, but do NOT double click!", on_mouseclick=mouseclick, on_mousedblclick=mousedblclick, on_mousedown=mousedown, on_mouseup=mouseup))
            # self.ui_main.append_child(ui.button(label="FOO", style="display:block", children=[ui.button(label="BAR", style="display:block")]))
            # self.ui_main.append_child(ui.button(id="alpha0", label="ABCDEFGHIJKLMNOPQRSTUVWXYZ 0"))
            # self.ui_main.append_child(ui.button(id="alpha1", label="ABCDEFGHIJKLMNOPQRSTUVWXYZ 1"))
            # self.ui_main.append_child(ui.button(id="alpha2", label="ABCDEFGHIJKLMNOPQRSTUVWXYZ 2"))
            # self.ui_main.append_child(ui.button(id="alpha3", label="ABCDEFGHIJKLMNOPQRSTUVWXYZ 3"))
            self.ui_main.append_child(ui.br())
            self.ui_main.append_child(ui.button(label="Reload Styles Now", on_mouseclick=reload_stylings))
            self.ui_main.append_child(ui.input_checkbox(label="test"))
            self.ui_main.append_child(ui.br())
            self.ui_main.append_child(ui.span(innerText="Options:"))
            self.ui_main.append_child(ui.input_radio(label="A", value="A", name="option"))
            self.ui_main.append_child(ui.input_radio(label="B", value="B", name="option"))
            self.ui_main.append_child(ui.input_radio(label="C", value="C", name="option"))
            # self.ui_main.append_child(ui.p(innerText="Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."))
            # self.ui_main.append_child(ui.textarea(innerText="Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."))

            self.ui_tools = ui.framed_dialog(id='toolsframe', label='Tools', parent=self.document.body)
            #self.ui_tools = self.ui_main
            state_p = self.ui_tools.append_child(ui.p())
            state_p.append_child(ui.span(innerText='State:'))
            self.state = state_p.append_child(ui.span(innerText='???'))
            self.ui_tools.append_child(ui.p(innerText="Foo Bar Baz"))
            ui_input = self.ui_tools.append_child(ui.input_text(id="inputtext"))
            ui_input.value = 'Lorem   ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
            div_width = self.ui_tools.append_child(ui.div())
            div_width.append_child(ui.span(innerText='width:'))
            div_width.append_child(ui.button(label='+', on_mouseclick=width_increase))
            div_width.append_child(ui.button(label='-', on_mouseclick=width_decrease))
            div_width.append_child(ui.button(label='=')).add_pseudoclass('disabled')
            self.ui_tools.right = 0
            self.ui_tools.top = 0
            print(self.document.body.structure())

        setup_main_ui()
        setup_options()
        setup_delete_ui()

        self.ui_tools = self.document.body.getElementsByName('tool')

