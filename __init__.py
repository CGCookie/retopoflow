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

# DEEP DEBUGGING
import os, sys
fn_debug = os.path.join(os.path.dirname(__file__), 'debug.txt')
if os.path.exists(fn_debug):
    print(f'REDIRECTING ALL STDOUT AND STDERR TEXT TO {fn_debug}')
    sys.stdout.flush()
    os.remove(fn_debug)
    # if debug.txt file exists, redirect ALL stdout and stderr to that file!
    # https://stackoverflow.com/questions/4675728/redirect-stdout-to-a-file-in-python/11632982#11632982
    # in C++, see https://stackoverflow.com/a/13888242 and https://cplusplus.com/reference/cstdio/freopen/
    os.close(1)
    os.open(fn_debug, os.O_WRONLY | os.O_CREAT)


import bpy

from .addon_common.hive.hive import Hive
from .addon_common.common import term_printer

#################################################################################################################################
# NOTE: the following lines are automatically updated based on hive.json
#       if "warning" is present (not commented out), a warning icon will show in add-ons list
bl_info = {
    "name":         "RetopoFlow",
    "description":  "A suite of retopology tools for Blender through a unified retopology mode",
    "author":       "Jonathan Denning, Jonathan Lampel, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "blender":      (3, 6, 0),
    "version":      (3, 4, 0),
    "doc_url":      "https://docs.retopoflow.com",
    "tracker_url":  "https://github.com/CGCookie/retopoflow/issues",
    "location":     "View 3D > Header",
    "category":     "3D View",
    "warning":      "Alpha",
}

# update bl_info above based on hive data
Hive.update_bl_info(bl_info, __file__)


def register():   pass
def unregister(): pass


if bpy.app.background:
    term_printer.boxed(
        f'RetopoFlow: Blender is running in background',
        f'Skipping any further initialization',
        margin=' ', sides='double', color='black', highlight='blue',
    )

elif bpy.app.version < Hive.get_version('blender hard minimum version'):
    term_printer.boxed(
        f'RetopoFlow: Blender version does not meet hard requirements',
        f'Minimum Blender Version: {Hive.get("blender hard minimum version")}',
        f'Skipping any further initialization',
        margin=' ', sides='double', color='black', highlight='red',
    )

else:
    from .retopoflow import blenderregister
    def register():   blenderregister.register(bl_info)
    def unregister(): blenderregister.unregister(bl_info)


