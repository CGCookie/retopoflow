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

from ..common.operator import RFOperator_Invoke
from ..common.segments import MIN_COUNT, detect_adjustable_strip, min_segment_count, same_chain_shape
from ...addon_common.common import bmesh_ops as bmops


COUNT_SENSITIVITY = 50  # pixels of horizontal mouse movement per segment


class RFOperator_AdjustSegmentCount(RFOperator_Invoke):
    ''' Resample the selected quad strip or edge run to a new segment count while retaining its shape. '''
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
    is_dragging = False   # True only while the menu-invoked modal is running

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'count')

    def invoke(self, context, event):
        # WHen chosen from a menu, it's a modal so the user can drag to adjust.
        # Ctrl+Scroll always passes `count` or `delta` and must stay immediate.
        interactive = not (self.properties.is_property_set('count') or self.properties.is_property_set('delta'))

        if not self.properties.is_property_set('count'):
            found = detect_adjustable_strip(context)
            if found is None:
                self.report({'WARNING'}, 'Adjust Segment Count: select a single quad strip, ring, or edge run first')
                return {'CANCELLED'}
            bm, em, provider, descriptor = found
            recipe = provider.capture(context, bm, descriptor)
            RFOperator_AdjustSegmentCount._cached_shape = recipe
            self.count = max(MIN_COUNT, recipe.current_count + self.delta)
            self.delta = 0

        if not interactive:
            return self.execute(context)

        self.is_dragging = True
        self.start_count = self.count
        self.start_mouse_x = event.mouse_x
        self.set_header_info(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def set_header_info(self, context):
        if context.area:
            context.area.header_text_set(
                f'Segments: {self.count}   |   LMB/Enter: Confirm   RMB/Esc: Cancel')

    def end(self, context):
        if context.area:
            context.area.header_text_set(None)

    def modal(self, context, event):
        if event.type == 'MOUSEMOVE':
            # absolute, never accumulated: execute() may clamp count up to the chain's
            # floor, and dragging back out has to recover from where the mouse actually is
            target = self.start_count + int((event.mouse_x - self.start_mouse_x) / COUNT_SENSITIVITY)
            target = max(MIN_COUNT, target)
            if target != self.count:
                self.count = target
                self.execute(context)
                self.set_header_info(context)
            return {'RUNNING_MODAL'}

        if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self.is_dragging = False
            self.end(context)
            return {'FINISHED'}

        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            if self.count != self.start_count:
                self.count = self.start_count
                self.execute(context)
            self.is_dragging = False
            self.end(context)
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def execute(self, context):
        found = detect_adjustable_strip(context)
        if found is None:
            self.report({'WARNING'}, 'Adjust Segment Count: select a single quad strip, ring, or edge run first')
            return {'CANCELLED'}
        bm, em, provider, descriptor = found

        cached = RFOperator_AdjustSegmentCount._cached_shape
        if self.is_dragging and cached is not None:
            recipe = provider.capture(context, bm, descriptor, shape_of=cached)
        else:
            fresh = provider.capture(context, bm, descriptor)
            reuse_shape = cached is not None and same_chain_shape(cached, fresh)
            recipe = provider.capture(context, bm, descriptor, shape_of=cached) if reuse_shape else fresh
        RFOperator_AdjustSegmentCount._cached_shape = recipe

        # Clamp to what the chain can actually be built at before comparing
        self.count = max(min_segment_count(recipe), self.count)

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


def adjust_selected_strip(context, sign):
    ''' Resegment the selected strip or edge run after the redo panel is gone. '''
    ops = context.window_manager.operators
    last = ops[-1] if ops else None
    if last is not None and last.name == RFOperator_AdjustSegmentCount.bl_label:
        # already adjusting: undo and re-run at the new absolute count, so consecutive
        # scrolls collapse onto one undo step (reading .count back respects an F9 edit)
        target = last.count + sign
        bpy.ops.ed.undo()
        # explicit `True` (undo) arg required for a REGISTER|UNDO op invoked
        # via a nested bpy.ops call (from inside another operator's own execute)
        # to properly register itself as the "last operator" so its F9 redo panel works
        bpy.ops.retopoflow.adjust_segment_count('INVOKE_DEFAULT', True, count=target)
    else:
        bpy.ops.retopoflow.adjust_segment_count('INVOKE_DEFAULT', True, delta=sign)
