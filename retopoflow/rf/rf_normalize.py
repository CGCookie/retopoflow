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

import os
import bpy
import json
import time
import functools
from datetime import datetime
from itertools import chain
from mathutils import Matrix, Vector
from bpy_extras.object_utils import object_data_add

from .rf_blender_objects import RetopoFlow_Blender_Objects
from ...config.options import sessionoptions, options

from ...addon_common.common.globals import Globals
from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.blender import matrix_vector_mult, get_preferences, set_object_selection, set_active_object, get_active_object
from ...addon_common.common.blender import toggle_screen_header, toggle_screen_toolbar, toggle_screen_properties, toggle_screen_lastop
from ...addon_common.common.maths import BBox, XForm, Point
from ...addon_common.common.debug import dprint

class RetopoFlow_Normalize:
    '''
    allows RetopoFlow to work with normalized lengths
    '''

    def update_view_sessionoptions(self, context):
        r3d = context.space_data.region_3d
        normalize_opts = sessionoptions['normalize']
        fac = normalize_opts['view scaling factor']
        view_opts = normalize_opts['view']
        view_opts['distance'] = r3d.view_distance / fac
        view_opts['location'] = r3d.view_location / fac

    @staticmethod
    def _normalize_set(
        *,
        factor=None,                            # ignored if None or <= 0
        context=None, space=None,
        restore_all=False,
        view='SCALE',                           # {'SCALE', 'OVERRIDE', 'RESTORE', 'IGNORE'}
        view_distance=None, view_location=None, # ignored if view != 'OVERRIDE'
        clip='SCALE',                           # {'SCALE', 'OVERRIDE', 'RESTORE', 'IGNORE'}
        clip_start=None, clip_end=None,         # ignored if clip != 'OVERRIDE'
        mesh='SCALE',                           # {'SCALE', 'RESTORE', 'IGNORE'}
    ):
        assert context or space, f'Must specify either context or space'
        if not space: space = context.space_data
        assert space.type == 'VIEW_3D', f"space.type must be 'VIEW_3D', not '{space.type}'"
        r3d = space.region_3d

        normalize_opts = sessionoptions['normalize']

        if restore_all:
            view = clip = mesh = 'RESTORE'
            factor = 1.0

        print(f'RetopoFlow: scaling to {factor=}, {view=}, {clip=}, {mesh=}')

        # scale view
        orig_view = normalize_opts['view']
        if view in {'SCALE', 'RESTORE'}:
            fac = factor if view == 'SCALE' else 1.0
            if fac and fac > 0.0:
                r3d.view_distance = orig_view['distance'] * fac
                r3d.view_location = Vector(orig_view['location']) * fac
            normalize_opts['view scaling factor'] = fac
        elif view == 'OVERRIDE':
            if view_distance is not None: r3d.view_distance = view_distance
            if view_location is not None: r3d.view_location = view_location
        elif view == 'IGNORE':
            pass
        else:
            assert False, f'unexpected view ({view})'

        # scale clip start and end
        orig_clip = normalize_opts['clip distances']
        if clip in {'SCALE', 'RESTORE'}:
            fac = (factor if clip == 'SCALE' else 1.0) or 0.0
            if fac > 0.0:
                space.clip_start = orig_clip['start'] * fac
                space.clip_end   = orig_clip['end']   * fac
        elif clip == 'OVERRIDE':
            if clip_start is not None: space.clip_start = clip_start
            if clip_end   is not None: space.clip_end   = clip_end
        elif clip == 'IGNORE':
            pass
        else:
            assert False, f'unexpected clip ({clip})'

        # scale meshes
        if mesh in {'SCALE', 'RESTORE'}:
            fac = (factor if mesh == 'SCALE' else 1.0) or 0.0
            if fac > 0.0:
                prev_factor = normalize_opts['mesh scaling factor']
                M = (Matrix.Identity(3) * (fac / prev_factor)).to_4x4()
                sources = RetopoFlow_Blender_Objects.get_sources()
                targets = [RetopoFlow_Blender_Objects.get_target()]
                for obj in chain(sources, targets):
                    if not obj: continue
                    obj.matrix_world = M @ obj.matrix_world
                normalize_opts['mesh scaling factor'] = fac
        elif mesh == 'IGNORE':
            pass
        else:
            assert False, f'unexpected mesh ({mesh})'

    @property
    def unit_scaling_factor(self):
        normalize_opts = sessionoptions['normalize']
        return normalize_opts['unit scaling factor']

    @staticmethod
    def end_normalize(context):
        print('RetopoFlow: unscaling from unit box')
        RetopoFlow_Normalize._normalize_set(context=context, restore_all=True)

    def start_normalize(self):
        print('RetopoFlow: scaling to unit box')
        self._normalize_set(
            factor=self.unit_scaling_factor,
            space=self.context.space_data,
            clip='OVERRIDE' if options['clip override'] else 'SCALE',
            clip_start=options['clip start override'],
            clip_end=options['clip end override'],
        )
        self.scene_scale_set(1.0)

    def init_normalize(self):
        '''
        initializes normalize functions
        call only once!
        '''
        normalize_opts = sessionoptions['normalize']

        space = self.context.space_data
        assert space.type == 'VIEW_3D', f"space.type must be 'VIEW_3D', not '{space.type}'"
        r3d = space.region_3d

        # store original clip distances
        print(f'RetopoFlow: storing clip distances: {space.clip_start} {space.clip_end}')
        normalize_opts['clip distances'] = {
            'start': space.clip_start,
            'end':   space.clip_end,
        }

        # store original view
        print(f'RetopoFlow: storing view: {r3d.view_location} {r3d.view_distance}')
        normalize_opts['view'] = {
            'distance': r3d.view_distance,
            'location': r3d.view_location,
        }

        print('RetopoFlow: computing unit scaling factor')
        normalize_opts['unit scaling factor'] = self._compute_unit_scaling_factor()
        print(f'  Unit scaling factor: {self.unit_scaling_factor}')

        self.start_normalize()


    @staticmethod
    def _compute_unit_scaling_factor():
        def get_source_bbox(s):
            verts = [s.matrix_world @ Vector((v[0], v[1], v[2], 1)) for v in s.bound_box]
            verts = [(v[0] / v[3], v[1] / v[3], v[2] / v[3]) for v in verts]
            return BBox(from_coords=verts)
        sources = RetopoFlow_Blender_Objects.get_sources()
        if not sources: return 1.0
        bbox = BBox.merge( get_source_bbox(s) for s in sources )
        max_length = bbox.get_max_dimension()
        scene_scale = bpy.context.scene.unit_settings.scale_length
        magic_scale = 10.0  # to make the unit box manageable
        return (scene_scale * magic_scale) / max_length








