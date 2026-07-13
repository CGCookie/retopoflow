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
from ..common.segments import detect_adjustable_strip
from ...addon_common.common import bmesh_ops as bmops


class RFOperator_AdjustStripWidth(RFOperator_Execute):
    ''' Rescale the selected quad strip's width while retaining its shape. '''
    bl_idname = 'retopoflow.adjust_strip_width'
    bl_label = 'Adjust Strip Width'
    bl_description = 'Rescale the width of the selected quad strip while retaining its shape'
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    scale_start: bpy.props.FloatProperty(
        name='Start Scale',
        description="Width scale at the strip's starting endpoint",
        default=1.0,
        min=0.0,
        soft_min=0.0,
        soft_max=5.0,
        precision=3,
    )
    scale_end: bpy.props.FloatProperty(
        name='End Scale',
        description="Width scale at the strip's last endpoint",
        default=1.0,
        min=0.0,
        soft_min=0.0,
        soft_max=5.0,
        precision=3,
    )
    # set only by a fresh Shift+Scroll and left at its default 0 for a menu/search click.
    delta_factor: bpy.props.FloatProperty(default=0.0, options={'HIDDEN', 'SKIP_SAVE'})

    _cached_shape = None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'scale_start')
        layout.prop(self, 'scale_end')

    def invoke(self, context, event):
        # explicit scale means the caller already knows its target so run as-is.
        if not self.properties.is_property_set('scale_start'):
            found = detect_adjustable_strip(context)
            if found is None:
                self.report({'WARNING'}, 'Adjust Strip Width: select a single quad strip or ring first')
                return {'CANCELLED'}
            bm, em, provider, descriptor = found
            recipe = provider.capture(context, bm, descriptor)
            RFOperator_AdjustStripWidth._cached_shape = recipe
            factor = self.delta_factor or 1.0
            self.scale_start = factor
            self.scale_end = factor
            self.delta_factor = 0.0
        return self.execute(context)

    def execute(self, context):
        found = detect_adjustable_strip(context)
        if found is None:
            self.report({'WARNING'}, 'Adjust Strip Width: select a single quad strip or ring first')
            return {'CANCELLED'}
        bm, em, provider, descriptor = found

        cached = RFOperator_AdjustStripWidth._cached_shape
        fresh = provider.capture(context, bm, descriptor)
        reuse_shape = cached is not None and provider.is_same_chain(cached, fresh)
        recipe = provider.capture(context, bm, descriptor, shape_of=cached) if reuse_shape else fresh
        RFOperator_AdjustStripWidth._cached_shape = recipe

        if self.scale_start == 1.0 and self.scale_end == 1.0:
            return {'FINISHED'} # Valid result but nothing to be done
        new_faces = provider.rebuild(
            context, bm, recipe, recipe.current_count,
            scale_start=self.scale_start, scale_end=self.scale_end,
        )
        if not new_faces:
            return {'CANCELLED'}
        bmops.deselect_all(bm)
        bmops.select_iter(bm, new_faces)
        bmops.flush_selection(bm, em)
        return {'FINISHED'}
