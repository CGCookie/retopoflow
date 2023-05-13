'''
Copyright (C) 2022 CG Cookie
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
from ...addon_common.common.drawing import Cursors
from ...addon_common.common.fsm import FSM
from ...addon_common.common.maths import Vec2D, Point2D, RelPoint2D, Direction2D
from ...addon_common.common.profiler import profiler
from ...addon_common.common.ui_core import UI_Element
from ...addon_common.common.utils import normalize_triplequote
from ...config.options import options, retopoflow_files


class RetopoFlow_FSM(CookieCutter): # CookieCutter must be here in order to override fns
    def setup_states(self):
        self.view_version = None
        self._last_rfwidget = None
        self._next_normal_check = 0

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
            self.rftool._callback('view change')
            if self.rftool.rfwidget:
                self.rftool.rfwidget._callback_widget('view change')

        self.actions.hit_pos,self.actions.hit_norm,_,_ = self.raycast_sources_mouse()
        fpsdiv = self.document.body.getElementById('fpsdiv')
        if fpsdiv: fpsdiv.innerText = 'UI FPS: %.2f' % self.document._draw_fps


    def which_pie_menu_section(self):
        delta = self.actions.mouse - self.pie_menu_center
        if delta.length < self.pie_menu_center_size / 2: return None
        count = len(self.pie_menu_options)
        clock_deg = (math.atan2(-delta.y, delta.x) * 180 / math.pi - self.pie_menu_rotation) % 360
        section = math.floor((clock_deg + 360 / count / 2) % 360 / (360 / count))
        return section

    @FSM.on_state('pie menu', 'enter')
    def pie_menu_enter(self):
        size,  size_opt,  size_center  = 512, 72, 100
        size_, size_opt_, size_center_ = self.drawing.scale(size), self.drawing.scale(size_opt), self.drawing.scale(size_center)
        doc_h = self.document.body.height_pixels
        centered = self.actions.mouse - Vec2D((size_ / 2, doc_h - size_ / 2)) # - Vec2D((36, -36))
        ui_pie_menu_contents = self.ui_pie_menu.getElementById('pie-menu-contents')
        ui_pie_menu_contents.clear_children()
        ui_pie_menu_contents.style = f'left:{centered.x}px; top:{centered.y}px; width:{size}px; height:{size}px; border-radius:{int(size/2)}px; padding:{int(size/2)}px'
        count = len(self.pie_menu_options)
        self.ui_pie_sections = []
        for i_option, option in enumerate(self.pie_menu_options):
            if not option:
                self.ui_pie_sections.append(None)
                continue
            if type(option) is str:   option = (option,)
            if type(option) is tuple: option = { k:v for k,v in zip(['text', 'value', 'image'], option) }
            option.setdefault('value', option['text'])
            option.setdefault('image', '')
            self.pie_menu_options[i_option] = option['value']
            r = ((i_option / count) * 360 + self.pie_menu_rotation) * (math.pi / 180)
            left, top = (size_*0.40) * math.cos(r) - (size_opt_/2), -((size_*0.40) * math.sin(r) - (size_opt_/2))
            ui = UI_Element.DIV(
                style=f'left:{int(left)}px; top:{int(top)}px; width:{size_opt}px; height:{size_opt}px',
                classes=f"pie-menu-option {'highlighted' if option['value'] == self.pie_menu_highlighted else ''}",
                children=[
                    UI_Element.DIV(classes='pie-menu-option-text', innerText=option['text']),
                    UI_Element.IMG(classes='pie-menu-option-image', src=option['image'], style=f'width:{size_opt}px')
                ],
                parent=ui_pie_menu_contents,
            )
            self.ui_pie_sections.append(ui)

        UI_Element.DIV(
            style=f'left:{-size_center_/2}px; top:{size_center_/2}px; width:{size_center}px; height:{size_center}px; border-radius:{size_center/2}px',
            classes=f'pie-menu-center',
            parent=ui_pie_menu_contents,
        )

        self.ui_pie_menu.is_visible = True
        self.pie_menu_center = self.actions.mouse
        self.pie_menu_center_size = size_center_
        self.pie_menu_mouse = self.actions.mouse
        self.document.focus(self.ui_pie_menu)
        self.document.force_clean(self.actions.context)

    @FSM.on_state('pie menu')
    def pie_menu_main(self):
        confirm_p = self.actions.pressed('pie menu confirm', ignoremods=True)
        confirm_r = self.actions.released(self.pie_menu_release, ignoremods=True)
        if confirm_p or confirm_r:
            # setting display to none in case callback needs to show some UI
            self.ui_pie_menu.is_visible = False
            i_option = self.which_pie_menu_section()
            option = self.pie_menu_options[i_option] if i_option is not None else None
            if option is not None or self.pie_menu_always_callback:
                self.pie_menu_callback(option)
            return 'main' if confirm_r else 'pie menu wait'
        if self.actions.pressed('cancel'):
            return 'pie menu wait'
        i_section = self.which_pie_menu_section()
        for i_s,ui in enumerate(self.ui_pie_sections):
            if not ui: continue
            if i_s == i_section:
                ui.add_pseudoclass('hover')
            else:
                ui.del_pseudoclass('hover')

    @FSM.on_state('pie menu', 'exit')
    def pie_menu_exit(self):
        self.ui_pie_menu.is_visible = False

    @FSM.on_state('pie menu wait')
    def pie_menu_wait(self):
        if self.actions.released(self.pie_menu_release, ignoremods=True):
            return 'main'

    def should_pass_through(self, context, event):
        return self.actions.using('blender passthrough')

    @FSM.on_state('main')
    def modal_main(self):
        # if self.actions.just_pressed: print('modal_main', self.actions.just_pressed)
        if self.rftool._fsm.state == 'main' and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm.state == 'main'):
            # exit
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

            if self.actions.pressed('pie menu'):
                self.show_pie_menu([
                    {'text':rftool.name, 'image':rftool.icon, 'value':rftool}
                    for rftool in self.rftools
                ], self.select_rftool, highlighted=self.rftool)
                return

            # debugging
            # if self.actions.pressed('SHIFT+F5'): breakit = 42 / 0
            # if self.actions.pressed('SHIFT+F6'): assert False
            # if self.actions.pressed('SHIFT+F7'): self.alert_user(message='Foo', level='exception', msghash='2ec5e386ae05c1abeb66dce8e1f1cb95')
            # if self.actions.pressed('F7'):
            #     assert False, 'test exception throwing'
            #     # self.alert_user(title='Test', message='foo bar', level='warning', msghash=None)
            #     return

            # profiler
            # if self.actions.pressed('SHIFT+F10'):
            #     profiler.clear()
            #     return
            # if self.actions.pressed('SHIFT+F11'):
            #     profiler.printout()
            #     self.document.debug_print()
            #     return

            if self.actions.pressed('reload css'):
                print('RetopoFlow: Reloading stylings')
                self.reload_stylings()
                return

            for rftool in self.rftools:
                if rftool == self.rftool: continue
                if self.actions.pressed(rftool.shortcut):
                    self.select_rftool(rftool)
                    return
                if self.actions.pressed(rftool.quick_shortcut, unpress=False):
                    self.quick_select_rftool(rftool)
                    return 'quick switch'

            # undo/redo
            if self.actions.pressed('blender undo'):
                self.undo_pop()
                if self.rftool: self.rftool._reset()
                return
            if self.actions.pressed('blender redo'):
                self.redo_pop()
                if self.rftool: self.rftool._reset()
                return

            # if self.actions.just_pressed: print('modal_main', self.actions.just_pressed)

            # handle selection
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


    @FSM.on_state('quick switch')
    def quick_switch(self):
        if self.rftool._fsm.state == 'main' and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm.state == 'main'):
            if self.actions.released(self.rftool.quick_shortcut):
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


    def setup_smart_selection_painting(self, bmelem_types, selecting=True, deselect_all=False, fn_filter_bmelem=None, kwargs_select=None, kwargs_deselect=None, kwargs_filter=None, **kwargs):
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
        if not bmelem: return   # nothing there; leave!

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
        self._last_mouse = None
        self.set_accel_defer(True)

    @FSM.on_state('smart selection painting')
    def smart_selection_painting(self):
        if self.actions.pressed('cancel'):
            self.undo_cancel()
            return 'main'
        if not self.actions.using({'select paint', 'select paint add'}, ignoremods=True):
            return 'main'

        opts = self.selection_painting_opts

        if not self.actions.mousemove_stop: return

        bmelem = opts['get']()
        if not bmelem: return
        if bmelem not in opts['path']: return
        if bmelem == opts['lastelem']: return

        opts['lastelem'] = bmelem

        for bme,s in opts['previous']: bme.select = s
        opts['previous'] = []
        while bmelem:
            opts['previous'].append((bmelem, bmelem.select))
            opts['op'](bmelem)
            bmelem = opts['path'][bmelem]

        tag_redraw_all('RF selection_painting')

    @FSM.on_state('smart selection painting', 'exit')
    def smart_selection_painting_exit(self):
        self.selection_painting_opts = None
        self.set_accel_defer(False)


    # def setup_selection_painting(self, bmelem_type, select=None, sel_only=True, deselect_all=False, fn_filter_bmelem=None, kwargs_select=None, kwargs_deselect=None, kwargs_filter=None, **kwargs):
    #     if type(bmelem_type) is str:
    #         accel_nearest2D = {
    #             'vert': self.accel_nearest2D_vert,
    #             'edge': self.accel_nearest2D_edge,
    #             'face': self.accel_nearest2D_face,
    #         }[bmelem_type]
    #     else:
    #         def mix(*args, **kwargs):
    #             bmelem, dist = None, float('inf')
    #             if 'vert' in bmelem_type:
    #                 _bmelem, _dist = self.accel_nearest2D_vert(*args, **kwargs)
    #                 if _bmelem and _dist < dist: bmelem,dist = _bmelem,_dist
    #             if 'edge' in bmelem_type:
    #                 _bmelem, _dist = self.accel_nearest2D_edge(*args, **kwargs)
    #                 if _bmelem and _dist < dist: bmelem,dist = _bmelem,_dist
    #             if 'face' in bmelem_type:
    #                 _bmelem, _dist = self.accel_nearest2D_face(*args, **kwargs)
    #                 if _bmelem and _dist < dist: bmelem,dist = _bmelem,_dist
    #             return bmelem,dist
    #         accel_nearest2D = mix

    #     fn_filter_bmelem = fn_filter_bmelem or (lambda _: True)
    #     kwargs_filter = kwargs_filter or {}
    #     kwargs_select = kwargs_select or {}
    #     kwargs_deselect = kwargs_deselect or {}

    #     def get_bmelem(use_filter=True):
    #         nonlocal accel_nearest2D, fn_filter_bmelem
    #         bmelem, dist = accel_nearest2D(max_dist=options['select dist'])
    #         if not use_filter or not bmelem: return bmelem
    #         return bmelem if fn_filter_bmelem(bmelem, **kwargs_filter) else None

    #     if select is None:
    #         # look at what's under the mouse and check if select add is used
    #         bmelem = get_bmelem(use_filter=False)
    #         if not bmelem: return               # nothing there; leave!
    #         if not bmelem.select: select = True # bmelem is not selected, so we are selecting
    #         else: select = sel_only             # bmelem is selected, so we are deselecting if "select add"
    #         deselect_all = sel_only             # deselect all if not "select add"
    #     else:
    #         bmelem = None

    #     if select:
    #         kwargs.update(kwargs_select)
    #     else:
    #         kwargs.update(kwargs_deselect)

    #     self.selection_painting_opts = {
    #         'select': select,
    #         'get': get_bmelem,
    #         'kwargs': kwargs,
    #     }

    #     self.undo_push('select' if select else 'deselect')
    #     if deselect_all: self.deselect_all()
    #     if bmelem: self.select(bmelem, only=False, **kwargs)

    #     return 'selection painting'

    # @FSM.on_state('selection painting', 'enter')
    # def selection_painting_enter(self):
    #     self._last_mouse = None

    # @FSM.on_state('selection painting')
    # def selection_painting(self):
    #     assert self.selection_painting_opts
    #     if self.actions.mousemove:
    #         tag_redraw_all('RF selection_painting')
    #     if self.actions.pressed('cancel'):
    #         self.selection_painting_opts = None
    #         return 'main'
    #     if not self.actions.using({'select paint', 'select paint add'}, ignoremods=True):
    #         self.selection_painting_opts = None
    #         return 'main'
    #     if self._last_mouse == self.actions.mouse: return
    #     self._last_mouse = self.actions.mouse
    #     bmelem = self.selection_painting_opts['get']()
    #     if not bmelem or bmelem.select == self.selection_painting_opts['select']:
    #         return
    #     if self.selection_painting_opts['select']:
    #         self.select(bmelem, only=False, **self.selection_painting_opts['kwargs'])
    #     else:
    #         self.deselect(bmelem, **self.selection_painting_opts['kwargs'])


