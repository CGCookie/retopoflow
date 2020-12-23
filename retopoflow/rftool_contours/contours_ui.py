'''
Copyright (C) 2020 CG Cookie
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
from ...addon_common.common.boundvar import BoundBool
from ...config.options import options


RFTool_Contours = rftools['RFTool_Contours']

class Contours_UI:
    @RFTool_Contours.on_ui_setup
    def ui(self):
        return ui.details(summary='Contours', children=[
            ui.input_checkbox(
                label='Uniform Cut',
                title='If enabled, all new vertices will be spread uniformly (equal distance) around the circumference of the new cut. If disabled, new vertices will try to match distances between vertices of the extended cut.',
                checked=self._var_uniform_cut,
                style='display:block',
            ),
            ui.input_checkbox(
                label='Non-manifold check',
                title='Check for non-manifold edges under each cut.',
                checked=self._var_nonmanifold,
            ),
            ui.labeled_input_text(
                label='Initial Count',
                title='Number of vertices to create in a new cut.',
                value=self._var_init_count,
            ),
            ui.labeled_input_text(
                label='Cut Count',
                title='Number of vertices in currently selected cut.',
                value=self._var_cut_count,
            ),
        ])
