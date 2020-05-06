'''
Copyright (C) 2020 CG Cookie
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
import time

from concurrent.futures import ThreadPoolExecutor


from .rf.rf_blender     import RetopoFlow_Blender
from .rf.rf_blendersave import RetopoFlow_BlenderSave
from .rf.rf_drawing     import RetopoFlow_Drawing
from .rf.rf_grease      import RetopoFlow_Grease
from .rf.rf_helpsystem  import RetopoFlow_HelpSystem
from .rf.rf_instrument  import RetopoFlow_Instrumentation
from .rf.rf_sources     import RetopoFlow_Sources
from .rf.rf_spaces      import RetopoFlow_Spaces
from .rf.rf_states      import RetopoFlow_States
from .rf.rf_target      import RetopoFlow_Target
from .rf.rf_tools       import RetopoFlow_Tools
from .rf.rf_ui          import RetopoFlow_UI
from .rf.rf_undo        import RetopoFlow_Undo

from ..addon_common.common import ui
from ..addon_common.common.blender import tag_redraw_all
from ..addon_common.common.debug import debugger
from ..addon_common.common.globals import Globals
from ..addon_common.common.profiler import profiler
from ..addon_common.common.utils import delay_exec
from ..addon_common.common.ui_styling import load_defaultstylings
from ..addon_common.cookiecutter.cookiecutter import CookieCutter

from ..config.keymaps import default_rf_keymaps
from ..config.options import options


class RetopoFlow_OpenHelpSystem(CookieCutter, RetopoFlow_HelpSystem):
    @classmethod
    def can_start(cls, context):
        return True

    def blender_ui_set(self):
        self.viewaa_simplify()
        # self.manipulator_hide()
        self.panels_hide()
        # self.overlays_hide()
        self.region_darken()
        self.header_text_set('RetopoFlow')

    def start(self):
        self.reload_stylings()
        self.blender_ui_set()
        self.helpsystem_open(self.rf_startdoc, done_on_esc=True)
        Globals.ui_document.body.dirty('changed document size', children=True)

    def end(self):
        self._cc_blenderui_end()

    @CookieCutter.FSM_State('main')
    def main(self):
        if self.actions.pressed({'ESC'}):
            self.done()
            return
        if self.actions.pressed({'F10'}):
            self.reload_stylings()
            return


class RetopoFlow(
    RetopoFlow_Blender,
    RetopoFlow_BlenderSave,
    RetopoFlow_Drawing,
    RetopoFlow_Grease,
    RetopoFlow_HelpSystem,
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

    @CookieCutter.FSM_State('loading', 'enter')
    def setup_next_stage_enter(self):
        d = {}
        d['working'] = False
        d['timer'] = self.actions.start_timer(30)
        d['ui_window'] = ui.framed_dialog(label='RetopoFlow is loading...', id='loadingdialog', closeable=False, parent=self.document.body)
        d['ui_div'] = ui.markdown(id='loadingdiv', mdown='Loading...', parent=d['ui_window'])
        d['i_stage'] = 0
        d['i_step'] = 0
        d['time'] = 0           # will be updated to current time
        d['delay'] = 0.05
        d['stages'] = [
            ('target mesh',              self.setup_target),
            ('source mesh(es)',          self.setup_sources),
            ('symmetry data structures', self.setup_sources_symmetry),    # must be called after self.setup_target()!!
            ('rotation target',          self.setup_rotate_about_active),
            ('RetopoFlow states',        self.setup_states),
            ('RetopoFlow tools',         self.setup_rftools),
            ('grease marks',             self.setup_grease),
            ('drawing callbacks',        self.setup_drawing),
            ('user interface',           self.setup_ui),                  # must be called after self.setup_target() and self.setup_rftools()!!
            ('undo system',              self.setup_undo),                # must be called after self.setup_ui()!!
        ]
        self._setup_data = d

    @CookieCutter.FSM_State('loading')
    def setup_next_stage(self):
        d = self._setup_data
        if d['working']: return
        if time.time() < d['time'] + d['delay']: return

        d['working'] = True
        try:
            stage_name, stage_fn = d['stages'][d['i_stage']]
            if d['i_step'] == 0:
                print('RetopoFlow: setting up %s' % stage_name)
                ui.set_markdown(d['ui_div'], mdown='Setting up %s' % stage_name)
            else:
                stage_fn()
        except Exception as e:
            debugger.print_exception()
            assert False
        d['i_step'] = (d['i_step'] + 1) % 2
        if d['i_step'] == 0: d['i_stage'] += 1
        d['time'] = time.time()         # record current time
        if d['i_stage'] == len(d['stages']):
            print('RetopoFlow: done with start')
            self.loading_done = True
            self.fsm.force_set_state('main')
            self.document.body.delete_child(d['ui_window']._default_element)
            d['timer'].done()
        d['working'] = False

    def start(self):
        self.loading_done = False

        self.store_window_state()
        RetopoFlow.instance = self
        bpy.ops.object.mode_set(mode='OBJECT')

        # get scaling factor to fit all sources into unit box
        print('RetopoFlow: setting up scaling factor')
        self.unit_scaling_factor = self.get_unit_scaling_factor()
        print('Unit scaling factor:', self.unit_scaling_factor)
        self.scale_to_unit_box()

        self.setup_ui_blender()
        self.reload_stylings()

        # the rest of setup is handled in `loading` state and self.setup_next_stage above
        self.fsm.force_set_state('loading')


    def end(self):
        self.blender_ui_reset()
        self.undo_clear()
        options.clear_callbacks()
        # self.end_rotate_about_active()
        # self.teardown_target()
        # self.unscale_from_unit_box()
        # bpy.ops.object.mode_set(mode='EDIT')
        # self.restore_window_state()
        self.tar_object = None
        RetopoFlow.instance = None

