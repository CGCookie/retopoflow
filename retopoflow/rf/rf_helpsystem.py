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

from ...addon_common.common import ui
from ...addon_common.common.globals import Globals
from ...addon_common.common.utils import delay_exec
from ...addon_common.common.ui_styling import load_defaultstylings


class RetopoFlow_HelpSystem:
    @staticmethod
    def reload_stylings():
        load_defaultstylings()
        path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'ui.css')
        try:
            Globals.ui_draw.load_stylesheet(path)
        except AssertionError as e:
            # TODO: show proper dialog to user here!!
            print('could not load stylesheet "%s"' % path)
            print(e)
        Globals.ui_document.body.dirty('Reloaded stylings', children=True)
        Globals.ui_document.body.dirty_styling()
        Globals.ui_document.body.dirty_flow()

    def helpsystem_open(self, mdown_path, done_on_esc=False):
        ui_markdown = self.document.body.getElementById('helpsystem-mdown')
        if not ui_markdown:
            def close():
                nonlocal done_on_esc
                if done_on_esc:
                    self.done()
                else:
                    e = self.document.body.getElementById('helpsystem')
                    if not e: return
                    self.document.body.delete_child(e)
            ui_help = ui.framed_dialog(
                label='RetopoFlow Help System',
                id='helpsystem',
                resizable=False,
                closeable=False,
                moveable=False,
                parent=self.document.body
            )
            ui_markdown = ui.markdown(id='helpsystem-mdown', parent=ui_help)
            ui.div(id='helpsystem-buttons', parent=ui_help, children=[
                ui.button(
                    label='Table of Contents',
                    title='Click to open table of contents for help.',
                    on_mouseclick=delay_exec("self.helpsystem_open('table_of_contents.md')"),
                    parent=ui_help,
                ),
                ui.button(
                    label='Close (Esc)',
                    title='Click to close this help dialog.',
                    on_mouseclick=close,
                    parent=ui_help,
                )
            ])
            def key(e):
                if e.key == 'ESC': close()
            ui_help.add_eventListener('on_keypress', key)
        ui.set_markdown(ui_markdown, mdown_path=mdown_path)
