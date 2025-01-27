'''
Copyright (C) 2023 CG Cookie
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


# initialize deep debugging as early as possible
from .addon_common.terminal.deepdebug import DeepDebug
DeepDebug.init(
    fn_debug='RetopoFlow_debug.txt',
    clear=True,                         # clear deep debugging file every Blender session
    enable_only_once=True,              # only allow this feature to be enabled for one session
)



#################################################################################################################################
# NOTE: the following lines are automatically updated based on hive.json
#       if "warning" is present (not commented out), a warning icon will show in add-ons list
bl_info = {
    "name":         "RetopoFlow",
    "description":  "A suite of retopology tools for Blender through a unified retopology mode",
    "author":       "Orange Turbine: Jonathan Denning, Jonathan Lampel, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart, JF Matheu",
    "blender":      (3, 6, 0),
    "version":      (3, 4, 5),
    "doc_url":      "https://docs.retopoflow.com",
    "tracker_url":  "https://github.com/CGCookie/retopoflow/issues",
    "location":     "View 3D > Header",
    "category":     "3D View",
}


import bpy
def register():   pass
def unregister(): pass


from .addon_common.terminal import term_printer
if bpy.app.background:
    term_printer.boxed(
        f'Blender is running in background',
        f'Skipping any further initialization',
        title='RetopoFlow', margin=' ', sides='double', color='black', highlight='blue',
    )

# elif bpy.app.version < Hive.get_version('blender hard minimum version'):
#     term_printer.boxed(
#         f'Blender version does not meet hard requirements',
#         f'Minimum Blender Version: {Hive.get("blender hard minimum version")}',
#         f'Skipping any further initialization',
#         title='RetopoFlow', margin=' ', sides='double', color='black', highlight='red',
#     )

else:
    from .retopoflow import blenderregister
    def register():   blenderregister.register()
    def unregister(): blenderregister.unregister()


