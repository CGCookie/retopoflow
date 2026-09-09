'''
Copyright (C) 2023 CG Cookie

https://github.com/CGCookie/retopoflow

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

import math
import random

import bpy
from bpy.types import SpaceView3D
from mathutils import Matrix

from ..common import gpustate
from ..common.globals import Globals
from ..common.gpustate import ScissorStack
from ..common.blender import bversion, tag_redraw_all, get_view3d_area, get_view3d_region, get_view3d_space
from ..common.decorators import blender_version_wrapper
from ..common.debug import debugger, tprint
from ..common.drawing import Drawing, DrawCallbacks
from ..common.ui_core_images import preload_image
from ..common.ui_document import UI_Document


if not bpy.app.background:
    import gpu
    from gpu_extras.batch import batch_for_shader

    # https://docs.blender.org/api/blender2.8/gpu.html#triangle-with-custom-shader
    cover_vshader = '''
        in vec2 position;
        void main() {
            gl_Position = vec4(position, 0.0f, 1.0f);
        }
    '''
    cover_fshader = '''
        uniform float darken;
        out vec4 outColor;
        void main() {
            // float r = length(gl_FragCoord.xy - vec2(0.5, 0.5));
            if(mod(floor(gl_FragCoord.x+gl_FragCoord.y), 2.0) == 0) {
                outColor = vec4(0.0,0.0,0.0,1.0);
            } else {
                outColor = vec4(0.0f, 0.0f, 0.0f, darken);
            }
        }
    '''
    Drawing.glCheckError(f'Pre-compile check: cover shader')
    shader, _ = gpustate.gpu_shader(f'blender ui cover', cover_vshader, cover_fshader)
    Drawing.glCheckError(f'Post-compile check: cover shader')

    # create batch to draw large triangle that covers entire clip space (-1,-1)--(+1,+1)
    batch_full = batch_for_shader(shader, 'TRIS', {"position": [(-100, -100), (300, -100), (-100, 300)]})



class CookieCutter_UI:
    '''
    Assumes that direct subclass will have singleton instance (shared CookieCutter among all instances of that subclass and any subclasses)
    '''

    def _cc_ui_init(self):
        # preload images
        preload_image(
            'checkmark.png', 'close.png', 'collapse_close.png', 'collapse_open.png', 'radio.png'
        )
        self.document = Globals.ui_document # UI_Document(self.context)
        self.document.init(self.context)
        self.document.add_exception_callback(lambda e: self._handle_exception(e, 'handle exception caught by UI'))
        self.drawing = Globals.drawing
        area = get_view3d_area()
        space = get_view3d_space()
        region = get_view3d_region()
        self.drawing.set_region(area, space, region, space.region_3d, bpy.context.window)
        self.drawcallbacks = DrawCallbacks(self)
        self._cc_blenderui_init()
        self._ignore_ui_events = False
        self._hover_ui = False
        tag_redraw_all('CC ui_init', only_tag=False)

    @property
    def ignore_ui_events(self):
        return self._ignore_ui_events
    @ignore_ui_events.setter
    def ignore_ui_events(self, v):
        self._ignore_ui_events = bool(v)

    @staticmethod
    def _cc_ui_orphan_recover():
        # subclasses override to put Blender back the way the session found it after the
        # operator's RNA dies underneath a live session.  MUST stay a staticmethod: a bound
        # method would raise ReferenceError the moment the orphan path tried to call it.
        pass

    def _cc_ui_start(self):
        # the handles live in this closure rather than on self, and unhooking goes through
        # it too.  if the operator's RNA is freed while these handlers are still hooked up
        # -- an add-on hot reload during a session -- then *every* attribute read on self
        # raises ReferenceError, including the ones needed to unhook or to report the error.
        handles  = []
        orphaned = []
        # captured while self is still alive: the region-darken covers are hooked to every
        # space type and would otherwise leave the whole editor dimmed with no way back.
        # region_darken/region_restore keep this list's identity stable so it stays current.
        if not hasattr(self, '_postpixel_callbacks'): self._postpixel_callbacks = []
        covers = self._postpixel_callbacks
        # a staticmethod read off the instance is a plain function, so it still works after
        # the RNA is gone -- unlike anything bound
        recover = getattr(self, '_cc_ui_orphan_recover')

        def unhook():
            space = bpy.types.SpaceView3D
            while handles: space.draw_handler_remove(handles.pop(), 'WINDOW')
            while covers:
                (s, a, cb) = covers.pop()
                try: s.draw_handler_remove(cb, a)
                except Exception: pass
            return None                         # do not repeat, when run as a timer

        def orphan_cleanup():
            unhook()
            try: recover()
            except Exception as e: print(f'CookieCutter: orphan recovery failed: {e}')
            tag_redraw_all('CC orphan cleanup', only_tag=False)
            return None

        def orphan():
            # self is unusable, so there is nothing to report through -- and nothing to do
            # but shut the session down from the outside.  it has to be deferred: unhooking
            # a later draw handler from inside a draw callback frees a node Blender's draw
            # loop still holds.
            if orphaned: return
            orphaned.append(True)
            print('CookieCutter: draw handlers outlived their operator; shutting session down')
            bpy.app.timers.register(orphan_cleanup, first_interval=0)

        def preview():
            if orphaned: return
            try: self.drawcallbacks.pre3d()
            except ReferenceError: orphan()
            except Exception as e:
                self._handle_exception(e, 'draw pre3d')
                ScissorStack.end(force=True)
        def postview():
            # print('***** postview')
            if orphaned: return
            try: self.drawcallbacks.post3d()
            except ReferenceError: orphan()
            except Exception as e:
                self._handle_exception(e, 'draw post3d')
                ScissorStack.end(force=True)
        def postpixel():
            # print('***** postpixel')
            if orphaned: return
            gpustate.blend('ALPHA')
            try: self.drawcallbacks.post2d()
            except ReferenceError: return orphan()
            except Exception as e:
                self._handle_exception(e, 'draw post2d')
                ScissorStack.end(force=True)
            try: self.document.draw(self.context)
            except ReferenceError: return orphan()
            except Exception as e:
                self._handle_exception(e, 'draw window UI')
                ScissorStack.end(force=True)
                self._done = True               # consider this a fatal failure

        space = bpy.types.SpaceView3D
        handles.append(space.draw_handler_add(preview,   tuple(), 'WINDOW', 'PRE_VIEW'))
        handles.append(space.draw_handler_add(postview,  tuple(), 'WINDOW', 'POST_VIEW'))
        handles.append(space.draw_handler_add(postpixel, tuple(), 'WINDOW', 'POST_PIXEL'))
        self._cc_ui_unhook = unhook
        tag_redraw_all('CC ui_start', only_tag=False)

    def _cc_ui_update(self):
        self.drawing.update_dpi()
        if self.ignore_ui_events: return False
        ret = self.document.update(self.context, self.event)
        self._hover_ui = ret and 'hover' in ret
        return self._hover_ui

    def _cc_ui_end(self):
        # unhook first: whatever else fails here, the handlers must not outlive the operator
        unhook = getattr(self, '_cc_ui_unhook', None)   # unset if we never reached _cc_ui_start
        if unhook: unhook()
        self._cc_blenderui_end()
        self.region_restore()
        self.context.workspace.status_text_set(None)
        tag_redraw_all('CC ui_end', only_tag=False)


    #########################################
    # Region Darkening

    def _cc_region_draw_cover(self, a):
        gpustate.blend('ALPHA')
        gpustate.depth_test('NONE')
        shader.bind()
        shader.uniform_float("darken", 0.50)
        batch_full.draw(shader)
        gpu.shader.unbind()

    def region_darken(self):
        if hasattr(self, '_region_darkened'): return    # already darkened!
        self._region_darkened = True
        # reuse the list rather than rebinding it: _cc_ui_start captures this exact list so
        # an orphaned handler can still undarken (see the comment there)
        if not hasattr(self, '_postpixel_callbacks'): self._postpixel_callbacks = []

        # darken all spaces
        spaces = [(getattr(bpy.types, n), n) for n in dir(bpy.types) if n.startswith('Space')]
        spaces = [(s,n) for (s,n) in spaces if hasattr(s, 'draw_handler_add')]

        # https://docs.blender.org/api/blender2.8/bpy.types.Region.html#bpy.types.Region.type
        #     ['WINDOW', 'HEADER', 'CHANNELS', 'TEMPORARY', 'UI', 'TOOLS', 'TOOL_PROPS', 'PREVIEW', 'NAVIGATION_BAR', 'EXECUTE']
        # NOTE: b280 has no TOOL_PROPS region for SpaceView3D!
        # handling SpaceView3D differently!
        general_areas  = ['WINDOW', 'HEADER', 'CHANNELS', 'TEMPORARY', 'UI', 'TOOLS', 'TOOL_PROPS', 'PREVIEW', 'HUD', 'NAVIGATION_BAR', 'EXECUTE', 'FOOTER', 'TOOL_HEADER'] #['WINDOW', 'HEADER', 'UI', 'TOOLS', 'NAVIGATION_BAR']
        SpaceView3D_areas = ['TOOLS', 'UI', 'HEADER', 'TOOL_PROPS']

        for (s,n) in spaces:
            areas = SpaceView3D_areas if n == 'SpaceView3D' else general_areas
            for a in areas:
                try:
                    cb = s.draw_handler_add(self._cc_region_draw_cover, (a,), a, 'POST_PIXEL')
                    self._postpixel_callbacks += [(s, a, cb)]
                except:
                    pass

        tag_redraw_all('CC region_darken', only_tag=False)

    def region_restore(self):
        # remove callback handlers
        if hasattr(self, '_postpixel_callbacks'):
            for (s,a,cb) in self._postpixel_callbacks: s.draw_handler_remove(cb, a)
            self._postpixel_callbacks.clear()           # clear, do not rebind: see region_darken
        if hasattr(self, '_region_darkened'):
            del self._region_darkened
        tag_redraw_all('CC region_restore', only_tag=False)


