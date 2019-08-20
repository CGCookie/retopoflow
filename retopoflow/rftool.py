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
    Assumes that subclass will have singleton instance (shared FSM among all instances)
    '''
    registry = []

    def __init_subclass__(cls, *args, **kwargs):
        if hasattr(cls, '_rftool'):
            # update registry, but do not add new FSM
            RFTool.registry[cls._rftool] = cls
        else:
            # add to registry and add FSM
            cls._rftool = len(RFTool.registry)
            RFTool.registry.append(cls)
            cls._fsm = FSM()
            cls.FSM_State = cls._fsm.wrapper
        super().__init_subclass__(*args, **kwargs)

    def __init__(self, rfcontext):
        self.rfcontext = rfcontext

    def undone(self): fsm.force_set_state('main')
    def fsm_init(self): fsm.init(self, start='main')
    def fsm_update(self): fsm.update()


