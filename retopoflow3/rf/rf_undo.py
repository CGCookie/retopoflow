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

import copy
from collections import namedtuple

from ...config.options import options
from ...addon_common.common.blender import tag_redraw_all
from ...addon_common.common.undostack import UndoStack


class RetopoFlow_Undo:
    def init_undo(self):
        def create_state(action):
            nonlocal self
            self.instrument_write(action)
            return {
                'action':       action,
                'tool':         self.rftool,
                'rftarget':     copy.deepcopy(self.rftarget),
                'grease_marks': copy.deepcopy(self.grease_marks),
            }

        def restore_state(state, *, set_tool=True, reset_tool=True, instrument_action=None):
            nonlocal self

            self.rftarget = state['rftarget']
            self.rftarget.rewrap()
            self.rftarget.dirty()
            self.rftarget_draw.replace_rfmesh(self.rftarget)
            self.grease_marks = state['grease_marks']

            if   set_tool:   self.select_rftool(state['tool'], reset=reset_tool)
            elif reset_tool: self.reset_rftool()

            if instrument_action: self.instrument_write(instrument_action)

            tag_redraw_all('restoring state')

        self._undostack = UndoStack(
            create_state,
            restore_state,
            max_size=options['undo depth'],
        )

    @property
    def change_count(self):
        return self._undostack.changes

    def undo_clear(self):
        self._undostack.clear()

    def get_last_action(self):
        return self._undostack.top_key()

    def undo_push(self, action, repeatable=False):
        self._undostack.push(action, repeatable=repeatable)

    def undo_repush(self, action):
        ### the restore method does not work?
        # self._undostack.restore(reset_tool=False)
        self._undostack.pop(reset_tool=False)
        self._undostack.push(action)

    def undo_pop(self):
        self._undostack.pop(reset_tool=True, instrument_action='undo')

    def undo_cancel(self):
        self._undostack.cancel(reset_tool=False, instrument_action='cancel (undo)')

    def redo_pop(self):
        self._undostack.pop(undo=False, reset_tool=True, instrument_action='redo')

    def undo_stack_actions(self):
        return self._undostack.keys() if hasattr(self, '_undostack') else []
