'''
Copyright (C) 2023 CG Cookie
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

import time
import random
import traceback
from itertools import chain
from enum import Enum
import numpy as np
import ctypes

import bpy

from mathutils import Vector
from mathutils.geometry import intersect_line_line_2d as intersect_segment_segment_2d

from ...config.options import visualization, options, retopoflow_datablocks
from ...addon_common.common.debug import dprint, Debugger
from ...addon_common.common.decorators import timed_call
from ...addon_common.common.profiler import profiler, time_it, timing
from ...addon_common.common.utils import iter_pairs, Dict
from ...addon_common.common.maths import Point, Vec, Direction, Normal, Ray, XForm, BBox
from ...addon_common.common.maths import Point2D, Vec2D, Direction2D
from ...addon_common.common.maths_accel import Accel2D
from ...addon_common.common.maths_accel_optimized import Accel2DOptimized, Accel2D_CyWrapper, AccelPointCtypes
from ...addon_common.common.text import fix_string
from ...addon_common.common.globals import Globals
from ...addon_common.common.useractions import Actions

from ..rfmesh.rfmesh import RFMesh, RFVert, RFEdge, RFFace
from ..rfmesh.rfmesh import RFSource, RFTarget
from ..rfmesh.rfmesh_render import RFMeshRender

from .event_blocker import is_outside_working_area


# For visual debugging.
image_name = "DEPTH"
framebuffer_image = None
DEPTH_COLOR_BUFFER = None

DEPTH_BUFFER = None
PERSP_MATRIX = None


class SelectedOnly(Enum):
    ALL = 0
    SELECTED = 1
    UNSELECTED = 2


class RetopoFlow_Target:
    '''
    functions to work on target mesh (RFTarget)
    '''

    @profiler.function
    def setup_target(self):
        ''' target is the active object.  must be selected and visible '''
        tar_object = self.get_target()
        assert tar_object, 'Could not find valid target?'
        self.rftarget = RFTarget.new(tar_object, self.unit_scaling_factor)
        opts = visualization.get_target_settings()
        self.rftarget_draw = RFMeshRender.new(self.rftarget, opts)
        self.rftarget_version = None
        self.hide_target()

        self.accel_defer_recomputing = False
        self.accel_data_all   = Dict(get_default=None)
        self.accel_data_sel   = Dict(get_default=None)
        self.accel_data_unsel = Dict(get_default=None)
        self.accel_recompute = True

        Globals.target_accel = None
        if options['use cython accel tools'] and Globals.CY_TargetMeshAccel is not None:
            self.setup_target_accel()

        self._draw_count = 0

    def setup_target_accel(self):
        with time_it('[CYTHON] TargetMeshAccel initialization', enabled=options['debug cython accel tools']):
            target = self.rftarget
            actions = Actions.get_instance(None)
            region_3d = actions.r3d
            region = actions.region
            space = actions.space

            Globals.target_accel = Globals.CY_TargetMeshAccel(
                target.obj,
                target.bme,
                region,
                space,
                region_3d,
                Globals.framebuffer,
                Globals.viewport_info,
                RFVert,
                RFEdge,
                RFFace
            )

    @property
    def accel_vis_verts(self): return self.accel_data_all.verts
    @property
    def accel_vis_edges(self): return self.accel_data_all.edges
    @property
    def accel_vis_faces(self): return self.accel_data_all.faces
    @property
    def accel_vis_accel(self): return self.accel_data_all.accel
    @property
    def accel_vis_recompute(self): return self.accel_data_all.recompute
    @accel_vis_recompute.setter
    def accel_vis_recompute(self, v): self.accel_data_all.recompute = v

    @property
    def accel_sel_verts(self): return self.accel_data_sel.verts
    @property
    def accel_sel_edges(self): return self.accel_data_sel.edges
    @property
    def accel_sel_faces(self): return self.accel_data_sel.faces
    @property
    def accel_sel_accel(self): return self.accel_data_sel.accel
    @property
    def accel_sel_recompute(self): return self.accel_data_sel.recompute
    @accel_sel_recompute.setter
    def accel_sel_recompute(self, v): self.accel_data_sel.recompute = v

    @property
    def accel_unsel_verts(self): return self.accel_data_unsel.verts
    @property
    def accel_unsel_edges(self): return self.accel_data_unsel.edges
    @property
    def accel_unsel_faces(self): return self.accel_data_unsel.faces
    @property
    def accel_unsel_accel(self): return self.accel_data_unsel.accel
    @property
    def accel_unsel_recompute(self): return self.accel_data_unsel.recompute
    @accel_unsel_recompute.setter
    def accel_unsel_recompute(self, v): self.accel_data_unsel.recompute = v

    @property
    def accel_recompute(self):
        return any([ self.accel_data_all.recompute, self.accel_data_sel.recompute, self.accel_data_unsel.recompute ])
    @accel_recompute.setter
    def accel_recompute(self, v):
        self.accel_data_all.recompute = v
        self.accel_data_sel.recompute = v
        self.accel_data_unsel.recompute = v

    def hide_target(self):
        self.rftarget.obj_viewport_hide()
        self.rftarget.obj_render_hide()

    def check_target_symmetry(self):
        bad = self.rftarget.check_symmetry()
        if not bad: return

        a = ", ".join(bad) + (" axis" if len(bad)==1 else " axes")
        p = "plane" if len(bad)==1 else "planes"

        self.alert_user(
            title='Bad Target Symmetry',
            message=fix_string(f'''
                Symmetry is enabled on the {a}, but vertices were found on the "wrong" side of the symmetry {p}.

                Editing these vertices will cause them to snap to the symmetry plane.
                (Editing vertices on the "correct" side of symmetry will work as expected)

                You can see these vertices by clicking Select Bad Symmetry button
                or flip these vertices by clicking Flip Bad Symmetry button.
                Both buttons are under Target Cleaning > Symmetry
            '''),
            level='warning',
        )

    def select_bad_symmetry(self):
        self.deselect_all()
        self.rftarget.select_bad_symmetry()

    def teardown_target(self):
        # IMPORTANT: changes here should also go in rf_blender_save.backup_recover()
        self.rftarget.obj_viewport_unhide()
        self.rftarget.obj_render_unhide()

    def done_target(self):
        del self.rftarget_draw
        del self.rftarget
        self.get_target().to_mesh_clear()


    #########################################
    # split target visualization

    def clear_split_target_visualization(self):
        self.rftarget_draw.split_visualization()

    def split_target_visualization(self, verts=None, edges=None, faces=None):
        self.rftarget_draw.split_visualization(verts=verts, edges=edges, faces=faces)

    def split_target_visualization_selected(self):
        self.rftarget_draw.split_visualization(
            verts=self.get_selected_verts(),
            edges=self.get_selected_edges(),
            faces=self.get_selected_faces(),
        )

    def split_target_visualization_visible(self):
        self.rftarget_draw.split_visualization(
            verts=self.accel_vis_verts,
            edges=self.accel_vis_edges,
            faces=self.accel_vis_faces,
        )


    #########################################
    # acceleration structures

    def set_accel_defer(self, defer): self.accel_defer_recomputing = defer

    def get_accel_visible(self, **kwargs):
        accel_data = self._generate_accel_data_struct(**kwargs)
        return accel_data.accel

    def refresh_depth_buffer(self, linearize_depth_buffer=True, scale_factor=10, color=False):
        if Globals.target_accel is None:
            return
        # TEST FRAMEBUFFER and VIEWPORT INFO:
        if Globals.framebuffer is None:
            # No framebuffer available yet.
            return
        print(f'{Globals.framebuffer=} {Globals.viewport_info=}')
        global PERSP_MATRIX
        if Globals.drawing is None:
            return
        persp_matrix = Globals.drawing.r3d.perspective_matrix
        if PERSP_MATRIX is not None and PERSP_MATRIX == persp_matrix:
            return
        # Changed view (navigation).
        PERSP_MATRIX = persp_matrix.copy()
        global DEPTH_BUFFER, DEPTH_COLOR_BUFFER, framebuffer_image, image_name
        # obtain depth from the framebuffer
        width = Globals.viewport_info[2]
        height = Globals.viewport_info[3]
        depth_buffer = Globals.framebuffer.read_depth(0, 0, width, height)
        
        # Convert to numpy array and reshape to 2D (height, width)
        depth_array = np.array(depth_buffer.to_list(), dtype=np.float32)
        depth_array_2d = depth_array.reshape(height, width)
        
        # original depth is encoded nonlinearly between 0 and 1. We can linearize and scale it for visualization
        if linearize_depth_buffer:
            space = Globals.drawing.space
            f = space.clip_end
            n = space.clip_start          
            depth_array_2d = n / (f - (f - n) * depth_array_2d) * scale_factor
        
        DEPTH_BUFFER = depth_array_2d
        
        # To Color (RGB).
        if color:
            if framebuffer_image is None:
                if not image_name in bpy.data.images:
                    framebuffer_image = bpy.data.images.new(image_name, width, height, alpha=False, float_buffer=True, is_data=True)
                else:
                    framebuffer_image = bpy.data.images[image_name]
                    framebuffer_image.scale(width, height)
            x = np.expand_dims(depth_array_2d, axis=2)
            pixel_array = np.pad(np.repeat(x, 3, 2), ((0,0),(0,0),(0,1)), 'constant', constant_values=1).flatten().tolist()    
            framebuffer_image.pixels.foreach_set(pixel_array)
            
        # Globals.target_accel.py_update_depth_buffer(DEPTH_BUFFER, width, height)

    ### @timing
    def _generate_accel_data_struct(self, *, selected_only=None, force=False):
        target_version = self.get_target_version(selection=selected_only)
        view_version = self.get_view_version()
        mm = self.rftarget.mirror_mod

        accel_data = {
            None:  self.accel_data_all,
            True:  self.accel_data_sel,
            False: self.accel_data_unsel,
        }[selected_only]

        # force |= self.accel_recompute
        needs_recomputed = any([
            accel_data.recompute,
            # missing acceleration data?
            accel_data.verts is None,
            accel_data.edges is None,
            accel_data.faces is None,
            accel_data.accel is None,
            # did any important thing change since we last generated accel structure?
            accel_data.target_version              != target_version,
            accel_data.view_version                != view_version,
            accel_data.visible_bbox_factor         != options['visible bbox factor'],
            accel_data.visible_dist_offset         != options['visible dist offset'],
            accel_data.selection_occlusion_test    != options['selection occlusion test'],
            accel_data.selection_backface_test     != options['selection backface test'],
            accel_data.ray_ignore_backface_sources != self.ray_ignore_backface_sources(),
            accel_data.mirror_mod                  != (mm.x, mm.y, mm.z),
        ])

        delay_recompute = ([
            self.accel_defer_recomputing,
            self._nav,                                  # do not recompute while artist is navigating
            (time.time() - self._nav_time) < options['accel recompute delay'],  # wait just a small amount of time after artist finishes navigating
            accel_data.draw_count == self._draw_count,
        ])

        recompute = force or (needs_recomputed and not any(delay_recompute))
        if not recompute:
            '''if Globals.target_accel is not None:
                res = Globals.target_accel.ensure_bmesh()
                if res == -1:
                    accel_data.verts.clear()
                    accel_data.edges.clear()
                    accel_data.faces.clear()
                    return accel_data
                elif res == 0:
                    return accel_data'''
            # if needs_recomputed and any(delay_recompute):
            #     print(f'VIS ACCEL NEEDS RECOMPUTED, BUT DELAYED: {delay_recompute}')
            if accel_data.verts: accel_data.verts = set(self.filter_is_valid(accel_data.verts))
            if accel_data.edges: accel_data.edges = set(self.filter_is_valid(accel_data.edges))
            if accel_data.faces: accel_data.faces = set(self.filter_is_valid(accel_data.faces))
            return accel_data

        accel_data.recompute = False

        try:
            if options['use cython accel tools']:
                if Globals.target_accel is None:
                    self.setup_target_accel()
                    
                use_cy_debug = options['debug cython accel tools']

                # TEST CYTHON ALTERNATIVE:
                # Use accelerated functions for geometry processing
                match selected_only:
                    case None:
                        selected_only = SelectedOnly.ALL
                    case True:
                        selected_only = SelectedOnly.SELECTED
                    case False:
                        selected_only = SelectedOnly.UNSELECTED
                    case _:
                        selected_only = SelectedOnly.ALL

                actions = Actions.get_instance(None)
                region = Globals.drawing.rgn
                Globals.target_accel.py_update_region(region)
                region3d = Globals.drawing.r3d
                space = Globals.drawing.space
                Globals.target_accel.py_update_view(space, region3d, Globals.framebuffer, Globals.viewport_info)

                Globals.target_accel.py_update_bmesh(self.rftarget.bme)
                Globals.target_accel.py_set_symmetry(mm.x, mm.y, mm.z)

                with time_it('[CYTHON] TargetMeshAccel.update()', enabled=use_cy_debug):
                    if use_cy_debug: print(f'[CYTHON] TargetMeshAccel.update()     <----- begin')
                    if not Globals.target_accel.update(selected_only.value, debug=use_cy_debug):
                        raise Exception('Error updating TargetMeshAccel.')
                        accel_data.accel = None
                        accel_data.verts = set()
                        accel_data.edges = set()
                        accel_data.faces = set()
                        return accel_data

                with time_it('[CYTHON] TargetMeshAccel.get_visible_geom()', enabled=use_cy_debug):
                    if use_cy_debug: print(f'[CYTHON] TargetMeshAccel.get_visible_geom()     <----- begin')
                    accel_data.verts, accel_data.edges, accel_data.faces = Globals.target_accel.get_visible_geom(self.rftarget.bme, verts=True, edges=True, faces=True)

                # with time_it('[CYTHON] getting selected geometry', enabled=use_cy_debug):
                #     sel_verts, sel_edges, sel_faces = Globals.target_accel.get_selected_geom(self.rftarget.bme, verts=True, edges=True, faces=True)

                # Test Cython SpatialAccel structure (WIP, unstable).
                # accel_data.accel = Accel2D_CyWrapper(Globals.target_accel)
                
                # TODO: REMOVE THIS WHEN CYTHON ACCEL IS COMPLETE.
                '''with time_it('[PYTHON] building accel struct', enabled=use_cy_debug):
                    accel_data.accel = Accel2D(
                        f'RFTarget visible geometry ({selected_only=})',
                        accel_data.verts,
                        accel_data.edges,
                        accel_data.faces,
                        self.iter_point2D_symmetries
                    )'''

                with time_it('[CYTHON+PYTHON] building Python Accel2DOptimized struct from Cython pre-computed accel2d_points', enabled=use_cy_debug):
                    accel_data.accel = Accel2DOptimized(
                        # accel_data.verts, accel_data.edges, accel_data.faces,
                        self.rftarget.bme.verts, self.rftarget.bme.edges, self.rftarget.bme.faces,
                        (RFVert, RFEdge, RFFace),  # wrappers...
                        *Globals.target_accel.get_accel2d_points_as_ctypes(),
                        region.width, region.height
                    )

            else:
                if Globals.target_accel is not None:
                    # NOTE: this is a hack to force the Python version to be used else where.
                    # in case user disabled the performance option.
                    Globals.target_accel = None

                # Fallback to the Python version.
                match selected_only:
                    case None:
                        verts, edges, faces = None, None, None
                    case True:
                        verts = self.get_selected_verts()
                        edges = self.get_selected_edges()
                        faces = self.get_selected_faces()
                    case False:
                        verts = self.get_unselected_verts()
                        edges = self.get_unselected_edges()
                        faces = self.get_unselected_faces()

                with time_it('getting visible geometry', enabled=False):
                    accel_data.verts = self.visible_verts(verts=verts)
                    accel_data.edges = self.visible_edges(edges=edges, verts=accel_data.verts)
                    accel_data.faces = self.visible_faces(faces=faces, verts=accel_data.verts)
                    print(f'[PYTHON] accel_data.verts={len(list(accel_data.verts))}')
                    print(f'[PYTHON] accel_data.edges={len(list(accel_data.edges))}')
                    print(f'[PYTHON] accel_data.faces={len(list(accel_data.faces))}')
                with time_it('building accel struct', enabled=False):
                    accel_data.accel = Accel2D(
                        f'RFTarget visible geometry ({selected_only=})',
                        accel_data.verts,
                        accel_data.edges,
                        accel_data.faces,
                        self.iter_point2D_symmetries
                    )

        except Exception as e:
            # TODO: Handle possible issues.
            print(f'[Cython] Error: {e}')
            import traceback
            traceback.print_exc()
            print("\nCall Stack:")
            traceback.print_stack()

        # remember important things that influence accel structure
        accel_data.target_version              = target_version
        accel_data.view_version                = view_version
        accel_data.visible_bbox_factor         = options['visible bbox factor']
        accel_data.visible_dist_offset         = options['visible dist offset']
        accel_data.selection_occlusion_test    = options['selection occlusion test']
        accel_data.selection_backface_test     = options['selection backface test']
        accel_data.ray_ignore_backface_sources = self.ray_ignore_backface_sources()
        accel_data.draw_count                  = self._draw_count
        accel_data.mirror_mod                  = (mm.x, mm.y, mm.z)
        
        return accel_data

    @staticmethod
    def filter_is_valid(bmelems): return filter(RFMesh.fn_is_valid, bmelems)

    ### @timing
    def get_vis_verts(self, **kwargs):
        self._generate_accel_data_struct(**kwargs)
        return self.accel_vis_verts
    ### @timing
    def get_vis_edges(self, **kwargs):
        self._generate_accel_data_struct(**kwargs)
        return self.accel_vis_edges
    ### @timing
    def get_vis_faces(self, **kwargs):
        self._generate_accel_data_struct(**kwargs)
        return self.accel_vis_faces
    ### @timing
    def get_vis_geom(self,  **kwargs):
        self._generate_accel_data_struct(**kwargs)
        return self.accel_vis_verts, self.accel_vis_edges, self.accel_vis_faces

    ### @timing
    def get_custom_vis_accel(self, selection_only=None, include_verts=True, include_edges=True, include_faces=True, symmetry=True):
        verts, edges, faces = self.visible_geom()
        if selection_only is not None:
            fn_select = lambda bmelem: bmelem.select == selection_only
            verts, edges, faces = list(filter(fn_select, verts)), list(filter(fn_select, edges)), list(filter(fn_select, faces))
        return Accel2D(
            'RFTarget custom',
            (verts if include_verts else []),
            (edges if include_edges else []),
            (faces if include_faces else []),
            self.iter_point2D_symmetries if symmetry else self.iter_point2D_nosymmetry,
        )

    ### @timing
    def accel_nearest2D_vert(self, point=None, max_dist=None, vis_accel=None, selected_only=None):
        if point is None:
            if self.actions.is_navigating:
                return (None, None)
            if self.actions.is_idle:
                return (None, None)
            if is_outside_working_area(self):
                return (None, None)
            point = self.actions.mouse
        p2d = self.get_point2D(point)

        if not vis_accel:
            vis_accel = self.get_accel_visible(selected_only=selected_only)
        if not vis_accel: return (None, None)

        if isinstance(vis_accel, (Accel2D, Accel2DOptimized)):
            if not max_dist:
                # no max_dist, so get _all_ visible vertices
                verts = self.accel_vis_verts
            else:
                # get all visible vertices within max_dist from mouse
                max_dist = self.drawing.scale(max_dist)
                verts = vis_accel.get_verts(p2d, max_dist)

            if verts is None:
                return None, None

            if selected_only is not None:
                verts = { bmv for bmv in verts if bmv.select == selected_only }

            return self.rftarget.nearest2D_bmvert_Point2D(p2d, self.iter_point2D_symmetries, verts=verts, max_dist=max_dist)
        else:
            if max_dist is None:
                max_dist = 0.0
            nearest_data = vis_accel.accel.find_nearest_vert(p2d.x, p2d.y, 0.0, max_dist, wrapped=True)  # x, y, depth, max_dist
            if nearest_data:
                return nearest_data['elem'], nearest_data['distance']
            return None, None

    ### @timing
    def accel_nearest2D_edge(self, point=None, max_dist=None, vis_accel=None, selected_only=None, edges_only=None):
        if point is None:
            if self.actions.is_navigating:
                return (None, None)
            if self.actions.is_idle:
                return (None, None)
            if is_outside_working_area(self):
                return (None, None)
            point = self.actions.mouse
        p2d = self.get_point2D(point)
        if not vis_accel:
            vis_accel = self.get_accel_visible(selected_only=selected_only)
        if not vis_accel: return (None, None)

        if isinstance(vis_accel, (Accel2D, Accel2DOptimized)):
            if not max_dist:
                edges = self.accel_vis_edges
            else:
                max_dist = self.drawing.scale(max_dist)
                edges = vis_accel.get_edges(p2d, max_dist)

            if selected_only is not None:
                edges = { bme for bme in edges if bme.select == selected_only }
            if edges_only is not None:
                edges = { bme for bme in edges if bme in edges_only }

            return self.rftarget.nearest2D_bmedge_Point2D(p2d, self.iter_point2D_symmetries, edges=edges, max_dist=max_dist)
        else:
            if max_dist is None:
                max_dist = 0.0
            nearest_data = vis_accel.accel.find_nearest_edge(p2d.x, p2d.y, 0.0, max_dist, wrapped=True)  # x, y, depth, max_dist
            if nearest_data:
                return nearest_data['elem'], nearest_data['distance']
            return None, None

    ### @timing
    def accel_nearest2D_face(self, point=None, max_dist=None, vis_accel=None, selected_only=None, faces_only=None):
        if point is None:
            if self.actions.is_navigating:
                return (None, None)
            if self.actions.is_idle:
                return (None, None)
            if is_outside_working_area(self):
                return (None, None)
            point = self.actions.mouse
        p2d = self.get_point2D(point)

        if not vis_accel:
            vis_accel = self.get_accel_visible(selected_only=selected_only)
        if not vis_accel: return (None, None)

        if isinstance(vis_accel, (Accel2D, Accel2DOptimized)):
            if not max_dist:
                faces = self.accel_vis_faces
            else:
                max_dist = self.drawing.scale(max_dist)
                faces = vis_accel.get_faces(p2d, max_dist)

            if selected_only is not None:
                faces = { bmf for bmf in faces if bmf.select == selected_only }
            if faces_only is not None:
                faces = { bmf for bmf in faces if bmf in faces_only }

            return self.rftarget.nearest2D_bmface_Point2D(self.Vec_forward(), p2d, self.iter_point2D_symmetries, faces=faces) #, max_dist=max_dist)
        else:
            if max_dist is None:
                max_dist = 0.0
            nearest_data = vis_accel.accel.find_nearest_edge(p2d.x, p2d.y, 0.0, max_dist, wrapped=True)  # x, y, depth, max_dist
            if nearest_data:
                return nearest_data['elem'], nearest_data['distance']
            return None, None

    def accel_nearest2D_geom(self, **kwargs):
        if (vert := self.accel_nearest2D_vert(**kwargs)[0]): return vert
        if (edge := self.accel_nearest2D_edge(**kwargs)[0]): return edge
        if (face := self.accel_nearest2D_face(**kwargs)[0]): return face
        return None



    #########################################
    # find target entities in screen space

    def get_point2D(self, point):
        if not point: return None
        if len(point) == 2: return point
        return self.Point_to_Point2D(point)

    def _iter_symmetry_points(self, point, normal):
        mm = self.rftarget.mirror_mod
        mx,my,mz = mm.x, mm.y, mm.z
        yield ( point, normal )
        if not mx and not my and not mz: return
        px,py,pz = point
        nx,ny,nz = normal
        if mx:               yield ( Point((-px,  py,  pz)), Normal((-nx,  ny,  nz)) )
        if my:               yield ( Point(( px, -py,  pz)), Normal(( nx, -ny,  nz)) )
        if mz:               yield ( Point(( px,  py, -pz)), Normal(( nx,  ny, -nz)) )
        if mx and my:        yield ( Point((-px, -py,  pz)), Normal((-nx, -ny,  nz)) )
        if mx and mz:        yield ( Point((-px,  py, -pz)), Normal((-nx,  ny, -nz)) )
        if my and mz:        yield ( Point(( px, -py, -pz)), Normal(( nx, -ny, -nz)) )
        if mx and my and mz: yield ( Point((-px, -py, -pz)), Normal((-nx, -ny, -nz)) )

    def iter_point2D_symmetries(self, co, normal, *, fwd=None):
        if not fwd: fwd = self.Vec_forward()
        yield from (
            pt2D
            for (pt3D, no3D) in self._iter_symmetry_points(co, normal)
            if self.Point2D_in_area(pt2D := self.Point_to_Point2D(pt3D)) and no3D.dot(fwd) <= 0
        )
    def iter_point2D_nosymmetry(self, co, normal, *, fwd=None):
        yield self.Point_to_Point2D(co)

    @profiler.function
    def nearest2D_vert(self, point=None, max_dist=None, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.iter_point2D_symmetries, verts=verts, max_dist=max_dist, fwd=self.Vec_forward())

    @profiler.function
    def nearest2D_verts(self, point=None, max_dist:float=10, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmverts_Point2D(xy, max_dist, self.iter_point2D_symmetries, verts=verts, fwd=self.Vec_forward())

    @profiler.function
    def nearest2D_edge(self, point=None, max_dist=None, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedge_Point2D(xy, self.iter_point2D_symmetries, edges=edges, max_dist=max_dist, fwd=self.Vec_forward())

    @profiler.function
    def nearest2D_edges(self, point=None, max_dist:float=10, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedges_Point2D(xy, max_dist, self.iter_point2D_symmetries, edges=edges, fwd=self.Vec_forward())

    # TODO: implement max_dist
    @profiler.function
    def nearest2D_face(self, point=None, max_dist=None, faces=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmface_Point2D(self.Vec_forward(), xy, self.iter_point2D_symmetries, faces=faces, fwd=self.Vec_forward())

    # TODO: fix this function! Izzza broken
    @profiler.function
    def nearest2D_faces(self, point=None, max_dist:float=10, faces=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmfaces_Point2D(xy, self.iter_point2D_symmetries, faces=faces, fwd=self.Vec_forward())


    ########################################
    # find target entities in world space

    def get_point3D(self, point):
        if point.is_3D(): return point
        xyz,_,_,_ = self.raycast_sources_Point2D(point)
        return xyz

    def nearest_verts_point(self, point, max_dist:float, bmverts=None):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.rftarget.nearest_bmverts_Point(xyz, max_dist, bmverts=bmverts)

    def nearest_verts_mouse(self, max_dist:float):
        return self.nearest_verts_point(self.actions.mouse, max_dist)


    #######################################
    # get visible geometry

    def visible_verts(self, verts=None):             return self.rftarget.visible_verts(self.gen_is_visible(), verts=verts)
    def visible_edges(self, verts=None, edges=None): return self.rftarget.visible_edges(self.gen_is_visible(), verts=verts, edges=edges)
    def visible_faces(self, verts=None, faces=None): return self.rftarget.visible_faces(self.gen_is_visible(), verts=verts, faces=faces)
    def visible_geom(self): return (verts := self.visible_verts()), self.visible_edges(verts=verts), self.visible_faces(verts=verts)

    def nonvisible_verts(self):             return self.rftarget.visible_verts(self.gen_is_nonvisible())
    def nonvisible_edges(self, verts=None): return self.rftarget.visible_edges(self.gen_is_nonvisible(), verts=verts)
    def nonvisible_faces(self, verts=None): return self.rftarget.visible_faces(self.gen_is_nonvisible(), verts=verts)
    def nonvisible_geom(self): return (verts := self.nonvisible_verts()), self.nonvisible_edges(verts=verts), self.nonvisible_faces(verts=verts)

    def iter_verts(self): yield from self.rftarget.iter_verts()
    def iter_edges(self): yield from self.rftarget.iter_edges()
    def iter_faces(self): yield from self.rftarget.iter_faces()

    ########################################
    # symmetry utils

    def apply_mirror_symmetry(self):
        self.undo_push('applying mirror symmetry')
        self.rftarget.apply_mirror_symmetry(self.nearest_sources_Point)
        self.dirty()

    def flip_symmetry_verts_to_correct_side(self):
        self.undo_push('flipping verts to correct side of symmetry')
        self.rftarget.flip_symmetry_verts_to_correct_side()
        self.dirty()

    @profiler.function
    def clip_pointloop(self, pointloop, connected):
        # assuming loop will cross symmetry line exactly zero or two times
        l2w_point,w2l_point = self.rftarget.xform.l2w_point,self.rftarget.xform.w2l_point
        pointloop = [w2l_point(pt) for pt in pointloop]
        if self.rftarget.mirror_mod.x and any(p.x < 0 for p in pointloop):
            if connected:
                rot_idx = next(i for i,p in enumerate(pointloop) if p.x < 0)
                pointloop = pointloop[rot_idx:] + pointloop[:rot_idx]
            npl = []
            for p0,p1 in iter_pairs(pointloop, connected):
                if p0.x < 0 and p1.x < 0: continue
                elif p0.x == 0: npl += [p0]
                elif p0.x > 0 and p1.x > 0: npl += [p0]
                else:
                    connected = False
                    npl += [p0 + (p1 - p0) * (p0.x / (p0.x - p1.x))]
            if npl:
                npl[0].x = 0
                npl[-1].x = 0
            pointloop = npl
        if self.rftarget.mirror_mod.y and any(p.y > 0 for p in pointloop):
            if connected:
                rot_idx = next(i for i,p in enumerate(pointloop) if p.y > 0)
                pointloop = pointloop[rot_idx:] + pointloop[:rot_idx]
            npl = []
            for p0,p1 in iter_pairs(pointloop, connected):
                if p0.y > 0 and p1.y > 0: continue
                elif p0.y == 0: npl += [p0]
                elif p0.y < 0 and p1.y < 0: npl += [p0]
                else:
                    connected = False
                    npl += [p0 + (p1 - p0) * (p0.y / (p0.y - p1.y))]
            if npl:
                npl[0].y = 0
                npl[-1].y = 0
            pointloop = npl
        if self.rftarget.mirror_mod.z and any(p.z < 0 for p in pointloop):
            if connected:
                rot_idx = next(i for i,p in enumerate(pointloop) if p.z < 0)
                pointloop = pointloop[rot_idx:] + pointloop[:rot_idx]
            npl = []
            for p0,p1 in iter_pairs(pointloop, connected):
                if p0.z < 0 and p1.z < 0: continue
                elif p0.z == 0: npl += [p0]
                elif p0.z > 0 and p1.z > 0: npl += [p0]
                else:
                    connected = False
                    npl += [p0 + (p1 - p0) * (p0.z / (p0.z - p1.z))]
            if npl:
                npl[0].z = 0
                npl[-1].z = 0
            pointloop = npl
        pointloop = [l2w_point(pt) for pt in pointloop]
        return (pointloop, connected)

    def clamp_pointloop(self, pointloop, connected):
        return (pointloop, connected)

    def is_point_on_mirrored_side(self, point):
        p = self.rftarget.xform.w2l_point(point)
        if self.rftarget.mirror_mod.x and p.x < 0: return True
        if self.rftarget.mirror_mod.y and p.y > 0: return True
        if self.rftarget.mirror_mod.z and p.z < 0: return True
        return False

    def symmetry_planes_for_point(self, point):
        point = self.rftarget.xform.w2l_point(point)
        mm = self.rftarget.mirror_mod
        th = mm.symmetry_threshold * self.rftarget.unit_scaling_factor / 2.0
        planes = set()
        if mm.x and abs(point.x) <= th: planes.add('x')
        if mm.y and abs(point.y) <= th: planes.add('y')
        if mm.z and abs(point.z) <= th: planes.add('z')
        return planes

    def mirror_point(self, point):
        mm = self.rftarget.mirror_mod
        if mm.x or mm.y or mm.z:
            xform = self.rftarget.xform
            p = xform.w2l_point(point)
            if mm.x and p.x < 0: p.x = -p.x
            if mm.y and p.y > 0: p.y = -p.y
            if mm.z and p.z < 0: p.z = -p.z
            point = xform.l2w_point(p)
        return point

    def mirror_point_normal(self, point, normal):
        mm = self.rftarget.mirror_mod
        if mm.x or mm.y or mm.z:
            xform = self.rftarget.xform
            p, n = xform.w2l_point(point), xform.w2l_normal(normal)
            if mm.x and p.x < 0: p.x, n.x = -p.x, -n.x
            if mm.y and p.y > 0: p.y, n.y = -p.y, -n.y
            if mm.z and p.z < 0: p.z, n.z = -p.z, -n.z
            point, normal = xform.l2w_point(p), xform.l2w_normal(n)
        return (point, normal)

    def get_point_symmetry(self, point):
        return self.rftarget.get_point_symmetry(point)

    def snap_to_symmetry(self, point, symmetry, to_world=True, from_world=True):
        return self.rftarget.snap_to_symmetry(point, symmetry, to_world=to_world, from_world=from_world)

    def clamp_point_to_symmetry(self, point):
        return self.rftarget.symmetry_real(point)

    def push_then_snap_all_verts(self):
        self.undo_push('push then snap all non-hidden verts')
        d = options['push and snap distance']
        bmvs = [bmv for bmv in self.rftarget.get_verts() if not bmv.hide]
        for bmv in bmvs: bmv.co += bmv.normal * d
        self.rftarget.snap_all_nonhidden_verts(self.nearest_sources_Point)
        self.recalculate_face_normals(verts=bmvs)

    def push_then_snap_selected_verts(self):
        self.undo_push('push then snap selected verts')
        d = options['push and snap distance']
        bmvs = self.rftarget.get_selected_verts()
        for bmv in bmvs: bmv.co += bmv.normal * d
        self.rftarget.snap_selected_verts(self.nearest_sources_Point)
        self.recalculate_face_normals(verts=bmvs)

#    def snap_verts_filter(self, fn_filter):
#        self.undo_push('snap filtered verts')
#        self.rftarget.snap_verts_filter(self.nearest_source_Point, fn_filter)
#
#    def snap_all_verts(self):
#        self.undo_push('snap all verts')
#        self.rftarget.snap_all_verts(self.nearest_sources_Point)
#
#    def snap_all_nonhidden_verts(self):
#        self.undo_push('snap all visible verts')
#        self.rftarget.snap_all_nonhidden_verts(self.nearest_sources_Point)
#
#    def snap_selected_verts(self):
#        self.undo_push('snap visible and selected verts')
#        self.rftarget.snap_selected_verts(self.nearest_sources_Point)
#
#    def snap_unselected_verts(self):
#        self.undo_push('snap visible and unselected verts')
#        self.rftarget.snap_unselected_verts(self.nearest_sources_Point)
#
#    def snap_visible_verts(self):
#        self.undo_push('snap visible verts')
#        nonvisible_verts = self.nonvisible_verts()
#        self.rftarget.snap_verts_filter(self.nearest_sources_Point, lambda v: not v.hide and v not in nonvisible_verts)
#
#    def snap_nonvisible_verts(self):
#        self.undo_push('snap non-visible verts')
#        nonvisible_verts = self.nonvisible_verts()
#        self.rftarget.snap_verts_filter(self.nearest_sources_Point, lambda v: not v.hide and v in nonvisible_verts)

    def remove_all_doubles(self):
        self.undo_push('remove all doubles')
        self.rftarget.remove_all_doubles(options['remove doubles dist'])

    def remove_selected_doubles(self):
        self.undo_push('remove selected doubles')
        self.rftarget.remove_selected_doubles(options['remove doubles dist'])

    def flip_face_normals(self):
        self.undo_push('flipping face normals')
        self.rftarget.flip_face_normals()

    def recalculate_face_normals(self, *, verts=None, faces=None):
        self.undo_push('recalculating face normals')
        self.rftarget.recalculate_face_normals(verts=verts, faces=faces)

    #######################################
    # target manipulation functions
    #
    # note: these do NOT dirty the target!
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    def snap_vert(self, vert:RFVert, *, snap_to_symmetry=None):
        if not vert or  not vert.is_valid: return
        xyz,norm,_,_ = self.nearest_sources_Point(vert.co)
        if snap_to_symmetry:
            xyz = self.snap_to_symmetry(xyz, snap_to_symmetry)
        vert.co = xyz
        vert.normal = norm

    def snap2D_vert(self, vert:RFVert):
        if not vert or  not vert.is_valid: return
        xy = self.Point_to_Point2D(vert.co)
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm

    def offset2D_vert(self, vert:RFVert, delta_xy:Vec2D):
        if not vert or  not vert.is_valid: return
        xy = self.Point_to_Point2D(vert.co) + delta_xy
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm

    def set2D_vert(self, vert:RFVert, xy:Point2D, snap_to_symmetry=None):
        if not vert or  not vert.is_valid: return
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        if snap_to_symmetry:
            xyz = self.snap_to_symmetry(xyz, snap_to_symmetry)
        vert.co = xyz
        vert.normal = norm
        return xyz

    def set2D_crawl_vert(self, vert:RFVert, xy:Point2D):
        if not vert or  not vert.is_valid: return
        hits = self.raycast_sources_Point2D_all(xy)
        if not hits: return
        # find closest
        co = vert.co
        p,n,_,_ = min(hits, key=lambda hit:(hit[0]-co).length)
        vert.co = p
        vert.normal = n


    def new_vert_point(self, xyz:Point, *, ignore_backface=None):
        if not xyz: return None
        xyz, norm, _, _ = self.nearest_sources_Point(xyz)
        if not xyz or not norm: return None
        rfvert = self.rftarget.new_vert(xyz, norm)
        d = self.Point_to_Direction(xyz)
        _, n, _, _ = self.raycast_sources_Point(xyz, ignore_backface=ignore_backface)
        if d and n and n.dot(d) > 0.5: self._detected_bad_normals = True
        # if (d is None or norm.dot(d) > 0.5) and self.is_visible(rfvert.co, bbox_factor_override=0, dist_offset_override=0):
        #     self._detected_bad_normals = True
        return rfvert

    def new2D_vert_point(self, xy:Point2D, *, ignore_backface=None):
        xyz, norm, _, _ = self.raycast_sources_Point2D(xy, ignore_backface=ignore_backface)
        if not xyz or not norm: return None
        rfvert = self.rftarget.new_vert(xyz, norm)
        if rfvert.normal.dot(self.Point2D_to_Direction(xy)) >= 0 and self.is_visible(rfvert.co):
            self._detected_bad_normals = True
        return rfvert

    def new2D_vert_mouse(self, *, ignore_backface=None):
        return self.new2D_vert_point(self.actions.mouse, ignore_backface=ignore_backface)

    def new_edge(self, verts):
        return self.rftarget.new_edge(verts)

    def new_face(self, verts):
        return self.rftarget.new_face(verts)

    def merge_vertices(self, vert1, vert2, merge_point: str = 'CENTER'):
        """
        Merge two vertices together
        
        Args:
            vert1: First RFVert
            vert2: Second RFVert
            merge_point: Merge location ('CENTER', 'FIRST', or 'LAST')
        """
        if not vert1 or not vert2: return None
        if not vert1.is_valid or not vert2.is_valid: return None

        # Perform the merge in the target
        ret = self.rftarget.merge_vertices(vert1, vert2, merge_point)
        self.update_verts_faces([ret])
        return ret
    
    def remove_by_distance(self, verts, dist):
        return self.rftarget.remove_by_distance(verts, dist)

    def bridge_vertloop(self, vloop0, vloop1, connected):
        assert len(vloop0) == len(vloop1), "loops must have same vertex counts"
        faces = []
        for pair0,pair1 in zip(iter_pairs(vloop0, connected), iter_pairs(vloop1, connected)):
            v00,v01 = pair0
            v10,v11 = pair1
            nf = self.new_face((v00,v01,v11,v10))
            if nf: faces.append(nf)
        return faces

    def holes_fill(self, edges, sides):
        self.rftarget.holes_fill(edges, sides)

    def update_verts_faces(self, verts):
        self.rftarget.update_verts_faces(verts)

    def update_face_normal(self, face):
        return self.rftarget.update_face_normal(face)

    def clean_duplicate_bmedges(self, vert):
        return self.rftarget.clean_duplicate_bmedges(vert)

    def remove_duplicate_bmfaces(self, vert):
        return self.rftarget.remove_duplicate_bmfaces(vert)

    ###################################################

    def ensure_lookup_tables(self):
        self.rftarget.ensure_lookup_tables()

    def dirty(self, *, selectionOnly=False):
        self.accel_recompute = True
        self.rftarget.dirty(selectionOnly=selectionOnly)

    def dirty_render(self):
        self.rftarget_draw.dirty()

    def get_target_version(self, selection=True):
        return self.rftarget.get_version(selection=selection)

    def get_target_geometry_counts(self):
        return self.rftarget.get_geometry_counts()

    ###################################################

    # determines if any of the edges cross
    # uses face normal to compute 2D projection
    # returns None if any of the points cannot project
    def is_face_twisted(self, bmverts, Point_to_Point2D=None):
        if not Point_to_Point2D:
            # estimate a normal
            v0, v1, v2 = bmverts[:3]
            n = (v1.co-v0.co).cross(v2.co-v0.co)
            t = Direction.uniform()
            y = Direction(t.cross(n))
            x = Direction(y.cross(n))
            Point_to_Point2D = lambda point: Vec2D((x.dot(point), y.dot(point)))
        pts = [Point_to_Point2D(bmv.co) for bmv in bmverts]
        if not all(pts): return None
        l = len(pts)
        for i0 in range(l):
            i1 = (i0 + 1) % l
            p0, p1 = pts[i0], pts[i1]
            for j0 in range(i1 + 1, l):
                j1 = (j0 + 1) % l
                p2, p3 = pts[j0], pts[j1]
                if intersect_segment_segment_2d(p0, p1, p2, p3): return True
        return False


    ###################################################


    def get_quadwalk_edgesequence(self, edge):
        return self.rftarget.get_quadwalk_edgesequence(edge)

    def get_edge_loop(self, edge):
        return self.rftarget.get_edge_loop(edge)

    def get_inner_edge_loop(self, edge):
        return self.rftarget.get_inner_edge_loop(edge)

    def get_face_loop(self, edge):
        return self.rftarget.get_face_loop(edge)

    def is_quadstrip_looped(self, edge):
        return self.rftarget.is_quadstrip_looped(edge)

    def iter_quadstrip(self, edge):
        yield from self.rftarget.iter_quadstrip(edge)

    ###################################################

    def get_selected_verts(self): return self.rftarget.get_selected_verts()
    def get_selected_edges(self): return self.rftarget.get_selected_edges()
    def get_selected_faces(self): return self.rftarget.get_selected_faces()
    def get_selected_geom(self): return self.get_selected_verts(), self.get_selected_edges(), self.get_selected_faces()

    def get_unselected_verts(self): return self.rftarget.get_unselected_verts()
    def get_unselected_edges(self): return self.rftarget.get_unselected_edges()
    def get_unselected_faces(self): return self.rftarget.get_unselected_faces()
    def get_unselected_geom(self): return self.get_unselected_verts(), self.get_unselected_edges(), self.get_unselected_faces()

    def get_hidden_verts(self): return self.rftarget.get_hidden_verts()
    def get_hidden_edges(self): return self.rftarget.get_hidden_edges()
    def get_hidden_faces(self): return self.rftarget.get_hidden_faces()
    def get_hidden_geom(self): return self.get_hidden_verts(), self.get_hidden_edges(), self.get_hidden_faces()

    def get_revealed_verts(self): return self.rftarget.get_revealed_verts()
    def get_revealed_edges(self): return self.rftarget.get_revealed_edges()
    def get_revealed_faces(self): return self.rftarget.get_revealed_faces()

    def any_verts_selected(self):
        return self.rftarget.any_verts_selected()

    def any_edges_selected(self):
        return self.rftarget.any_edges_selected()

    def any_faces_selected(self):
        return self.rftarget.any_faces_selected()

    def any_selected(self):
        return self.rftarget.any_selected()

    def none_selected(self):
        return not self.any_selected()

    def deselect_all(self):
        self.rftarget.deselect_all()

    def deselect(self, elems, supparts=True, subparts=True):
        self.rftarget.deselect(elems, supparts=supparts, subparts=subparts)

    def select(self, elems, supparts=True, subparts=True, only=True):
        self.rftarget.select(elems, supparts=supparts, subparts=subparts, only=only)

    def select_toggle(self):
        self.rftarget.select_toggle()

    def select_invert(self):
        self.rftarget.select_invert()

    def select_linked(self, *, select=True, connected_to=None):
        self.rftarget.select_linked(select=select, connected_to=connected_to)

    def select_edge_loop(self, edge, only=True, **kwargs):
        eloop,connected = self.get_edge_loop(edge)
        self.rftarget.select(eloop, only=only, **kwargs)

    def select_inner_edge_loop(self, edge, **kwargs):
        eloop,connected = self.get_inner_edge_loop(edge)
        self.rftarget.select(eloop, **kwargs)

    def pin_selected(self):
        self.undo_push('pinning selected')
        self.rftarget.pin_selected()
        self.dirty()
    def unpin_selected(self):
        self.undo_push('unpinning selected')
        self.rftarget.unpin_selected()
        self.dirty()
    def unpin_all(self):
        self.undo_push('unpinning all')
        self.rftarget.unpin_all()
        self.dirty()

    def mark_seam_selected(self):
        self.undo_push('pinning selected')
        self.rftarget.mark_seam_selected()
        self.dirty()
    def clear_seam_selected(self):
        self.undo_push('unpinning selected')
        self.rftarget.clear_seam_selected()
        self.dirty()

    def hide_selected(self):
        self.undo_push('hide selected')
        verts, edges, faces = self.get_selected_geom()
        hide_elems = {
            *verts, *(bmv for bme in edges for bmv in bme.verts),      *(bmv for bmf in faces for bmv in bmf.verts),
            *edges, *(bme for bmf in faces for bme in bmf.edges),      *(bme for bmv in verts for bme in bmv.link_edges),
            *faces, *(bmf for bmv in verts for bmf in bmv.link_faces), *(bmf for bme in edges for bmf in bme.link_faces),
        }
        for e in hide_elems:
            e.select = False  # Fix #1265. Hiding part of the mesh breaks orbit around selection.
            e.hide = True
        self.dirty()

    def hide_visible(self):
        self.undo_push('hide visible')
        verts, edges, faces = self.get_vis_geom()
        hide_elems = {
            *verts, *(bmv for bme in edges for bmv in bme.verts),      *(bmv for bmf in faces for bmv in bmf.verts),
            *edges, *(bme for bmf in faces for bme in bmf.edges),      *(bme for bmv in verts for bme in bmv.link_edges),
            *faces, *(bmf for bmv in verts for bmf in bmv.link_faces), *(bmf for bme in edges for bmf in bme.link_faces),
        }
        for e in hide_elems: e.hide = True
        self.dirty()

    def hide_nonvisible(self):
        self.undo_push('hide visible')
        verts, edges, faces = self.nonvisible_geom()
        hide_elems = {
            *verts, *(bmv for bme in edges for bmv in bme.verts),      *(bmv for bmf in faces for bmv in bmf.verts),
            *edges, *(bme for bmf in faces for bme in bmf.edges),      *(bme for bmv in verts for bme in bmv.link_edges),
            *faces, *(bmf for bmv in verts for bmf in bmv.link_faces), *(bmf for bme in edges for bmf in bme.link_faces),
        }
        for e in hide_elems: e.hide = True
        self.dirty()

    def hide_unselected(self):
        self.undo_push('hide unselected')
        for e in chain(*self.get_unselected_geom()): e.hide = True
        self.dirty()

    def reveal_hidden(self):
        self.undo_push('reveal hidden')
        for e in chain(*self.get_hidden_geom()): e.hide = False
        self.dirty()


    #######################################################

    def get_verts_link_edges(self, verts):
        return RFVert.get_link_edges(verts)

    def get_verts_link_faces(self, verts):
        return RFVert.get_link_faces(verts)

    def get_edges_verts(self, edges):
        return RFEdge.get_verts(edges)

    def get_faces_verts(self, faces):
        return RFFace.get_verts(faces)

    #######################################################
    def smooth_edge_flow(self, iterations=10):
        self.undo_push(f'smooth edge flow')

        # get connected loops/strips
        all_edges = set(self.get_selected_edges())
        edge_sets = []
        while all_edges:
            current_set = set()
            working = { next(iter(all_edges)) }
            while working:
                e = working.pop()
                if e not in all_edges: continue
                all_edges.discard(e)
                current_set.add(e)
                v0,v1 = e.verts
                working.update(o for o in v0.link_edges if o.select)
                working.update(o for o in v1.link_edges if o.select)
            edge_sets.append(current_set)

        niters = 1 if len(edge_sets)==1 else iterations

        for i in range(niters):
            for current_set in edge_sets:
                for e in current_set:
                    v0,v1 = e.verts
                    faces0 = e.shared_faces(v0)
                    edges0 = [edge for f in faces0 for edge in f.edges if not edge.select and edge != e and edge.share_vert(e)]
                    verts0 = [edge.other_vert(v0) for edge in edges0]
                    verts0 = [v for v in verts0 if v and v != v1]
                    faces1 = e.shared_faces(v1)
                    edges1 = [edge for f in faces1 for edge in f.edges if not edge.select and edge != e and edge.share_vert(e)]
                    verts1 = [edge.other_vert(v1) for edge in edges0]
                    verts1 = [v for v in verts1 if v and v != v0]
                    if len(verts0) > 1:
                        v0.co = Point.average([v.co for v in verts0])
                        self.snap_vert(v0)
                    if len(verts1) > 1:
                        v1.co = Point.average([v.co for v in verts1])
                        self.snap_vert(v1)

        self.dirty()


    #######################################################


    def merge_verts_by_dist(self, bmverts, merge_dist, *, select_merged=True):
        """ Merging colocated visible verts """

        # TODO: remove colocated faces

        if merge_dist is None: return

        bmverts = set(bmverts)
        accel_data = self.get_custom_vis_accel(
            selection_only=False,
            include_verts=True, include_edges=False, include_faces=False,
            symmetry=False,
        )
        snappable_bmverts = { bmv for bmv in accel_data.verts if bmv not in bmverts }
        kwargs = { 'max_dist': self.drawing.scale(merge_dist), 'vis_accel': accel_data }
        update_verts = []
        for bmv in bmverts:
            if not (xy := self.Point_to_Point2D(bmv.co)): continue
            if not (bmv1 := self.accel_nearest2D_vert(point=xy, **kwargs)[0]): continue
            bmv1.merge_robust(bmv)
            update_verts.append(bmv1)

        self.update_verts_faces(update_verts)
        if select_merged:
            self.select(update_verts, only=False)

        return update_verts



    #######################################################

    def update_rot_object(self):
        bbox = self.rftarget.get_selection_bbox()
        if bbox.min == None:
            if not options['move rotate object if no selection']: return
            #bbox = BBox.merge(src.get_bbox() for src in self.rfsources)
            bboxes = []
            for s in self.rfsources:
                verts = [(s.obj.matrix_world @ Vector((v[0], v[1], v[2], 1))) for v in s.obj.bound_box]
                verts = [(v[0]/v[3], v[1]/v[3], v[2]/v[3]) for v in verts]
                bboxes.append(BBox(from_coords=verts))
            bbox = BBox.merge(bboxes)
        # print('update_rot_object', bbox)
        diff = bbox.max - bbox.min
        rot_object = bpy.data.objects[retopoflow_datablocks['rotate object']]
        rot_object.location = bbox.min + diff / 2
        rot_object.scale = diff / 2

    #######################################################
    # delete / dissolve

    def delete_dissolve_collapse_option(self, opt):
        actions = {
            'Dissolve': self.dissolve_option,
            'Delete':   self.delete_option,
            'Collapse': self.collapse_option,
            'Merge':    self.merge_option,
        }
        if opt is None or opt[0] not in actions: return
        action = actions[opt[0]]
        action(opt[1])

    def dissolve_option(self, opt):
        sel_verts = self.rftarget.get_selected_verts()
        sel_edges = self.rftarget.get_selected_edges()
        sel_faces = self.rftarget.get_selected_faces()
        try:
            self.undo_push('dissolve %s' % opt)
            if opt == 'Vertices' and sel_verts:
                self.dissolve_verts(sel_verts)
            elif opt == 'Edges' and sel_edges:
                self.dissolve_edges(sel_edges)
            elif opt == 'Faces' and sel_faces:
                self.dissolve_faces(sel_faces)
            elif opt == 'Loops' and sel_edges:
                self.dissolve_edges(sel_edges)
                self.dissolve_verts(self.rftarget.get_selected_verts())
                #self.dissolve_loops()
            self.dirty()
        except RuntimeError as e:
            self.undo_cancel()
            self.alert_user('Error while dissolving:\n' + '\n'.join(e.args))

    def delete_option(self, opt):
        del_empty_edges=True
        del_empty_verts=True
        del_verts=True
        del_edges=True
        del_faces=True

        if opt == 'Vertices':
            pass
        elif opt == 'Edges':
            del_verts = False
        elif opt == 'Faces':
            del_verts = False
            del_edges = False
        elif opt == 'Only Edges & Faces':
            del_verts = False
            del_empty_verts = False
        elif opt == 'Only Faces':
            del_verts = False
            del_edges = False
            del_empty_verts = False
            del_empty_edges = False

        try:
            self.undo_push('delete %s' % opt)
            self.delete_selection(del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts, del_verts=del_verts, del_edges=del_edges, del_faces=del_faces)
            self.dirty()
        except RuntimeError as e:
            self.undo_cancel()
            self.alert_user('Error while deleting:\n' + '\n'.join(e.args))

    def collapse_option(self, opt):
        del_empty_edges=True
        del_empty_verts=True
        del_verts=True
        del_edges=True
        del_faces=True

        if opt == 'Edges & Faces':
            pass
        else:
            return

        try:
            self.undo_push('collapse %s' % opt)
            self.collapse_edges_faces()
            self.dirty()
        except RuntimeError as e:
            self.undo_cancel()
            self.alert_user('Error while collapsing:\n' + '\n'.join(e.args))

    def merge_option(self, opt):
        if opt == 'At Center':
            pass
        elif opt == 'By Distance':
            pass
        else:
            return

        try:
            self.undo_push('merge %s' % opt)
            if opt == 'At Center':
                self.merge_at_center()
            elif opt == 'By Distance':
                self.remove_selected_doubles()
            self.dirty()
        except RuntimeError as e:
            self.undo_cancel()
            self.alert_user('Error while merging:\n' + '\n'.join(e.args))

    def merge_at_center(self):
        self.rftarget.merge_at_center(self.nearest_sources_Point)

    def collapse_edges_faces(self):
        self.rftarget.collapse_edges_faces(self.nearest_sources_Point)

    def delete_selection(self, del_empty_edges=True, del_empty_verts=True, del_verts=True, del_edges=True, del_faces=True):
        self.rftarget.delete_selection(del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts, del_verts=del_verts, del_edges=del_edges, del_faces=del_faces)

    def delete_verts(self, verts):
        self.rftarget.delete_verts(verts)

    def delete_edges(self, edges):
        self.rftarget.delete_edges(edges)

    def delete_faces(self, faces, del_empty_edges=True, del_empty_verts=True):
        self.rftarget.delete_faces(faces, del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts)

    def dissolve_verts(self, verts, use_face_split=False, use_boundary_tear=False):
        self.rftarget.dissolve_verts(verts, use_face_split, use_boundary_tear)

    def dissolve_edges(self, edges, use_verts=True, use_face_split=False):
        self.rftarget.dissolve_edges(edges, use_verts, use_face_split)

    def dissolve_faces(self, faces, use_verts=True):
        self.rftarget.dissolve_faces(faces, use_verts)

    # def find_loops(self, edges):
    #     if not edges: return []
    #     touched,loops = set(),[]

    #     def crawl(v0, edge01, vert_list):
    #         nonlocal edges, touched
    #         # ... -- v0 -- edge01 -- v1 -- edge12 -- ...
    #         #  > came-^-from-^        ^-going-^-to >
    #         vert_list.append(v0)
    #         touched.add(edge01)
    #         v1 = edge01.other_vert(v0)
    #         if v1 == vert_list[0]: return vert_list
    #         next_edges = [e for e in v1.link_edges if e in edges and e != edge01]
    #         if not next_edges: return []
    #         if len(next_edges) == 1: edge12 = next_edges[0]
    #         else: edge12 = next_edge_in_string(edge01, v1)
    #         if not edge12 or edge12 in touched or edge12 not in edges: return []
    #         return crawl(v1, edge12, vert_list)

    #     for edge in edges:
    #         if edge in touched: continue
    #         vert_list = crawl(edge.verts[0], edge, [])
    #         if vert_list:
    #             loops.append(vert_list)

    #     return loops

    # def dissolve_loops(self):
    #     sel_edges = self.get_selected_edges()
    #     sel_loops = self.find_loops(sel_edges)
    #     if not sel_loops:
    #         dprint('Could not find any loops')
    #         return

    #     while sel_loops:
    #         ploop = None
    #         for loop in sel_loops:
    #             sloop = set(loop)
    #             # find a parallel loop next to loop
    #             adj_verts = {e.other_vert(v) for v in loop for e in v.link_edges} - sloop
    #             adj_verts = {v for v in adj_verts if v.is_valid}
    #             parallel_edges = [e for v in adj_verts for e in v.link_edges if e.other_vert(v) in adj_verts]
    #             parallel_loops = self.find_loops(parallel_edges)
    #             if len(parallel_loops) != 2: continue
    #             ploop = parallel_loops[0]
    #             break
    #         if not ploop: break
    #         # merge loop into ploop
    #         eloop = [v0.shared_edge(v1) for v0,v1 in iter_pairs(loop, wrap=True)]
    #         self.deselect(loop)
    #         self.deselect(eloop)
    #         self.deselect([f for e in eloop for f in e.link_faces])
    #         v01 = {v0:next(v1 for v1 in ploop if v0.share_edge(v1)) for v0 in loop}
    #         edges = [v0.shared_edge(v1) for v0,v1 in v01.items()]
    #         self.delete_edges(edges)
    #         touched = set()
    #         for v0,v1 in v01.items():
    #             v1.merge(v0)
    #             touched.add(v1)
    #         for v in touched:
    #             self.clean_duplicate_bmedges(v)
    #         # remove dissolved loop
    #         sel_loops = [l for l in sel_loops if l != loop]
