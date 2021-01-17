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

import math
import time
import random

from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.drawing import Cursors
from ...addon_common.common.maths import Vec2D, Point2D, RelPoint2D, Direction2D
from ...addon_common.common.profiler import profiler
from ...addon_common.cookiecutter.cookiecutter import CookieCutter
from ...config.options import options


class RetopoFlow_States(CookieCutter):
    def setup_states(self):
        self.view_version = None
        self._last_rfwidget = None
        self._next_normal_check = 0

    def update(self, timer=True):
        if not self.loading_done:
            # calling self.fsm.update() in case mouse is hovering over ui
            self.fsm.update()
            return

        options.clean()

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
            self.view_version = view_version
            self.rftool._callback('view change')
            if self.rftool.rfwidget:
                self.rftool.rfwidget._callback_widget('view change')

        self.actions.hit_pos,self.actions.hit_norm,_,_ = self.raycast_sources_mouse()
        fpsdiv = self.document.body.getElementById('fpsdiv')
        if fpsdiv: fpsdiv.innerText = 'UI FPS: %.2f' % self.document._draw_fps


    def which_pie_menu_section(self):
        delta = self.actions.mouse - self.pie_menu_center
        angle = math.floor(-(math.atan2(delta.y, delta.x) * 180 / math.pi - 90 - 360 / 16) % 360 / (360 / 8))
        return None if delta.length < self.drawing.scale(50) else angle

    @CookieCutter.FSM_State('pie menu', 'enter')
    def pie_menu_enter(self):
        options = self.pie_menu_options
        dial = {
            1: [0],
            2: [0, 4],
            3: [0, 3, 5],
            4: [0, 2, 4, 6],
            5: [0, 2, 3, 4, 6],
            6: [7, 0, 1, 3, 4, 5],
            7: [0, 2, 3, 4, 5, 6, 7],
            8: [0, 1, 2, 3, 4, 5, 6, 7],
        }[len(options)]
        self.pie_menu_options = [None] * 8
        for (sct,text,img) in self.ui_pie_sections:
            text.innerText = ''
            sct.style = 'display:none'
            img.src = ''
            sct.del_pseudoclass('hover')
            sct.del_class('highlighted')
        for i_option, i_section in enumerate(dial):
            option = options[i_option]
            (sct,text,img) = self.ui_pie_sections[i_section]
            if option is None: continue
            if type(option) is str: option = {'text':option, 'value':option}
            elif type(option) is tuple: option = {'text':option[0], 'value':option[1]}
            text.innerText = option['text']
            sct.style = ''
            if option['value'] == self.pie_menu_highlighted:
                sct.add_class('highlighted')
            if option.get('image', None):
                img.src = option['image']
                img.dirty()
            self.pie_menu_options[i_section] = option['value']

        self.ui_pie_menu.is_visible = True
        self.document.force_clean(self.actions.context)
        doc_h = self.document.body.height_pixels
        # NOTE: I DO NOT KNOW WHY self.ui_pie_table.width_pixels DOES NOT RETURN THE CORRECT THING!
        centered = self.actions.mouse - Vec2D((self.ui_pie_table.height_pixels / 2, doc_h - self.ui_pie_table.height_pixels / 2))
        self.pie_menu_center = self.actions.mouse
        self.ui_pie_table.style = f'left: {centered.x}px; top: {centered.y}px;'
        self.pie_menu_mouse = self.actions.mouse
        self.document.focus(self.ui_pie_menu)

        self.document.force_clean(self.actions.context)
        # self.document.center_on_mouse(self.ui_pie_table)
        # self.document.sticky_element = win

    @CookieCutter.FSM_State('pie menu')
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
        for i_s,(sct,text,img) in enumerate(self.ui_pie_sections):
            if i_s == i_section:
                sct.add_pseudoclass('hover')
            else:
                sct.del_pseudoclass('hover')

    @CookieCutter.FSM_State('pie menu', 'exit')
    def pie_menu_exit(self):
        self.ui_pie_menu.is_visible = False

    @CookieCutter.FSM_State('pie menu wait')
    def pie_menu_wait(self):
        if self.actions.released(self.pie_menu_release, ignoremods=True):
            return 'main'


    @CookieCutter.FSM_State('main')
    def modal_main(self):
        # if self.actions.just_pressed: print('modal_main', self.actions.just_pressed)
        if self.rftool._fsm.state == 'main' and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm.state == 'main'):
            if self.actions.pressed({'done'}):
                if options['confirm tab quit']:
                    self.show_quit_dialog()
                else:
                    self.done()
                return
            if options['escape to quit'] and self.actions.pressed({'done alt0'}):
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
                hide = self.ui_main.is_visible or self.ui_tiny.is_visible
                if hide:
                    self._reshow_main = self.ui_main.is_visible
                    self.ui_main.is_visible = False
                    self.ui_tiny.is_visible = False
                    self.ui_options.is_visible = False
                    self.ui_geometry.is_visible = False
                else:
                    if self._reshow_main:
                        self.ui_main.is_visible = True
                    else:
                        self.ui_tiny.is_visible = True
                    self.ui_options.is_visible = self.ui_show_options.disabled
                    self.ui_geometry.is_visible = self.ui_show_geometry.disabled
                return

            if self.actions.pressed('pie menu'):
                self.show_pie_menu([{'text':rftool.name, 'image':rftool.icon, 'value':rftool} for rftool in self.rftools], self.select_rftool, highlighted=self.rftool)
                return

            # if self.actions.pressed('SHIFT+F5'): breakit = 42 / 0
            # if self.actions.pressed('SHIFT+F6'): assert False

            if self.actions.pressed('SHIFT+F10'):
                profiler.clear()
                return
            if self.actions.pressed('SHIFT+F11'):
                profiler.printout()
                self.document.debug_print()
                return
            if self.actions.pressed('F12'):
                print('RetopoFlow: Reloading stylings')
                self.reload_stylings()
                return

            for rftool in self.rftools:
                if not rftool.shortcut: continue
                if self.actions.pressed(rftool.shortcut):
                    self.select_rftool(rftool)
                    return

            # if self.actions.pressed('F7'):
            #     assert False, 'test exception throwing'
            #     # self.alert_user(title='Test', message='foo bar', level='warning', msghash=None)
            #     return

            # handle undo/redo
            if self.actions.pressed('blender undo'):
                self.undo_pop()
                if self.rftool: self.rftool._reset()
                return
            if self.actions.pressed('blender redo'):
                self.redo_pop()
                if self.rftool: self.rftool._reset()
                return

            # handle selection
            # if self.actions.just_pressed: print('modal_main', self.actions.just_pressed)
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

            if self.actions.pressed('delete'):
                self.show_delete_dialog()
                return

            if self.actions.pressed('delete pie menu'):
                def callback(option):
                    if not option: return
                    self.delete_dissolve_option(option)
                self.show_pie_menu([
                    ('Delete Verts',   ('Delete',   'Vertices')),
                    ('Delete Edges',   ('Delete',   'Edges')),
                    ('Delete Faces',   ('Delete',   'Faces')),
                    ('Dissolve Faces', ('Dissolve', 'Faces')),
                    ('Dissolve Edges', ('Dissolve', 'Edges')),
                    ('Dissolve Verts', ('Dissolve', 'Vertices')),
                    #'Dissolve Loops',
                ], callback, release='delete pie menu', always_callback=True)
                return

            if self.actions.pressed('smooth edge flow'):
                self.smooth_edge_flow(iterations=options['smooth edge flow iterations'])
                return


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


    def setup_action(self, pt0, pt1, fn_callback, done_pressed=None, done_released=None, cancel_pressed=None):
        v01 = pt1 - pt0
        self.action_data = {
            'p0': pt0, 'p1': pt1, 'v01': v01,
            'fn callback': fn_callback,
            'done pressed': done_pressed, 'done released': done_released, 'cancel pressed': cancel_pressed,
            'val': lambda p: v01.dot(p - pt0),
        }
        return 'action handler'

    @CookieCutter.FSM_State('action handler', 'enter')
    def action_handler_enter(self):
        assert self.action_data
        self.undo_push('action handler')
        self.action_data['timer'] = self.actions.start_timer(120.0)
        self.action_data['mouse'] = self.actions.mouse
        self.action_data['val start'] = self.action_data['val'](self.actions.mouse)

    @CookieCutter.FSM_State('action handler')
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

    @CookieCutter.FSM_State('action handler', 'exit')
    def action_handler_exit(self):
        self.action_data['timer'].done()



    @CookieCutter.FSM_State('rotate selected', 'can enter')
    @profiler.function
    def rotate_selected_canenter(self):
        if not self.get_selected_verts(): return False

    @CookieCutter.FSM_State('rotate selected', 'enter')
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
        self.rotate_selected_opts = opts
        self.undo_push('rotate')

    @CookieCutter.FSM_State('rotate selected')
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
        opts['mouselast'] = self.actions.mouse

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

    @CookieCutter.FSM_State('rotate selected', 'exit')
    def rotate_selected_exit(self):
        opts = self.rotate_selected_opts
        opts['timer'].done()



    @CookieCutter.FSM_State('scale selected', 'can enter')
    @profiler.function
    def scale_selected_canenter(self):
        if not self.get_selected_verts(): return False

    @CookieCutter.FSM_State('scale selected', 'enter')
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
        self.scale_selected_opts = opts
        self.undo_push('scale')

    @CookieCutter.FSM_State('scale selected')
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
        opts['mouselast'] = self.actions.mouse

        dist = (self.actions.mouse - opts['center']).length

        set2D_vert = self.set2D_vert
        for bmv,xy in opts['bmverts']:
            if not bmv.is_valid: continue
            dxy = xy - opts['center']
            nxy = dxy * dist / opts['start_dist'] + opts['center']
            set2D_vert(bmv, nxy)
        self.update_verts_faces(v for v,_ in opts['bmverts'])
        self.dirty()

    @CookieCutter.FSM_State('scale selected', 'exit')
    def scale_selected_exit(self):
        opts = self.scale_selected_opts
        opts['timer'].done()




    def setup_selection_painting(self, bmelem_type, select=None, sel_only=True, deselect_all=False, fn_filter_bmelem=None, kwargs_select=None, kwargs_deselect=None, kwargs_filter=None, **kwargs):
        if type(bmelem_type) is str:
            accel_nearest2D = {
                'vert': self.accel_nearest2D_vert,
                'edge': self.accel_nearest2D_edge,
                'face': self.accel_nearest2D_face,
            }[bmelem_type]
        else:
            def mix(*args, **kwargs):
                bmelem, dist = None, float('inf')
                if 'vert' in bmelem_type:
                    _bmelem, _dist = self.accel_nearest2D_vert(*args, **kwargs)
                    if _bmelem and _dist < dist: bmelem,dist = _bmelem,_dist
                if 'edge' in bmelem_type:
                    _bmelem, _dist = self.accel_nearest2D_edge(*args, **kwargs)
                    if _bmelem and _dist < dist: bmelem,dist = _bmelem,_dist
                if 'face' in bmelem_type:
                    _bmelem, _dist = self.accel_nearest2D_face(*args, **kwargs)
                    if _bmelem and _dist < dist: bmelem,dist = _bmelem,_dist
                return bmelem,dist
            accel_nearest2D = mix

        fn_filter_bmelem = fn_filter_bmelem or (lambda _: True)
        kwargs_filter = kwargs_filter or {}
        kwargs_select = kwargs_select or {}
        kwargs_deselect = kwargs_deselect or {}

        def get_bmelem(use_filter=True):
            nonlocal accel_nearest2D, fn_filter_bmelem
            bmelem, dist = accel_nearest2D(max_dist=options['select dist'])
            if not use_filter or not bmelem: return bmelem
            return bmelem if fn_filter_bmelem(bmelem, **kwargs_filter) else None

        if select is None:
            # look at what's under the mouse and check if select add is used
            bmelem = get_bmelem(use_filter=False)
            if not bmelem: return               # nothing there; leave!
            if not bmelem.select: select = True # bmelem is not selected, so we are selecting
            else: select = sel_only             # bmelem is selected, so we are deselecting if "select add"
            deselect_all = sel_only             # deselect all if not "select add"
        else:
            bmelem = None

        if select:
            kwargs.update(kwargs_select)
        else:
            kwargs.update(kwargs_deselect)

        self.selection_painting_opts = {
            'select': select,
            'get': get_bmelem,
            'kwargs': kwargs,
        }

        self.undo_push('select' if select else 'deselect')
        if deselect_all: self.deselect_all()
        if bmelem: self.select(bmelem, only=False, **kwargs)

        return 'selection painting'

    @CookieCutter.FSM_State('selection painting', 'enter')
    def selection_painting_enter(self):
        self._last_mouse = None

    @CookieCutter.FSM_State('selection painting')
    def selection_painting(self):
        assert self.selection_painting_opts
        if self.actions.mousemove:
            tag_redraw_all('RF selection_painting')
        if self.actions.pressed('cancel'):
            self.selection_painting_opts = None
            return 'main'
        if not self.actions.using({'select paint', 'select paint add'}, ignoremods=True):
            self.selection_painting_opts = None
            return 'main'
        if self._last_mouse == self.actions.mouse: return
        self._last_mouse = self.actions.mouse
        bmelem = self.selection_painting_opts['get']()
        if not bmelem or bmelem.select == self.selection_painting_opts['select']:
            return
        if self.selection_painting_opts['select']:
            self.select(bmelem, only=False, **self.selection_painting_opts['kwargs'])
        else:
            self.deselect(bmelem, **self.selection_painting_opts['kwargs'])


