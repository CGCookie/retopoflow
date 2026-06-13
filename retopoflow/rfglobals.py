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


from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .rfcore import RFCore as RFCore_class
    from .rfcore import InvalidationManager as InvalidationManager_class
else:
    RFCore_class = object


_RFCore : type[RFCore_class] | None = None
def set_RFCore(rfcore : type[RFCore_class]):
    global _RFCore
    _RFCore = rfcore

_InvalidationManager : type[InvalidationManager_class] | None = None
def set_InvalidationManager(invalidationmanager : type[InvalidationManager_class]):
    global _InvalidationManager
    _InvalidationManager = invalidationmanager

class StaticPropertyMeta(type):
    @property
    def RFCore(cls) -> type[RFCore_class]:
        assert _RFCore
        return _RFCore
    @property
    def RFCore_None(cls) -> type[RFCore_class] | None:
        return _RFCore

    @property
    def InvalidationManager(cls) -> type[InvalidationManager_class]:
        assert _InvalidationManager
        return _InvalidationManager
    @property
    def InvalidationManager_None(cls) -> type[InvalidationManager_class] | None:
        return _InvalidationManager

class RFGlobals(metaclass=StaticPropertyMeta):
    pass
