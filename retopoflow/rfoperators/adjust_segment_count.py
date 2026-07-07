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
from ..common.bmesh import get_bmesh_emesh
from ..rfoverlays.segment_count_providers import QuadStripProvider, MIN_COUNT
from ...addon_common.common import bmesh_ops as bmops


# Providers tried in order; the first that recognises the selection wins. Only
# quad strips are handled today -- an EdgeLoopProvider slots in here later with
# no change to this operator (see segment_count_providers).
_PROVIDERS = [QuadStripProvider()]


def _detect(context):
    ''' Find the single adjustable chain in the current selection. Returns
    (bm, em, provider, descriptor) or None. '''
    bm, em = get_bmesh_emesh(context, ensure_lookup_tables=True)
    for provider in _PROVIDERS:
        descriptor = provider.detect(context, bm)
        if descriptor is not None:
            return bm, em, provider, descriptor
    return None


class RFOperator_AdjustSegmentCount(RFOperator_Execute):
    '''
    Generic "adjust segment count": resegment the selected quad strip to a new
    quad count while retaining its shape and every connection to surrounding
    topology. REGISTER|UNDO, so it is one undo step with a `count` field the
    user can also edit via F9. Repeated Ctrl+Scroll in PolyStrips collapses onto
    THIS single undo step -- the scroll keymap undoes the previous adjust and
    re-runs at the new count (see rftool_polystrips/polystrips.py).

    That undo-collapse alone isn't enough to keep the strip's shape stable
    across a long run of scrolls: re-deriving (capturing) the shape fresh on
    every execute means fitting a curve to whatever the PREVIOUS rebuild left
    behind, and a fit is generally a little shorter than the polyline it's fit
    through (it smooths corners) -- fitting a fit's output over and over
    compounds that shrink each scroll, visibly shrinking the strip over a
    session. `_cached_shape` fixes this: the strip's shape is captured ONCE,
    the first time this session touches it, and every later scroll resamples
    that SAME fit at a different count rather than re-deriving and re-fitting
    it -- see segment_count_providers.SegmentGeometryProvider.capture's
    `shape_of` and `is_same_chain`.
    '''
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
    # set only by a fresh Ctrl+Scroll (the desired +/-1 change); left at its
    # default 0 for a menu/search click (see invoke's `is_seed`) or a
    # continuation call, which pass an explicit `count` instead. Never
    # persisted -- invoke immediately resolves it into the absolute `count`
    # that actually drives the rebuild and the F9 redo panel.
    delta: bpy.props.IntProperty(default=0, options={'HIDDEN', 'SKIP_SAVE'})

    # class-level, mirroring RFOperator_PolyStrips_Insert.logic: the pristine
    # shape captured for whichever strip is currently being adjusted this
    # session. Never dereference its strip_faces/strip_verts/end?_verts (those
    # are stale BMesh refs from a past capture) -- only its pure shape fields
    # are ever read, via capture's `shape_of`.
    _cached_shape = None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'count')

    def invoke(self, context, event):
        # an explicit `count` means the caller (the Ctrl+Scroll continuation
        # path in polystrips.py) already knows its target -- run as-is. A
        # "seed" invocation -- the context menu, operator search, or a fresh
        # Ctrl+Scroll passing only `delta` -- has no target yet: detect the
        # strip and seed `count` from its actual current count (offset by
        # `delta`, 0 for a raw menu/search click).
        if not self.properties.is_property_set('count'):
            found = _detect(context)
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
        found = _detect(context)
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
            # already at this count -- leave the strip untouched. A menu/search
            # click seeds `count` to exactly this value, so without this guard
            # every such click would still re-fit and re-snap the whole strip
            # (never byte-identical to the original even at an unchanged quad
            # count), visibly jumping the strip for no reason. Still FINISHED
            # (not CANCELLED) -- the strip is valid, so the F9 redo panel
            # should stay available to dial `count` to something else.
            return {'FINISHED'}
        new_faces = provider.rebuild(context, bm, recipe, self.count)
        if not new_faces:
            return {'CANCELLED'}
        bmops.deselect_all(bm)
        bmops.select_iter(bm, new_faces)
        bmops.flush_selection(bm, em)
        return {'FINISHED'}
