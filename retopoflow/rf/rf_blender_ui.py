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
from datetime import datetime
from mathutils import Matrix, Vector
from bpy_extras.object_utils import object_data_add

from ...config.options import (
    options,
    sessionoptions,
    retopoflow_datablocks,
    retopoflow_product,
)

from ...addon_common.common.blender import (
    mode_translate,
    matrix_vector_mult,
    get_preferences,
    set_object_selection,
    get_active_object, set_active_object,
    toggle_screen_header,
    toggle_screen_toolbar,
    toggle_screen_properties,
    toggle_screen_lastop,
    index_of_area_space,
)
from ...addon_common.common.debug import dprint
from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.globals import Globals
from ...addon_common.common.maths import BBox



class RetopoFlow_Blender_UI:
    pass
    # def store_window_state(self, find_r3d, find_space):
    #     '''
    #     capture current configuration of blender so that we can restore it after
    #     ending RetopoFlow or when recovering from auto save.
    #     '''

    #     ctx = self.context
    #     prefs = get_preferences()

    #     sessionoptions.set({
    #         'context': {
    #             'mode':             ctx.mode,
    #             'mode translated':  mode_translate(ctx.mode),
    #             'screen':           ctx.screen,
    #         },
    #         'objects': {
    #             'active':           ctx.view_layer.objects.active.name,
    #             'select':           [o.name for o in ctx.view_layer.objects if o.select_get()],
    #             'hidden':           [o.name for o in ctx.view_layer.objects if o.hide_get()],
    #         },
    #         'blender': {
    #             'region_overlap':   prefs.system.use_region_overlap,
    #         },
    #         'window managers': {
    #             wm.name: {
    #                 f'{i_win}': {
    #                     f'{i_area}': {
    #                         'index':              index_of_area_space(area, space),

    #                         'the_space':          find_space == space,
    #                         'the_r3d':            find_r3d   == r3d,

    #                         'quadview':           bool(space.region_quadviews),

    #                         'show_gizmo':         space.show_gizmo,
    #                         'show_overlays':      space.overlay.show_overlays,
    #                         'shading.type':       space.shading.type,

    #                         'lock_cursor':        space.lock_cursor,
    #                         'clip_start':         space.clip_start,
    #                         'clip_end':           space.clip_end,
    #                         'r3d.view_distance':  r3d.view_distance,
    #                         'r3d.view_location':  list(r3d.view_location),

    #                         # region visibility
    #                         'show_region_header':      space.show_region_header,
    #                         'show_region_hud':         space.show_region_hud,
    #                         'show_region_tool_header': space.show_region_tool_header,
    #                         'show_region_toolbar':     space.show_region_toolbar,
    #                         'show_region_sidebar':     space.show_region_ui,
    #                     }
    #                     for i_area, area in enumerate(win.screen.areas)
    #                     if area.type == 'VIEW_3D' and (space := area.spaces.active).type == 'VIEW_3D' and (r3d := space.region_3d)
    #                 }
    #                 for i_win, win in enumerate(wm.windows)
    #             }
    #             for wm in bpy.data.window_managers
    #         }
    #     })

    #     return


    #     data = {}
    #     data['timestamp'] = str(datetime.now())
    #     data['retopoflow'] = retopoflow_product['version']

    #     # remember current mode and set to object mode so we can control
    #     # how the target mesh is rendered and so we can push new data
    #     # into target mesh
    #     data['mode'] = bpy.context.mode
    #     data['mode translated'] = {
    #         'OBJECT':        'OBJECT',          # for some reason, we must
    #         'EDIT_MESH':     'EDIT',            # translate bpy.context.mode
    #         'SCULPT':        'SCULPT',          # to something that
    #         'PAINT_VERTEX':  'VERTEX_PAINT',    # bpy.ops.object.mode_set()
    #         'PAINT_WEIGHT':  'WEIGHT_PAINT',    # accepts...
    #         'PAINT_TEXTURE': 'TEXTURE_PAINT',
    #     }[bpy.context.mode]                     # WHY DO YOU DO THIS, BLENDER!?!?!?

    #     tar = self.get_target()
    #     data['active object'] = tar.name if tar else ''
    #     data['unit scaling factor'] = self.get_unit_scaling_factor()

    #     data['screen name'] = bpy.context.screen.name

    #     data['data_wm'] = {}
    #     for wm in bpy.data.window_managers:
    #         data_wm = []
    #         for win in wm.windows:
    #             data_win = []
    #             for area in win.screen.areas:
    #                 data_area = []
    #                 if area.type == 'VIEW_3D':
    #                     for space in area.spaces:
    #                         data_space = {}
    #                         data_space['type'] = space.type
    #                         if space.type == 'VIEW_3D':
    #                             data_space['quadview'] = bool(space.region_quadviews)
    #                             data_space['lock_cursor'] = space.lock_cursor
    #                             data_space['show_gizmo'] = space.show_gizmo
    #                             data_space['show_overlays'] = space.overlay.show_overlays
    #                             data_space['show_region_header'] = space.show_region_header
    #                             data_space['clip_start'] = space.clip_start
    #                             data_space['clip_end'] = space.clip_end
    #                             data_space['region_3d.view_distance'] = space.region_3d.view_distance
    #                             data_space['region_3d.view_location'] = list(space.region_3d.view_location)
    #                             if hasattr(space, 'show_region_tool_header'):
    #                                 data_space['show_region_tool_header'] = space.show_region_tool_header
    #                             data_space['shading.type'] = space.shading.type
    #                             if space == find_space:
    #                                 data_space['the_space'] = True
    #                             if space.region_3d == find_r3d:
    #                                 data_space['the_r3d'] = True
    #                             if hasattr(space, 'show_manipulator'):
    #                                 data_space['show_manipulator'] = space.show_manipulator
    #                             if hasattr(space, 'show_region_toolbar'):
    #                                 data_space['toolbar'] = space.show_region_toolbar
    #                             if hasattr(space, 'show_region_ui'):
    #                                 data_space['properties'] = space.show_region_ui
    #                         data_area.append(data_space)
    #                 data_win.append(data_area)
    #             data_wm.append(data_win)
    #         data['data_wm'][wm.name] = data_wm

    #     # assuming RF is invoked from 3D View context
    #     rgn_toolshelf = bpy.context.area.regions[1]
    #     rgn_properties = bpy.context.area.regions[3]
    #     data['show_toolshelf'] = rgn_toolshelf.width > 1
    #     data['show_properties'] = rgn_properties.width > 1
    #     data['region_overlap'] = get_preferences().system.use_region_overlap

    #     data['selected objects'] = [o.name for o in bpy.data.objects if getattr(o, 'select', False)]
    #     data['hidden objects'] = [o.name for o in bpy.data.objects if getattr(o, 'hide', False)]

    #     sessionoptions['window state'] = data
    #     self.write_window_state(data)

    # @staticmethod
    # def write_window_state(data):
    #     # store data in text block (might need to create textblock!)
    #     name = retopoflow_datablocks['session data']
    #     texts = bpy.data.texts
    #     text = texts[name] if name in texts else texts.new(name)
    #     text.from_string(json.dumps(data, indent=4, sort_keys=True))

    # @staticmethod
    # def restore_window_state(*, ignore_panels=False, ignore_mode=False):
    #     name = options['blender state']
    #     if name not in bpy.data.texts: return  # no stored blender state!?!?
    #     #data = json.loads(bpy.data.texts[name].as_string())
    #     data = sessionoptions['window state']
    #     if not data: return

    #     if data['retopoflow'] != retopoflow_product['version']:
    #         print(f'WARNING!!!')
    #         print(f'Recovery data from a different version of RetopoFlow!')
    #         print(f'Recovering might cause RF / Blender to crash')
    #         print(f'Cancelling restoration')
    #         return

    #     # bpy.context.window.screen = bpy.data.screens[data['screen name']]

    #     found = {}
    #     for wm in bpy.data.window_managers:
    #         data_wm = data['data_wm'][wm.name]
    #         for win,data_win in zip(wm.windows, data_wm):
    #             for area,data_area in zip(win.screen.areas, data_win):
    #                 if area.type != 'VIEW_3D': continue
    #                 for space,data_space in zip(area.spaces, data_area):
    #                     if space.type != 'VIEW_3D': continue
    #                     space.lock_cursor = data_space['lock_cursor']
    #                     space.show_gizmo = data_space['show_gizmo']
    #                     space.overlay.show_overlays = data_space['show_overlays']
    #                     space.show_region_header = data_space['show_region_header']
    #                     if hasattr(space, 'show_region_tool_header'):
    #                         space.show_region_tool_header = data_space['show_region_tool_header']
    #                     space.shading.type = data_space['shading.type']
    #                     space.clip_start = data_space['clip_start']
    #                     space.clip_end = data_space['clip_end']
    #                     space.region_3d.view_distance = data_space['region_3d.view_distance']
    #                     space.region_3d.view_location = Vector(data_space['region_3d.view_location'])
    #                     if not ignore_panels:
    #                         if hasattr(space, 'show_region_toolbar') and 'toolbar' in data_space:
    #                             space.show_region_toolbar = data_space['toolbar']
    #                         if hasattr(space, 'show_region_ui') and 'properties' in data_space:
    #                             space.show_region_ui = data_space['properties']
    #                     if hasattr(space, 'show_manipulator') and 'show_manipulator' in data_space:
    #                         space.show_manipulator = data_space['show_manipulator']
    #                     if getattr(space, 'the_space', False):
    #                         found['space'] = space
    #                     if getattr(space, 'the_r3d', False):
    #                         found['r3d'] = space.region_3d

    #     # if data['region_overlap'] and not ignore_panels:
    #     #     try:
    #     #         # TODO: CONTEXT IS INCORRECT when maximize_area was True????
    #     #         ctx = {
    #     #             'area': self.actions.area,
    #     #             'space_data': self.actions.space,
    #     #             'window': self.actions.window,
    #     #             'screen': self.actions.screen
    #     #         }
    #     #         rgn_toolshelf = bpy.context.area.regions[1]
    #     #         rgn_properties = bpy.context.area.regions[3]
    #     #         if data['show_toolshelf']  and rgn_toolshelf.width  <= 1: toggle_screen_toolbar(ctx)
    #     #         if data['show_properties'] and rgn_properties.width <= 1: toggle_screen_properties(ctx)
    #     #     except Exception as e:
    #     #         print('restore_window_state:', str(e))
    #     #         pass
    #     #         #self.ui_toggle_maximize_area(use_hide_panels=False)

    #     Globals.cursors.set('DEFAULT')

    #     for o in bpy.data.objects:
    #         if hasattr(o, 'hide'):
    #             o.hide = o.name in data['hidden objects']
    #         if hasattr(o, 'select'):
    #             set_object_selection(o, o.name in data['selected objects'])
    #         if o.name == data['active object']:
    #             set_object_selection(o, True)
    #             set_active_object(o)

    #     if not ignore_mode:
    #         bpy.ops.object.mode_set(mode=data['mode translated'])










