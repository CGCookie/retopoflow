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
import bmesh
from bpy.props import BoolProperty, EnumProperty, FloatProperty
from mathutils import Vector
from mathutils.geometry import intersect_line_line

from ..common.operator import RFRegisterClass, hotkey_owns_context
from ..common.raycast import iter_all_valid_sources, nearest_point_valid_sources
from ..rfglobals import RFGlobals


def rf_is_running() -> bool:
    RFCore = RFGlobals.RFCore_None
    return bool(RFCore and RFCore.is_running)


class RFOperator_InsertDiamondJunction(RFRegisterClass, bpy.types.Operator):
    bl_idname = "retopoflow.insert_diamond_junction"
    bl_label = "Diamond Bevel (Retopoflow)"
    bl_description = (
        "Bevel each selected edge run into three loops. The loops are capped with diamond quads or run straight off the boundary."
    )
    bl_space_type = "VIEW_3D"
    bl_region_type = "TOOLS"
    bl_options = {'REGISTER', 'UNDO'}

    rf_label = "Diamond Bevel"

    factor: FloatProperty(
        name='Factor',
        description='How far the new edge loops slide from the initial loop',
        subtype='FACTOR',
        min=0.0, max=1.0, default=0.5,
    )
    merge_ends: BoolProperty(
        name='Merge Ends',
        description="Merge the diamond's outside vert into the end vert of the initial loop so the "
                    "adjacent faces stay quads. When off, the diamond stops short of the end "
                    "and leaves an n-gon on each side.",
        default=True,
    )
    flatten: EnumProperty(
        name='Flatten',
        description='On sharp surfaces, move middle loop verts along their normals to keep '
                    'the new faces from bending across the original loop',
        items=[
            ('LOOPS', 'Loops', 'Level the middle loop with the two outer loops so the face '
                               'runs between the caps are as flat as possible'),
            ('CAPS', 'Caps', 'Flatten each diamond cap, then interpolate the rest of the '
                             'middle loop between the cap heights'),
            ('NONE', 'None', 'Leave the middle loop verts where they are'),
        ],
        default='LOOPS',
    )

    # set on the standalone Mesh-keymap item only, so hotkey_owns_context governs the key
    # and not the right-click menu entry
    hotkey: BoolProperty(
        name='From Hotkey',
        default=False,
        options={'HIDDEN', 'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        # total_edge_sel lags a beat behind edit-mode changes, which is the same
        # trade-off Blender's own selection-dependent polls make
        return (
            context.mode == 'EDIT_MESH'
            and context.edit_object is not None
            and context.edit_object.data.total_edge_sel > 2
        )

    def invoke(self, context, event):
        if self.hotkey and not hotkey_owns_context(context, 'diamond_bevel_tool_context'):
            return {'PASS_THROUGH'}
        return self.execute(context)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        layout.prop(self, 'factor', slider=True)
        if not rf_is_running():
            layout.row().prop(self, 'flatten', expand=True)
        layout.prop(self, 'merge_ends')

    def execute(self, context):
        me = context.edit_object.data
        bm = bmesh.from_edit_mesh(me)
        bm.normal_update()  # the flatten modes offset mid verts along vert normals

        # In RF mode the new verts are snapped to the source not flattened
        self.use_source_snap = rf_is_running()

        runs, dropped_branching = self.collect_runs(bm)
        if not runs:
            msg = 'selection branches; select simple edge runs' if dropped_branching else 'select one or more edge runs'
            self.report({'WARNING'}, f'Diamond Junction: {msg}')
            return {'CANCELLED'}

        # Analyze every run before mutating anything so a bad run cancels cleanly
        plans, errors, claimed_faces = [], [], set()
        if dropped_branching:
            errors.append('selection branches')
        for chain, edges, is_cycle in runs:
            plan = self.analyze_run(chain, edges, is_cycle, claimed_faces)
            if isinstance(plan, str):
                errors.append(plan)
            else:
                plans.append(plan)
        if not plans:
            self.report({'WARNING'}, f'Diamond Junction: {errors[0]}')
            return {'CANCELLED'}

        old_faces, new_sel_faces, touched_verts = [], [], []
        for plan in plans:
            touched_verts.extend(self.apply_run(bm, plan, old_faces, new_sel_faces))
        bmesh.ops.delete(bm, geom=old_faces, context='FACES')

        if self.factor < 1e-6 or self.factor > 1.0 - 1e-6:
            self.merge_extreme_factor_doubles(bm, plans, touched_verts)

        if self.use_source_snap:
            self.snap_to_sources(context, touched_verts)

        for bmv in bm.verts:
            bmv.select = False
        for bme in bm.edges:
            bme.select = False
        for bmf in bm.faces:
            bmf.select = False
        for bmf in new_sel_faces:
            if not bmf.is_valid:
                continue  # welded away by the extreme-factor merge pass
            bmf.select = True
            for bmv in bmf.verts:
                bmv.select = True
            for bme in bmf.edges:
                bme.select = True
        if not any(bmf.is_valid for bmf in new_sel_faces):
            # factor 0 welded the bevel back onto the original loop; reselect it
            # so the selection survives and poll keeps the redo panel alive
            for plan in plans:
                chain = plan['chain']
                pairs = zip(chain, chain[1:] + (chain[:1] if plan['is_cycle'] else []))
                for va, vb in pairs:
                    if not (va.is_valid and vb.is_valid):
                        continue
                    bme = next((e for e in va.link_edges if e.other_vert(va) is vb), None)
                    if bme is not None:
                        bme.select = True
                        va.select = True
                        vb.select = True
        bm.select_flush_mode()

        bmesh.update_edit_mesh(me, loop_triangles=True, destructive=True)
        if errors:
            self.report({'WARNING'}, f'Diamond Junction: skipped some runs ({errors[0]})')
        return {'FINISHED'}

    def snap_to_sources(self, context, verts):
        ''' Pull the verts this operator created or moved onto the nearest source surface. '''
        sources = [
            (obj, obj.matrix_world, obj.matrix_world.inverted_safe())
            for obj in iter_all_valid_sources(context)
        ]
        if not sources:
            return
        M = context.edit_object.matrix_world
        Mi = M.inverted_safe()
        for bmv in verts:
            if not bmv.is_valid:
                continue  # welded away by the extreme-factor merge pass
            snapped = nearest_point_valid_sources(
                context, M @ bmv.co, world=True, sources=sources, respect_clip_planes=True,
            )
            if snapped:
                bmv.co = Mi @ Vector(snapped)

    def merge_extreme_factor_doubles(self, bm, plans, touched_verts):
        ''' At factor 0 or 1 every moved or created vert lands exactly on an
        existing vert, so weld the touched verts and their one-ring. '''
        scale = max(
            (
                (plan['chain'][i].co - plan['chain'][i + 1].co).length
                for plan in plans
                for i in range(len(plan['chain']) - 1)
            ),
            default=0.0,
        )
        if scale <= 0.0:
            return
        dist = scale * 1e-5
        touched = {bmv for bmv in touched_verts if bmv.is_valid}
        pool = set(touched)
        for bmv in list(touched):
            pool.update(bme.other_vert(bmv) for bme in bmv.link_edges)
        # weld moved and new verts INTO untouched originals, so at factor 0 the
        # original loop survives (keeping a selection alive for the redo panel)
        keepers = pool - touched
        doubles = bmesh.ops.find_doubles(bm, verts=list(pool), keep_verts=list(keepers), dist=dist)
        if doubles['targetmap']:
            bmesh.ops.weld_verts(bm, targetmap=doubles['targetmap'])
        # touched verts can also coincide with each other, e.g. a three-edge
        # run's two inner verts meeting at factor 1
        remaining = [bmv for bmv in touched if bmv.is_valid]
        if remaining:
            bmesh.ops.remove_doubles(bm, verts=remaining, dist=dist)

    # ------------------------------------------------------------------
    # Selection: ordered runs of selected edges
    # ------------------------------------------------------------------

    @staticmethod
    def collect_runs(bm):
        ''' Split the selected edges into simple runs, each an ordered vert chain
        with its edge chain and whether it closes into a cycle. Components that
        branch (a vert with 3+ selected edges) are dropped. '''
        sel_edges = [bme for bme in bm.edges if bme.select and not bme.hide]
        adj: dict = {}
        for bme in sel_edges:
            for bmv in bme.verts:
                adj.setdefault(bmv, []).append(bme)
        branches = {bmv for bmv, edges in adj.items() if len(edges) > 2}

        visited = set()
        def walk(start_v, start_e):
            chain, edge_chain = [start_v], []
            bmv, bme = start_v, start_e
            while bme is not None and bme not in visited:
                visited.add(bme)
                edge_chain.append(bme)
                bmv = bme.other_vert(bmv)
                chain.append(bmv)
                onward = [e for e in adj[bmv] if e is not bme]
                bme = onward[0] if len(onward) == 1 else None
            return chain, edge_chain

        runs, dropped_branching = [], False
        for bmv, edges in adj.items():
            if len(edges) != 1 or edges[0] in visited:
                continue
            chain, edge_chain = walk(bmv, edges[0])
            if branches & set(chain):
                dropped_branching = True
            else:
                runs.append((chain, edge_chain, False))
        for bme in sel_edges:  # remaining components are cycles
            if bme in visited:
                continue
            chain, edge_chain = walk(bme.verts[0], bme)
            chain.pop()  # closed: last vert repeats the first
            if branches & set(chain):
                dropped_branching = True
            else:
                runs.append((chain, edge_chain, True))
        return runs, dropped_branching

    # ------------------------------------------------------------------
    # Analysis: sides, split verts, and new positions (no mutation)
    # ------------------------------------------------------------------

    def analyze_run(self, chain, edges, is_cycle, claimed_faces):
        ''' Returns a plan dict, or an error string when the run cannot be handled. '''
        n, m = len(chain), len(edges)
        if any(len(bme.link_faces) != 2 for bme in edges):
            return 'run edges must have exactly two faces'

        # Consistently assign each run edge's two faces to side A and side B by
        # walking along the run: consecutive same-side faces share the rung edge
        # at the vert between them.
        def next_sides(prev_a, prev_b, bme):
            ''' Continue the A/B assignment onto bme's two faces. At a corner one
            of bme's faces IS the previous side face (the inside of the turn) and
            keeps its side; on straight runs same-side faces share the rung edge
            at the vert between the run edges. '''
            f0, f1 = bme.link_faces
            if f0 is prev_a or f1 is prev_b:
                return f0, f1
            if f1 is prev_a or f0 is prev_b:
                return f1, f0
            prev_edges = set(prev_a.edges)
            s0, s1 = bool(prev_edges & set(f0.edges)), bool(prev_edges & set(f1.edges))
            if s0 == s1:
                # Ambiguous adjacency (triangles, tight turns): fall back to
                # whichever face center is nearer the previous side-A center
                center = prev_a.calc_center_median()
                s0 = (f0.calc_center_median() - center).length <= (f1.calc_center_median() - center).length
            return (f0, f1) if s0 else (f1, f0)

        side_a, side_b = [None] * m, [None] * m
        side_a[0], side_b[0] = edges[0].link_faces
        for i in range(1, m):
            side_a[i], side_b[i] = next_sides(side_a[i - 1], side_b[i - 1], edges[i])
        if is_cycle and next_sides(side_a[-1], side_b[-1], edges[0])[0] is not side_a[0]:
            return 'cycle has inconsistent face flow'

        face_side = {}
        for i in range(m):
            for bmf, side in ((side_a[i], 'A'), (side_b[i], 'B')):
                if face_side.get(bmf, side) != side:
                    return 'run touches the same face from both sides'
                face_side[bmf] = side

        # Which verts get split into three. Interior verts always do; an open
        # run's end splits only when it sits on the mesh boundary (loops run
        # straight off the edge there), otherwise the end becomes a diamond tip.
        if is_cycle:
            split_idxs = list(range(n))
        else:
            split_idxs = [i for i in range(1, n - 1)]
            for i in (0, n - 1):
                if chain[i].is_boundary:
                    split_idxs.append(i)
        if len(split_idxs) < 2:
            # nothing left to bevel (one edge, both ends caps) or a two-edge run
            # whose only split vert is shared by both caps, leaving no strip
            return 'run is too short to bevel'

        # Every face touching a split vert gets rebuilt; two runs must not claim
        # the same face (e.g. parallel loops only one face apart)
        affected = {bmf for i in split_idxs for bmf in chain[i].link_faces}
        if affected & claimed_faces:
            return 'runs are too close together'
        claimed_faces |= affected

        run_edges = set(edges)
        def edges_at_vert(i):
            if is_cycle:
                return [(i - 1) % m, i % m]
            return [j for j in (i - 1, i) if 0 <= j < m]

        # Pole faces: faces around a split vert that touch no run edge still need
        # a side, found by spreading from the known side faces around that vert.
        for i in split_idxs:
            faces_v = [bmf for bmf in chain[i].link_faces]
            pending = [bmf for bmf in faces_v if bmf not in face_side]
            while pending:
                progressed = False
                for bmf in list(pending):
                    for bme in bmf.edges:
                        if chain[i] not in bme.verts:
                            continue
                        other = next((f for f in bme.link_faces if f is not bmf and f in face_side), None)
                        if other is not None:
                            face_side[bmf] = face_side[other]
                            pending.remove(bmf)
                            progressed = True
                            break
                if not progressed:
                    return 'non-manifold geometry around the run'

        # New positions: slide along the perpendicular rung edges by factor
        def rung_target(i, faces):
            cos, seen = [], set()
            for bmf in faces:
                for bme in bmf.edges:
                    if chain[i] not in bme.verts or bme in run_edges or bme in seen:
                        continue
                    seen.add(bme)
                    cos.append(bme.other_vert(chain[i]).co)
            if not cos:
                run_neighbors = {
                    bme.other_vert(chain[i])
                    for bme in chain[i].link_edges if bme in run_edges
                }
                for bmf in set(faces):
                    cos.extend(
                        bmv.co for bmv in bmf.verts
                        if bmv is not chain[i] and bmv not in run_neighbors
                    )
            if not cos:
                return None
            return sum(cos, Vector()) / len(cos)

        positions = {}
        for i in split_idxs:
            adjacent = edges_at_vert(i)
            target_a = rung_target(i, [side_a[j] for j in adjacent])
            target_b = rung_target(i, [side_b[j] for j in adjacent])
            if target_a is None or target_b is None:
                return 'no rung edge to slide along'
            co = chain[i].co
            positions[i] = (co.lerp(target_a, self.factor), co.lerp(target_b, self.factor))

        # Corner verts pinch the strip when their rails just slide toward the corner's own rung targets.
        # Match bevel instead: put each corner rail at the miter, the intersection of the two neighboring
        # segments' rail lines, so the strip runs straight nd even width through the turn.
        miters = {}
        for i in split_idxs:
            adjacent = edges_at_vert(i)
            if len(adjacent) != 2:
                continue
            e0, e1 = adjacent
            if side_a[e0] is not side_a[e1] and side_b[e0] is not side_b[e1]:
                continue  # run goes straight through this vert
            prev_i, next_i = (i - 1) % n, (i + 1) % n
            if prev_i not in positions or next_i not in positions:
                continue  # neighbor is a cap tip: keep the first-pass rail
            d_prev = chain[i].co - chain[prev_i].co
            d_next = chain[next_i].co - chain[i].co
            pair = []
            for side in (0, 1):
                p_prev, p_next = positions[prev_i][side], positions[next_i][side]
                hit = intersect_line_line(p_prev, p_prev + d_prev, p_next, p_next + d_next)
                pair.append((hit[0] + hit[1]) * 0.5 if hit else positions[i][side])
            miters[i] = tuple(pair)
        positions.update(miters)

        # Each diamond's inner vert slides along the run away from the tip by the
        # same factor, keeping the diamond compact. A two-edge run shares one
        # inner vert between both diamonds, so the two slides (mostly) cancel.
        mid_slides, inner_aways, inner_slide_t = {}, {}, {}
        if not is_cycle:
            slides = [
                (inner_i, away_i)
                for tip_i, inner_i, away_i in ((0, 1, 2), (n - 1, n - 2, n - 3))
                if tip_i not in split_idxs and inner_i in split_idxs and 0 <= away_i < n
            ]
            # On a three-edge run the two inner verts slide toward each other along
            # the one shared segment, so a full factor would carry them past each
            # other. Halving both makes factor 1 exactly where the caps meet.
            inners = {inner_i: away_i for inner_i, away_i in slides}
            for inner_i, away_i in slides:
                t = self.factor
                if inners.get(away_i) == inner_i:
                    t *= 0.5
                mid_slides[inner_i] = mid_slides.get(inner_i, Vector()) + (chain[away_i].co - chain[inner_i].co) * t
                inner_aways.setdefault(inner_i, []).append(away_i)
                inner_slide_t[inner_i] = t

        # With Merge Ends off, the diamond's outside vert becomes its own vert
        # sitting `factor` of the way from the inner vert toward the run's end,
        # and the two faces past it become n-gons instead of staying quads.
        tip_caps = {}
        if not is_cycle and not self.merge_ends:
            for tip_i, inner_i in ((0, 1), (n - 1, n - 2)):
                if tip_i in split_idxs or inner_i not in split_idxs:
                    continue
                tip_caps[tip_i] = chain[inner_i].co.lerp(chain[tip_i].co, self.factor)

        # On a sharp surface the middle loop sits on the crease while the rails sit on the slopes.
        # The flatten modes offset mid verts along their vert normals.
        def vert_normal(i):
            nrm = chain[i].normal
            return nrm.normalized() if nrm.length > 1e-9 else None

        def slid_co(i):
            return chain[i].co + mid_slides.get(i, Vector())

        mid_flatten = {}
        flatten = 'NONE' if getattr(self, 'use_source_snap', False) else self.flatten
        if flatten == 'LOOPS':
            # Level each mid vert with the midpoint of its rails. A slid cap inner
            # vert no longer sits between its own rails, so it levels with the rail
            # plane: both rails lerped by the same factor toward the next station.
            for i in split_idxs:
                nrm = vert_normal(i)
                if nrm is None:
                    continue
                aways = inner_aways.get(i, [])
                if len(aways) == 1 and aways[0] in positions:
                    j = aways[0]
                    t = inner_slide_t[i]
                    co_a = positions[i][0].lerp(positions[j][0], t)
                    co_b = positions[i][1].lerp(positions[j][1], t)
                else:
                    co_a, co_b = positions[i]
                t = ((co_a + co_b) * 0.5 - slid_co(i)).dot(nrm)
                mid_flatten[i] = nrm * t
        elif flatten == 'CAPS' and not is_cycle:
            # Drop each diamond's inner vert onto the plane of its tip and rails,
            # then interpolate the rest of the middle loop between the cap offsets
            # by arc length (a capless boundary end anchors at zero offset)
            cap_ts = {}
            for tip_i, inner_i in ((0, 1), (n - 1, n - 2)):
                if tip_i in split_idxs or inner_i not in split_idxs:
                    continue
                nrm = vert_normal(inner_i)
                if nrm is None:
                    continue
                tip_co = tip_caps[tip_i] if tip_i in tip_caps else chain[tip_i].co
                co_a, co_b = positions[inner_i]
                plane_nrm = (co_a - tip_co).cross(co_b - tip_co)
                if plane_nrm.length < 1e-12:
                    continue
                denom = nrm.dot(plane_nrm)
                if abs(denom) < 1e-6 * plane_nrm.length:
                    continue  # normal (nearly) parallel to the cap plane
                t = (tip_co - slid_co(inner_i)).dot(plane_nrm) / denom
                cap_ts.setdefault(inner_i, []).append(t)
            # a two-edge run's shared inner vert averages its two cap planes
            t_at = {i: sum(ts) / len(ts) for i, ts in cap_ts.items()}
            if t_at:
                lo, hi = min(split_idxs), max(split_idxs)
                cum = [0.0]
                for i in range(lo, hi):
                    cum.append(cum[-1] + (chain[i + 1].co - chain[i].co).length)
                total = cum[-1] or 1.0
                t_lo, t_hi = t_at.get(lo, 0.0), t_at.get(hi, 0.0)
                for k, i in enumerate(range(lo, hi + 1)):
                    nrm = vert_normal(i)
                    if nrm is None:
                        continue
                    t = t_lo + (t_hi - t_lo) * (cum[k] / total)
                    mid_flatten[i] = nrm * t

        return {
            'chain': chain, 'edges': edges, 'is_cycle': is_cycle,
            'side_a': side_a, 'side_b': side_b, 'face_side': face_side,
            'split_idxs': set(split_idxs), 'positions': positions,
            'mid_slides': mid_slides, 'tip_caps': tip_caps, 'mid_flatten': mid_flatten,
        }

    # ------------------------------------------------------------------
    # Mutation: split verts, rebuild neighbor faces, build strip and diamonds
    # ------------------------------------------------------------------

    def apply_run(self, bm, plan, old_faces, new_sel_faces):
        chain, edges, is_cycle = plan['chain'], plan['edges'], plan['is_cycle']
        side_a, side_b, face_side = plan['side_a'], plan['side_b'], plan['face_side']
        split_idxs, positions = plan['split_idxs'], plan['positions']
        n, m = len(chain), len(edges)

        # The rail positions were computed from the inner vert's original spot,
        # so slide it only after analysis has finished with every run
        touched = []
        for lookup in (plan['mid_slides'], plan['mid_flatten']):
            for i, offset in lookup.items():
                if offset.length_squared == 0.0:
                    continue  # factor 0: an unmoved vert must stay a weld keeper
                chain[i].co += offset
                touched.append(chain[i])

        verts_a, verts_b = {}, {}
        for i in split_idxs:
            co_a, co_b = positions[i]
            for lookup, co in ((verts_a, co_a), (verts_b, co_b)):
                # the example vert copies custom data; copy_from would invalidate
                # the new vert's python reference
                bmv = bm.verts.new(co, chain[i])
                lookup[chain[i]] = bmv
                touched.append(bmv)

        # Unmerged diamond tips get their own vert, and the two end faces absorb
        # both it and the rail vert where the inner vert used to be (an n-gon)
        new_tips, tip_subs = {}, {}
        for tip_i, co in plan['tip_caps'].items():
            new_tips[tip_i] = bm.verts.new(co, chain[tip_i])
            touched.append(new_tips[tip_i])
            s = 0 if tip_i == 0 else m - 1
            inner = chain[1] if tip_i == 0 else chain[n - 2]
            for bmf in (side_a[s], side_b[s]):
                tip_subs[bmf] = (inner, chain[tip_i], new_tips[tip_i])

        # Rebuild every face touching a split vert, substituting the vert for its
        # side's new copy. The originals are deleted at the end (context 'FACES'
        # also removes the old rung edges and end edges they leave behind).
        rebuilt = set()
        for i in split_idxs:
            for bmf in chain[i].link_faces:
                if bmf in rebuilt:
                    continue
                rebuilt.add(bmf)
                lookup = verts_a if face_side[bmf] == 'A' else verts_b
                sub = tip_subs.get(bmf)
                new_verts = []
                for loop in bmf.loops:
                    bmv = loop.vert
                    if sub and bmv is sub[0]:
                        inner, tip_orig, tip_new = sub
                        rail = lookup[inner]
                        # keep loop order: the new tip vert sits between the old
                        # tip and the rail vert
                        if loop.link_loop_prev.vert is tip_orig:
                            new_verts.extend((tip_new, rail))
                        else:
                            new_verts.extend((rail, tip_new))
                    else:
                        new_verts.append(lookup.get(bmv, bmv))
                new_face = bm.faces.new(new_verts, bmf)
                new_face.smooth = bmf.smooth
                new_face.material_index = bmf.material_index
                old_faces.append(bmf)

        def forward(i):
            # True when side A's face traverses run edge i from chain[i] onward,
            # which fixes the winding of every new face built along that segment
            for loop in side_a[i].loops:
                if loop.edge is edges[i]:
                    return loop.vert is chain[i % n]
            return True

        def make_face(verts, example):
            bmf = bm.faces.new(verts, example)
            bmf.smooth = example.smooth
            bmf.material_index = example.material_index
            new_sel_faces.append(bmf)

        # Strip quads between consecutive split verts; the original edge stays
        # as the middle loop
        for i in range(m):
            va, vb = chain[i], chain[(i + 1) % n]
            if va not in verts_a or vb not in verts_a:
                continue
            a0, a1 = verts_a[va], verts_a[vb]
            b0, b1 = verts_b[va], verts_b[vb]
            if forward(i):
                make_face([a1, a0, va, vb], side_a[i])
                make_face([b0, b1, vb, va], side_b[i])
            else:
                make_face([a0, a1, vb, va], side_a[i])
                make_face([b1, b0, va, vb], side_b[i])

        # Diamond caps at open ends that were not split. Every cap starts its
        # loop on a rail vert, putting the rails at slots 0 and 2 so the quad's
        # triangulation splits rail-to-rail instead of tip-to-inner (rotating
        # the start keeps the cyclic order, so the winding is unchanged).
        if not is_cycle:
            inner = chain[1]
            if chain[0] not in verts_a and inner in verts_a:
                tip = new_tips.get(0, chain[0])
                if forward(0):
                    make_face([verts_a[inner], tip, verts_b[inner], inner], side_a[0])
                else:
                    make_face([verts_a[inner], inner, verts_b[inner], tip], side_a[0])
            inner = chain[n - 2]
            if chain[n - 1] not in verts_a and inner in verts_a:
                tip = new_tips.get(n - 1, chain[n - 1])
                if forward(m - 1):
                    make_face([verts_a[inner], inner, verts_b[inner], tip], side_a[m - 1])
                else:
                    make_face([verts_a[inner], tip, verts_b[inner], inner], side_a[m - 1])

        return touched


keymaps = []

def register():
    keyconfigs = bpy.context.window_manager.keyconfigs.addon
    if not keyconfigs: return
    km = keyconfigs.keymaps.new(name='Mesh')
    kmi = km.keymap_items.new(RFOperator_InsertDiamondJunction.bl_idname, 'B', 'PRESS', ctrl=True, shift=False, alt=True)
    kmi.properties.hotkey = True
    keymaps.append((km, kmi))

def unregister():
    for km, kmi in keymaps:
        km.keymap_items.remove(kmi)
    keymaps.clear()
