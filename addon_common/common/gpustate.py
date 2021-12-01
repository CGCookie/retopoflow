'''
Copyright (C) 2021 CG Cookie
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

@only_in_blender_version('< 2.93')
@warn_once('gpustate.blend: modes mapping for 2.93 is NOT complete')
def blend(mode):
    # https://learnopengl.com/Advanced-OpenGL/Blending
    gldisable[mode == 'NONE'](bgl.GL_BLEND)
    if   mode == 'NONE':             pass
    elif mode == 'ALPHA':            bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
    elif mode == 'ALPHA_PREMULT':    bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
    elif mode == 'ADDITIVE':         bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
    elif mode == 'ADDITIVE_PREMULT': bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
    elif mode == 'MULTIPLY':         bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
    elif mode == 'SUBTRACT':         bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_ALPHA)
    elif mode == 'INVERT':           bgl.glBlendFunc(bgl.GL_ONE, bgl.GL_ONE_MINUS_SRC_COLOR)
@only_in_blender_version('>= 2.93')
def blend(mode): gpu.state.blend_set(mode)

@only_in_blender_version('< 2.93')
def depth_test(mode):
    gldisable[mode == 'NONE'](bgl.GL_DEPTH_TEST)
    # https://khronos.org/registry/OpenGL-Refpages/gl4/html/glDepthFunc.xhtml
    if   mode == 'NONE':          pass
    elif mode == 'ALWAYS':        bgl.glDepthFunc(bgl.GL_ALWAYS)
    elif mode == 'LESS':          bgl.glDepthFunc(bgl.GL_LESS)
    elif mode == 'LESS_EQUAL':    bgl.glDepthFunc(bgl.GL_LEQUAL)
    elif mode == 'EQUAL':         bgl.glDepthFunc(bgl.GL_EQUAL)
    elif mode == 'GREATER':       bgl.glDepthFunc(bgl.GL_GREATER)
    elif mode == 'GREATER_EQUAL': bgl.glDepthFunc(bgl.GL_GEQUAL)
@only_in_blender_version('>= 2.93')
def depth_test(mode): gpu.state.depth_test_set(mode)


# https://www.khronos.org/registry/OpenGL-Refpages/gl2.1/xhtml/glGetString.xml
@only_in_blender_version('< 3.00')
def gpu_info(): return f'{bgl.glGetString(bgl.GL_VENDOR)}, {bgl.glGetString(bgl.GL_RENDERER)}, {bgl.glGetString(bgl.GL_VERSION)}, {bgl.glGetString(bgl.GL_SHADING_LANGUAGE_VERSION)}'
@only_in_blender_version('>= 3.00')
@warn_once('gpustate.gpu_info cannot get shader version!')
def gpu_info(): return f'{gpu.platform.vendor_get()}, {gpu.platform.renderer_get()}, {gpu.platform.version_get()}, (no shader version)'




########################################
# functions without known equivalents

# ...



######################################
# deprecated functionality

@only_in_blender_version('< 2.93', ignore_others=True)
@warn_once('gpustate.lighting is deprecated')
def lighting(enable): glenable[enable](bgl.GL_LIGHTING)

@only_in_blender_version('< 2.93', ignore_others=True)
@warn_once('gpustate.multisample is deprecated')
def multisample(enable): glenable[enable](bgl.GL_MULTISAMPLE)

@only_in_blender_version('< 2.93', ignore_others=True)
@warn_once('gpustate.point_smooth is deprecated')
def point_smooth(enable): glenable[enable](bgl.GL_POINT_SMOOTH)

@only_in_blender_version('< 2.93', ignore_others=True)
@warn_once('gpustate.line_smooth is deprecated')
def line_smooth(enable): glenable[enable](bgl.GL_LINE_SMOOTH)


