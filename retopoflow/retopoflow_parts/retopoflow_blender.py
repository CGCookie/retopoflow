'''
Copyright (C) 2019 CG Cookie
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
from mathutils import Matrix, Vector
from bpy_extras.object_utils import object_data_add

from ...config.options import options

from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.blender import matrix_vector_mult, get_preferences
from ...addon_common.common.maths import BBox
from ...addon_common.common.debug import dprint

class RetopoFlow_Blender:
    @staticmethod
    @blender_version_wrapper('<','2.80')
    def is_valid_source(o):
        assert False, "TODO: NEED TO UPDATE!!! SEE 2.80+ VERSION BELOW"
        if not o: return False
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, o.layers)): return False
        if o.hide: return False
        if o.select and o == bpy.context.active_object: return False
        if not o.data.polygons: return False
        return True

    @staticmethod
    @blender_version_wrapper('>=','2.80')
    def is_valid_source(o):
        if not o: return False
        if o == bpy.context.active_object: return False
        # if o == bpy.context.edit_object: return False
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not o.visible_get(): return False
        if not o.data.polygons: return False
        return True

    @staticmethod
    @blender_version_wrapper('<','2.80')
    def is_valid_target(o):
        assert False, "TODO: NEED TO UPDATE!!! SEE 2.80+ VERSION BELOW"
        if not o: return False
        if o != bpy.context.active_object: return False
        if type(o) is not bpy.types.Object: return False
        if type(o.data) is not bpy.types.Mesh: return False
        if not any(vl and ol for vl,ol in zip(bpy.context.scene.layers, o.layers)): return False
        if o.hide: return False
        if not o.select: return False
        return True

    @staticmethod
    @blender_version_wrapper('>=','2.80')
    def is_valid_target(o):
        if not o: return False
        if o != bpy.context.active_object: return False
        # if o != bpy.context.edit_object: return False
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

    # @staticmethod
    # @blender_version_wrapper('<','2.80')
    # def get_sources():
    #     return [o for o in bpy.context.scene.objects if RetopoFlow_Blender.is_valid_source(o)]

    @staticmethod
    def get_sources():
        return [o for o in bpy.data.objects if RetopoFlow_Blender.is_valid_source(o)]

    @staticmethod
    def get_target():
        o = bpy.context.active_object
        return o if RetopoFlow_Blender.is_valid_target(o) else None


    ###################################################
    # handle scaling objects and view so sources fit
    # in unit box for scale-independent rendering

    def scale_by(self, factor):
        dprint('Scaling view, sources, and target by %0.2f' % factor)

        def scale_object(o):
            for i in range(3):
                for j in range(4):
                    o.matrix_world[i][j] *= factor

        self.actions.r3d.view_distance *= factor
        self.actions.r3d.view_location *= factor
        self.actions.space.clip_start *= factor
        self.actions.space.clip_end *= factor
        for src in self.get_sources(): scale_object(src)
        scale_object(self.get_target())

    def scale_to_unit_box(self):
        self.scale_by(1.0 / self.unit_scaling_factor)

    def unscale_from_unit_box(self):
        self.scale_by(self.unit_scaling_factor)

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

    @blender_version_wrapper('<', '2.80')
    def setup_rotate_about_active(self):
        self.end_rotate_about_active()      # clear out previous rotate-about object
        o = bpy.data.objects.new('RetopoFlow_Rotate', None)
        bpy.context.scene.objects.link(o)
        o.select = True
        bpy.context.scene.objects.active = o
        self.rot_object = o
        self.update_rot_object()
    @blender_version_wrapper('>=', '2.80')
    def setup_rotate_about_active(self):
        self.end_rotate_about_active()      # clear out previous rotate-about object
        o = object_data_add(bpy.context, None, name='RetopoFlow_Rotate')
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        self.rot_object = o
        self.update_rot_object()

    @blender_version_wrapper('<', '2.80')
    def end_rotate_about_active(self):
        if 'RetopoFlow_Rotate' not in bpy.data.objects: return
        self.del_rotate_object()
        bpy.context.scene.objects.active = self.tar_object
        del self.rot_object
    @blender_version_wrapper('>=', '2.80')
    def end_rotate_about_active(self):
        if 'RetopoFlow_Rotate' not in bpy.data.objects: return
        self.del_rotate_object()
        bpy.context.view_layer.objects.active = self.tar_object
        del self.rot_object

    @staticmethod
    @blender_version_wrapper('<', '2.80')
    def del_rotate_object():
        if 'RetopoFlow_Rotate' not in bpy.data.objects: return
        bpy.data.objects.remove(bpy.data.objects['RetopoFlow_Rotate'], do_unlink=True)
    @staticmethod
    @blender_version_wrapper('>=', '2.80')
    def del_rotate_object():
        if 'RetopoFlow_Rotate' not in bpy.data.objects: return
        bpy.data.objects.remove(bpy.data.objects['RetopoFlow_Rotate'], do_unlink=True)

    ################################################
    # Blender State methods

    @staticmethod
    def store_window_state():
        print('RetopoFlow: update implementation for store_window_state')
        return

        data = {}
        # 'region overlap': False,    # TODO
        # 'region toolshelf': False,  # TODO
        # 'region properties': False, # TODO

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

        tar = RFContext.get_target()
        data['active object'] = tar.name if tar else ''

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
                            if space.type == 'VIEW_3D':
                                data_space = {
                                    'lock_cursor':      space.lock_cursor,
                                    'show_only_render': space.show_only_render,
                                    'show_manipulator': space.show_manipulator,
                                }
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

        filepath = options.temp_filepath('state')
        open(filepath, 'wt').write(json.dumps(data))

    @staticmethod
    def update_window_state(key, val):
        print('RetopoFlow: update implementation for update_window_state')
        return

        filepath = options.temp_filepath('state')
        if not os.path.exists(filepath): return
        data = json.loads(open(filepath, 'rt').read())
        data[key] = val
        open(filepath, 'wt').write(json.dumps(data))

    def restore_window_state(self, ignore_panels=False):
        print('RetopoFlow: update implementation for restore_window_state')
        return

        filepath = options.temp_filepath('state')
        if not os.path.exists(filepath): return
        data = json.loads(open(filepath, 'rt').read())

        bpy.context.window.screen = bpy.data.screens[data['screen name']]

        for wm in bpy.data.window_managers:
            data_wm = data['data_wm'][wm.name]
            for win,data_win in zip(wm.windows, data_wm):
                for area,data_area in zip(win.screen.areas, data_win):
                    if area.type != 'VIEW_3D': continue
                    for space,data_space in zip(area.spaces, data_area):
                        if space.type != 'VIEW_3D': continue
                        space.lock_cursor = data_space['lock_cursor']
                        space.show_only_render = data_space['show_only_render']
                        space.show_manipulator = data_space['show_manipulator']

        if data['region_overlap'] and not ignore_panels:
            try:
                # TODO: CONTEXT IS INCORRECT when maximize_area was True????
                ctx = { 'area': self.area, 'space_data': self.space, 'window': self.window, 'screen': self.screen }
                rgn_toolshelf = bpy.context.area.regions[1]
                rgn_properties = bpy.context.area.regions[3]
                if data['show_toolshelf'] and rgn_toolshelf.width <= 1: bpy.ops.view3d.toolshelf(ctx)
                if data['show_properties'] and rgn_properties.width <= 1: bpy.ops.view3d.properties(ctx)
            except Exception as e:
                print(str(e))
                pass
                #self.ui_toggle_maximize_area(use_hide_panels=False)

        Drawing.set_cursor('DEFAULT')

        for o in bpy.data.objects:
            if hasattr(o, 'hide'):
                o.hide = o.name in data['hidden objects']
            if hasattr(o, 'select'):
                set_object_selection(o, o.name in data['selected objects'])
            if o.name == data['active object']:
                set_object_selection(o, True)
                set_active_object(o)

        bpy.ops.object.mode_set(mode=data['mode translated'])

    def overwrite_window_state(self):
        print('RetopoFlow: update implementation for overwrite_window_state')
        return

        if bpy.context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        # overwrite space info by hiding all non-renderable items
        for wm in bpy.data.window_managers:
            for win in wm.windows:
                for area in win.screen.areas:
                    if area.type != 'VIEW_3D': continue
                    for space in area.spaces:
                        if space.type != 'VIEW_3D': continue
                        space.lock_cursor = False
                        space.show_only_render = True
                        space.show_manipulator = False

        # hide tool shelf and properties panel if region overlap is enabled
        rgn_overlap = get_preferences().system.use_region_overlap
        if rgn_overlap and bpy.context.area:
            show_toolshelf = bpy.context.area.regions[1].width > 1
            show_properties = bpy.context.area.regions[3].width > 1
            if show_toolshelf: bpy.ops.view3d.toolshelf()
            if show_properties: bpy.ops.view3d.properties()

        # hide meshes so we can render internally
        self.rfctx.rftarget.obj_hide()
        self.rfctx.rftarget.obj_unhide_render()
        for rfsource in self.rfctx.rfsources:
            rfsource.obj_set_select(False)
            rfsource.obj_unhide_render()


    #############################################
    # backup / restore methods

    def check_auto_save(self):
        use_auto_save_temporary_files = get_preferences(self.actions.context).filepaths.use_auto_save_temporary_files
        if not use_auto_save_temporary_files: return

        auto_save_time = get_preferences(self.actions.context).filepaths.auto_save_time * 60
        if not hasattr(self, 'time_to_save'):
            self.time_to_save = auto_save_time
            return

        self.time_to_save -= self.actions.time_delta
        if self.time_to_save > 0: return
        self.save_backup()
        self.time_to_save = auto_save_time

    @staticmethod
    def has_backup():
        filepath = options.temp_filepath('blend')
        # os.path.exists(options.temp_filepath('state'))
        return os.path.exists(filepath)

    @staticmethod
    def backup_recover():
        filepath = options.temp_filepath('blend')
        if not os.path.exists(filepath): return
        bpy.ops.wm.open_mainfile(filepath=filepath)
        RetopoFlow_Blender.del_rotate_object()  # need to remove empty object for rotation
        #RFMode.restore_window_state()

    def save_backup(self):
        filepath = options.temp_filepath('blend')
        dprint('saving backup to %s' % filepath)
        if os.path.exists(filepath): os.remove(filepath)
        self.restore_window_state(ignore_panels=True)
        bpy.ops.wm.save_as_mainfile(filepath=filepath, check_existing=False, copy=True)
        self.overwrite_window_state()

    def save_normal(self):
        self.restore_window_state(ignore_panels=True)
        bpy.ops.wm.save_mainfile()
        self.overwrite_window_state()
        # note: filepath might not be set until after save
        filepath = os.path.abspath(bpy.data.filepath)
        dprint('saved to %s' % filepath)

