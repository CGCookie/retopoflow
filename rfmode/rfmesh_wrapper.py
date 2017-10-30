import bmesh
from bmesh.types import BMesh, BMVert, BMEdge, BMFace
from bmesh.utils import edge_split, vert_splice, face_split
from ..common.utils import iter_pairs
from ..common.maths import triangle2D_overlap, triangle2D_det, triangle2D_area, segment2D_intersection
from ..common.maths import Vec2D

'''
BMElemWrapper wraps BMverts, BMEdges, BMFaces to automagically handle
world-to-local and local-to-world transformations.

Must override any property that can be set (TODO: find more elegant
way to handle this!) and function that returns a BMVert, BMEdge, or
BMFace.  All functions and read-only properties are handled with
__getattr__().

user-writable properties:

    BMVert: co, normal
    BMEdge: seam, smooth
    BMFace: material_index, normal, smooth
    common: hide, index. select, tag

NOTE: RFVert, RFEdge, RFFace do NOT mark RFMesh as dirty!
'''


class BMElemWrapper:
    @staticmethod
    def wrap(rftarget):
        BMElemWrapper.rftarget   = rftarget
        BMElemWrapper.xform      = rftarget.xform
        BMElemWrapper.l2w_point  = rftarget.xform.l2w_point
        BMElemWrapper.w2l_point  = rftarget.xform.w2l_point
        BMElemWrapper.l2w_normal = rftarget.xform.l2w_normal
        BMElemWrapper.w2l_normal = rftarget.xform.w2l_normal
        BMElemWrapper.symmetry   = rftarget.symmetry

    @staticmethod
    def _unwrap(bmelem):
        if bmelem is None: return None
        if isinstance(bmelem, BMElemWrapper): return bmelem.bmelem
        return bmelem

    def __init__(self, bmelem):
        self.bmelem = bmelem

    def __repr__(self):
        return '<BMElemWrapper: %s>' % repr(self.bmelem)
    def __hash__(self):
        return hash(self.bmelem)
    def __eq__(self, other):
        if other is None: return False
        if isinstance(other, BMElemWrapper):
            return self.bmelem == other.bmelem
        return self.bmelem == other
    def __ne__(self, other):
        return not self.__eq__(other)

    @property
    def hide(self): return self.bmelem.hide
    @hide.setter
    def hide(self, v): self.bmelem.hide = v

    @property
    def index(self): return self.bmelem.index
    @index.setter
    def index(self, v): self.bmelem.index = v

    @property
    def select(self): return self.bmelem.select
    @select.setter
    def select(self, v): self.bmelem.select = v

    @property
    def tag(self): return self.bmelem.tag
    @tag.setter
    def tag(self, v): self.bmelem.tag = v

    def __getattr__(self, k):
        if k in self.__dict__:
            return getattr(self, k)
        return getattr(self.bmelem, k)


