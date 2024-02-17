'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

from enum import Enum, IntEnum


class ValueIntEnum(IntEnum):
    # allows us to use [] to get corresponding enum name (key) from value
    @staticmethod
    def __getitem__(v):
        match v:
            case int():
                for k in dir(PP_Action):
                    if getattr(PP_Action, k) == v:
                        return k
            case str():
                return getattr(PP_Action, v)
            case _:
                return None
