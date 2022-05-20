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

import os
import bpy
import json
import time
from datetime import datetime
from mathutils import Matrix, Vector
from bpy_extras.object_utils import object_data_add

from ...config.options import options, retopoflow_version

from ...addon_common.common.globals import Globals
from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.blender import matrix_vector_mult, get_preferences, set_object_selection, set_active_object, get_active_object
from ...addon_common.common.blender import toggle_screen_header, toggle_screen_toolbar, toggle_screen_properties, toggle_screen_lastop
from ...addon_common.common.maths import BBox
from ...addon_common.common.debug import dprint

class RetopoFlow_Blender:
    '''
    handles most interactions with blender
    '''

    @staticmethod
    def is_valid_source(o, test_poly_count=True):
        if not o: return False
        mark = RetopoFlow_Blender.get_sources_target_mark(o)
        if mark is not None: return mark == 'source'
        # if o == get_active_object(): return False
        if o == bpy.context.edit_object: return False
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not o.visible_get(): return False
        if test_poly_count and not o.data.polygons: return False
        return True

    @staticmethod
    def is_valid_target(o):
        if not o: return False
        mark = RetopoFlow_Blender.get_sources_target_mark(o)
        if mark is not None: return mark == 'target'
        # if o != get_active_object(): return False
        if o != bpy.context.edit_object: return False
        if not o.visible_get(): return False
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        return True

    @staticmethod
    def has_valid_source():
        return any(RetopoFlow_Blender.is_valid_source(o) for o in bpy.context.scene.objects)

    @staticmethod
    def has_valid_target():
        return RetopoFlow_Blender.get_target() is not None

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
            if RetopoFlow_Blender.is_valid_source(obj):
                # set as source
                obj['RetopFlow'] = 'source'
            elif RetopoFlow_Blender.is_valid_target(obj):
                obj['RetopoFlow'] = 'target'
            else:
                obj['RetopoFlow'] = 'unused'

    @staticmethod
    def unmark_sources_target():
        for obj in bpy.data.objects:
            if 'RetopoFlow' not in obj: continue
            del obj['RetopoFlow']

    @staticmethod
    def get_sources_target_mark(obj):
        if 'RetopoFlow' not in obj: return None
        return obj['RetopoFlow']

    @staticmethod
    def get_sources():
        is_valid = RetopoFlow_Blender.is_valid_source
        return [ o for o in bpy.data.objects if is_valid(o) ]

    @staticmethod
    def get_target():
        is_valid = RetopoFlow_Blender.is_valid_target
        return next(( o for o in bpy.data.objects if is_valid(o) ), None)

    @staticmethod
    def create_new_target(context):
        auto_edit_mode = bpy.context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
        bpy.context.preferences.edit.use_enter_edit_mode = False

        for o in bpy.data.objects: o.select_set(False)

        mesh = bpy.data.meshes.new('RetopoFlow')
        obj = object_data_add(context, mesh, name='RetopoFlow')

        obj.select_set(True)
        context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='EDIT')

        bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode

    ###################################################
    # handle scaling objects and view so sources fit
    # in unit box for scale-independent rendering

    def _scale_by(self, factor, clip_override=True, clip_start=None, clip_end=None, clip_restore=False):
        r3d = self.actions.r3d
        space = self.actions.space

        print('RetopoFlow: scaling view, sources, and target by %0.2f' % factor)

        # scale view
        self.scale_view(r3d, factor)

        # override/scale clipping distances
        if not hasattr(self, '_clip_distances'):
            # store original clip distances
            print(f'RetopoFlow: storing clip distances: {space.clip_start} {space.clip_end}')
            self._clip_distances = {
                'start': space.clip_start,
                'end':   space.clip_end,
            }

        if clip_restore:
            space.clip_start = self._clip_distances['start']
            space.clip_end   = self._clip_distances['end']
        else:
            if clip_override and clip_start is not None:
                space.clip_start = clip_start
            else:
                space.clip_start *= factor
            if clip_override and clip_end is not None:
                space.clip_end = clip_end
            else:
                space.clip_end *= factor

        self.scale_sources_target(factor)

    @staticmethod
    def scale_view(r3d, factor):
        r3d.view_distance *= factor
        r3d.view_location *= factor

    @staticmethod
    def scale_sources_target(factor):
        M = Matrix.Identity(4) * factor
        objects = RetopoFlow_Blender.get_sources()
        objects += [RetopoFlow_Blender.get_target()]
        for obj in objects:
            if not obj: continue
            obj.matrix_world = M @ obj.matrix_world

    def scale_to_unit_box(self, clip_override=True, clip_start=None, clip_end=None):
        self._scale_by(1.0 / self.unit_scaling_factor, clip_override=clip_override, clip_start=clip_start, clip_end=clip_end)

    def unscale_from_unit_box(self):
        self._scale_by(self.unit_scaling_factor, clip_restore=True)

    @staticmethod
    def get_unit_scaling_factor():
        def get_vs(s):
            x,y,z = s.scale
            return [Vector((v[0]*x, v[1]*y, v[2]*z)) for v in s.bound_box]
        sources = RetopoFlow_Blender.get_sources()
        if not sources: return 1.0
        bboxes = []
        for s in sources:
            verts = [matrix_vector_mult(s.matrix_world, Vector((v[0], v[1], v[2], 1))) for v in s.bound_box]
            verts = [(v[0]/v[3], v[1]/v[3], v[2]/v[3]) for v in verts]
            bboxes.append(BBox(from_coords=verts))
        bbox = BBox.merge(bboxes)
        return bbox.get_max_dimension() / bpy.context.scene.unit_settings.scale_length / 10.0


    ####################################################
    # methods for rotating about selection

    def setup_rotate_about_active(self):
        self.end_rotate_about_active()      # clear out previous rotate-about object
        auto_edit_mode = bpy.context.preferences.edit.use_enter_edit_mode # working around blender bug, see https://github.com/CGCookie/retopoflow/issues/786
        bpy.context.preferences.edit.use_enter_edit_mode = False
        o = object_data_add(bpy.context, None, name=options['rotate object'])
        bpy.context.preferences.edit.use_enter_edit_mode = auto_edit_mode
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        self.update_rot_object()

    def end_rotate_about_active(self):
        # IMPORTANT: changes here should also go in rf_blendersave.backup_recover()
        if options['rotate object'] not in bpy.data.objects: return
        self.del_rotate_object()
        bpy.context.view_layer.objects.active = self.get_target()

    @staticmethod
    def del_rotate_object():
        # IMPORTANT: changes here should also go in rf_blendersave.backup_recover()
        name = options['rotate object']
        if name not in bpy.data.objects: return
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)

    ################################################
    # Blender State methods

    @staticmethod
    def store_window_state(find_r3d, find_space):
        '''
        capture current configuration of blender so that we can restore it after
        ending RetopoFlow or when recovering from auto save.
        '''

        data = {}
        data['timestamp'] = str(datetime.now())
        data['retopoflow'] = retopoflow_version

        # remember current mode and set to object mode so we can control
        # how the target mesh is rendered and so we can push new data
        # into target mesh
        data['mode'] = bpy.context.mode
        data['mode translated'] = {
            'OBJECT':        'OBJECT',          # for some reason, we must
            'EDIT_MESH':     'EDIT',            # translate bpy.context.mode
            'SCULPT':        'SCULPT',          # to something that
            'PAINT_VERTEX':  'VERTEX_PAINT',    # bpy.ops.object.mode_set()
            'PAINT_WEIGHT':  'WEIGHT_PAINT',    # accepts...
            'PAINT_TEXTURE': 'TEXTURE_PAINT',
            }[bpy.context.mode]                 # WHY DO YOU DO THIS, BLENDER!?!?!?

        tar = RetopoFlow_Blender.get_target()
        data['active object'] = tar.name if tar else ''
        data['unit scaling factor'] = RetopoFlow_Blender.get_unit_scaling_factor()

        data['screen name'] = bpy.context.screen.name

        data['data_wm'] = {}
        for wm in bpy.data.window_managers:
            data_wm = []
            for win in wm.windows:
                data_win = []
                for area in win.screen.areas:
                    data_area = []
                    if area.type == 'VIEW_3D':
                        for space in area.spaces:
                            data_space = {}
                            data_space['type'] = space.type
                            if space.type == 'VIEW_3D':
                                data_space['quadview'] = bool(space.region_quadviews)
                                data_space['lock_cursor'] = space.lock_cursor
                                data_space['show_gizmo'] = space.show_gizmo
                                data_space['show_overlays'] = space.overlay.show_overlays
                                data_space['show_region_header'] = space.show_region_header
                                data_space['clip_start'] = space.clip_start
                                data_space['clip_end'] = space.clip_end
                                data_space['region_3d.view_distance'] = space.region_3d.view_distance
                                data_space['region_3d.view_location'] = list(space.region_3d.view_location)
                                if hasattr(space, 'show_region_tool_header'):
                                    data_space['show_region_tool_header'] = space.show_region_tool_header
                                data_space['shading.type'] = space.shading.type
                                if space == find_space:
                                    data_space['the_space'] = True
                                if space.region_3d == find_r3d:
                                    data_space['the_r3d'] = True
                                if hasattr(space, 'show_manipulator'):
                                    data_space['show_manipulator'] = space.show_manipulator
                                if hasattr(space, 'show_region_toolbar'):
                                    data_space['toolbar'] = space.show_region_toolbar
                                if hasattr(space, 'show_region_ui'):
                                    data_space['properties'] = space.show_region_ui
                            data_area.append(data_space)
                    data_win.append(data_area)
                data_wm.append(data_win)
            data['data_wm'][wm.name] = data_wm

        # assuming RF is invoked from 3D View context
        rgn_toolshelf = bpy.context.area.regions[1]
        rgn_properties = bpy.context.area.regions[3]
        data['show_toolshelf'] = rgn_toolshelf.width > 1
        data['show_properties'] = rgn_properties.width > 1
        data['region_overlap'] = get_preferences().system.use_region_overlap

        data['selected objects'] = [o.name for o in bpy.data.objects if getattr(o, 'select', False)]
        data['hidden objects'] = [o.name for o in bpy.data.objects if getattr(o, 'hide', False)]

        RetopoFlow_Blender.write_window_state(data)

    @staticmethod
    def write_window_state(data):
        # store data in text block (might need to create textblock!)
        name = options['blender state']
        texts = bpy.data.texts
        text = texts[name] if name in texts else texts.new(name)
        text.from_string(json.dumps(data, indent=4, sort_keys=True))

    @staticmethod
    def restore_window_state(*, ignore_panels=False, ignore_mode=False):
        name = options['blender state']
        if name not in bpy.data.texts: return  # no stored blender state!?!?
        data = json.loads(bpy.data.texts[name].as_string())

        if data['retopoflow'] != retopoflow_version:
            print(f'WARNING!!!')
            print(f'Recovery data from a different version of RetopoFlow!')
            print(f'Recovering might cause RF / Blender to crash')
            print(f'Cancelling restoration')
            return

        # bpy.context.window.screen = bpy.data.screens[data['screen name']]

        found = {}
        for wm in bpy.data.window_managers:
            data_wm = data['data_wm'][wm.name]
            for win,data_win in zip(wm.windows, data_wm):
                for area,data_area in zip(win.screen.areas, data_win):
                    if area.type != 'VIEW_3D': continue
                    for space,data_space in zip(area.spaces, data_area):
                        if space.type != 'VIEW_3D': continue
                        space.lock_cursor = data_space['lock_cursor']
                        space.show_gizmo = data_space['show_gizmo']
                        space.overlay.show_overlays = data_space['show_overlays']
                        space.show_region_header = data_space['show_region_header']
                        if hasattr(space, 'show_region_tool_header'):
                            space.show_region_tool_header = data_space['show_region_tool_header']
                        space.shading.type = data_space['shading.type']
                        space.clip_start = data_space['clip_start']
                        space.clip_end = data_space['clip_end']
                        space.region_3d.view_distance = data_space['region_3d.view_distance']
                        space.region_3d.view_location = Vector(data_space['region_3d.view_location'])
                        if not ignore_panels:
                            if hasattr(space, 'show_region_toolbar') and 'toolbar' in data_space:
                                space.show_region_toolbar = data_space['toolbar']
                            if hasattr(space, 'show_region_ui') and 'properties' in data_space:
                                space.show_region_ui = data_space['properties']
                        if hasattr(space, 'show_manipulator') and 'show_manipulator' in data_space:
                            space.show_manipulator = data_space['show_manipulator']
                        if getattr(space, 'the_space', False):
                            found['space'] = space
                        if getattr(space, 'the_r3d', False):
                            found['r3d'] = space.region_3d

        # if data['region_overlap'] and not ignore_panels:
        #     try:
        #         # TODO: CONTEXT IS INCORRECT when maximize_area was True????
        #         ctx = {
        #             'area': self.actions.area,
        #             'space_data': self.actions.space,
        #             'window': self.actions.window,
        #             'screen': self.actions.screen
        #         }
        #         rgn_toolshelf = bpy.context.area.regions[1]
        #         rgn_properties = bpy.context.area.regions[3]
        #         if data['show_toolshelf']  and rgn_toolshelf.width  <= 1: toggle_screen_toolbar(ctx)
        #         if data['show_properties'] and rgn_properties.width <= 1: toggle_screen_properties(ctx)
        #     except Exception as e:
        #         print('restore_window_state:', str(e))
        #         pass
        #         #self.ui_toggle_maximize_area(use_hide_panels=False)

        Globals.cursors.set('DEFAULT')

        for o in bpy.data.objects:
            if hasattr(o, 'hide'):
                o.hide = o.name in data['hidden objects']
            if hasattr(o, 'select'):
                set_object_selection(o, o.name in data['selected objects'])
            if o.name == data['active object']:
                set_object_selection(o, True)
                set_active_object(o)

        if not ignore_mode:
            bpy.ops.object.mode_set(mode=data['mode translated'])










