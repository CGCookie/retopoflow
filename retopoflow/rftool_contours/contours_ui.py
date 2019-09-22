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
from ...addon_common.common.boundvar import BoundVar, BoundInt
from ...addon_common.common.utils import delay_exec
from ...config.options import options


RFTool_Contours = rftools['RFTool_Contours']

class Contours_UI:
    @RFTool_Contours.on_ui_setup
    def ui(self):
        self.init_count = BoundInt('''options['contours count']''', min_value=3)

        container = ui.collapsible('Contours')
        self.ui_count = ui.labeled_input_text(
            'Initial Count',
            value=self.init_count,
            parent=container,
        )
        ui.labeled_input_text('test', id='foo', value='foo', parent=container)
        return container
