'''
Copyright (C) 2018 CG Cookie

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

import inspect

class CookieCutter_FSM:
    @staticmethod
    def fsm_add_mode(mode):
        def wrap(fn):
            def run(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print('Caught exception in mode "%s", calling "%s"' % (mode, fn.__name__))
                    print(e)
                    return None
            run.fnname = fn.__name__
            run.fsmmode = mode
            return run
        return wrap

    def fsm_init(self):
        c = type(self)
        self._fsm_modes = {}
        for k in dir(c):
            fn = getattr(c, k)
            if not inspect.isfunction(fn): continue
            m = getattr(fn, 'fsmmode', None)
            if not m: continue
            self._fsm_modes[m] = fn


