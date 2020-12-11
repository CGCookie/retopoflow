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

from ..rfwidgets.rfwidget_brushstroke import RFWidget_BrushStroke_Factory
from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory

from ...addon_common.common.boundvar import BoundBool, BoundInt, BoundFloat, BoundString

from ...config.options import options, themes


class PolyStrips_RFWidgets:
    RFWidget_Default = RFWidget_Default_Factory.create()
    RFWidget_BrushStroke = RFWidget_BrushStroke_Factory.create(
        BoundFloat('''options['polystrips radius']'''),
        outer_border_color=themes['polystrips']
    )
    RFWidget_Move = RFWidget_Default_Factory.create('HAND')

    def init_rfwidgets(self):
        self.rfwidgets = {
            'default':     self.RFWidget_Default(self),
            'brushstroke': self.RFWidget_BrushStroke(self),
            'move':        self.RFWidget_Move(self),
        }
        self.rfwidget = None

