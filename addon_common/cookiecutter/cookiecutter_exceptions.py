'''
Copyright (C) 2022 CG Cookie
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
from ..common.functools import find_fns

class CookieCutter_Exceptions:
    @staticmethod
    def _handle_exception(e, action, fatal=False):
        print(f'CookieCutter_Exceptions: handling caught exception')
        print(f'    action: {action}')
        debugger.print_exception()
        if fatal: assert False
        CookieCutter_Exceptions._instance._callback_exception_callbacks(e)

    @staticmethod
    def _exception_callback_wrapper(fn):
        fn._cc_exception_callback = True
        return fn
    Exception_Callback = _exception_callback_wrapper

    @ExceptionHandler.on_exception
    def _callback_exception_callbacks(self, e):
        print(f'CookieCutter_Exceptions._callback_exception_callbacks: {e}')
        # debugger.dcallstack(0)
        for fn_name in self._exception_callbacks:
            try:
                fn = getattr(self, fn_name)
                fn(e)
            except Exception as e2:
                print(f'CookieCutter caught exception while calling back exception callbacks: {fn.__name__}')
                debugger.print_exception()

    def _cc_exception_init(self):
        self._exception_callbacks = [fn.__name__ for (_,fn) in find_fns(self, '_cc_exception_callback')]
        self._exceptionhandler = ExceptionHandler(self)
        #self._exceptionhandler.add_callback(self._callback_exception_callbacks, universal=True)
        CookieCutter_Exceptions._instance = self

    def _cc_exception_done(self):
        del self._exceptionhandler
        self._exceptionhandler = None
        ExceptionHandler.clear_universal_callbacks()
