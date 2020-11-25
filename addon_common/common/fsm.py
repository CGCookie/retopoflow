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

import inspect

from .debug import ExceptionHandler
from .debug import debugger
from .utils import find_fns


def get_state(state, substate):
    return '%s__%s' % (str(state), str(substate))

class FSM:
    def __init__(self):
        self.wrapper = self._create_wrapper()
        self.onlyinstate_wrapper = self._create_onlyinstate_wrapper()
        self._exceptionhandler = ExceptionHandler()

    def add_exception_callback(self, fn, universal=True):
        self._exceptionhandler.add_callback(fn, universal=universal)

    def _create_wrapper(self):
        fsm = self
        seen = set()
        class FSM_State:
            def __init__(self, state, substate='main'):
                self.state = state
                self.substate = substate

            def __call__(self, fn):
                self.fn = fn
                self.fnname = fn.__name__
                if self.fnname in seen:
                    print('FSM Warning: detected multiple functions with same name: "%s"' % self.fnname)
                    st = inspect.stack()
                    f = st[1]
                    print('  %s:%d' % (f.filename, f.lineno))
                seen.add(self.fnname)
                def run(*args, **kwargs):
                    try:
                        return fn(*args, **kwargs)
                    except Exception as e:
                        print('Caught exception in function "%s" (state:"%s", substate:"%s")' % (
                            self.fnname, self.state, self.substate
                        ))
                        debugger.print_exception()
                        print(e)
                        fsm._exceptionhandler.handle_exception(e)
                        fsm.force_set_state(fsm._reset_state, call_exit=False, call_enter=True)
                        return
                run.fnname = self.fnname
                run.fsmstate = self.state
                run.fsmstate_full = get_state(self.state, self.substate)
                # print('%s: registered %s as %s' % (str(fsm), self.fnname, run.fsmstate_full))
                return run
        return FSM_State

    def _create_onlyinstate_wrapper(self):
        fsm = self
        class FSM_OnlyInState:
            def __init__(self, states, default=None):
                if type(states) is str: states = {states}
                else: states = set(states)
                self.states = states
                self.default = default
            def __call__(self, fn):
                self.fn = fn
                self.fnname = fn.__name__
                def run(*args, **kwargs):
                    if fsm.state not in self.states:
                        return self.default
                    try:
                        return fn(*args, **kwargs)
                    except Exception as e:
                        print('Caught exception in function "%s" ("%s")' % (
                            self.fnname, fsm.state
                        ))
                        debugger.print_exception()
                        print(e)
                        fsm._exceptionhandler.handle_exception(e)
                        fsm.force_set_state(fsm._reset_state, call_exit=False, call_enter=True)
                        return self.default
                run.fnname = self.fnname
                run.fsmstate = ' '.join(self.states)
                return run
        return FSM_OnlyInState

    def init(self, obj, start='main', reset_state='main'):
        self._obj = obj
        self._state_next = start
        self._state = None
        self._reset_state = reset_state
        self._fsm_states = {}
        self._fsm_states_handled = { st for (st,fn) in find_fns(self._obj, 'fsmstate') }
        for (m,fn) in find_fns(self._obj, 'fsmstate_full'):
            assert m not in self._fsm_states, 'Duplicate states registered!'
            self._fsm_states[m] = fn
            # print('%s: found fn %s as %s' % (str(self), str(fn), m))

    def _call(self, state, substate='main', fail_if_not_exist=False):
        s = get_state(state, substate)
        if s not in self._fsm_states:
            assert not fail_if_not_exist, 'Could not find state "%s" with substate "%s" (%s)' % (state, substate, str(s))
            return
        try:
            return self._fsm_states[s](self._obj)
        except Exception as e:
            print('Caught exception in state ("%s")' % (s))
            debugger.print_exception()
            self._exceptionhandler.hondle_exception(e)
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

    def force_set_state(self, state, call_exit=False, call_enter=True):
        if call_exit: self._call(self._state, substate='exit')
        self._state = state
        self._state_next = state
        if call_enter: self._call(self._state, substate='enter')


def FSMClass(cls):
    cls.fsm = FSM()
    cls.FSM_State = cls.fsm.wrapper
    return cls

    # https://krzysztofzuraw.com/blog/2016/python-class-decorators.html
    # class Wrapper(object):
    #     def __init__(self, *args, **kwargs):
    #         self._wrapped = cls(*args, **kwargs)

