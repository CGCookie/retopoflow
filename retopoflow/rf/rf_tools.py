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

# the order of these tools dictates the order tools show in UI
from ..rftool_contours.contours     import Contours
from ..rftool_polystrips.polystrips import PolyStrips
from ..rftool_strokes.strokes       import Strokes
from ..rftool_patches.patches       import Patches
from ..rftool_polypen.polypen       import PolyPen
from ..rftool_loops.loops           import Loops
from ..rftool_tweak.tweak           import Tweak
from ..rftool_relax.relax           import Relax

from ..rftool import RFTool

from ...config.options import options

class RetopoFlow_Tools:
    def setup_rftools(self):
        self.rftools = [rftool(self) for rftool in RFTool.registry]

    def select_rftool(self, rftool):
        assert rftool in self.rftools
        self.rftool = rftool
        self.rftool._reset()
        e = self.document.body.getElementById(f'tool-{rftool.name.lower()}')
        if e: e.checked = True
        e = self.document.body.getElementById(f'ttool-{rftool.name.lower()}')
        if e: e.checked = True
        self.ui_tiny.dirty(cause='changed tools', children=True)
        self.ui_main.dirty(cause='changed tools', children=True)
        statusbar = self.substitute_keymaps(rftool.statusbar, wrap='', pre='', post=':', separator='/', onlyfirst=2)
        statusbar = statusbar.replace('\t', '    ')
        self.context.workspace.status_text_set(f'{rftool.name}: {statusbar}')
        self.update_ui()
        options['quickstart tool'] = rftool.name

