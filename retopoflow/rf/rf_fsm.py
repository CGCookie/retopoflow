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
from ...addon_common.common.utils import normalize_triplequote
from ...config.options import options, retopoflow_files
from ...addon_common.common.timerhandler import StopwatchHandler, CallGovernor

class RetopoFlow_FSM(CookieCutter): # CookieCutter must be here in order to override fns
    def setup_states(self):
        self.view_version = None
        self._last_rfwidget = None
        self._next_normal_check = 0
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
            self.rftool._callback('target change')
            if self.rftool.rfwidget:
                self.rftool.rfwidget._callback_widget('target change')
            self.update_ui_geometry()
            tag_redraw_all('RF_States update')

        view_version = self.get_view_version()
        if self.view_version != view_version:
            self.update_view_sessionoptions(self.context)
            self.update_clip_settings(rescale=False)
            self.view_version = view_version
            if not hasattr(self, '_stopwatch_view_change'):
                def callback_view_change():
                    self.rftool._callback('view change')
                    if self.rftool.rfwidget:
                        self.rftool.rfwidget._callback_widget('view change')
                self._stopwatch_view_change = StopwatchHandler(options['view change delay'], callback_view_change)
            self._stopwatch_view_change.reset()

        self.actions.hit_pos,self.actions.hit_norm,_,_ = self.raycast_sources_mouse()
        fpsdiv = self.document.body.getElementById('fpsdiv')
        if fpsdiv: fpsdiv.innerText = f'UI FPS: {self.document._draw_fps:.2f}'


    def should_pass_through(self, context, event):
        return self.actions.using('blender passthrough')

    @FSM.on_state('main')
    def modal_main(self):
        # if self.actions.just_pressed: print('modal_main', self.actions.just_pressed)
        if self.rftool._fsm.state == 'main' and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm.state == 'main'):
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

        ct, nt = time.time(), self._next_normal_check
        if ct > nt:
            self._next_normal_check = ct + 0.25
            self.normal_check()

        if self.rftool.rfwidget:
            Cursors.set(self.rftool.rfwidget.rfw_cursor)
            if self.rftool.rfwidget.redraw_on_mouse:
                if self.actions.mousemove:
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
        self.action_data['timer'] = self.actions.start_timer(120.0)
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
        self.action_data['timer'].done()



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
        opts['timer'] = self.actions.start_timer(120.0)
        opts['mouselast'] = self.actions.mouse
        opts['lasttime'] = 0
        self.rotate_selected_opts = opts
        self.undo_push('rotate')
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
        opts = self.rotate_selected_opts
        opts['timer'].done()
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
        opts['timer'] = self.actions.start_timer(120.0)
        opts['mouselast'] = self.actions.mouse
        opts['lasttime'] = 0
        self.scale_selected_opts = opts
        self.undo_push('scale')
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
        opts = self.scale_selected_opts
        opts['timer'].done()
        self.clear_split_target_visualization()
        self.set_accel_defer(False)


    def select_path(self, bmelem_types, fn_filter_bmelem=None, kwargs_select=None, kwargs_filter=None, **kwargs):
        kwargs_filter = kwargs_filter or {}
        fn_filter = (lambda e: fn_filter_bmelem(e, **kwargs_filter)) if fn_filter_bmelem else (lambda _: True)

        vis_accel = self.get_vis_accel()
        nearest2D_vert = self.accel_nearest2D_vert
        nearest2D_edge = self.accel_nearest2D_edge
        nearest2D_face = self.accel_nearest2D_face

        def get_bmelem(*args, **kwargs):
            nonlocal fn_filter, bmelem_types, vis_accel, nearest2D_vert, nearest2D_edge, nearest2D_face
            if 'vert' in bmelem_types:
                bmelem, _ = nearest2D_vert(*args, vis_accel=vis_accel, **kwargs)
                if bmelem and fn_filter(bmelem): return bmelem
            if 'edge' in bmelem_types:
                bmelem, _ = nearest2D_edge(*args, vis_accel=vis_accel, **kwargs)
                if bmelem and fn_filter(bmelem): return bmelem
            if 'face' in bmelem_types:
                bmelem, _ = nearest2D_face(*args, vis_accel=vis_accel, **kwargs)
                if bmelem and fn_filter(bmelem): return bmelem
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
        kwargs_filter = kwargs_filter or {}
        fn_filter = (lambda e: fn_filter_bmelem(e, **kwargs_filter)) if fn_filter_bmelem else (lambda _: True)

        vis_accel = self.get_vis_accel()
        nearest2D_vert = self.accel_nearest2D_vert
        nearest2D_edge = self.accel_nearest2D_edge
        nearest2D_face = self.accel_nearest2D_face

        def get_bmelem(*args, **kwargs):
            nonlocal fn_filter, bmelem_types, vis_accel, nearest2D_vert, nearest2D_edge, nearest2D_face
            if 'vert' in bmelem_types:
                bmelem, _ = nearest2D_vert(*args, vis_accel=vis_accel, **kwargs)
                if bmelem and fn_filter(bmelem): return bmelem
            if 'edge' in bmelem_types:
                bmelem, _ = nearest2D_edge(*args, vis_accel=vis_accel, **kwargs)
                if bmelem and fn_filter(bmelem): return bmelem
            if 'face' in bmelem_types:
                bmelem, _ = nearest2D_face(*args, vis_accel=vis_accel, **kwargs)
                if bmelem and fn_filter(bmelem): return bmelem
            return None

        bmelem = get_bmelem(max_dist=options['select dist'])  # find what's under the mouse
        if not bmelem:
            # nothing there; either leave or use select tool
            if not use_select_tool:
                return
            rftool_select = next(rftool for rftool in self.rftools if rftool.name=='Select')
            self.quick_select_rftool(rftool_select)
            rftool_select._callback('quickselect start')
            return 'quick switch'

        bmelem_types = { RFVert: {'vert'}, RFEdge: {'edge'}, RFFace: {'face'} }[type(bmelem)]
        selecting |= not bmelem.select              # if not explicitly selecting, start selecting only if elem under mouse is not selected
        kwargs_select   = kwargs_select   or {}
        kwargs_deselect = kwargs_deselect or {}
        kwargs.update(kwargs_select if selecting else kwargs_deselect)
        if selecting: kwargs['only'] = False

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
        while working:
            bme, from_bme = working.popleft()
            if bme in path: continue
            path[bme] = from_bme
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

        op = (lambda e: self.select(e, **kwargs)) if selecting else (lambda e: self.deselect(e, **kwargs))

        self.selection_painting_opts = {
            'bmelem':    bmelem,
            'selecting': selecting,
            'get':       get_bmelem,
            'kwargs':    kwargs,
            'path':      path,
            'op':        op,
            'deselect':  deselect_all,
            'previous':  [],
            'lastelem':  None,
        }

        self.undo_push('smart select' if selecting else 'smart deselect')
        if deselect_all: self.deselect_all()
        op(bmelem)

        return 'smart selection painting'

    @FSM.on_state('smart selection painting', 'enter')
    def smart_selection_painting_enter(self):
        self.fast_update_timer.start()
        self.set_accel_defer(True)


    @DrawCallbacks.on_draw('predraw')
    @FSM.onlyinstate('smart selection painting')
    def unpause_smart_selection_painting_update(self):
        self.smart_selection_painting_update.unpause()

    @CallGovernor.limit(pause_after_call=True)
    def smart_selection_painting_update(self):
        opts = self.selection_painting_opts

        bmelem = opts['get']()
        if not bmelem: return
        if bmelem not in opts['path']: return
        if bmelem == opts['lastelem']: return

        opts['lastelem'] = bmelem

        for (bme, s) in opts['previous']: bme.select = s
        opts['previous'] = []
        while bmelem:
            opts['previous'].append((bmelem, bmelem.select))
            opts['op'](bmelem)
            bmelem = opts['path'][bmelem]

        tag_redraw_all('RF selection_painting')


    @FSM.on_state('smart selection painting')
    def smart_selection_painting(self):
        if self.actions.pressed('cancel'):
            self.undo_cancel()
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
        self.set_accel_defer(False)

