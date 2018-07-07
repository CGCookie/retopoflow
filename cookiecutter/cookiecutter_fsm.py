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

class CookieCutter_FSM:
    class FSM_State:
        def __init__(self, state):
            self.state = state
        def __call__(self, fn):
            self.fn = fn
            self.fnname = fn.__name__
            def run(*args, **kwargs):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    print('Caught exception in function "%s" (state: "%s")' % (self.fnname, self.state))
                    print(e)
                    return None
            run.fnname = self.fnname
            run.fsmstate = self.state
            return run
    
    def fsm_init(self):
        self._state = 'main'
        self._fsm_states = {}
        for (m,fn) in self.find_fns('fsmstate'):
            assert m not in self._fsm_states
            self._fsm_states[m] = fn
    
    def fsm_update(self):
        assert self._state in self._fsm_states
        nmode = self._fsm_states[self._state](self)
        if nmode: self._state = nmode
    


