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
from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundString, BoundStringToBool, BoundFloat
from ...config.options import options


RFTool_Contours = rftools['RFTool_Contours']

class Contours_UI:
    @RFTool_Contours.on_ui_setup
    def ui(self):
        if True:
            path_folder = os.path.dirname(__file__)
            path_html = os.path.join(path_folder, 'contours_ui.html')
            html = open(path_html, 'rt').read()
            return ui.from_html(html)

        return ui.details(children=[
            ui.summary(innerText='Contours'),
            ui.div(classes='contents', children=[
                ui.label(
                    innerText='Uniform Cut',
                    title='If enabled, all new vertices will be spread uniformly (equal distance) around the circumference of the new cut. If disabled, new vertices will try to match distances between vertices of the extended cut.',
                    children=[
                        ui.input_checkbox(
                            title='If enabled, all new vertices will be spread uniformly (equal distance) around the circumference of the new cut. If disabled, new vertices will try to match distances between vertices of the extended cut.',
                            checked=self._var_uniform_cut,
                        ),
                    ],
                ),
                ui.label(
                    innerText='Non-manifold check',
                    title='Check for non-manifold edges under each cut.',
                    children=[
                        ui.input_checkbox(
                            title='Check for non-manifold edges under each cut.',
                            checked=BoundBool('''options['contours non-manifold check']'''),
                        ),
                    ],
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
            ]),
        ])
