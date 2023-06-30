'''
Copyright (C) 2023 CG Cookie
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
import glob
import time
import atexit

from .rf.rf_blender_objects import RetopoFlow_Blender_Objects
from .rf.rf_blender_save    import RetopoFlow_Blender_Save
from .rf.rf_drawing         import RetopoFlow_Drawing
from .rf.rf_fsm             import RetopoFlow_FSM
from .rf.rf_grease          import RetopoFlow_Grease
from .rf.rf_helpsystem      import RetopoFlow_HelpSystem
from .rf.rf_instrument      import RetopoFlow_Instrumentation
from .rf.rf_normalize       import RetopoFlow_Normalize
from .rf.rf_sources         import RetopoFlow_Sources
from .rf.rf_spaces          import RetopoFlow_Spaces
from .rf.rf_target          import RetopoFlow_Target
from .rf.rf_tools           import RetopoFlow_Tools
from .rf.rf_ui              import RetopoFlow_UI
from .rf.rf_ui_alert        import RetopoFlow_UI_Alert
from .rf.rf_undo            import RetopoFlow_Undo
from .rf.rf_updatersystem   import RetopoFlow_UpdaterSystem

from ..addon_common.common.blender import (
    tag_redraw_all,
    get_path_from_addon_root,
    workspace_duplicate,
    show_error_message, BlenderPopupOperator, BlenderIcon,
    scene_duplicate,
)
from ..addon_common.common import ui_core
from ..addon_common.common.decorators import add_cache
from ..addon_common.common.debug import debugger
from ..addon_common.common.drawing import Drawing, DrawCallbacks
from ..addon_common.common.fsm import FSM
from ..addon_common.common.globals import Globals
from ..addon_common.common.image_preloader import ImagePreloader
from ..addon_common.common.profiler import profiler
from ..addon_common.common.utils import delay_exec, abspath, StopWatch
from ..addon_common.common.ui_styling import load_defaultstylings
from ..addon_common.common.ui_core import UI_Element
from ..addon_common.common.useractions import ActionHandler
from ..addon_common.cookiecutter.cookiecutter import CookieCutter

from ..config.keymaps import get_keymaps
from ..config.options import options, sessionoptions


class RetopoFlow(
    RetopoFlow_Blender_Objects,
    RetopoFlow_Blender_Save,
    RetopoFlow_Drawing,
    RetopoFlow_FSM,
    RetopoFlow_Grease,
    RetopoFlow_HelpSystem,
    RetopoFlow_Instrumentation,
    RetopoFlow_Normalize,
    RetopoFlow_Sources,
    RetopoFlow_Spaces,
    RetopoFlow_Target,
    RetopoFlow_Tools,
    RetopoFlow_UI,
    RetopoFlow_UI_Alert,
    RetopoFlow_Undo,
    RetopoFlow_UpdaterSystem,
):

    instance = None

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
        if not ob.visible_get(): return False
        # make sure we have source meshes
        if not cls.get_sources(): return False
        # all seems good!
        return True


    # def prestart(self):
    #     # duplicate workspace and scene so we can alter (most) settings without need to store/restore
    #     self.workspace = workspace_duplicate(name='RetopoFlow')
    #     self.scene = scene_duplicate(name='RetopoFlow')

    def start(self):
        sw = StopWatch()

        RetopoFlow.instance = self

        keymaps = get_keymaps(force_reload=True)
        self.actions = ActionHandler(self.context, keymaps)

        print(f'RetopoFlow: Starting... keymaps and actions {sw.elapsed():0.2f}')

        # start loading
        self.statusbar_text_set('RetopoFlow is loading...')

        # DO THESE BEFORE SWITCHING TO OBJECT MODE BELOW AND BEFORE SETTING UP SOURCES AND TARGET!
        # we need to store which objects are sources and which is target
        self.mark_sources_target()

        print(f'RetopoFlow: Starting... statusbar and marking {sw.elapsed():0.2f}')

        ui_core.ASYNC_IMAGE_LOADING = options['async image loading']
        self.loading_done = False
        self.init_undo()   # hack to work around issue #949

        print(f'RetopoFlow: Starting... undo {sw.elapsed():0.2f}')

        # self.store_window_state(self.actions.r3d, self.actions.space)

        bpy.ops.object.mode_set(mode='OBJECT')
        self.init_normalize()       # get scaling factor to fit all sources into unit box

        print(f'RetopoFlow: Starting... normalizing {sw.elapsed():0.2f}')

        self.setup_ui_blender()
        print(f'RetopoFlow: Starting... Blender UI {sw.elapsed():0.2f}')
        self.reload_stylings()
        print(f'RetopoFlow: Starting... stylings {sw.elapsed():0.2f}')

        # the rest of setup is handled in `loading` state
        self.fsm.force_set_state('loading')
        print(f'RetopoFlow: Starting Total: {sw.total_elapsed():0.2f}')


    def end(self):
        options.clear_callbacks()
        self.end_normalize(self.context)
        self.blender_ui_reset()
        self.undo_clear()
        self.done_target()
        self.done_sources()
        # one more toggle, because done_target() might push to target mesh
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')
        self.unmark_sources_target()  # DO THIS AS ONE OF LAST
        sessionoptions.clear()
        RetopoFlow.instance = None



    @FSM.on_state('loading', 'enter')
    def setup_next_stage_enter(self):
        win = UI_Element.fromHTMLFile(abspath('html/loading_dialog.html'))[0]
        self.document.body.append_child(win)

        self._setup_data = {
            'timer':      self.actions.start_timer(120),
            'ui_window':  win,
            'ui_div':     win.getElementById('loadingdiv'),
            'broken':     False,    # indicates if a setup stage broke
            'ui_drawn':   False,    # used to know when UI has been drawn
            'i_stage':    -1,       # which stage are we currently on?
            'stage_data': None,     # which stage is to be run
            'stages': [
                ('Pausing help image preloading',       ImagePreloader.pause),
                ('Setting up target mesh',              self.setup_target),
                ('Setting up source mesh(es)',          self.setup_sources),
                ('Setting up symmetry data structures', self.setup_sources_symmetry),    # must be called after self.setup_target()!!
                ('Setting up rotation target',          self.setup_rotate_about_active),
                ('Setting up RetopoFlow states',        self.setup_states),
                ('Setting up RetopoFlow tools',         self.setup_rftools),
                ('Setting up grease marks',             self.setup_grease),
                ('Setting up visualizations',           self.setup_drawing),
                ('Setting up user interface',           self.setup_ui),                  # must be called after self.setup_target() and self.setup_rftools()!!
                ('Setting up undo system',              self.undo_clear),                # must be called after self.setup_ui()!!
                ('Checking auto save / save',           self.check_auto_save_warnings),
                ('Checking target symmetry',            self.check_target_symmetry),
                ('Loading welcome message',             self.show_welcome_message),
                ('Resuming help image preloading',      ImagePreloader.resume),
            ],
        }

    @DrawCallbacks.on_draw('post2d')
    @FSM.onlyinstate('loading')
    def setup_next_stage_drawn(self):
        self._setup_data['ui_drawn'] = True
        tag_redraw_all('allow startup dialog to render')

    @FSM.on_state('loading')
    def setup_next_stage(self):
        tag_redraw_all('allow startup dialog to render')
        d = self._setup_data

        if d['broken']:
            self.done(cancel=True, emergency_bail=True)
            show_error_message(
                [
                    'An unexpected error occurred while trying to start RetopoFlow.',
                    'Please consider reporting this issue so that we can fix it.',
                    BlenderPopupOperator('cgcookie.retopoflow_web_blendermarket', icon='URL'),
                    BlenderPopupOperator('cgcookie.retopoflow_web_github_newissue', icon='URL'),
                ],
                title='RetopoFlow Error',
            )
            return

        if d['stage_data']:
            if not d['ui_drawn']:
                # UI has not been updated yet
                return
            stage_name, stage_fn = d['stage_data']
            d['stage_data'] = None
            start_time = time.time()
            try:
                print(f'RetopoFlow: {stage_name}')
                stage_fn()
                print(f'  elapsed: {(time.time() - start_time):0.2f} secs')
            except Exception as e:
                print(f'RetopoFlow Exception: {e}')
                debugger.print_exception()
                d['broken'] = True
            return

        d['i_stage'] += 1
        if d['i_stage'] == len(d['stages']):
            # done with all stages!
            print('RetopoFlow: done with start')
            self.loading_done = True
            self.fsm.force_set_state('main')
            self.document.body.delete_child(d['ui_window'])
            d['timer'].done()
            return

        # start next stage
        stage_name, stage_fn = d['stages'][d['i_stage']]
        d['ui_drawn'] = False
        d['stage_data'] = (stage_name, stage_fn)
        d['ui_div'].set_markdown(mdown=stage_name)


RetopoFlow.cc_debug_print_to = 'RetopoFlow_Debug'

