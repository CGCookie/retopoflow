'''
Copyright (C) 2021 CG Cookie
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

import os
import re
import math
from itertools import chain

import bpy
import bgl
from mathutils import Matrix

from ..rftool import rftools

from ...addon_common.common.boundvar import BoundBool, BoundInt
from ...addon_common.common.utils import delay_exec
from ...config.options import options


RFTool_Contours = rftools['RFTool_Contours']

class Contours_Props:
    @RFTool_Contours.on_init
    def init_props(self):
        self._var_init_count  = BoundInt('''options['contours count']''', min_value=3, max_value=500)
        self._var_cut_count   = BoundInt('''self.var_cut_count''', min_value=3, max_value=500)
        self._var_uniform_cut = BoundBool('''options['contours uniform']''')
        self._var_nonmanifold = BoundBool('''options['contours non-manifold check']''')

    @property
    def var_cut_count(self):
        return getattr(self, '_var_cut_count_value', 0)
    @var_cut_count.setter
    def var_cut_count(self, v):
        if self.var_cut_count == v: return
        self._var_cut_count_value = v
        if self._var_cut_count.disabled: return
        self.rfcontext.undo_push('change segment count', repeatable=True)
        self.change_count(count=v)

