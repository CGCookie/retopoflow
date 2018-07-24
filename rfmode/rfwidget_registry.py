'''
Copyright (C) 2017 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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

from ..common.debug import dprint

class RFWidget_Registry:
    class Register_FSM_State:
        def __init__(self, widget_name, state):
            self.widget_name = widget_name
            self.state = state

        def __call__(self, fn):
            self.fn = fn
            self.fn = fn.__name__

            def run(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print('Caught exception in function "%s" (state: "%s")' % (self.fnname, self.state))
                    print(e)
                    return None

            run.rfwidget_fsm_state = True
            run.fnname = fn.__name__
            run.widget_name = self.widget_name
            run.state = self.state

            return run

        @staticmethod
        def find_all(o):
            c = type(o)
            objs = [getattr(c, k) for k in dir(c)]
            fns = [fn for fn in objs if inspect.isfunction(fn)]
            fns = [fn for fn in fns if hasattr(fn, 'rfwidget_fsm_state')]
            return fns

    class Register_Callback:
        def __init__(self, widget_name, callback):
            self.widget_name = widget_name
            self.callback = callback

        def __call__(self, fn):
            self.fn = fn
            self.fn = fn.__name__

            def run(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print('Caught exception in function "%s" (callback: "%s")' % (self.fnname, self.callback))
                    print(e)
                    return None

            run.rfwidget_callback = True
            run.fnname = fn.__name__
            run.widget_name = self.widget_name
            run.callback = self.callback

            return run

        @staticmethod
        def find_all(o):
            c = type(o)
            objs = [getattr(c, k) for k in dir(c)]
            fns = [fn for fn in objs if inspect.isfunction(fn)]
            fns = [fn for fn in fns if hasattr(fn, 'rfwidget_callback')]
            return fns

    def registry_init(self):
        widgets = {}

        # collect all widget fsm states
        for fn in RFWidget_Registry.Register_FSM_State.find_all(self):
            n = fn.widget_name
            widgets.setdefault(n, {})
            widgets[n].setdefault('fsm', {})
            widgets[n]['fsm'][fn.state] = fn
            dprint('"%s" "%s" %s' % (n, fn.state, str(fn)))

        # collect all widget callbacks
        for fn in RFWidget_Registry.Register_Callback.find_all(self):
            n = fn.widget_name
            widgets.setdefault(n, {})
            widgets[n][fn.callback] = fn
            dprint('"%s" "%s" %s' % (n, fn.callback, str(fn)))

        # self.widgets = widgets
