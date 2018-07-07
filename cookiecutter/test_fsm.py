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

from .cookiecutter import CookieCutter

class CookieCutter_Test_FSM:
    @CookieCutter.fsm_add_mode('main')
    def modal_main(self):
        if self.actions.pressed('grab'):
            print('grab!')
            return 'grab'
    
    @CookieCutter.fsm_add_mode('grab')
    def modal_grab(self):
        if self.actions.pressed('commit'):
            print('commit')
            return 'main'
        if self.actions.pressed('cancel'):
            print('cancel')
            return 'main'

