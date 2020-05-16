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

from ..rfwidgets import rfwidget_default, rfwidget_linecut

class Contours_RFWidgets:
    RFWidget_Default = rfwidget_default.create_new_class()
    RFWidget_Move = rfwidget_default.create_new_class('HAND')
    RFWidget_LineCut = rfwidget_linecut.create_new_class()

    def init_rfwidgets(self):
        self.rfwidgets = {
            'default': self.RFWidget_Default(self),
            'cut':     self.RFWidget_LineCut(self),
            'hover':   self.RFWidget_Move(self),
        }
        self.rfwidget = None

