'''
Copyright (C) 2022 CG Cookie
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
from ..rftool_knife.knife           import Knife
from ..rftool_loops.loops           import Loops
from ..rftool_tweak.tweak           import Tweak
from ..rftool_relax.relax           import Relax

from ..rftool import RFTool

from ...config.options import options

class RetopoFlow_Tools:
    def setup_rftools(self):
        self.rftool = None
        self.rftools = [rftool(self) for rftool in RFTool.registry]
        self._rftool_return = None

    def reset_rftool(self):
        self.rftool._reset()

    def _select_rftool(self, rftool, *, reset=True):
        assert rftool in self.rftools

        # return if tool already set
        if rftool == self.rftool:
            if reset: self.reset_rftool()
            return False

        self.rftool = rftool
        if reset: self.reset_rftool()
        self._update_rftool_ui(rftool)
        self.update_ui()
        return True

    def _update_rftool_ui(self, rftool):
        self.ui_main.getElementById(f'tool-{rftool.name.lower()}').checked = True
        self.ui_tiny.getElementById(f'ttool-{rftool.name.lower()}').checked = True
        self.ui_main.dirty(cause='changed tools', children=True)
        self.ui_tiny.dirty(cause='changed tools', children=True)

        statusbar = self.substitute_keymaps(rftool.statusbar, wrap='', pre='', post=':', separator='/', onlyfirst=2)
        statusbar = statusbar.replace('\t', '    ')
        self.context.workspace.status_text_set(f'{rftool.name}: {statusbar}')

    def select_rftool(self, rftool, *, reset=True):
        self.rftool_return = None
        if self._select_rftool(rftool, reset=reset):
            # remember this tool as last used, so clicking diamond can start with this tool
            options['starting tool'] = rftool.name

    def quick_select_rftool(self, rftool, *, reset=True):
        prev_tool = self.rftool
        if self._select_rftool(rftool, reset=reset):
            self._rftool_return = prev_tool

    def quick_restore_rftool(self, *, reset=True):
        if not self._rftool_return: return
        if self.select_rftool(self._rftool_return, reset=reset):
            self._rftool_return = None

