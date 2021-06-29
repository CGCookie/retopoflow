'''
Copyright (C) 2021 CG Cookie

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

from ..common.drawing import Drawing, DrawCallbacks, ScissorStack

class CookieCutter_Callbacks:
    '''
    Assumes that direct subclass will have singleton instance (shared CookieCutter among all instances of that subclass and any subclasses)
    '''

    drawcallbacks = DrawCallbacks()
    Draw = drawcallbacks.wrapper
    PreDraw = drawcallbacks.wrapper_pre
