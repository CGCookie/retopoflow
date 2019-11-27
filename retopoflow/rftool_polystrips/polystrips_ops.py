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

import math
from mathutils import Vector
from mathutils.geometry import intersect_point_tri_2d, intersect_point_tri_2d

from ..rftool import RFTool, rftools

from ..rfwidgets.rfwidget_brushstroke import RFWidget_BrushStroke_PolyStrips
from ...addon_common.common.bezier import CubicBezierSpline, CubicBezier
from ...addon_common.common.debug import dprint
from ...addon_common.common.drawing import Drawing, Cursors
from ...addon_common.common.profiler import profiler
from ...addon_common.common.utils import iter_pairs

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


RFTool_PolyStrips = rftools['RFTool_PolyStrips']

class PolyStrips_Ops:
    @RFWidget_BrushStroke_PolyStrips.on_action
    @RFTool_PolyStrips.dirty_when_done
    def new_brushstroke(self):
        # called when artist finishes a stroke
        radius = self.rfwidgets['brushstroke'].size
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

        stroke = list(self.rfwidgets['brushstroke'].stroke2D)
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


    @RFTool_PolyStrips.dirty_when_done
    def change_count(self, *, count=None, delta=None):
        '''
        find parallel strips of boundary edges, fit curve to verts of strips, then
        recompute faces based on curves.

        note: this op will only change counts along boundaries.  otherwise, use loop cut
        '''

        nfaces = []

        def process(bmfs, bmes):
            nonlocal nfaces

            # find edge strips
            strip0,strip1 = [bmes[0].verts[0]], [bmes[0].verts[1]]
            edges0,edges1 = [],[]
            for bmf,bme0 in zip(bmfs,bmes):
                bme1,bme2 = bmf.neighbor_edges(bme0)
                if strip0[-1] in bme2.verts: bme1,bme2 = bme2,bme1
                strip0.append(bme1.other_vert(strip0[-1]))
                strip1.append(bme2.other_vert(strip1[-1]))
                edges0.append(bme1)
                edges1.append(bme2)
            pts0,pts1 = [v.co for v in strip0],[v.co for v in strip1]
            lengths0 = [(p0-p1).length for p0,p1 in iter_pairs(pts0, False)]
            lengths1 = [(p0-p1).length for p0,p1 in iter_pairs(pts1, False)]
            length0,length1 = sum(lengths0),sum(lengths1)

            max_error = min(min(lengths0),min(lengths1)) / 100.0   # arbitrary!
            spline0 = CubicBezierSpline.create_from_points([[Vector(p) for p in pts0]], max_error)
            spline1 = CubicBezierSpline.create_from_points([[Vector(p) for p in pts1]], max_error)
            len0,len1 = len(spline0), len(spline1)

            ccount = len(bmfs)
            if count is not None: ncount = count
            else: ncount = ccount + delta
            ncount = max(1, ncount)

            # approximate ts along each strip
            def approx_ts(spline_len, lengths):
                nonlocal ncount,ccount
                accum_ts_old = [0]
                for l in lengths: accum_ts_old.append(accum_ts_old[-1] + l)
                total_ts_old = sum(lengths)
                ts_old = [Vector((i, t / total_ts_old, 0)) for i,t in enumerate(accum_ts_old)]
                spline_ts_old = CubicBezierSpline.create_from_points([ts_old], 0.01)
                spline_ts_old_len = len(spline_ts_old)
                ts = [spline_len * spline_ts_old.eval(spline_ts_old_len * i / ncount).y for i in range(ncount+1)]
                return ts
            ts0 = approx_ts(len0, lengths0)
            ts1 = approx_ts(len1, lengths1)

            self.rfcontext.delete_edges(edges0 + edges1 + bmes[1:-1])

            new_vert = self.rfcontext.new_vert_point
            verts0 = strip0[:1] + [new_vert(spline0.eval(t)) for t in ts0[1:-1]] + strip0[-1:]
            verts1 = strip1[:1] + [new_vert(spline1.eval(t)) for t in ts1[1:-1]] + strip1[-1:]

            for (v00,v01),(v10,v11) in zip(iter_pairs(verts0,False), iter_pairs(verts1,False)):
                nfaces.append(self.rfcontext.new_face([v00,v01,v11,v10]))



        # find selected faces that are not part of strips
        #  [ | | | | | | | ]
        #      |O|     |O|    <- with either of these selected, split into two
        #  [ | | | ]

        bmquads = [bmf for bmf in self.rfcontext.get_selected_faces() if len(bmf.verts) == 4]
        bmquads = [bmq for bmq in bmquads if not any(bmq in strip for strip in self.strips)]
        for bmf in bmquads:
            bmes = list(bmf.edges)
            boundaries = [len(bme.link_faces) == 2 for bme in bmf.edges]
            if (boundaries[0] or boundaries[2]) and not boundaries[1] and not boundaries[3]:
                process([bmf], [bmes[0],bmes[2]])
                continue
            if (boundaries[1] or boundaries[3]) and not boundaries[0] and not boundaries[2]:
                process([bmf], [bmes[1],bmes[3]])
                continue

        # find boundary portions of each strip
        # TODO: what if there are multiple boundary portions??
        #  [ | |O| | ]
        #      |O|      <-
        #      |O|      <- only working on this part of strip
        #      |O|      <-
        #      |O| | ]
        #  [ | |O| | ]

        for strip in self.strips:
            bmfs,bmes = [],[]
            bme0 = strip.bme0
            for bmf in strip:
                bme2 = bmf.opposite_edge(bme0)
                bme1,bme3 = bmf.neighbor_edges(bme0)
                if len(bme1.link_faces) == 1 and len(bme3.link_faces) == 1:
                    bmes.append(bme0)
                    bmfs.append(bmf)
                else:
                    # if we've already seen a portion of the strip that can be modified, break!
                    if bmfs:
                        bmes.append(bme0)
                        break
                bme0 = bme2
            else:
                bmes.append(bme0)
            if not bmfs: continue
            process(bmfs, bmes)

        if nfaces:
            self.rfcontext.select(nfaces, supparts=False, only=False)
        else:
            #self.rfcontext.alert_user('PolyStrips', 'Could not find a strip to adjust')
            pass

