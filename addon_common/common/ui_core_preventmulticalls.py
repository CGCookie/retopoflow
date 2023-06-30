'''
Copyright (C) 2023 CG Cookie
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


class UI_Core_PreventMultiCalls:
    multicalls = {}

    @staticmethod
    def reset_multicalls():
        # print(UI_Core_PreventMultiCalls.multicalls)
        UI_Core_PreventMultiCalls.multicalls = {}

    def record_multicall(self, label):
        # returns True if already called!
        d = UI_Core_PreventMultiCalls.multicalls
        if   label not in d:            d[label] = { self._uid }
        elif self._uid not in d[label]: d[label].add(self._uid)
        else:                           return True
        return False

