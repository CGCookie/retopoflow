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

from .rf.rf_blender    import RetopoFlow_Blender
from .rf.rf_drawing    import RetopoFlow_Drawing
from .rf.rf_grease     import RetopoFlow_Grease
from .rf.rf_instrument import RetopoFlow_Instrumentation
from .rf.rf_sources    import RetopoFlow_Sources
from .rf.rf_spaces     import RetopoFlow_Spaces
from .rf.rf_states     import RetopoFlow_States
from .rf.rf_target     import RetopoFlow_Target
from .rf.rf_tools      import RetopoFlow_Tools
from .rf.rf_ui         import RetopoFlow_UI
from .rf.rf_undo       import RetopoFlow_Undo

from ..addon_common.common import ui
from ..addon_common.common.globals import Globals
from ..addon_common.common.profiler import profiler
from ..addon_common.common.utils import delay_exec
from ..addon_common.common.ui_styling import load_defaultstylings
from ..addon_common.cookiecutter.cookiecutter import CookieCutter

from ..config.keymaps import default_rf_keymaps


class RetopoFlow_QuickStart(CookieCutter):
    @classmethod
    def can_start(cls, context):
        return True

    def reload_stylings(self):
        load_defaultstylings()
        path = os.path.join(os.path.dirname(__file__), '..', 'config', 'ui.css')
        try:
            Globals.ui_draw.load_stylesheet(path)
        except AssertionError as e:
            # TODO: show proper dialog to user here!!
            print('could not load stylesheet "%s"' % path)
            print(e)
        Globals.ui_document.body.dirty('Reloaded stylings', children=True)
        Globals.ui_document.body.dirty_styling()
        Globals.ui_document.body.dirty_flow()

    def helpsystem_open(self, mdown_path):
        ui_markdown = self.document.body.getElementById('helpsystem-mdown')
        if not ui_markdown:
            ui_help = ui.framed_dialog(
                label='RetopoFlow Help System',
                id='helpsystem',
                style='width:90%; left:5%;',
                resizable=False,
                closeable=False,
                moveable=False,
                parent=self.document.body
            )
            ui_markdown = ui.markdown(id='helpsystem-mdown', parent=ui_help)
            ui.div(parent=ui_help, style='margin:1px; width:100%', children=[
                ui.button(
                    label='Table of Contents',
                    on_mouseclick=delay_exec("self.helpsystem_open('table_of_contents.md')"),
                    style='display:inline; width:49.5%',
                    parent=ui_help,
                ),
                ui.button(
                    label='Close (Esc)',
                    on_mouseclick=self.done,
                    style='display:inline; width:49.5%',
                    parent=ui_help,
                )
            ])
            def key(e):
                if e.key == 'ESC': self.done()
            ui_help.add_eventListener('on_keypress', key)
        ui.set_markdown(ui_markdown, mdown_path=mdown_path)

    def blender_ui_set(self):
        self.manipulator_hide()
        self.panels_hide()
        self.overlays_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')

    def start(self):
        #profiler.set_profiler_enabled(True)
        self.reload_stylings()
        self.blender_ui_set()
        self.helpsystem_open('quick_start.md')
        Globals.ui_document.body.dirty('changed document size', children=True)

    def end(self):
        self._cc_blenderui_end()
        #profiler.printout()
        #print("Children: %d" % self.document.body.count_children())
        #print("All children: %d" % self.document.body.count_all_children())

    @CookieCutter.FSM_State('main')
    def main(self):
        if self.actions.pressed({'ESC'}):
            self.done()
            return


class RetopoFlow(
    RetopoFlow_Blender,
    RetopoFlow_Drawing,
    RetopoFlow_Grease,
    RetopoFlow_Instrumentation,
    RetopoFlow_Sources,
    RetopoFlow_Spaces,
    RetopoFlow_States,
    RetopoFlow_Target,
    RetopoFlow_Tools,
    RetopoFlow_UI,
    RetopoFlow_Undo,
):

    instance = None

    default_keymap = default_rf_keymaps

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
        # make sure we have source meshes
        if not cls.get_sources(): return False
        # all seems good!
        return True

    def start(self):
        self.store_window_state()
        RetopoFlow.instance = self
        bpy.ops.object.mode_set(mode='OBJECT')

        # get scaling factor to fit all sources into unit box
        print('RetopoFlow: setting up scaling factor')
        self.unit_scaling_factor = self.get_unit_scaling_factor()
        print('Unit scaling factor:', self.unit_scaling_factor)
        self.scale_to_unit_box()

        print('RetopoFlow: setting up target')
        self.setup_target()
        print('RetopoFlow: setting up source(s)')
        self.setup_sources()
        print('RetopoFlow: setting up source(s) symmetry')
        self.setup_sources_symmetry()   # must be called after self.setup_target()!!
        print('RetopoFlow: setting up rotation target')
        self.setup_rotate_about_active()

        print('RetopoFlow: setting up states')
        self.setup_states()
        print('RetopoFlow: setting up rftools')
        self.setup_rftools()
        print('RetopoFlow: setting up grease')
        self.setup_grease()
        print('RetopoFlow: setting up ui')
        self.setup_ui()                 # must be called after self.setup_target() and self.setup_rftools()!!
        print('RetopoFlow: setting up undo')
        self.setup_undo()               # must be called after self.setup_ui()!!

        print('RetopoFlow: done with start')

    def end(self):
        self.blender_ui_reset()
        # self.end_rotate_about_active()
        # self.teardown_target()
        # self.unscale_from_unit_box()
        # bpy.ops.object.mode_set(mode='EDIT')
        # self.restore_window_state()
        self.tar_object = None
        RetopoFlow.instance = None

