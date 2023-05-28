'''
Copyright (C) 2022 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson

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


#######################################################################
# THE FOLLOWING FUNCTIONS ARE ONLY FOR THE TRANSITION FROM BGL TO GPU #
# THIS FILE **SHOULD** GO AWAY ONCE WE DROP SUPPORT FOR BLENDER 2.83  #
# AROUND JUNE 2022 AS BLENDER 2.93 HAS GPU MODULE                     #
#######################################################################


import bpy

from .decorators import only_in_blender_version, warn_once



# note: not all supported by user system, but we don't need full functionality
# https://en.wikipedia.org/wiki/OpenGL_Shading_Language#Versions
#     OpenGL  GLSL    OpenGL  GLSL
#      2.0    110      4.0    400
#      2.1    120      4.1    410
#      3.0    130      4.2    420
#      3.1    140      4.3    430
#      3.2    150      4.4    440
#      3.3    330      4.5    450
#                      4.6    460


#########################################################################
# import the appropriate module
# note: there is a small overlap of modules imported [2.93, 3.00)

major, minor, rev = bpy.app.version
blender_ver = f'{major}.{minor:02d}'

if blender_ver < '3.00':
    import bgl
    glenable = {                 # convenience function
        True:  bgl.glEnable,
        False: bgl.glDisable,
    }
    gldisable = {                # negation of above
        False: bgl.glEnable,
        True:  bgl.glDisable,
    }

if blender_ver >= '2.93':
    import gpu




######################################
#

def blend(mode): gpu.state.blend_set(mode)

def depth_test(mode): gpu.state.depth_test_set(mode)


# https://www.khronos.org/registry/OpenGL-Refpages/gl2.1/xhtml/glGetString.xml
@only_in_blender_version('< 3.00')
def gpu_info():
    import bgl
    return f'{bgl.glGetString(bgl.GL_VENDOR)}, {bgl.glGetString(bgl.GL_RENDERER)}, {bgl.glGetString(bgl.GL_VERSION)}, {bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION)}'

@only_in_blender_version('>= 3.00', '< 3.04')
def gpu_info():
    import gpu
    return f'{gpu.platform.vendor_get()}, {gpu.platform.renderer_get()}, {gpu.platform.version_get()}'

@only_in_blender_version('>= 3.04')
def gpu_info():
    import gpu
    return f'backend:{gpu.platform.backend_type_get()}, device:{gpu.platform.device_type_get()}, vendor:{gpu.platform.vendor_get()}, renderer:{gpu.platform.renderer_get()}, version:{gpu.platform.version_get()}'

if not bpy.app.background:
    print(f'Addon Common: {gpu_info()}')


