'''
Copyright (C) 2019 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

import bgl
import bpy
import math
from mathutils.geometry import intersect_point_tri_2d, intersect_point_tri_2d

from ..rftool import RFTool

from ..rfwidgets.rfwidget_brushstroke import RFWidget_BrushStroke
from ...addon_common.common.bezier import CubicBezierSpline, CubicBezier
from ...addon_common.common.debug import dprint
from ...addon_common.common.drawing import Drawing, Cursors
from ...addon_common.common.maths import Vec2D
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs

from ...config.options import options


from .polystrips_utils import (
    RFTool_PolyStrips_Strip,
    hash_face_pair,
    strip_details,
    crawl_strip,
    is_boundaryvert, is_boundaryedge,
    process_stroke_filter, process_stroke_source,
    process_stroke_get_next, process_stroke_get_marks,
    mark_info,
    )


class RFTool_PolyStrips(RFTool):
    name        = 'PolyStrips'
    description = 'Create and edit strips of quads'
    icon        = 'polystrips_32.png'


################################################################################################
# following imports must happen *after* the above class, because each subclass depends on
# above class to be defined

from .polystrips_ops import PolyStrips_Ops


class PolyStrips(RFTool_PolyStrips, PolyStrips_Ops):
    @RFTool_PolyStrips.on_init
    def init(self):
        self.rfwidget = RFWidget_BrushStroke(self)

    @RFTool_PolyStrips.on_reset
    def reset(self):
        self.strips = []
        self.strip_pts = []
        self.hovering_strips = set()
        self.hovering_handles = []
        self.sel_cbpts = []
        self.stroke_cbs = CubicBezierSpline()

    @RFTool_PolyStrips.on_target_change
    @profiler.function
    def update_target(self):
        self.strips = []

        # get selected quads
        bmquads = set(bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4)
        if not bmquads: return

        # find junctions at corners
        junctions = set()
        for bmf in bmquads:
            # skip if in middle of a selection
            if not any(is_boundaryvert(bmv, bmquads) for bmv in bmf.verts): continue
            # skip if in middle of possible strip
            edge0,edge1,edge2,edge3 = [is_boundaryedge(bme, bmquads) for bme in bmf.edges]
            if (edge0 or edge2) and not (edge1 or edge3): continue
            if (edge1 or edge3) and not (edge0 or edge2): continue
            junctions.add(bmf)

        # find junctions that might be in middle of strip but are ends to other strips
        boundaries = set((bme,bmf) for bmf in bmquads for bme in bmf.edges if is_boundaryedge(bme, bmquads))
        while boundaries:
            bme,bmf = boundaries.pop()
            for bme_ in bmf.neighbor_edges(bme):
                strip = crawl_strip(bmf, bme_, bmquads, junctions)
                if strip is None: continue
                junctions.add(strip[-1])

        # find strips between junctions
        touched = set()
        for bmf0 in junctions:
            bme0,bme1,bme2,bme3 = bmf0.edges
            edge0,edge1,edge2,edge3 = [is_boundaryedge(bme, bmquads) for bme in bmf0.edges]

            def add_strip(bme):
                strip = crawl_strip(bmf0, bme, bmquads, junctions)
                if not strip:
                    return
                bmf1 = strip[-1]
                if len(strip) > 1 and hash_face_pair(bmf0, bmf1) not in touched:
                    touched.add(hash_face_pair(bmf0,bmf1))
                    touched.add(hash_face_pair(bmf1,bmf0))
                    self.strips.append(RFTool_PolyStrips_Strip(strip))

            if not edge0: add_strip(bme0)
            if not edge1: add_strip(bme1)
            if not edge2: add_strip(bme2)
            if not edge3: add_strip(bme3)
            if options['polystrips max strips'] and len(self.strips) > options['polystrips max strips']:
                self.strips = []
                break

        self.update_strip_viz()

    @profiler.function
    def update_strip_viz(self):
        self.strip_pts = [[strip.curve.eval(i/10) for i in range(10+1)] for strip in self.strips]


    @RFTool_PolyStrips.FSM_State('main')
    def main(self) :
        Cursors.set('CROSSHAIR')

        if self.actions.pressed({'select', 'select add'}):
            return self.rfcontext.setup_selection_painting(
                'face',
                #fn_filter_bmelem=self.filter_edge_selection,
                kwargs_select={'supparts': False},
                kwargs_deselect={'subparts': False},
            )


    @RFWidget_BrushStroke.on_action
    def new_brushstroke(self):
        # called when artist finishes a stroke
        radius = self.rfwidget.size
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        Point2D_to_Ray = self.rfcontext.Point2D_to_Ray
        nearest_sources_Point = self.rfcontext.nearest_sources_Point
        raycast = self.rfcontext.raycast_sources_Point2D
        vis_verts = self.rfcontext.visible_verts()
        vis_edges = self.rfcontext.visible_edges(verts=vis_verts)
        vis_faces = self.rfcontext.visible_faces(verts=vis_verts)
        vis_edges2D,vis_faces2D = [],[]
        new_geom = []

        def add_edge(bme): vis_edges2D.append((bme, [Point_to_Point2D(bmv.co) for bmv in bme.verts]))
        def add_face(bmf): vis_faces2D.append((bmf, [Point_to_Point2D(bmv.co) for bmv in bmf.verts]))

        def intersect_face(pt):
            # todo: rewrite! inefficient!
            nonlocal vis_faces2D
            for f,vs in vis_faces2D:
                v0 = vs[0]
                for v1,v2 in iter_pairs(vs[1:], False):
                    if intersect_point_tri_2d(pt, v0, v1, v2): return f
            return None

        def snap_point(p2D_init, dist):
            p = raycast(p2D_init)[0]
            if p is None:
                # did not hit source, so find nearest point on source to where the point would have been
                r = Point2D_to_Ray(p2D_init)
                p = nearest_sources_Point(r.eval(dist))[0]
            return p

        def create_edge(center, tangent, mult, perpendicular):
            nonlocal new_geom

            # find direction of projecting tangent
            # p0,n0,_,d0 = raycast(center)
            # p1 = raycast(center+tangent*0.01)[0] # snap_point(center+tangent*0.0001, d0)
            # d01 = (p1 - p0).normalize()
            # t = n0.cross(d01).normalize()
            # r = Point2D_to_Ray(center)
            # print(tangent,p0,p1,d01,n0,t,r.d,t.dot(r.d), mult)
            # rad = radius * abs(t.dot(r.d))
            rad = radius

            hd,mmult = None,mult
            while not hd:
                p = center + tangent * mmult
                hp,hn,hi,hd = raycast(p)
                mmult -= 0.1
            p0 = snap_point(center + tangent * mult + perpendicular * rad, hd)
            p1 = snap_point(center + tangent * mult - perpendicular * rad, hd)
            bmv0 = self.rfcontext.new_vert_point(p0)
            bmv1 = self.rfcontext.new_vert_point(p1)
            bme = self.rfcontext.new_edge([bmv0,bmv1])
            add_edge(bme)
            new_geom += [bme]
            return bme

        def create_face_in_l(bme0, bme1):
            '''
            creates a face strip between edges that share a vertex (L-shaped)
            '''
            # find shared vert
            nonlocal new_geom
            bmv1 = bme0.shared_vert(bme1)
            bmv0,bmv2 = bme0.other_vert(bmv1),bme1.other_vert(bmv1)
            c0,c1,c2 = bmv0.co,bmv1.co,bmv2.co
            c3 = nearest_sources_Point(c1 + (c0-c1) + (c2-c1))[0]
            bmv3 = self.rfcontext.new_vert_point(c3)
            bmf = self.rfcontext.new_face([bmv0,bmv1,bmv2,bmv3])
            bme2,bme3 = bmv2.shared_edge(bmv3),bmv3.shared_edge(bmv0)
            add_face(bmf)
            add_edge(bme2)
            add_edge(bme3)
            new_geom += [bme2,bme3,bmf]
            return bmf

        def create_face(bme01, bme23):
            #  0  3      0--3
            #  |  |  ->  |  |
            #  1  2      1--2
            nonlocal new_geom
            if bme01.share_vert(bme23): return create_face_in_l(bme01, bme23)
            bmv0,bmv1 = bme01.verts
            bmv2,bmv3 = bme23.verts
            if bme01.vector().dot(bme23.vector()) > 0: bmv2,bmv3 = bmv3,bmv2
            bmf = self.rfcontext.new_face([bmv0,bmv1,bmv2,bmv3])
            bme12 = bmv1.shared_edge(bmv2)
            bme30 = bmv3.shared_edge(bmv0)
            add_edge(bme12)
            add_edge(bme30)
            add_face(bmf)
            new_geom += [bme12, bme30, bmf]
            return bmf


        for bme in vis_edges: add_edge(bme)
        for bmf in vis_faces: add_face(bmf)

        self.rfcontext.undo_push('stroke')

        stroke = list(self.rfwidget.stroke2D)
        # filter stroke down where each pt is at least 1px away to eliminate local wiggling
        stroke = process_stroke_filter(stroke)
        stroke = process_stroke_source(stroke, self.rfcontext.raycast_sources_Point2D, self.rfcontext.is_point_on_mirrored_side)

        from_edge = None
        while len(stroke) > 2:
            # get stroke segment to work on
            from_edge,cstroke,to_edge,cont,stroke = process_stroke_get_next(stroke, from_edge, vis_edges2D)

            # filter cstroke to contain unique points
            while True:
                ncstroke = [cstroke[0]]
                for cp,np in iter_pairs(cstroke,False):
                    if (cp-np).length > 0: ncstroke += [np]
                if len(cstroke) == len(ncstroke): break
                cstroke = ncstroke

            # discard stroke segment if it lies in a face
            if intersect_face(cstroke[1]):
                dprint('stroke is on face (1)')
                from_edge = to_edge
                continue
            if intersect_face(cstroke[-2]):
                dprint('stroke is on face (-2)')
                from_edge = to_edge
                continue

            # estimate length of stroke (used with radius to determine num of quads)
            stroke_len = sum((p0-p1).length for (p0,p1) in iter_pairs(cstroke,False))

            # marks start and end at center of quad, and alternate with
            # edge and face, each approx radius distance apart
            # +---+---+---+---+---+
            # |   |   |   |   |   |
            # +---+---+---+---+---+
            #   ^ ^ ^ ^ ^ ^ ^ ^ ^  <-----marks (nmarks: 9, nquads: 5)
            #     ^ ^ ^ ^ ^ ^ ^ ^  <- if from_edge not None
            #   ^ ^ ^ ^ ^ ^ ^ ^    <- if to_edge not None
            #     ^ ^ ^ ^ ^ ^ ^    <- if from_edge and to_edge are not None
            # mark counts:
            #     min marks = 3   [ | ]    (2 quads)
            #     marks = 5      [ | | ]   (3 quads)
            #     marks = 7     [ | | | ]  (4 quads)
            #     marks must be odd
            # if from_edge is not None, then stroke starts at edge
            # if to_edge is not None, then stroke ends at edge
            markoff0 = 0 if from_edge is None else 1
            markoff1 = 0 if to_edge   is None else 1
            nmarks = int(math.ceil(stroke_len / radius))        # approx num of marks
            nmarks = nmarks + (1 - ((nmarks+markoff0+markoff1) % 2))  # make sure odd count
            nmarks = max(nmarks, 3-markoff0-markoff1)           # min marks = 3
            nmarks = max(nmarks, 2)                             # fix div by 0 :(
            # marks are found at dists along stroke
            at_dists = [stroke_len*i/(nmarks-1) for i in range(nmarks)]
            # compute marks
            marks = process_stroke_get_marks(cstroke, at_dists)

            # compute number of quads
            nquads = int(((nmarks-markoff0-markoff1) + 1) / 2)
            dprint('nmarks = %d, markoff0 = %d, markoff1 = %d, nquads = %d' % (nmarks, markoff0, markoff1, nquads))

            if from_edge and to_edge and nquads == 1:
                if from_edge.share_vert(to_edge):
                    create_face_in_l(from_edge, to_edge)
                    continue

            # add edges
            if from_edge is None:
                # create from_edge
                dprint('creating from_edge')
                pt,tn,pe = mark_info(marks, 0)
                from_edge = create_edge(pt, -tn, radius, pe)
            else:
                new_geom += list(from_edge.link_faces)

            if to_edge is None:
                dprint('creating to_edge')
                pt,tn,pe = mark_info(marks, nmarks-1)
                to_edge = create_edge(pt, tn, radius, pe)
            else:
                new_geom += list(to_edge.link_faces)

            for iquad in range(1, nquads):
                #print('creating edge')
                pt,tn,pe = mark_info(marks, iquad*2+markoff0-1)
                bme = create_edge(pt, tn, 0.0, pe)
                bmf = create_face(from_edge, bme)
                from_edge = bme
            bmf = create_face(from_edge, to_edge)

            from_edge = to_edge if cont else None

        self.rfcontext.select(new_geom, supparts=False)

    @RFTool_PolyStrips.Draw('post3d')
    def draw_post3d_spline(self):
        if not self.strips: return

        strips = self.strips
        hov_strips = self.hovering_strips

        Point_to_Point2D = self.rfcontext.Point_to_Point2D

        def is_visible(v):
            return True   # self.rfcontext.is_visible(v, None)

        def draw(alphamult, hov_alphamult, hover):
            nonlocal strips

            if not hover: hov_alphamult = alphamult

            size_outer = options['polystrips handle outer size']
            size_inner = options['polystrips handle inner size']
            border_outer = options['polystrips handle border']
            border_inner = options['polystrips handle border']

            bgl.glEnable(bgl.GL_BLEND)

            # draw outer-inner lines
            pts = [Point_to_Point2D(p) for strip in strips for p in strip.curve.points()]
            self.rfcontext.drawing.draw2D_lines(pts, (1,1,1,0.45), width=2)

            # draw junction handles (outer control points of curve)
            faces_drawn = set() # keep track of faces, so don't draw same handles 2+ times
            pts_outer,pts_inner = [],[]
            for strip in strips:
                bmf0,bmf1 = strip.end_faces()
                p0,p1,p2,p3 = strip.curve.points()
                if bmf0 not in faces_drawn:
                    if is_visible(p0): pts_outer += [Point_to_Point2D(p0)]
                    faces_drawn.add(bmf0)
                if bmf1 not in faces_drawn:
                    if is_visible(p3): pts_outer += [Point_to_Point2D(p3)]
                    faces_drawn.add(bmf1)
                if is_visible(p1): pts_inner += [Point_to_Point2D(p1)]
                if is_visible(p2): pts_inner += [Point_to_Point2D(p2)]
            self.rfcontext.drawing.draw2D_points(pts_outer, (1.00,1.00,1.00,1.0), radius=size_outer, border=border_outer, borderColor=(0.00,0.00,0.00,0.5))
            self.rfcontext.drawing.draw2D_points(pts_inner, (0.25,0.25,0.25,0.8), radius=size_inner, border=border_inner, borderColor=(0.75,0.75,0.75,0.4))

        if True:
            # always draw on top!
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glDisable(bgl.GL_DEPTH_TEST)
            bgl.glDepthMask(bgl.GL_FALSE)
            draw(1.0, 1.0, False)
            bgl.glEnable(bgl.GL_DEPTH_TEST)
            bgl.glDepthMask(bgl.GL_TRUE)
        else:
            # allow handles to go under surface
            bgl.glDepthRange(0, 0.9999)     # squeeze depth just a bit
            bgl.glEnable(bgl.GL_BLEND)
            bgl.glDepthMask(bgl.GL_FALSE)   # do not overwrite depth
            bgl.glEnable(bgl.GL_DEPTH_TEST)

            # draw in front of geometry
            bgl.glDepthFunc(bgl.GL_LEQUAL)
            draw(
                options['target alpha'],
                options['target alpha'], # hover
                False, #options['polystrips handle hover']
            )

            # draw behind geometry
            bgl.glDepthFunc(bgl.GL_GREATER)
            draw(
                options['target hidden alpha'],
                options['target hidden alpha'], # hover
                False, #options['polystrips handle hover']
            )

            bgl.glDepthFunc(bgl.GL_LEQUAL)
            bgl.glDepthRange(0.0, 1.0)
            bgl.glDepthMask(bgl.GL_TRUE)

    @RFTool_PolyStrips.Draw('post2d')
    def draw_post2d(self):
        self.rfcontext.drawing.set_font_size(12)
        Point_to_Point2D = self.rfcontext.Point_to_Point2D
        text_draw2D = self.rfcontext.drawing.text_draw2D

        for strip in self.strips:
            c = len(strip)
            vs = [Point_to_Point2D(f.center()) for f in strip]
            vs = [Vec2D(v) for v in vs if v]
            if not vs: continue
            ctr = sum(vs, Vec2D((0,0))) / len(vs)
            text_draw2D('%d' % c, ctr+Vec2D((2,14)), color=(1,1,0,1), dropshadow=(0,0,0,0.5))
