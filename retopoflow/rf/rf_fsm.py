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

import math
import time
import random
from itertools import chain
from functools import partial
from collections import deque

from ..rfmesh.rfmesh_wrapper import RFVert, RFEdge, RFFace

from ...addon_common.cookiecutter.cookiecutter import CookieCutter
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.drawing import Cursors, DrawCallbacks
from ...addon_common.common.fsm import FSM
from ...addon_common.common.maths import Vec2D, Point2D, RelPoint2D, Direction2D
from ...addon_common.common.profiler import profiler
from ...addon_common.common.ui_core import UI_Element
from ...addon_common.common.utils import normalize_triplequote, Dict
from ...config.options import options, retopoflow_files
from ...addon_common.common.timerhandler import StopwatchHandler, CallGovernor

class RetopoFlow_FSM(CookieCutter): # CookieCutter must be here in order to override fns
    def setup_states(self):
        self.view_version = None
        self._last_rfwidget = None
        self.fast_update_timer = self.actions.start_timer(120.0, enabled=False)

    def update(self, timer=True):
        if not self.loading_done:
            # calling self.fsm.update() in case mouse is hovering over ui
            self.fsm.update()
            return

        options.clean(raise_exception=False)
        if options.write_error and not hasattr(self, '_write_error_reported'):
            # could not write options to file for some reason
            # issue #1070
            self._write_error_reported = True
            message = normalize_triplequote(f'''
                    Could not write options to file (incorrect permissions).

                    Check that you have permission to write to `{retopoflow_files["options filename"]}` to the RetopoFlow add-on folder.

                    Or, try: uninstall RetopoFlow from Blender, restart Blender, then install the latest version of RetopoFlow from the Blender Market.

                    Note: You can continue using RetopoFlow, but any changes to options will not be saved.
                    This error will not be reported again during the current RetopoFlow session.
            ''')
            self.alert_user(message, level='error')

        if timer:
            self.rftool._callback('timer')
            if self.rftool.rfwidget:
                self.rftool.rfwidget._callback_widget('timer')

        if self.rftool.rfwidget != self._last_rfwidget:
            # force redraw when widget changes to clear out any widget drawing
            self._last_rfwidget = self.rftool.rfwidget
            tag_redraw_all('RFWidget change')

        rftarget_version = self.rftarget.get_version()
        if self.rftarget_version != rftarget_version:
            self.rftarget_version = rftarget_version
            self.update_rot_object()
            self.callback_target_change()
            tag_redraw_all('RF_FSM target change')

        view_version = self.get_view_version()
        if self.view_version != view_version:
            self.update_view_sessionoptions(self.context)
            self.update_clip_settings(rescale=False)
            self.view_version = view_version
            self.callback_view_change()
            tag_redraw_all('RF_FSM view change')

        self.actions.hit_pos,self.actions.hit_norm,_,_ = self.raycast_sources_mouse()
        fpsdiv = self.document.body.getElementById('fpsdiv')
        if fpsdiv: fpsdiv.innerText = f'UI FPS: {self.document._draw_fps:.2f}'

    # @CallGovernor.limit(fn_delay=lambda:options['target change delay'])
    def callback_target_change(self):
        # throttling this fn will cause target_change and draw callbacks to get out-of-sync
        # ex: contours depends on data collected in target change callback!
        self.rftool._callback('target change')
        if self.rftool.rfwidget:
            self.rftool.rfwidget._callback_widget('target change')
        self.update_ui_geometry()
        tag_redraw_all('RF_FSM target change')

    @CallGovernor.limit(fn_delay=lambda:options['view change delay'])
    def callback_view_change(self):
        self.rftool._callback('view change')
        if self.rftool.rfwidget:
            self.rftool.rfwidget._callback_widget('view change')
        tag_redraw_all('RF_FSM view change')

    def should_pass_through(self, context, event):
        return self.actions.using('blender passthrough')

    @FSM.on_state('main')
    def modal_main(self):
        # if self.actions.just_pressed: print('modal_main', self.actions.just_pressed)
        if self.rftool._fsm_in_main() and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm_in_main()):
            # handle exit
            if self.actions.pressed('done'):
                if options['confirm tab quit']:
                    self.show_quit_dialog()
                else:
                    self.done()
                return
            if options['escape to quit'] and self.actions.pressed('done alt0'):
                self.done()
                return

            # handle help actions
            if self.actions.pressed('all help'):
                self.helpsystem_open('table_of_contents.md')
                return
            if self.actions.pressed('general help'):
                self.helpsystem_open('general.md')
                return
            if self.actions.pressed('tool help'):
                self.helpsystem_open(self.rftool.help)
                return

            # user wants to save?
            if self.actions.pressed('blender save'):
                self.save_normal()
                return

            # toggle ui
            if self.actions.pressed('toggle ui'):
                # hide ui if main (or minimized main, tiny) is visible
                ui_hide = self.ui_main.is_visible or self.ui_tiny.is_visible
                if ui_hide:
                    self.ui_hide = True
                    self.ui_main.is_visible         = False
                    self.ui_tiny.is_visible         = False
                    self.ui_options.is_visible      = False
                    self.ui_options_min.is_visible  = False
                    self.ui_geometry.is_visible     = False
                    self.ui_geometry_min.is_visible = False
                else:
                    self.ui_main.is_visible         =     options['show main window']
                    self.ui_tiny.is_visible         = not options['show main window']
                    self.ui_options.is_visible      =     options['show options window']
                    self.ui_options_min.is_visible  = not options['show options window']
                    self.ui_geometry.is_visible     =     options['show geometry window']
                    self.ui_geometry_min.is_visible = not options['show geometry window']
                    self.ui_hide = False
                return

            # handle pie menu
            if self.actions.pressed('pie menu'):
                self.show_pie_menu([
                    {'text':rftool.name, 'image':rftool.icon, 'value':rftool}
                    for rftool in self.rftools
                ], self.select_rftool, highlighted=self.rftool)
                return

            # debugging
            if False:
                if self.actions.pressed('SHIFT+F5'): breakit = 42 / 0
                if self.actions.pressed('SHIFT+F6'): assert False
                if self.actions.pressed('SHIFT+F7'): self.alert_user(message='Foo', level='exception', msghash='2ec5e386ae05c1abeb66dce8e1f1cb95')
                if self.actions.pressed('F7'):
                    assert False, 'test exception throwing'
                    # self.alert_user(title='Test', message='foo bar', level='warning', msghash=None)
                    return
                if self.actions.just_pressed: print('modal_main', self.actions.just_pressed)

            # profiler
            if False:
                if self.actions.pressed('SHIFT+F10'):
                    profiler.clear()
                    return
                if self.actions.pressed('SHIFT+F11'):
                    profiler.printout()
                    self.document.debug_print()
                    return

            # reload CSS
            if self.actions.pressed('reload css'):
                print('RetopoFlow: Reloading stylings')
                self.reload_stylings()
                return

            # handle tool switching
            for rftool in self.rftools:
                if rftool == self.rftool: continue
                if self.actions.pressed(rftool.shortcut):
                    self.select_rftool(rftool)
                    return
                if self.actions.pressed(rftool.quick_shortcut, unpress=False):
                    self.quick_select_rftool(rftool)
                    return 'quick switch'

            # handle undo/redo
            if self.actions.pressed('blender undo'):
                self.undo_pop()
                if self.rftool: self.rftool._reset()
                return
            if self.actions.pressed('blender redo'):
                self.redo_pop()
                if self.rftool: self.rftool._reset()
                return

            # handle general selection (each tool will handle specific selection / selection painting)
            if self.actions.pressed('select all'):
                # print('modal_main:selecting all toggle')
                self.undo_push('select all')
                self.select_toggle()
                return
            if self.actions.pressed('deselect all'):
                self.undo_push('deselect all')
                self.deselect_all()
                return
            if self.actions.pressed('select invert'):
                self.undo_push('select invert')
                self.select_invert()
                return
            if self.actions.pressed('select linked'):
                self.undo_push('select linked')
                self.select_linked()
                return
            if self.actions.pressed({'select linked mouse', 'deselect linked mouse'}, unpress=False):
                select = self.actions.pressed('select linked mouse')
                self.actions.unpress()
                bmv,_ = self.accel_nearest2D_vert(max_dist=options['select dist'])
                bme,_ = self.accel_nearest2D_edge(max_dist=options['select dist'])
                bmf,_ = self.accel_nearest2D_face(max_dist=options['select dist'])
                connected_to = bmv or bme or bmf
                if connected_to:
                    self.undo_push('select linked mouse')
                    self.select_linked(connected_to=connected_to, select=select)
                return

            # hide/reveal
            if self.actions.pressed('hide selected'):
                self.hide_selected()
                return
            if self.actions.pressed('hide unselected'):
                self.hide_unselected()
                return
            if self.actions.pressed('reveal hidden'):
                self.reveal_hidden()
                return

            # delete
            if self.actions.pressed('delete'):
                self.show_delete_dialog()
                return
            if self.actions.pressed('delete pie menu'):
                def callback(option):
                    if not option: return
                    self.delete_dissolve_collapse_option(option)
                self.show_pie_menu([
                    ('Delete Verts',   ('Delete',   'Vertices')),
                    ('Delete Edges',   ('Delete',   'Edges')),
                    ('Delete Faces',   ('Delete',   'Faces')),
                    ('Dissolve Faces', ('Dissolve', 'Faces')),
                    ('Dissolve Edges', ('Dissolve', 'Edges')),
                    ('Dissolve Verts', ('Dissolve', 'Vertices')),
                    # ('Collapse Edges & Faces', ('Collapse', 'Edges & Faces')),
                    #'Dissolve Loops',
                ], callback, release='delete pie menu', always_callback=True, rotate=-60)
                return

            # smoothing
            if self.actions.pressed('smooth edge flow'):
                self.smooth_edge_flow(iterations=options['smooth edge flow iterations'])
                return

            # pin/unpin
            if self.actions.pressed('pin'):
                self.pin_selected()
                return
            if self.actions.pressed('unpin'):
                self.unpin_selected()
                return
            if self.actions.pressed('unpin all'):
                self.unpin_all()
                return

        return self.modal_main_rest()

    def modal_main_rest(self):
        self.ignore_ui_events = False

        self.normal_check()  # this call is governed!

        if self.rftool.rfwidget:
            Cursors.set(self.rftool.rfwidget.rfw_cursor)
            if self.rftool.rfwidget.redraw_on_mouse and self.actions.mousemove:
                tag_redraw_all('RFTool.RFWidget.redraw_on_mouse')
            ret = self.rftool.rfwidget._fsm_update()
            if self.fsm.is_state(ret):
                return ret
            if self.rftool.rfwidget._fsm.state != 'main':
                self.ignore_ui_events = True
                return

        ret = self.rftool._fsm_update()
        if self.fsm.is_state(ret):
            self.ignore_ui_events = True
            return ret
        if self.fsm.state != 'main':
            self.ignore_ui_events = True

        if not self.ignore_ui_events:
            self.handle_auto_save()

            if self.actions.pressed('rotate'):
                return 'rotate selected'

            if self.actions.pressed('scale'):
                return 'scale selected'

    @FSM.on_state('quick switch', 'enter')
    def quick_switch_enter(self):
        self._quick_switch_wait = 2

    @FSM.on_state('quick switch')
    def quick_switch(self):
        self._quick_switch_wait -= 1
        if self.rftool._fsm.state == 'main' and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm.state == 'main'):
            if self._quick_switch_wait < 0 and self.actions.released(self.rftool.quick_shortcut):
                return 'main'
        self.modal_main_rest()

    @FSM.on_state('quick switch', 'exit')
    def quick_switch_exit(self):
        self.quick_restore_rftool()


    def setup_action(self, pt0, pt1, fn_callback, done_pressed=None, done_released=None, cancel_pressed=None):
        v01 = pt1 - pt0
        self.action_data = {
            'p0': pt0, 'p1': pt1, 'v01': v01,
            'fn callback': fn_callback,
            'done pressed': done_pressed, 'done released': done_released, 'cancel pressed': cancel_pressed,
            'val': lambda p: v01.dot(p - pt0),
        }
        return 'action handler'

    @FSM.on_state('action handler', 'enter')
    def action_handler_enter(self):
        assert self.action_data
        self.undo_push('action handler')
        self.fast_update_timer.start()
        self.action_data['mouse'] = self.actions.mouse
        self.action_data['val start'] = self.action_data['val'](self.actions.mouse)

    @FSM.on_state('action handler')
    def action_handler(self):
        d = self.action_data
        if self.actions.pressed(d['done pressed']) or self.actions.released(d['done released']):
            self.actions_data = None
            return 'main'
        if self.actions.released(d['cancel pressed']):
            self.undo_pop()
            self.dirty()
            return 'main'
        if not self.actions.mousemove: return
        val = self.action_data['val'](self.actions.mouse)
        self.action_data['fn callback'](val - self.action_data['val start'])
        self.dirty()

    @FSM.on_state('action handler', 'exit')
    def action_handler_exit(self):
        self.fast_update_timer.stop()



    @FSM.on_state('rotate selected', 'can enter')
    @profiler.function
    def rotate_selected_canenter(self):
        if not self.get_selected_verts(): return False

    @FSM.on_state('rotate selected', 'enter')
    def rotate_selected_enter(self):
        bmverts = self.get_selected_verts()
        opts = {}
        opts['bmverts'] = [(bmv, self.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        opts['center'] = RelPoint2D.average(co for _,co in opts['bmverts'])
        opts['rotate_x'] = Direction2D(self.actions.mouse - opts['center'])
        opts['rotate_y'] = Direction2D((-opts['rotate_x'].y, opts['rotate_x'].x))
        opts['move_done_pressed'] = 'confirm'
        opts['move_done_released'] = None
        opts['move_cancelled'] = 'cancel'
        opts['mouselast'] = self.actions.mouse
        opts['lasttime'] = 0
        self.rotate_selected_opts = opts
        self.undo_push('rotate')
        self.fast_update_timer.start()
        self.split_target_visualization_selected()
        self.set_accel_defer(True)

    @FSM.on_state('rotate selected')
    @profiler.function
    def rotate_selected(self):
        opts = self.rotate_selected_opts
        if self.actions.pressed(opts['move_done_pressed']):
            return 'main'
        if self.actions.released(opts['move_done_released']):
            return 'main'
        if self.actions.pressed(opts['move_cancelled']):
            self.undo_cancel()
            self.actions.unuse(opts['move_done_released'], ignoremods=True, ignoremulti=True)
            return 'main'

        if (self.actions.mouse - opts['mouselast']).length == 0: return
        if time.time() < opts['lasttime'] + 0.05: return
        opts['mouselast'] = self.actions.mouse
        opts['lasttime'] = time.time()

        delta = Direction2D(self.actions.mouse - opts['center'])
        dx,dy = opts['rotate_x'].dot(delta),opts['rotate_y'].dot(delta)
        theta = math.atan2(dy, dx)

        set2D_vert = self.set2D_vert
        for bmv,xy in opts['bmverts']:
            if not bmv.is_valid: continue
            dxy = xy - opts['center']
            nx = dxy.x * math.cos(theta) - dxy.y * math.sin(theta)
            ny = dxy.x * math.sin(theta) + dxy.y * math.cos(theta)
            nxy = Point2D((nx, ny)) + opts['center']
            set2D_vert(bmv, nxy)
        self.update_verts_faces(v for v,_ in opts['bmverts'])
        self.dirty()

    @FSM.on_state('rotate selected', 'exit')
    def rotate_selected_exit(self):
        self.fast_update_timer.stop()
        self.clear_split_target_visualization()
        self.set_accel_defer(False)



    @FSM.on_state('scale selected', 'can enter')
    @profiler.function
    def scale_selected_canenter(self):
        if not self.get_selected_verts(): return False

    @FSM.on_state('scale selected', 'enter')
    def scale_selected_enter(self):
        bmverts = self.get_selected_verts()
        opts = {}
        opts['bmverts'] = [(bmv, self.Point_to_Point2D(bmv.co)) for bmv in bmverts]
        opts['center'] = RelPoint2D.average(co for _,co in opts['bmverts'])
        opts['start_dist'] = (self.actions.mouse - opts['center']).length
        opts['move_done_pressed'] = 'confirm'
        opts['move_done_released'] = None
        opts['move_cancelled'] = 'cancel'
        opts['mouselast'] = self.actions.mouse
        opts['lasttime'] = 0
        self.scale_selected_opts = opts
        self.undo_push('scale')
        self.fast_update_timer.start()
        self.split_target_visualization_selected()
        self.set_accel_defer(True)

    @FSM.on_state('scale selected')
    @profiler.function
    def scale_selected(self):
        opts = self.scale_selected_opts
        if self.actions.pressed(opts['move_done_pressed']):
            return 'main'
        if self.actions.released(opts['move_done_released']):
            return 'main'
        if self.actions.pressed(opts['move_cancelled']):
            self.undo_cancel()
            self.actions.unuse(opts['move_done_released'], ignoremods=True, ignoremulti=True)
            return 'main'

        if (self.actions.mouse - opts['mouselast']).length == 0: return
        if time.time() < opts['lasttime'] + 0.05: return
        opts['mouselast'] = self.actions.mouse
        opts['lasttime'] = time.time()

        dist = (self.actions.mouse - opts['center']).length

        set2D_vert = self.set2D_vert
        for bmv,xy in opts['bmverts']:
            if not bmv.is_valid: continue
            dxy = xy - opts['center']
            nxy = dxy * dist / opts['start_dist'] + opts['center']
            set2D_vert(bmv, nxy)
        self.update_verts_faces(v for v,_ in opts['bmverts'])
        self.dirty()

    @FSM.on_state('scale selected', 'exit')
    def scale_selected_exit(self):
        self.fast_update_timer.stop()
        self.clear_split_target_visualization()
        self.set_accel_defer(False)


    def select_path(self, bmelem_types, fn_filter_bmelem=None, kwargs_select=None, kwargs_filter=None, **kwargs):
        vis_accel = self.get_accel_visible()
        nearest2D_vert = self.accel_nearest2D_vert
        nearest2D_edge = self.accel_nearest2D_edge
        nearest2D_face = self.accel_nearest2D_face

        kwargs_filter = kwargs_filter or {}
        def fn_filter(bmelem):
            if not bmelem: return False
            if not fn_filter_bmelem: return True
            return fn_filter_bmelem(bmelem, **kwargs_filter)
        def get_bmelem(*args, **kwargs):
            if 'vert' in bmelem_types:
                bmelem, _ = nearest2D_vert(*args, vis_accel=vis_accel, **kwargs)
                if fn_filter(bmelem): return bmelem
            if 'edge' in bmelem_types:
                bmelem, _ = nearest2D_edge(*args, vis_accel=vis_accel, **kwargs)
                if fn_filter(bmelem): return bmelem
            if 'face' in bmelem_types:
                bmelem, _ = nearest2D_face(*args, vis_accel=vis_accel, **kwargs)
                if fn_filter(bmelem): return bmelem
            return None

        bmelem = get_bmelem(max_dist=options['select dist'])  # find what's under the mouse
        if not bmelem:
            # print('found nothing under mouse')
            return   # nothing there; leave!

        bmelem_types = { RFVert: {'vert'}, RFEdge: {'edge'}, RFFace: {'face'} }[type(bmelem)]
        kwargs_select   = kwargs_select   or {}
        kwargs.update(kwargs_select)
        kwargs['only'] = False

        # find all other visible elements
        vis_elems = self.accel_vis_verts | self.accel_vis_edges | self.accel_vis_faces

        # walk from bmelem to all other connected visible geometry
        path = {}
        working = deque()
        working.append((bmelem, None))
        def add(o, bme):
            nonlocal vis_elems, path, working
            if o not in vis_elems or o in path: return
            if not fn_filter(o): return
            working.append((o, bme))
        closest = None
        while working:
            bme, from_bme = working.popleft()
            if bme in path: continue
            path[bme] = from_bme
            if bme.select:
                # found closest!
                closest = bme
                break
            if 'vert' in bmelem_types:
                for c in bme.link_edges:
                    o = c.other_vert(bme)
                    add(o, bme)
            if 'edge' in bmelem_types:
                for c in bme.verts:
                    for o in c.link_edges:
                        add(o, bme)
            if 'face' in bmelem_types:
                for c in bme.edges:
                    for o in c.link_faces:
                        add(o, bme)

        if not closest:
            # print('could not find closest element')
            return

        self.undo_push('select path')
        while closest:
            self.select(closest, **kwargs)
            closest = path[closest]


    def setup_smart_selection_painting(self, bmelem_types, *, use_select_tool=False, selecting=True, deselect_all=False, fn_filter_bmelem=None, kwargs_select=None, kwargs_deselect=None, kwargs_filter=None, **kwargs):
        vis_accel = self.get_accel_visible()
        nearest2D_vert = self.accel_nearest2D_vert
        nearest2D_edge = self.accel_nearest2D_edge
        nearest2D_face = self.accel_nearest2D_face

        kwargs_filter   = kwargs_filter   or {}
        kwargs_select   = kwargs_select   or {}
        kwargs_deselect = kwargs_deselect or {}

        def fn_filter(bmelem):
            if not bmelem: return False
            if not fn_filter_bmelem: return True
            return fn_filter_bmelem(bmelem, **kwargs_filter)
        def get_bmelem(*args, **kwargs):
            if 'vert' in bmelem_types:
                bmelem, _ = nearest2D_vert(*args, vis_accel=vis_accel, **kwargs)
                if fn_filter(bmelem): return bmelem
            if 'edge' in bmelem_types:
                bmelem, _ = nearest2D_edge(*args, vis_accel=vis_accel, **kwargs)
                if fn_filter(bmelem): return bmelem
            if 'face' in bmelem_types:
                bmelem, _ = nearest2D_face(*args, vis_accel=vis_accel, **kwargs)
                if fn_filter(bmelem): return bmelem
            return None

        bmelem_first = get_bmelem(max_dist=options['select dist'])  # find what's under the mouse
        if not bmelem_first:
            # nothing there; either leave or use select tool
            if not use_select_tool:
                return
            rftool_select = next(rftool for rftool in self.rftools if rftool.name=='Select')
            self.quick_select_rftool(rftool_select)
            rftool_select._callback('quickselect start')
            return 'quick switch'

        bmelem_type, vis_elems = {
            RFVert: ('vert', self.accel_vis_verts),
            RFEdge: ('edge', self.accel_vis_edges),
            RFFace: ('face', self.accel_vis_faces),
        }[type(bmelem_first)]
        bmelem_types = { bmelem_type }          # needed so get_bmelem returns correct type

        selecting |= not bmelem_first.select    # if not explicitly selecting, start selecting only if elem under mouse is not selected
        kwargs.update(kwargs_select if selecting else kwargs_deselect)
        if selecting: kwargs['only'] = False

        # walk from bmelem_first to all other connected visible geometry
        path_to_first = {}
        working = deque()
        def add_to_working(from_bmelem, to_bmelem):
            if to_bmelem not in vis_elems or to_bmelem in path_to_first: return
            if not fn_filter(to_bmelem): return
            working.append((from_bmelem, to_bmelem))
        add_to_working(None, bmelem_first)
        while working:
            from_bmelem, bmelem = working.popleft()
            if bmelem in path_to_first: continue
            path_to_first[bmelem] = from_bmelem
            match bmelem_type:
                case 'vert':
                    for edge in bmelem.link_edges:
                        for vert in edge.verts:
                            add_to_working(bmelem, vert)
                case 'edge':
                    for vert in bmelem.verts:
                        for edge in vert.link_edges:
                            add_to_working(bmelem, edge)
                case 'face':
                    for edge in bmelem.edges:
                        for face in edge.link_faces:
                            add_to_working(bmelem, face)

        fn_select = partial((self.select if selecting else self.deselect), **kwargs)

        self.selection_painting_opts = Dict(
            fn_get_bmelem      = get_bmelem,
            path_to_first      = path_to_first,
            fn_select          = fn_select,
            previous_selection = [],
            last_bmelem        = bmelem_first,
        )

        self.undo_push('smart select' if selecting else 'smart deselect')
        if deselect_all: self.deselect_all()
        fn_select(bmelem_first)

        return 'smart selection painting'

    @FSM.on_state('smart selection painting', 'enter')
    def smart_selection_painting_enter(self):
        self.fast_update_timer.start()
        self.split_target_visualization_visible()
        self.set_accel_defer(True)


    @DrawCallbacks.on_draw('predraw')
    @FSM.onlyinstate('smart selection painting')
    def unpause_smart_selection_painting_update(self):
        self.smart_selection_painting_update.unpause()

    @CallGovernor.limit(pause_after_call=True)
    def smart_selection_painting_update(self):
        opts = self.selection_painting_opts

        bmelem = opts.fn_get_bmelem()
        if not bmelem or bmelem not in opts.path_to_first: return

        # hovering over same bmelem
        if bmelem == opts.last_bmelem: return
        opts.last_bmelem = bmelem

        # reset to previous selection
        for (bme, s) in opts.previous_selection: bme.select = s

        # get bmelems from hovered back to first
        current_selection = []
        while bmelem:
            current_selection.append(bmelem)
            bmelem = opts.path_to_first[bmelem]
        opts.previous_selection = [(bmelem, bmelem.select) for bmelem in current_selection]
        opts.fn_select(current_selection)


    @FSM.on_state('smart selection painting')
    def smart_selection_painting(self):
        if self.actions.pressed('cancel'):
            self.undo_cancel()
            self.actions.unuse('select paint', ignoremods=True, ignoremulti=True)
            self.actions.unuse('select paint add', ignoremods=True, ignoremulti=True)
            return 'main'

        if not self.actions.using({'select paint', 'select paint add'}, ignoremods=True):
            return 'main'

        if self.actions.mousemove:
            self.smart_selection_painting_update()
            tag_redraw_all('RF selection_painting') # needed to force perform update


    @FSM.on_state('smart selection painting', 'exit')
    def smart_selection_painting_exit(self):
        self.selection_painting_opts = None
        self.fast_update_timer.stop()
        self.clear_split_target_visualization()
        self.set_accel_defer(False)

