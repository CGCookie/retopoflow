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

class RFBrush_Base:
    RFCore = None
    InvalidationManager = None

    _subclasses = {}
    def __new__(cls):
        if cls not in RFBrush_Base._subclasses:
            RFBrush_Base._subclasses[cls] = super(RFBrush_Base, cls).__new__(cls)
        return RFBrush_Base._subclasses[cls]

    _instances = set()
    def __init__(self, *args, **kwargs):
        RFBrush_Base._instances.add(self)
        self.init(*args, **kwargs)
    def __del__(self):
        RFBrush_Base._instances.remove(self)

    @classmethod
    def get_instances(cls):
        yield from (
            instance
            for instance in RFBrush_Base._instances
            if isinstance(instance, cls)
        )

    def init(self): pass
    def update(self, context, event): pass
    def draw_postpixel(self, context): pass
    def draw_postview(self, context): pass

    @classmethod
    def depsgraph_update(cls): pass
