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

from ..common.operator import RFOperator_Execute
from ..common.segments import MIN_COUNT, detect_adjustable_strip
from ...addon_common.common import bmesh_ops as bmops


class RFOperator_AdjustSegmentCount(RFOperator_Execute):
    ''' Resample the selected quad strip to a new quad count while retaining its shape. '''
    bl_idname = 'retopoflow.adjust_segment_count'
    bl_label = 'Adjust Segment Count'
    bl_description = 'Adjust the number of segments in the selected strip while retaining its shape'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    count: bpy.props.IntProperty(
        name='Segments',
        description='Number of quads along the strip',
        default=MIN_COUNT,
        min=MIN_COUNT,
        max=512,
    )
    # set only by a fresh Ctrl+Scroll and left at its default 0 for a menu click.
    # Never persisted as invoke immediately sets it to the existing count of the selection.
    delta: bpy.props.IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})

    _cached_shape = None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'count')

    def invoke(self, context, event):
        # An explicit `count` means the caller already knows its target so run as-is.
        if not self.properties.is_property_set('count'):
            found = detect_adjustable_strip(context)
            if found is None:
                self.report({'WARNING'}, 'Adjust Segment Count: select a single quad strip or ring first')
                return {'CANCELLED'}
            bm, em, provider, descriptor = found
            recipe = provider.capture(context, bm, descriptor)
            RFOperator_AdjustSegmentCount._cached_shape = recipe
            self.count = max(MIN_COUNT, recipe.current_count + self.delta)
            self.delta = 0
        return self.execute(context)

    def execute(self, context):
        found = detect_adjustable_strip(context)
        if found is None:
            self.report({'WARNING'}, 'Adjust Segment Count: select a single quad strip or ring first')
            return {'CANCELLED'}
        bm, em, provider, descriptor = found

        cached = RFOperator_AdjustSegmentCount._cached_shape
        fresh = provider.capture(context, bm, descriptor)
        reuse_shape = cached is not None and provider.is_same_chain(cached, fresh)
        recipe = provider.capture(context, bm, descriptor, shape_of=cached) if reuse_shape else fresh
        RFOperator_AdjustSegmentCount._cached_shape = recipe

        if self.count == recipe.current_count:
            # Already at this count so don't reshape.
            return {'FINISHED'} # Not cancelled because it's still a valid result
        new_faces = provider.rebuild(context, bm, recipe, self.count)
        if not new_faces:
            return {'CANCELLED'}
        bmops.deselect_all(bm)
        bmops.select_iter(bm, new_faces)
        bmops.flush_selection(bm, em)
        return {'FINISHED'}
