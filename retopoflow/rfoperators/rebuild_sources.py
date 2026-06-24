'''
Copyright (C) 2024 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Lampel

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

import bpy

from ..common.operator import RFRegisterClass
from ..common.accel import SourceCache, SourceMeshCache


class RFOperator_RebuildSourceCache(RFRegisterClass, bpy.types.Operator):
    bl_idname = 'retopoflow.rebuild_source_cache'
    bl_label = 'Rebuild Source Cache'
    bl_description = (
        'Rebuild the source feature-detection cache from the current source objects and '
        'detection settings. Use this after changing sources or settings while Auto Rebuild is off'
    )
    bl_options = {'INTERNAL'}

    def execute(self, context):
        # Non-blocking: kicks the incremental build (restarting any in-flight one) and returns
        # immediately. Progress shows in the Source Feature Detection panel.
        SourceCache.request_rebuild(context, restart=True, manual=True)
        # Also rebuild walk topology data when Contours Walk is active
        tool = context.workspace.tools.from_space_view3d_mode('EDIT_MESH', create=False)
        props = tool.operator_properties('retopoflow.contours') if tool else None
        if props and props.process_source_method == 'walk':
            SourceMeshCache.clear()
            SourceMeshCache.request_warmup(context)
        self.report({'INFO'}, 'Rebuilding source feature cache…')
        return {'FINISHED'}


class RFOperator_CancelSourceCacheRebuild(RFRegisterClass, bpy.types.Operator):
    bl_idname = 'retopoflow.cancel_source_cache_rebuild'
    bl_label = 'Cancel Source Cache Rebuild'
    bl_description = 'Stop the in-progress source feature cache rebuild and keep the previous cache'
    bl_options = {'INTERNAL'}

    def execute(self, context):
        SourceCache.cancel_rebuild()
        self.report({'INFO'}, 'Source feature cache rebuild cancelled')
        return {'FINISHED'}


class RFOperator_EvictSourceCacheObject(RFRegisterClass, bpy.types.Operator):
    bl_idname = 'retopoflow.evict_source_cache_object'
    bl_label = 'Remove Object from Cache'
    bl_description = (
        'Remove this object\'s cached data (feature edges and/or Walk topology) so it is '
        'rescanned on the next rebuild.  All other cached objects are unaffected'
    )
    bl_options = {'INTERNAL'}

    obj_name: bpy.props.StringProperty(name='Object Name')

    def execute(self, context):
        SourceCache.evict_object(self.obj_name)
        SourceMeshCache.evict(self.obj_name)
        return {'FINISHED'}
