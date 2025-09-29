'''
Copyright (C) 2024 Orange Turbine
http://orangeturbine.com
orangeturbine@cgcookie.com

This file is part of RetopoFlow.

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
    "name":         "Retopoflow 4",
    "description":  "A suite of retopology tools for Blender through a unified retopology mode",
    "author":       "Orange Turbine: Jonathan Denning, Jonathan Lampel, JF Matheu, Jonathan Williamson, Patrick Moore, Patrick Crawford, Christopher Gearhart",
    "blender":      (4, 2, 0),
    "version":      (4, 0, 0, 'β', 7),
    "doc_url":      "https://docs.retopoflow.com",
    "tracker_url":  "https://github.com/CGCookie/retopoflow/issues",
    "location":     "Edit Mode Toolbar",
    "category":     "3D View",
    "warning":      "Alpha Version",
}

import bpy

# the following two functions will be overwritten later, as long as everything looks good!
def register():   pass
def unregister(): pass


from .addon_common.terminal import term_printer
if bpy.app.background:
    term_printer.boxed(
        f'Blender is running in background',
        f'Skipping any further initialization',
        title='RetopoFlow', margin=' ', sides='double', color='black', highlight='blue',
    )

elif bpy.app.version < bl_info['blender']:
    vM,vm,vr = bl_info['blender']
    term_printer.boxed(
        f'Blender version does not meet hard requirements',
        f'Minimum Blender Version: {vM}.{vm}.{vr}',
        f'Skipping any further initialization',
        title='RetopoFlow', margin=' ', sides='double', color='black', highlight='red',
    )

else:
    from .retopoflow.rfcore import RFCore
    def register():
        RFCore.register()
    def unregister():
        try:
            print(f'Unregistering RetopoFlow...')
            RFCore.unregister()
            print(f'Successfully unregistered RetopoFlow!')
        except ReferenceError as e:
            from .addon_common.common.debug import debugger
            print(f'Caught ReferenceError while trying to unregister RetopoFlow')
            debugger.print_exception()
