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

from collections import namedtuple


class UndoStack:
    def __init__(self, fn_create_state, fn_restore_state, *, max_size=100):
        self._fn_step = namedtuple('UndoStep', 'key repeatable state')
        self._fn_create = fn_create_state
        self._fn_restore = fn_restore_state
        self._max_size = max_size
        self.clear()

    def _pop(self, *, undo=True):
        stack = (self._undo if undo else self._redo)
        return stack.pop()

    def _restore(self, step, *args, **kwargs):
        self._fn_restore(step.state, *args, **kwargs)

    def _push_step(self, key, *, repeatable=False, undo=True, clear=True):
        step = self._fn_step(key, repeatable, self._fn_create(key))
        if undo:
            self._undo.append(step)
            if clear:
                self._redo.clear()
            # limit stack size
            while len(self._undo) > self._max_size:
                self._undo.pop(0)
        else:
            self._redo.append(step)

    def _is_empty(self, *, undo=True):
        return not bool(self._undo if undo else self._redo)

    def keys(self, *, undo=True):
        stack = reversed(self._undo if undo else self._redo)
        return [step.key for step in stack]

    def _top(self, *, undo=True):
        stack = (self._undo if undo else self._redo)
        return stack[-1] if stack else None

    def top_key(self, *, undo=True):
        top = self._top(undo=undo)
        return top.key if top else None

    def clear(self):
        self._undo = []
        self._redo = []
        self._changes = 0

    @property
    def changes(self):
        return self._changes

    def push(self, key, *, repeatable=False):
        # skip pushing to undo if action is repeatable and we are repeating actions
        top = self._top()
        if repeatable and top and top.repeatable and top.key == key: return
        self._push_step(key, repeatable=repeatable)
        self._changes += 1

    def pop(self, *args, undo=True, **kwargs):
        if self._is_empty(undo=undo): return
        key = 'undo' if undo else 'redo'
        self._push_step(key, undo=not undo, clear=undo)
        step = self._pop(undo=undo)
        self._restore(step, *args, **kwargs)
        self._changes += 1

    #### the following code is not working??
    # def restore(self, *args, **kwargs):
    #     if self._is_empty(): return
    #     step = self._top()
    #     self._restore(step, *args, **kwargs)
    #     self._redo.clear()
    #     self._changes += 1

    def cancel(self, *args, **kwargs):
        if self._is_empty(): return
        step = self._pop()
        self._restore(step, *args, **kwargs)
        self._changes += 1

    def break_repeatable(self):
        if self._is_empty(): return
        self._top().repeatable = False

