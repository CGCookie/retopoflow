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

import copy

from ...config.options import options
from ...addon_common.common.blender import tag_redraw_all

class RetopoFlow_Undo:
    def setup_undo(self):
        self.undo = []
        self.redo = []
        self.change_count = 0

        # # touching undo stack to work around weird bug
        # # to reproduce:
        # #     start PS, select a strip, drag a handle but then cancel, exit RF
        # #     start PS again, drag (already selected) handle... but strip does not move
        # # i believe the bug has something to do with caching of RFMesh, but i'm not sure
        # # pushing and then canceling an undo will flush the cache enough to circumvent it
        self.undo_push('initial')
        self.undo_cancel()

    def _create_state(self, action):
        return {
            'action':       action,
            'tool':         self.rftool,
            'rftarget':     copy.deepcopy(self.rftarget),
            'grease_marks': copy.deepcopy(self.grease_marks),
            }
    def _restore_state(self, state, set_tool=True):
        self.rftarget = state['rftarget']
        self.rftarget.rewrap()
        self.rftarget.dirty()
        self.rftarget_draw.replace_rfmesh(self.rftarget)
        self.grease_marks = state['grease_marks']
        if set_tool:
            self.select_rftool(state['tool']) #, forceUpdate=True, changeTool=options['undo change tool'])
        tag_redraw_all('restoring state')

    def undo_push(self, action, repeatable=False):
        # skip pushing to undo if action is repeatable and we are repeating actions
        if repeatable and self.undo and self.undo[-1]['action'] == action: return
        self.undo.append(self._create_state(action))
        while len(self.undo) > options['undo depth']: self.undo.pop(0)     # limit stack size
        self.redo.clear()
        self.instrument_write(action)
        self.change_count += 1

    def undo_repush(self, action):
        if not self.undo: return
        self._restore_state(self.undo.pop(), set_tool=False)
        self.undo.append(self._create_state(action))
        self.redo.clear()
        self.change_count += 1

    def undo_pop(self):
        if not self.undo: return
        self.redo.append(self._create_state('undo'))
        self._restore_state(self.undo.pop())
        self.instrument_write('undo')
        self.change_count += 1

    def undo_cancel(self):
        if not self.undo: return
        self._restore_state(self.undo.pop())
        self.instrument_write('cancel (undo)')
        self.change_count += 1

    def redo_pop(self):
        if not self.redo: return
        self.undo.append(self._create_state('redo'))
        self._restore_state(self.redo.pop())
        self.instrument_write('redo')
        self.change_count += 1

    def undo_stack_actions(self):
        return [u['action'] for u in reversed(self.undo)]
