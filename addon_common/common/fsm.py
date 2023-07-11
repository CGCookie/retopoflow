'''
Copyright (C) 2023 CG Cookie
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
from functools import wraps

from .debug import ExceptionHandler
from .debug import debugger
from .functools import find_fns


def get_state(state, substate):
    return '%s__%s' % (str(state), str(substate))


class FSM:
    def __init__(self, obj, *, start='main', reset_state=None):
        if False: print(f'FSM.__init__: {self}, {obj}, {start}, {reset_state}')

        if False:
            # debugging print
            for i, entry in enumerate(inspect.stack()):
                if i == 0: continue
                if 'frozen importlib.' in entry.filename: continue
                s = f'{entry.filename}:{entry.lineno}'
                s = s + ' '*max(0, 150-len(s))
                c = entry.code_context[0].replace('\n','')
                print(f'  {s}  {c}')

        if reset_state is None: reset_state = start

        self._obj         = obj
        self._state_next  = start
        self._state       = None
        self._reset_state = reset_state

        # collect and update state fns
        self._fsm_states_handled = { data['state'] for (data, _) in find_fns(obj, '_fsm_state') if data['substate'] == 'main' }
        self._fsm_states = {}
        for (data,fn) in find_fns(obj, '_fsm_state'):
            state_substate = data['full']
            assert state_substate not in self._fsm_states, f'FSM: Duplicate states ({data}, {fn}) registered!'
            self._fsm_states[state_substate] = fn
            data['fsm'] = self
            if False: print(f'FSM: state {data["full"]} {fn}')
            # print('%s: found fn %s as %s' % (str(self), str(fn), m))
        assert start in self._fsm_states_handled, f'FSM: start state "{start}" not in handled states ({self._fsm_states_handled})'
        assert reset_state in self._fsm_states_handled, f'FSM: reset state "{reset_state}" not in handled states ({self._fsm_states_handled})'

        # update only-in-state fns
        for (data, fn) in find_fns(obj, '_fsm_onlyinstate'):
            if False: print(f'FSM: only-in-state {data["states"]} {fn}')
            data['fsm'] = self

        # collect and update exception handler fns
        self._exceptionhandler = ExceptionHandler()
        for (data, fn) in find_fns(obj, '_fsm_exception'):
            if False: print(f'FSM: exception {fn}')
            self._exceptionhandler.add_callback(fn, universal=data['universal'])
            data['fsm'] = self


    def handle_exception(self, e):
        self._exceptionhandler.handle_exception(e)
    def add_exception_callback(self, fn, universal=True):
        self._exceptionhandler.add_callback(fn, universal=universal)


    #################################################################################################################################
    # these function decorators will mark the fn with special data that will be collected upon instantiation of subclass of FSM

    @staticmethod
    def on_exception(universal=False):
        def wrapper(fn):
            fr = inspect.getframeinfo(inspect.currentframe().f_back)
            location = f'{fr.filename}:{fr.lineno}'
            data = {
                'fsm':       None,              # FSM object, to be set when FSM object is created + initialized
                'fn':        fn,
                'location':  location,
                'universal': universal,
            }
            @wraps(fn)
            def wrapped(*args, **kwargs):
                nonlocal data, fn, location
                try:
                    fn(*args, **kwargs)
                except Exception as e:
                    print(f'FSM: Caught exception while handling exception in {fn.__name__} (loc:{location}")')
                    print(f'     Exception: {e}')
                    debugger.print_exception()
                return None
            wrapped._fsm_exception = data
            return wrapped
        return wrapper

    @staticmethod
    def onlyinstate(states, *, default=None):
        def wrapper(fn):
            nonlocal states, default
            if type(states) is str: states = { states }
            fr = inspect.getframeinfo(inspect.currentframe().f_back)
            location = f'{fr.filename}:{fr.lineno}'
            data = {
                'fsm':      None,               # FSM object, to be set when FSM object is created + initialized
                'fn':       fn,
                'location': location,
                'states':   states,
                'default':  default,
            }
            @wraps(fn)
            def wrapped(*args, **kwargs):
                nonlocal data, fn, location, states, default
                fsm = data['fsm']
                if not fsm:
                    print(f'FSM: attempting to run {fn.__name__} ({location}) without an FSM instanced')
                    print(f'     returning default value')
                    return default
                if fsm.state not in data['states']:
                    # not in correct state to run this function
                    return default
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print(f'FSM: Caught exception in {fn.__name__} (loc:{location}, states:"{states}")')
                    print(f'     Exception: {e}')
                    debugger.print_exception()
                    fsm.handle_exception(e)
                    fsm.force_reset()
                    return default
            wrapped._fsm_onlyinstate = data
            return wrapped
        return wrapper

    @staticmethod
    def on_state(state, substate='main'):
        def wrapper(fn):
            fr = inspect.getframeinfo(inspect.currentframe().f_back)
            location = f'{fr.filename}:{fr.lineno}'
            assert substate in {'main', 'can enter', 'enter', 'can exit', 'exit'}, f'FSM: unexpected substate "{substate}" in {fn.__name__} ({location})'
            data = {
                'fsm':      None,               # FSM object, to be set when FSM object is created + initialized
                'fn':       fn,
                'location': location,
                'state':    state,
                'substate': substate,
                'full':     get_state(state, substate),
            }
            @wraps(fn)
            def wrapped(*args, **kwargs):
                nonlocal data, fn, location, state, substate
                fsm = data['fsm']
                if not fsm:
                    print(f'FSM: attempting to run {fn.__name__} ({location}) without an FSM instanced. returning')
                    return
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print(f'FSM: Caught exception in {fn.__name__} (loc:{location}, state:"{state}", substate:"{substate}")')
                    print(f'     Exception: {e}')
                    debugger.print_exception()
                    fsm.handle_exception(e)
                    fsm.force_reset()
                    return
            wrapped._fsm_state = data
            return wrapped
        return wrapper


    def _call(self, state, substate='main', fail_if_not_exist=False):
        s = get_state(state, substate)
        if s not in self._fsm_states:
            assert not fail_if_not_exist, f'FSM: Could not find state "{state}" with substate "{substate}" ({s})'
            return
        try:
            return self._fsm_states[s](self._obj)
        except Exception as e:
            print('Caught exception in state ("%s")' % (s))
            debugger.print_exception()
            self._exceptionhandler.handle_exception(e)
            return

    def update(self):
        if self._state_next is not None and self._state_next != self._state:
            if self._call(self._state, substate='can exit') == False:
                # print('Cannot exit %s' % str(self._state))
                self._state_next = None
                return
            if self._call(self._state_next, substate='can enter') == False:
                # print('Cannot enter %s' % str(self._state_next))
                self._state_next = None
                return
            # print('%s -> %s' % (str(self._state), str(self._state_next)))
            self._call(self._state, substate='exit')
            self._state = self._state_next
            self._call(self._state, substate='enter')

        ret = self._call(self._state, fail_if_not_exist=True)

        if ret is None:
            self._state_next = ret
            ret = None
        elif type(ret) is str:
            if self.is_state(ret):
                self._state_next = ret
                ret = None
            else:
                self._state_next = None
                ret = ret
        elif type(ret) is tuple:
            st = {s for s in ret if self.is_state(s)}
            if len(st) == 0:
                self._state_next = None
                ret = ret
            elif len(st) == 1:
                self._state_next = next(st)
                ret = ret - st
            else:
                assert False, 'unhandled FSM return value "%s"' % str(ret)
        else:
            assert False, 'unhandled FSM return value "%s"' % str(ret)

        return ret

    def is_state(self, state):
        return state in self._fsm_states_handled

    @property
    def state(self):
        return self._state

    def force_set_state(self, state, *, call_exit=False, call_enter=True):
        if call_exit: self._call(self._state, substate='exit')
        self._state = state
        self._state_next = state
        if call_enter: self._call(self._state, substate='enter')

    def force_reset(self, **kwargs):
        self.force_set_state(self._reset_state, **kwargs)
