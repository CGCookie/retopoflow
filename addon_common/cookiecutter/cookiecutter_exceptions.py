'''
Copyright (C) 2020 CG Cookie
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

import contextlib

from ..common.fsm import FSM
from ..common.debug import debugger, ExceptionHandler
from ..common.utils import find_fns

from .cookiecutter_fsm import CookieCutter_FSM

class CookieCutter_Exceptions:
    @staticmethod
    def _handle_exception(e, action, fatal=False):
        print('CookieCutter handling exception caught while trying to "%s"' % action)
        debugger.print_exception()
        if fatal: assert False
        CookieCutter_Exceptions._instance._callback_exception_callbacks(e)

    @staticmethod
    def _exception_callback_wrapper(fn):
        fn._cc_exception_callback = True
        return fn
    Exception_Callback = _exception_callback_wrapper

    def _callback_exception_callbacks(self, e):
        print('CookieCutter_Exceptions._callback_exception_callbacks:', e)
        # debugger.dcallstack(0)
        for fn_name in self._exception_callbacks:
            try:
                fn = getattr(self, fn_name)
                fn(e)
            except Exception as e2:
                print('CookieCutter caught exception while calling back exception callbacks: %s' % fn.__name__)
                debugger.print_exception()

    def _cc_exception_init(self):
        self._exception_callbacks = [fn.__name__ for (_,fn) in find_fns(self, '_cc_exception_callback')]
        ExceptionHandler.add_universal_callback(self._callback_exception_callbacks)
        CookieCutter_Exceptions._instance = self

    def _cc_exception_done(self):
        ExceptionHandler.remove_universal_callback(self._callback_exception_callbacks)
