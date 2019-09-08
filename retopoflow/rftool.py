'''
Copyright (C) 2019 CG Cookie
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

from ..addon_common.common.fsm import FSM


class RFTool:
    '''
    Assumes that direct subclass will have singleton instance (shared FSM among all instances of that subclass and any subclasses)
    '''
    registry = []

    def __init_subclass__(cls, *args, **kwargs):
        if not hasattr(cls, '_rftool_index'):
            # add cls to registry (might get updated later) and add FSM
            cls._rftool_index = len(RFTool.registry)
            RFTool.registry.append(cls)
            cls._fsm = FSM()
            cls.FSM_State = cls._fsm.wrapper
        else:
            # update registry, but do not add new FSM
            RFTool.registry[cls._rftool_index] = cls
        super().__init_subclass__(*args, **kwargs)

    def __init__(self, rfcontext):
        self.rfcontext = rfcontext
        self.actions = rfcontext.actions
        self._fsm.init(self, start='main')
        self.init()

    def undone(self):
        self._fsm.force_set_state('main')

    def fsm_update(self):
        return self._fsm.update()

    def update_all(self):
        self.update_timer()
        self.update_target()
        self.update_view()

    @staticmethod
    def dirty_when_done(fn):
        def wrapper(*args, **kwargs):
            ret = fn(*args, **kwargs)
            RFTool.rfcontext.dirty()
            return ret
        return wrapper

    ####################################################
    # methods that subclasses can overwrite

    def init(self):          pass       # called when RF starts up
    def update_timer(self):  pass       # called every timer interval
    def update_target(self): pass       # called whenever rftarget has changed (selection, edited)
    def update_view(self):   pass       # called whenever view has changed
