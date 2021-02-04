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

from ..rfwidgets.rfwidget_default import RFWidget_Default_Factory
from ..rfwidgets.rfwidget_linecut import RFWidget_LineCut_Factory

class Contours_RFWidgets:
    RFWidget_Default = RFWidget_Default_Factory.create()
    RFWidget_Move = RFWidget_Default_Factory.create('HAND')
    RFWidget_LineCut = RFWidget_LineCut_Factory.create()

    def init_rfwidgets(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'cut':     self.RFWidget_LineCut(self),
            'hover':   self.RFWidget_Move(self),
        }
        self.rfwidget = None

