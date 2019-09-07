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

import bpy
from mathutils import Matrix, Vector
from bpy_extras.object_utils import object_data_add

from ...addon_common.common.decorators import blender_version_wrapper
from ...addon_common.common.blender import matrix_vector_mult
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
        if o == bpy.context.edit_object: return False
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
        if o != bpy.context.edit_object: return False
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
        # need to remove empty object for rotation
        bpy.data.objects.remove(bpy.data.objects['RetopoFlow_Rotate'], do_unlink=True)
        bpy.context.scene.objects.active = self.tar_object
        del self.rot_object

    @blender_version_wrapper('>=', '2.80')
    def end_rotate_about_active(self):
        if 'RetopoFlow_Rotate' not in bpy.data.objects: return
        # need to remove empty object for rotation
        bpy.data.objects.remove(self.rot_object, do_unlink=True)
        bpy.context.view_layer.objects.active = self.tar_object
        del self.rot_object