class RFVert(BMElemWrapper):
    def __repr__(self):
        return '<RFVert: %s>' % repr(self.bmelem)

    @property
    def co(self): return self.l2w_point(self.bmelem.co)
    @co.setter
    def co(self, co):
        co = self.w2l_point(co)
        if 'x' in self.symmetry: co.x = max(0, co.x)
        if 'y' in self.symmetry: co.y = min(0, co.y)
        if 'z' in self.symmetry: co.z = max(0, co.z)
        self.bmelem.co = co

    @property
    def normal(self): return self.l2w_normal(self.bmelem.normal)

    @normal.setter
    def normal(self, norm): self.bmelem.normal = self.w2l_normal(norm)

    @property
    def link_edges(self):
        return [RFEdge(bme) for bme in self.bmelem.link_edges]

    @property
    def link_faces(self):
        return [RFFace(bmf) for bmf in self.bmelem.link_faces]

    #############################################

    def share_edge(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        return any(bmv1 in bme.verts for bme in bmv0.link_edges)

    def shared_edge(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        bme = next((bme for bme in bmv0.link_edges if bmv1 in bme.verts), None)
        return RFEdge(bme) if bme else None

    def shared_faces(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        return [RFFace(bmf) for bmf in bmv0.link_faces if bmv1 in bmf.verts]

    def merge(self, other):
        bmv0 = BMElemWrapper._unwrap(self)
        bmv1 = BMElemWrapper._unwrap(other)
        vert_splice(bmv1, bmv0)


class RFEdge(BMElemWrapper):
    def __repr__(self):
        return '<RFEdge: %s>' % repr(self.bmelem)

    @property
    def seam(self): return self.bmelem.seam
    @seam.setter
    def seam(self, v): self.bmelem.seam = v

    @property
    def smooth(self): return self.bmelem.smooth
    @smooth.setter
    def smooth(self, v): self.bmelem.smooth = v

    def other_vert(self, bmv):
        bmv = self._unwrap(bmv)
        o = self.bmelem.other_vert(bmv)
        if o is None: return None
        return RFVert(o)
    
    def shared_vert(self, bme):
        bme = self._unwrap(bme)
        verts = [v for v in self.bmelem.verts if v in bme.verts]
        if not verts: return None
        return RFVert(verts[0])
    
    @property
    def verts(self):
        bmv0,bmv1 = self.bmelem.verts
        return (RFVert(bmv0), RFVert(bmv1))

    @property
    def link_faces(self):
        return [RFFace(bmf) for bmf in self.bmelem.link_faces]

    #############################################

    def normal(self):
        n,c = Vector(),0
        for bmf in self.bmelem.link_faces:
            n += bmf.normal
            c += 1
        return n / max(1,c)
    
    def calc_length(self):
        v0,v1 = self.bmelem.verts
        return (self.l2w_point(v0.co) - self.l2w_point(v1.co)).length
    
    def calc_center(self):
        v0,v1 = self.bmelem.verts
        return self.l2w_point((v0.co + v1.co) / 2)
    
    #############################################

    def split(self, vert=None, fac=0.5):
        bme = BMElemWrapper._unwrap(self)
        bmv = BMElemWrapper._unwrap(vert) or bme.verts[0]
        bme_new,bmv_new = edge_split(bme, bmv, fac)
        return RFEdge(bme_new), RFVert(bmv_new)

    def collapse(self):
        bme = BMElemWrapper._unwrap(self)
        bmv0,bmv1 = bme.verts
        del_faces = [f for f in bme.link_faces if len(f.verts) == 3]
        for bmf in del_faces: self.rftarget.bme.faces.remove(bmf)
        bmesh.ops.collapse(self.rftarget.bme, edges=[bme], uvs=True)
        return bmv0 if bmv0.is_valid else bmv1


class RFFace(BMElemWrapper):
    def __repr__(self):
        return '<RFFace: %s>' % repr(self.bmelem)

    @property
    def material_index(self): return self.bmelem.material_index
    @material_index.setter
    def material_index(self, v): self.bmelem.material_index = v

    @property
    def normal(self): return self.l2w_normal(self.bmelem.normal)
    @normal.setter
    def normal(self, v): self.bmelem.normal = self.w2l_normal(v)

    @property
    def smooth(self): return self.bmelem.smooth
    @smooth.setter
    def smooth(self, v): self.bmelem.smooth = v

    @property
    def edges(self):
        return [RFEdge(bme) for bme in self.bmelem.edges]

    def shared_edge(self, other):
        edges = set(self.bmelem.edges)
        for bme in other.bmelem.edges:
            if bme in edges: return bme
    
    def opposite_edge(self, e):
        if len(self.bmelem.edges) != 4: return None
        e = self._unwrap(e)
        for i,bme in self.bmelem.edges:
            if bme == e: return RFEdge(self.bmelem.edges[(i+2)%4])
        return None
    
    @property
    def verts(self):
        return [RFVert(bmv) for bmv in self.bmelem.verts]
    
    def get_vert_co(self):
        return [self.l2w_point(bmv.co) for bmv in self.bmelem.verts]
    def get_vert_normal(self):
        return [self.l2w_normal(bmv.normal) for bmv in self.bmelem.verts]
    
    def is_quad(self): return len(self.bmelem.verts)==4
    def is_triangle(self): return len(self.bmelem.verts)==3
    
    #############################################
    
    def overlap2D(self, other, Point_to_Point2D):
        return self.overlap2D_center(other, Point_to_Point2D)
    
    def overlap2D_center(self, other, Point_to_Point2D):
        verts0 = list(map(Point_to_Point2D, [v.co for v in self.bmelem.verts]))
        verts1 = list(map(Point_to_Point2D, [v.co for v in self._unwrap(other).verts]))
        center0 = sum(map(Vec2D, verts0), Vec2D((0,0))) / len(verts0)
        center1 = sum(map(Vec2D, verts1), Vec2D((0,0))) / len(verts1)
        radius0 = sum((v-center0).length for v in verts0) / len(verts0)
        radius1 = sum((v-center1).length for v in verts1) / len(verts1)
        ratio = 1 - (center0-center1).length / (radius0 + radius1)
        return max(0, ratio)
    
    def overlap2D_Sutherland_Hodgman(self, other, Point_to_Point2D):
        # computes area in image space of overlap between self and other
        # this is done by clipping other to self by iterating through all of edges in self
        # and clipping to the "inside" half-space.
        # Sutherland-Hodgman Algorithm https://en.wikipedia.org/wiki/Sutherland%E2%80%93Hodgman_algorithm
        
        # NOTE: assumes self and other are convex! (not a terrible assumption)
        
        verts0 = list(map(Point_to_Point2D, [v.co for v in self.bmelem.verts]))
        verts1 = list(map(Point_to_Point2D, [v.co for v in self._unwrap(other).verts]))
        
        for v00,v01 in zip(verts0, verts0[1:]+verts0[:1]):
            # other polygon (verts1) by line v00-v01
            len1 = len(verts1)
            sides = [triangle2D_det(v00, v01, v1)<=0 for v1 in verts1]
            intersections = [segment2D_intersection(v00, v01, v10, v11) for v10,v11 in zip(verts1,verts1[1:]+verts1[:1])]
            nverts1 = []
            for i0 in range(len1):
                i1 = (i0+1) % len1
                v10,v11 = verts1[i0],verts1[i1]
                s10,s11 = sides[i0],sides[i1]
                
                if s10 and s11:
                    # both outside. might intersect
                    if intersections[i0]:
                        nverts1 += [intersections[i0]]
                elif not s11:
                    if s10:
                        # v10 is outside, v11 is inside
                        if intersections[i0]:
                            nverts1 += [intersections[i0]]
                    nverts1 += [v11]
            verts1 = nverts1
            print(verts1)
        
        if len(verts1) < 3: return 0
        v0 = verts1[0]
        return sum(triangle2D_area(v0,v1,v2) for v1,v2 in zip(verts1[1:-1],verts1[2:]))
    
    def merge(self, other):
        # find vert of other that is closest to self's v0
        verts0,verts1 = list(self.bmelem.verts),list(other.bmelem.verts)
        l = len(verts0)
        assert l == len(verts1), 'RFFaces must have same vert count'
        self.rftarget.bme.faces.remove(self._unwrap(other))
        offset = min(range(l), key=lambda i:(verts1[i].co - verts0[0].co).length)
        # assuming verts are in same rotational order (should be)
        for i0 in range(l):
            i1 = (i0 + offset) % l
            vert_splice(verts1[i1], verts0[i0])
        #for v in verts0:
        #    self.rftarget.clean_duplicate_bmedges(v)
    
    #############################################
    
    def split(self, vert_a, vert_b):
        bmf = BMElemWrapper._unwrap(self)
        bmva = BMElemWrapper._unwrap(vert_a)
        bmvb = BMElemWrapper._unwrap(vert_b)
        bmf_new,bml_new = face_split(bmf, bmva, bmvb)
        return RFFace(bmf_new)


class RFEdgeSequence:
    def __init__(self, sequence):
        if not sequence:
            self.verts = []
            self.edges = []
            self.loop = False
            return
        
        sequence = list(BMElemWrapper._unwrap(elem) for elem in sequence)
        
        if type(sequence[0]) is BMVert:
            self.verts = sequence
            self.loop = len(sequence) > 1 and len(set(sequence[0].link_edges) & set(sequence[-1].link_edges)) != 0
            self.edges = [next(iter(set(v0.link_edges) & set(v1.link_edges))) for v0,v1 in iter_pairs(sequence, self.loop)]
        elif type(sequence[0]) is BMEdge:
            self.edges = sequence
            self.loop = len(sequence) > 2 and len(set(sequence[0].verts) & set(sequence[-1].verts)) != 0
            if len(sequence) == 1 and not self.loop:
                self.verts = sequence[0].verts
            else:
                self.verts = [next(iter(set(e0.verts) & set(e1.verts))) for e0,e1 in iter_pairs(sequence, self.loop)]
        else:
            assert False, 'unhandled type: %s' % str(type(sequence[0]))
    
    def __repr__(self):
        e = min(map(repr, self.edges)) if self.edges else None
        return '<RFEdgeSequence: %d,%s,%s>' % (len(self.verts),str(self.loop),str(e))
    
    def __len__(self): return len(self.edges)
    def get_verts(self): return [RFVert(bmv) for bmv in self.verts]
    def get_edges(self): return [RFEdge(bme) for bme in self.edges]
    def is_loop(self): return self.loop
    def iter_vert_pairs(self): return iter_pairs(self.get_verts(), self.loop)
    def iter_edge_pairs(self): return iter_pairs(self.get_edges(), self.loop)

