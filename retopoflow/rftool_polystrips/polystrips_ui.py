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

import os
import re
import math
from itertools import chain

import bpy
import bgl
from mathutils import Matrix

from ..rftool import rftools

from ...addon_common.common import ui
from ...addon_common.common.utils import delay_exec
from ...config.options import options


RFTool_PolyStrips = rftools['RFTool_PolyStrips']

class PolyStrips_UI:
    @RFTool_PolyStrips.on_ui_setup
    def ui(self):
        container = ui.collapsible('PolyStrips')
        container.builder([
            ui.labeled_input_text(
                label='Cut Count',
                title='Number of cuts along selected strip.',
                value=self._var_cut_count,
            ),
            ui.labeled_input_text(
                label='Scale Falloff',
                title='Controls how quickly control point scaling falls off.',
                value=self._var_scale_falloff,
            ),
        ])
        return container
