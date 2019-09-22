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

from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.cookiecutter.cookiecutter import CookieCutter
from ...config.options import options


class RetopoFlow_States(CookieCutter):
    def setup_states(self):
        self.view_version = None

    def update(self):
        self.rftool._callback('timer')
        if self.rftool.rfwidget:
            self.rftool.rfwidget._callback('timer')

        rftarget_version = self.rftarget.get_version()
        if self.rftarget_version != rftarget_version:
            self.rftarget_version = rftarget_version
            self.rftool._callback('target change')
            if self.rftool.rfwidget:
                self.rftool.rfwidget._callback('target change')
            tag_redraw_all()

        view_version = self.get_view_version()
        if self.view_version != view_version:
            self.view_version = view_version
            self.rftool._callback('view change')
            if self.rftool.rfwidget:
                self.rftool.rfwidget._callback('view change')

    @CookieCutter.FSM_State('main')
    def modal_main(self):
        if self.rftool._fsm.state == 'main' and (not self.rftool.rfwidget or self.rftool.rfwidget._fsm.state == 'main'):
            if self.actions.pressed({'done'}):
                self.done()
                return

            # handle help actions
            if self.actions.pressed('help'):
                # show help
                return

            # handle undo/redo
            if self.actions.pressed('undo'):
                self.undo_pop()
                if self.rftool: self.rftool._reset()
                return
            if self.actions.pressed('redo'):
                self.redo_pop()
                if self.rftool: self.rftool._reset()
                return

            # handle selection
            if self.actions.pressed('select all'):
                self.undo_push('select all')
                self.select_toggle()
                return

        self.check_auto_save()

        self.ignore_ui_events = False

        if self.rftool.rfwidget:
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

    def setup_selection_painting(self, bmelem, select=None, deselect_all=False, fn_filter_bmelem=None, kwargs_select=None, kwargs_deselect=None, kwargs_filter=None, **kwargs):
        accel_nearest2D = {
            'vert': self.accel_nearest2D_vert,
            'edge': self.accel_nearest2D_edge,
            'face': self.accel_nearest2D_face,
        }[bmelem]

        fn_filter_bmelem = fn_filter_bmelem or (lambda bmelem: True)
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
            adding = self.actions.using('select add')
            if not bmelem: return               # nothing there; leave!
            if not bmelem.select: select = True # bmelem is not selected, so we are selecting
            else: select = not adding           # bmelem is selected, so we are deselecting if "select add"
            deselect_all = not adding           # deselect all if not "select add"
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

    @CookieCutter.FSM_State('selection painting')
    def selection_painting(self):
        assert self.selection_painting_opts
        if not self.actions.using(['select','select add']):
            self.selection_painting_opts = None
            return 'main'
        bmelem = self.selection_painting_opts['get']()
        if not bmelem or bmelem.select == self.selection_painting_opts['select']:
            return
        if self.selection_painting_opts['select']:
            self.select(bmelem, only=False, **self.selection_painting_opts['kwargs'])
        else:
            self.deselect(bmelem, **self.selection_painting_opts['kwargs'])


