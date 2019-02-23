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

bl_info = {
    "name":        "RetopoFlow",
    "description": "A suite of retopology tools for Blender through a unified retopology mode",
    "author":      "Jonathan Denning, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "version":     (3, 0, 0),  # 3.0.0
    "blender":     (2, 80, 0),
    "location":    "View 3D > Tool Shelf",
    # "warning":     "beta 2",  # used for warning icon and text in addons panel
    "wiki_url":    "http://docs.retopoflow.com",
    "tracker_url": "https://github.com/CGCookie/retopoflow/issues",
    "category":    "3D View"
}

import bpy

from .retopoflow.rfmode import VIEW3D_OT_RetopoFlow


# registration
classes = (
    VIEW3D_OT_RetopoFlow,
)

register,unregister = bpy.utils.register_classes_factory(classes)

if __name__ == "__main__":
    register()
