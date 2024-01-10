'''
Copyright (C) 2023 CG Cookie
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

import os
import bpy
import json
import time
from datetime import datetime
from mathutils import Matrix, Vector
from bpy_extras.object_utils import object_data_add

from ...config.options import (
    options,
    retopoflow_datablocks,
    retopoflow_product,
)

from ...addon_common.common.globals import Globals
from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.blender import (
    set_object_selection,
    get_active_object, set_active_object,
    toggle_screen_header,
    toggle_screen_toolbar,
    toggle_screen_properties,
    toggle_screen_lastop,
)
from ...addon_common.common.blender_preferences import get_preferences
from ...addon_common.common.maths import BBox
from ...addon_common.common.debug import dprint

class RetopoFlow_Blender_Objects:
    @staticmethod
    def is_valid_source(o, *, test_poly_count=True, context=None):
        if not o: return False
        context = context or bpy.context
        mark = RetopoFlow_Blender_Objects.get_sources_target_mark(o)
        if mark is not None: return mark == 'source'
        # if o == get_active_object(): return False
        if o == context.edit_object: return False
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not o.visible_get(): return False
        if test_poly_count and not o.data.polygons: return False
        return True

    @staticmethod
    def is_valid_target(o, *, ignore_edit_mode=False, context=None):
        if not o: return False
        context = context or bpy.context
        mark = RetopoFlow_Blender_Objects.get_sources_target_mark(o)
        if mark is not None: return mark == 'target'
        # if o != get_active_object(): return False
        if not ignore_edit_mode and o != context.edit_object: return False
        if not o.visible_get(): return False
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        return True

    @staticmethod
    def has_valid_source():
        return any(RetopoFlow_Blender_Objects.is_valid_source(o) for o in bpy.context.scene.objects)

    @staticmethod
    def has_valid_target():
        return RetopoFlow_Blender_Objects.get_target() is not None

    @staticmethod
    def is_in_valid_mode():
        for area in bpy.context.screen.areas:
            if area.type != 'VIEW_3D': continue
            if area.spaces[0].local_view:
                # currently in local view
                return False
        return True

    @staticmethod
    def mark_sources_target():
        for obj in bpy.data.objects:
            if RetopoFlow_Blender_Objects.is_valid_source(obj):
                # set as source
                obj['RetopFlow'] = 'source'
            elif RetopoFlow_Blender_Objects.is_valid_target(obj):
                obj['RetopoFlow'] = 'target'
            else:
                obj['RetopoFlow'] = 'unused'

    @staticmethod
    def unmark_sources_target():
        for obj in bpy.data.objects:
            if 'RetopoFlow' not in obj: continue
            del obj['RetopoFlow']

    @staticmethod
    def any_marked_sources_target():
        return any('RetopoFlow' in obj for obj in bpy.data.objects)

    @staticmethod
    def get_sources_target_mark(obj):
        if 'RetopoFlow' not in obj: return None
        return obj['RetopoFlow']

    @staticmethod
    def get_sources(*, ignore_active=False):
        is_valid = RetopoFlow_Blender_Objects.is_valid_source
        active = bpy.context.active_object
        is_ignored = lambda o: (ignore_active and o == active)
        return [ o for o in bpy.data.objects if is_valid(o) and not is_ignored(o) ]

    @staticmethod
    def get_target():
        is_valid = RetopoFlow_Blender_Objects.is_valid_target
        return next(( o for o in bpy.data.objects if is_valid(o) ), None)

    @staticmethod
    def create_new_target(context, *, matrix_world=None):
        auto_edit_mode = bpy.context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
        bpy.context.preferences.edit.use_enter_edit_mode = False

        for o in bpy.data.objects: o.select_set(False)

        mesh = bpy.data.meshes.new('RetopoFlow')
        obj = object_data_add(context, mesh, name='RetopoFlow')

        obj.select_set(True)
        context.view_layer.objects.active = obj

        if matrix_world:
            obj.matrix_world = matrix_world

        bpy.ops.object.mode_set(mode='EDIT')

        bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode


    ####################################################
    # methods for rotating about selection

    def setup_rotate_about_active(self):
        self.end_rotate_about_active()      # clear out previous rotate-about object
        auto_edit_mode = bpy.context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
        bpy.context.preferences.edit.use_enter_edit_mode = False
        o = object_data_add(bpy.context, None, name=retopoflow_datablocks['rotate object'])
        bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode
        o.select_set(True)
        o.scale = Vector((0.01, 0.01, 0.01))
        bpy.context.view_layer.objects.active = o
        self.update_rot_object()

    @staticmethod
    def end_rotate_about_active(*, reset_active=True):
        # IMPORTANT: changes here should also go in rf_blender_save.backup_recover()
        name = retopoflow_datablocks['rotate object']
        if name not in bpy.data.objects: return
        is_active = (bpy.context.view_layer.objects.active == bpy.data.objects[name])
        # delete rotate object
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)
        if is_active and reset_active:
            bpy.context.view_layer.objects.active = RetopoFlow_Blender_Objects.get_target()



