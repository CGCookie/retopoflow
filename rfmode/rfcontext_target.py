'''
Copyright (C) 2017 CG Cookie
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
from itertools import chain
from mathutils import Vector
from ..common.debug import dprint
from ..common.profiler import profiler
from ..common.utils import iter_pairs
from ..common.maths import Point, Vec, Direction, Normal, Ray, XForm
from ..common.maths import Point2D, Vec2D, Direction2D, Accel2D
from .rfmesh import RFMesh, RFVert, RFEdge, RFFace
from .rfmesh import RFSource, RFTarget
from .rfmesh_render import RFMeshRender
from ..options import visualization, options


class RFContext_Target:
    '''
    functions to work on RFTarget
    '''

    @profiler.profile
    def _init_target(self):
        ''' target is the active object.  must be selected and visible '''
        self.tar_object = self.get_target()
        assert self.tar_object, 'Could not find valid target?'
        self.rftarget = RFTarget.new(self.tar_object, self.unit_scaling_factor)
        self.update_displace_option()
        opts = visualization.get_target_settings()
        self.rftarget_draw = RFMeshRender.new(self.rftarget, opts)

        self.accel_defer_recomputing = False
        self.accel_recompute = True
        self.accel_target_version = None
        self.accel_view_version = None
        self.accel_vis_verts = None
        self.accel_vis_edges = None
        self.accel_vis_faces = None
        self.accel_vis_accel = None

    #########################################
    # acceleration structures

    def set_accel_defer(self, defer): self.accel_defer_recomputing = defer

    @profiler.profile
    def get_vis_accel(self, force=False):
        target_version = self.get_target_version(selection=False)
        view_version = self.get_view_version()

        recompute = self.accel_recompute
        recompute |= self.accel_target_version != target_version
        recompute |= self.accel_view_version != view_version
        recompute |= self.accel_vis_verts is None
        recompute |= self.accel_vis_edges is None
        recompute |= self.accel_vis_faces is None
        recompute |= self.accel_vis_accel is None
        recompute &= not self.accel_defer_recomputing
        recompute &= not self.nav and (time.time() - self.nav_time) > 0.25

        self.accel_recompute = False

        if force or recompute:
            self.accel_target_version = target_version
            self.accel_view_version = view_version
            self.accel_vis_verts = self.visible_verts()
            self.accel_vis_edges = self.visible_edges(verts=self.accel_vis_verts)
            self.accel_vis_faces = self.visible_faces(verts=self.accel_vis_verts)
            self.accel_vis_accel = Accel2D(self.accel_vis_verts, self.accel_vis_edges, self.accel_vis_faces, self.get_point2D)
        else:
            self.accel_vis_verts = { bmv for bmv in self.accel_vis_verts if bmv.is_valid } if self.accel_vis_verts is not None else None
            self.accel_vis_edges = { bme for bme in self.accel_vis_edges if bme.is_valid } if self.accel_vis_edges is not None else None
            self.accel_vis_faces = { bmf for bmf in self.accel_vis_faces if bmf.is_valid } if self.accel_vis_faces is not None else None

        return self.accel_vis_accel

    @profiler.profile
    def accel_nearest2D_vert(self, point=None, max_dist=None):
        xy = self.get_point2D(point or self.actions.mouse)
        vis_accel = self.get_vis_accel()
        if not vis_accel: return None,None

        if not max_dist:
            verts = self.accel_vis_verts
        else:
            max_dist = self.drawing.scale(max_dist)
            verts = vis_accel.get_verts(xy, max_dist)

        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.Point_to_Point2D, verts=verts, max_dist=max_dist)

    @profiler.profile
    def accel_nearest2D_edge(self, point=None, max_dist=None):
        xy = self.get_point2D(point or self.actions.mouse)
        vis_accel = self.get_vis_accel()
        if not vis_accel: return None,None

        if not max_dist:
            edges = self.accel_vis_edges
        else:
            max_dist = self.drawing.scale(max_dist)
            edges = vis_accel.get_edges(xy, max_dist)

        return self.rftarget.nearest2D_bmedge_Point2D(xy, self.Point_to_Point2D, edges=edges, max_dist=max_dist)

    @profiler.profile
    def accel_nearest2D_face(self, point=None, max_dist=None):
        xy = self.get_point2D(point or self.actions.mouse)
        vis_accel = self.get_vis_accel()
        if not vis_accel: return None

        if not max_dist:
            faces = self.accel_vis_faces
        else:
            max_dist = self.drawing.scale(max_dist)
            faces = vis_accel.get_faces(xy, max_dist)

        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D, faces=faces) #, max_dist=max_dist)


    #########################################
    # find target entities in screen space

    def get_point2D(self, point):
        if point.is_2D(): return point
        return self.Point_to_Point2D(point)

    @profiler.profile
    def nearest2D_vert(self, point=None, max_dist=None, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmvert_Point2D(xy, self.Point_to_Point2D, verts=verts, max_dist=max_dist)

    @profiler.profile
    def nearest2D_verts(self, point=None, max_dist:float=10, verts=None):
        xy = self.get_point2D(point or self.actions.mouse)
        max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmverts_Point2D(xy, max_dist, self.Point_to_Point2D, verts=verts)

    @profiler.profile
    def nearest2D_edge(self, point=None, max_dist=None, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedge_Point2D(xy, self.Point_to_Point2D, edges=edges, max_dist=max_dist)

    @profiler.profile
    def nearest2D_edges(self, point=None, max_dist:float=10, edges=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmedges_Point2D(xy, max_dist, self.Point_to_Point2D, edges=edges)

    # TODO: implement max_dist
    @profiler.profile
    def nearest2D_face(self, point=None, max_dist=None, faces=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D, faces=faces)

    # TODO: fix this function! Izzza broken
    @profiler.profile
    def nearest2D_faces(self, point=None, max_dist:float=10, faces=None):
        xy = self.get_point2D(point or self.actions.mouse)
        if max_dist: max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest2D_bmfaces_Point2D(xy, self.Point_to_Point2D, faces=faces)

    ####################
    # REWRITE BELOW!!! #
    ####################

    def nearest2D_face_Point2D(self, point:Point2D, faces=None):
        return self.rftarget.nearest2D_bmface_Point2D(point, self.Point_to_Point2D, faces=faces)

    def nearest2D_face_point(self, point):
        xy = self.get_point2D(point)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)

    def nearest2D_face_mouse(self):
        return self.nearest2D_face_point(self.actions.mouse)

    def nearest2D_face_point(self, point):
        # if max_dist: max_dist = self.drawing.scale(max_dist)
        xy = self.get_point2D(point)
        return self.rftarget.nearest2D_bmface_Point2D(xy, self.Point_to_Point2D)


    ########################################
    # find target entities in world space

    def get_point3D(self, point):
        if point.is_3D(): return point
        xyz,_,_,_ = self.raycast_sources_Point2D(point)
        return xyz

    def nearest_vert_point(self, point, verts=None):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.target.nearest_bmvert_Point(xyz, verts=verts)

    def nearest_vert_mouse(self, verts=None):
        return self.nearest_vert_point(self.actions.mouse, verts=verts)

    def nearest_verts_point(self, point, max_dist:float):
        xyz = self.get_point3D(point)
        if xyz is None: return None
        return self.rftarget.nearest_bmverts_Point(xyz, max_dist)

    def nearest_verts_mouse(self, max_dist:float):
        return self.nearest_verts_point(self.actions.mouse, max_dist)

    def nearest_edges_Point(self, point, max_dist:float):
        max_dist = self.drawing.scale(max_dist)
        return self.rftarget.nearest_bmedges_Point(point, max_dist)

    def nearest_edge_Point(self, point:Point, edges=None):
        return self.rftarget.nearest_bmedge_Point(point, edges=edges)


    #######################################
    # get visible geometry

    @profiler.profile
    def visible_verts(self):
        return self.rftarget.visible_verts(self.is_visible)

    @profiler.profile
    def visible_edges(self, verts=None):
        return self.rftarget.visible_edges(self.is_visible, verts=verts)

    @profiler.profile
    def visible_faces(self, verts=None):
        return self.rftarget.visible_faces(self.is_visible, verts=verts)


    ########################################
    # symmetry utils

    @profiler.profile
    def clip_pointloop(self, pointloop, connected):
        # assuming loop will cross symmetry line exactly zero or two times
        l2w_point,w2l_point = self.rftarget.xform.l2w_point,self.rftarget.xform.w2l_point
        pointloop = [w2l_point(pt) for pt in pointloop]
        if 'x' in self.rftarget.symmetry and any(p.x < 0 for p in pointloop):
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
        if 'y' in self.rftarget.symmetry and any(p.y > 0 for p in pointloop):
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
        if 'z' in self.rftarget.symmetry and any(p.z < 0 for p in pointloop):
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
        if 'x' in self.rftarget.symmetry and p.x < 0: return True
        if 'y' in self.rftarget.symmetry and p.y > 0: return True
        if 'z' in self.rftarget.symmetry and p.z < 0: return True
        return False

    def mirror_point(self, point):
        p = self.rftarget.xform.w2l_point(point)
        if 'x' in self.rftarget.symmetry: p.x = abs(p.x)
        if 'y' in self.rftarget.symmetry: p.y = abs(p.y)
        if 'z' in self.rftarget.symmetry: p.z = abs(p.z)
        return self.rftarget.xform.l2w_point(p)

    def get_point_symmetry(self, point):
        return self.rftarget.get_point_symmetry(point)

    def snap_to_symmetry(self, point, symmetry):
        return self.rftarget.snap_to_symmetry(point, symmetry)

    def clamp_point_to_symmetry(self, point):
        return self.rftarget.symmetry_real(point)

    def snap_all_verts(self):
        self.undo_push('snap all verts')
        self.rftarget.snap_all_verts(self.nearest_sources_Point)

    def snap_selected_verts(self):
        self.undo_push('snap selected verts')
        self.rftarget.snap_selected_verts(self.nearest_sources_Point)

    def remove_all_doubles(self):
        self.undo_push('remove all doubles')
        self.rftarget.remove_all_doubles(options['remove doubles dist'])

    def remove_selected_doubles(self):
        self.undo_push('remove selected doubles')
        self.rftarget.remove_selected_doubles(options['remove doubles dist'])

    #######################################
    # target manipulation functions
    #
    # note: these do NOT dirty the target!
    # ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

    def snap_vert(self, vert:RFVert):
        xyz,norm,_,_ = self.nearest_sources_Point(vert.co)
        vert.co = xyz
        vert.normal = norm

    def snap2D_vert(self, vert:RFVert):
        xy = self.Point_to_Point2D(vert.co)
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm

    def offset2D_vert(self, vert:RFVert, delta_xy:Vec2D):
        xy = self.Point_to_Point2D(vert.co) + delta_xy
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm

    def set2D_vert(self, vert:RFVert, xy:Point2D):
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if xyz is None: return
        vert.co = xyz
        vert.normal = norm
        return xyz

    def set2D_crawl_vert(self, vert:RFVert, xy:Point2D):
        hits = self.raycast_sources_Point2D_all(xy)
        if not hits: return
        # find closest
        co = vert.co
        p,n,_,_ = min(hits, key=lambda hit:(hit[0]-co).length)
        vert.co = p
        vert.normal = n


    def new_vert_point(self, xyz:Point):
        xyz,norm,_,_ = self.nearest_sources_Point(xyz)
        if not xyz or not norm: return None
        return self.rftarget.new_vert(xyz, norm)

    def new2D_vert_point(self, xy:Point2D):
        xyz,norm,_,_ = self.raycast_sources_Point2D(xy)
        if not xyz or not norm: return None
        return self.rftarget.new_vert(xyz, norm)

    def new2D_vert_mouse(self):
        return self.new2D_vert_point(self.actions.mouse)

    def new_edge(self, verts):
        return self.rftarget.new_edge(verts)

    def new_face(self, verts):
        return self.rftarget.new_face(verts)

    def bridge_vertloop(self, vloop0, vloop1, connected):
        assert len(vloop0) == len(vloop1), "loops must have same vertex counts"
        faces = []
        for pair0,pair1 in zip(iter_pairs(vloop0, connected), iter_pairs(vloop1, connected)):
            v00,v01 = pair0
            v10,v11 = pair1
            faces += [self.new_face((v00,v01,v11,v10))]
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

    def dirty(self):
        self.rftarget.dirty()

    def get_target_version(self, selection=True):
        return self.rftarget.get_version(selection=selection)

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

    def get_selected_verts(self):
        return self.rftarget.get_selected_verts()

    def get_selected_edges(self):
        return self.rftarget.get_selected_edges()

    def get_selected_faces(self):
        return self.rftarget.get_selected_faces()

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
        if self.tool: self.tool.update()
        self.update_rot_object()

    def deselect(self, elems, supparts=True, subparts=True):
        self.rftarget.deselect(elems, supparts=supparts, subparts=subparts)
        if self.tool: self.tool.update()
        self.update_rot_object()

    def select(self, elems, supparts=True, subparts=True, only=True):
        self.rftarget.select(elems, supparts=supparts, subparts=subparts, only=only)
        if self.tool: self.tool.update()
        self.update_rot_object()

    def reselect(self):
        if self.tool: self.tool.update()
        self.update_rot_object()

    def select_toggle(self):
        self.rftarget.select_toggle()
        if self.tool: self.tool.update()
        self.update_rot_object()

    def select_edge_loop(self, edge, only=True, **kwargs):
        eloop,connected = self.get_edge_loop(edge)
        self.rftarget.select(eloop, only=only, **kwargs)
        if self.tool: self.tool.update()
        self.update_rot_object()

    def select_inner_edge_loop(self, edge, **kwargs):
        eloop,connected = self.get_inner_edge_loop(edge)
        self.rftarget.select(eloop, **kwargs)
        if self.tool: self.tool.update()
        self.update_rot_object()

    def update_rot_object(self):
        self.rot_object.location = self.rftarget.get_selection_center()

    #######################################################
    # delete / dissolve

    def delete_dissolve_option(self, opt):
        self.last_delete_dissolve_option = opt
        if opt in [('Dissolve','Vertices'), ('Dissolve','Edges'), ('Dissolve','Faces'), ('Dissolve','Loops')]:
            self.dissolve_option(opt[1])
        elif opt in [('Delete','Vertices'), ('Delete','Edges'), ('Delete','Faces'), ('Delete','Only Edges & Faces'), ('Delete','Only Faces')]:
            self.delete_option(opt[1])
        self.tool.update()

    def dissolve_option(self, opt):
        sel_verts = self.rftarget.get_selected_verts()
        sel_edges = self.rftarget.get_selected_edges()
        sel_faces = self.rftarget.get_selected_faces()
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

        self.undo_push('delete %s' % opt)
        self.delete_selection(del_empty_edges=del_empty_edges, del_empty_verts=del_empty_verts, del_verts=del_verts, del_edges=del_edges, del_faces=del_faces)
        self.dirty()

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

    def dissolve_edges(self, edges, use_verts=False, use_face_split=False):
        self.rftarget.dissolve_edges(edges, use_verts, use_face_split)

    def dissolve_faces(self, faces, use_verts=False):
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
