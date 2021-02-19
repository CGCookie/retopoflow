'''
Copyright (C) 2021 CG Cookie
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

from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor


from .rf.rf_blender       import RetopoFlow_Blender
from .rf.rf_blendersave   import RetopoFlow_BlenderSave
from .rf.rf_drawing       import RetopoFlow_Drawing
from .rf.rf_grease        import RetopoFlow_Grease
from .rf.rf_helpsystem    import RetopoFlow_HelpSystem
from .rf.rf_instrument    import RetopoFlow_Instrumentation
from .rf.rf_sources       import RetopoFlow_Sources
from .rf.rf_spaces        import RetopoFlow_Spaces
from .rf.rf_states        import RetopoFlow_States
from .rf.rf_target        import RetopoFlow_Target
from .rf.rf_tools         import RetopoFlow_Tools
from .rf.rf_ui            import RetopoFlow_UI
from .rf.rf_undo          import RetopoFlow_Undo
from .rf.rf_updatersystem import RetopoFlow_UpdaterSystem

from ..addon_common.common.blender import tag_redraw_all
from ..addon_common.common.decorators import add_cache
from ..addon_common.common.debug import debugger
from ..addon_common.common.globals import Globals
from ..addon_common.common.profiler import profiler
from ..addon_common.common.utils import delay_exec, abspath
from ..addon_common.common.ui_styling import load_defaultstylings
from ..addon_common.common.ui_core import preload_image, set_image_cache, UI_Element
from ..addon_common.common import ui_core
from ..addon_common.common.useractions import ActionHandler
from ..addon_common.cookiecutter.cookiecutter import CookieCutter

from ..config.keymaps import get_keymaps
from ..config.options import options


@add_cache('paused', False)
@add_cache('quit', False)
def preload_help_images(version='thread'):
    # preload help images to allow help to load faster
    path_cur = os.getcwd()
    path_here = os.path.abspath(os.path.dirname(__file__))

    path_images = []
    os.chdir(os.path.join(path_here, '..', 'help'))
    path_images += list(glob.glob('*.png'))
    os.chdir(os.path.join(path_here, '..', 'icons'))
    path_images += list(glob.glob('*.png'))
    os.chdir(os.path.join(path_here, '..', 'addon_common', 'common', 'images'))
    path_images += list(glob.glob('*.png'))
    os.chdir(path_cur)

    if version == 'process':
        # this version spins up new Processes, so Python's GIL isn't an issue
        # :) loading is much FASTER!      (truly parallel loading)
        # :( DIFFICULT to pause or abort  (no shared resources)
        def setter(p):
            if preload_help_images.quit: return
            for path_image, img in p.result():
                if img is None: continue
                print(f'RetopoFlow: {path_image} is preloaded')
                set_image_cache(path_image, img)
        executor = ProcessPoolExecutor() # ThreadPoolExecutor()
        for path_image in path_images:
            p = executor.submit(preload_image, path_image)
            p.add_done_callback(setter)
        def abort():
            nonlocal executor
            preload_help_images.quit = True
            # the following line causes a crash :(
            # executor.shutdown(wait=False)
        atexit.register(abort)

    elif version == 'thread':
        # this version spins up new Threads, so Python's GIL is used
        # :( loading is much SLOWER!  (serial loading)
        # :) EASY to pause and abort  (shared resources)
        def abort():
            preload_help_images.quit = True
        atexit.register(abort)
        def start():
            for png in path_images:
                print(f'RetopoFlow: preloading image "{png}"')
                preload_image(png)
                time.sleep(0.5)
                for loop in range(10):
                    if not preload_help_images.paused: break
                    if preload_help_images.quit: break
                    time.sleep(0.5)
                else:
                    # if looped too many times, just quit
                    return
                if preload_help_images.quit:
                    return
            print(f'RetopoFlow: all images preloaded')
        ThreadPoolExecutor().submit(start)


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

    @CookieCutter.FSM_State('loading', 'enter')
    def setup_next_stage_enter(self):
        win = UI_Element.fromHTMLFile(abspath('rf/loading_dialog.html'))[0]
        self.document.body.append_child(win)

        d = {}
        d['working'] = False
        d['timer'] = self.actions.start_timer(120)
        d['ui_window'] = win
        d['ui_div'] = win.getElementById('loadingdiv')
        d['i_stage'] = 0
        d['i_step'] = 0
        d['time'] = 0           # will be updated to current time
        d['delay'] = 0.001
        d['stages'] = [
            ('Pausing help image preloading',       self.preload_help_pause),
            ('Setting up target mesh',              self.setup_target),
            ('Setting up source mesh(es)',          self.setup_sources),
            ('Setting up symmetry data structures', self.setup_sources_symmetry),    # must be called after self.setup_target()!!
            ('Setting up rotation target',          self.setup_rotate_about_active),
            ('Setting up RetopoFlow states',        self.setup_states),
            ('Setting up RetopoFlow tools',         self.setup_rftools),
            ('Setting up grease marks',             self.setup_grease),
            ('Setting up visualizations',           self.setup_drawing),
            ('Setting up user interface',           self.setup_ui),                  # must be called after self.setup_target() and self.setup_rftools()!!
            ('Setting up undo system',              self.setup_undo),                # must be called after self.setup_ui()!!
            ('Checking auto save / save',           self.check_auto_save_warnings),
            ('Loading welcome message',             self.show_welcome_message),
            ('Resuming help image preloading',      self.preload_help_resume),
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
                print(f'RetopoFlow: {stage_name} ({time.time()-d["time"]})')
                d['ui_div'].set_markdown(mdown=stage_name)
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
            self.document.body.delete_child(d['ui_window'])
            d['timer'].done()
        d['working'] = False

    def preload_help_pause(self):
        preload_help_images.paused = True

    def preload_help_resume(self):
        preload_help_images.paused = False

    def start(self):
        ui_core.ASYNC_IMAGE_LOADING = options['async image loading']

        self.loading_done = False

        self.undo, self.redo = [], []   # hack to work around issue #949

        keymaps = get_keymaps()
        self.actions = ActionHandler(self.context, keymaps)

        self.context.workspace.status_text_set_internal('RetopoFlow is loading...')

        self.store_window_state(self.actions.r3d, self.actions.space)
        RetopoFlow.instance = self

        self.scene_scale_set(1.0)

        # DO THESE BEFORE SWITCHING TO OBJECT MODE BELOW AND BEFORE SETTING UP SOURCES AND TARGET!
        self.src_objects = self.get_sources()
        self.tar_object = self.get_target()

        # bpy.context.object.update_from_editmode()
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
        options.clear_callbacks()
        self.blender_ui_reset()
        self.undo_clear(touch=False)
        self.done_target()
        self.done_sources()
        # one more toggle, because done_target() might push to target mesh
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.mode_set(mode='EDIT')
        RetopoFlow.instance = None

