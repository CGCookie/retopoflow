'''
Copyright (C) 2014 Plasmasolutions
software@plasmasolutions.de

Created by Thomas Beck
Donated to CGCookie and the world

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

#This class makes it easier to be install location independent
import sys
import os


class AddonLocator(object):
    def __init__(self):
        self.fullInitPath = __file__
        self.FolderPath = os.path.dirname(self.fullInitPath)
        self.FolderName = os.path.basename(self.FolderPath)

    def AppendPath(self):
        sys.path.append(self.FolderPath)
        print("Addon path has been registered into system path for this session")