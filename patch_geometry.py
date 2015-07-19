'''
Created on Jul 18, 2015

@author: Patrick
'''

def tri_prim_0(v0, v1, v2):
    
    pole0 = .5*v0 + .5*v1
    verts = [v0, pole0, v1, v2]
    faces = [(0,1,2,3)]
    
    return verts, faces

def tri_prim_1(v0,v1,v2):
    pole0 = .5*v0 + .5*v1 
    pole1 = .5*v2 + .5*pole0
    c00 = .5*v0 + .5*pole0
    c01 = .5*pole0 + .5*v1

    verts = [v0, c00, pole0, c01, v1, v2, pole1]
    faces= [(0,1,6,5),
            (1,2,3,6),
            (3,4,5,6)]
    
    return verts, faces

def quad_prim_1(v0, v1, v2, v3, x = 0):
    
    N = 3*x + 7
    
    pole0 = 0.25 * (v0 + v1 + v2 + v3)
    c0 = .5*v0 + .5*v1
    c1 = .5*v1 + .5*v2
    
    
    verts = [v0, v3, v2]
    faces = []
    for i in range(0,x):
        A = (i+1)/(x+1)
        B =  (x-i)/(x+1)
        verts += [A*c0 + B*v0]
        verts += [A*pole0 + B*v3]
        verts += [A*c1 + B*v2]
    
    verts += [c0, pole0, c1, v1]
     
    for i in range(0,x+1):
        for j in range(0,2):
            f = (3*i+j, 3*i+j+3, 3*i+j+4, 3*i+j+1)
            print((i,j,f))
            faces += [f]
        
    faces += [(N-4, N-1, N-2, N-3)]
    return verts, faces


def quad_prim_2(v0, v1, v2, v3, x = 0, y = 0):
    
    c0 = .67 * v0 + .33 * v1
    pole0 = .67 * v1 + .33 * v0
    
    verts = []
    for i in range(0,y+2):
        A = (i)/(y+1)
        B =  (y-i+1)/(y+1) 
    
        verts += [B*v3 + A*v0]
        
        vlow  = B*v2 + A*c0
        vhigh = B*v1 + A*pole0
        
        for j in range(0,x+2):
            C = (j)/(x+1)
            D =  (x-j+1)/(x+1)
            
            verts+= [D*vlow + C*vhigh]
            
    faces = []
    N = 6 + 2*x + 3*y + x*y
    for i in range(0, y+1):
        for j in range(0,x+2):
            A =i*(x+3) + j
            B =(i + 1) * (x+3) + j
            faces += [(A, B, B+1, A+1)] 
    return verts, faces


def quad_prim_3(v0, v1, v2, v3):
    
    c00 = .67 * v0 + .33 * v1
    c01 = .33 * v0 + .67 * v1
    
    pole0 = .67 * (.5*v0 + .5*v3) + .33 * (.5*v1 + .5*v2) 
    pole1 = .33 * (.5*v0 + .5*v3) + .67 * (.5*v1 + .5*v2)
    
    verts = [v0, c00, c01, v1, v2, v3, pole0, pole1]
    faces  = [(0,1,6,5),
            (1,2,7,6),
            (2,3,4,7),
            (7,4,5,6)]
    
    return verts, faces

def quad_prim_4(v0, v1, v2, v3):
    
    c00 = .75 * v0 + .25 * v1
    c01 = .5 * v0 + .5 * v1
    c02 = .25 * v0 + .75 * v1
    c10 = .5*v1 + .5*v2
    
    pole0 = .4 * c00 + .6*(.25*v2 + .75*v3)
    pole1 = .6 * c02 + .4*(.75*v2 + .25*v3)
    cp01 = .5*pole0 + .5*pole1
    
    
    verts = [v0, c00, c01, c02, v1, c10, v2, v3, pole0, cp01, pole1]
    faces  = [(0,1,8,7),
              (1,2,9,8),
              (2,3,10,9),
              (3,4,5,10),
              (5,6,9,10),
              (8,9,6,7)]

    return verts, faces


def pent_prim_0(v0, v1, v2, v3, v4):
    
    c0 = .5*v0 + .5*v1
    verts = [v0,c0,v1,v2,v3,v4]
    faces = [(0,1,4,5),(1,2,3,4)]
    
    return verts, faces
    
def pent_prim_1(v0, v1, v2, v3, v4):
    c0 = .5*v0 + .5*v1
    
    verts = [v0,c0,v1,v2,v3,v4]
    faces = [(0,1,2,3),(0,3,4,5)]
    
    return verts, faces
    
def pent_prim_2(v0, v1, v2, v3, v4):
    
    c00 = .75*v0 + .25*v1
    pole0 = .5*v0 + .5*v1
    c01 = .25*v0 + .75*v1
    pole1 = .75*pole0 + .25*v3
    cp0 = .5*pole1 + .5*v3
    
    verts = [v0, c00, pole0, c01, v1, v2, v3, v4, cp0, pole1]
    faces = [(0,1,9,8),
             (1,2,3,9),
             (3,4,8,9),
             (4,5,6,8),
             (6,7,0,8)]
    return verts, faces

def pent_prim_3(v0, v1, v2, v3, v4):
    
    c00 = .8*v0 + .2*v1
    c01 = .6*v0 + .4*v1
    c02 = .4*v0 + .6*v1
    c03 = .2*v0 + .8*v1
    
    c10 = .5*v1 + .5*v2
    
    pole0 = .5*c00 + .5*(.5*v3 + .5*v4)
    cp0 = .25 * c01 + .75*v3
    cp1 = .75 * (.33*v2 + .67*v3) + .25*c02
    pole1 = .5 * c03 + .5*(.67*v2 + .33*v3)
    
    verts = [v0,c00,c01,c02,c03,v1,c10,v2,v3,v4, pole0, cp0, cp1, pole1]
    
    faces = [(0,1,10,9),
             (1,2,11,10),
             (2,3,12,11),
             (3,4,13,12),
             (4,5,6,13),
             (6,7,12,13),
             (7,8,11,12),
             (8,9,10,11)]
    
    return verts, faces
    
    
def hex_prim_0(v0, v1, v2, v3, v4,v5):
    
    verts = [v0,v1,v2,v3,v4,v5]
    faces = [(0,1,2,5), (2,3,4,5)]
    
    return verts, faces

def hex_prim_1(v0, v1, v2, v3, v4,v5):

    c0 = .5*v0  +.5*v1
    c1 = .5*v1 + .5*v2
    cp0 = .18*(v3 + v4 + v5) + .1533*(v0 + v1 + v2)
    pole1 = .33*c0 + .33 * c1 + .34 * cp0
    verts = [v0, c0, v1, c1, v2, v3, v4, v5, cp0, pole1]
    faces = [(0,1,9,8),
             (1,2,3,9),
             (3,4,8,9),
             (4,5,6,8),
             (6,7,0,8)]
    
    return verts, faces

def hex_prim_2(v0, v1, v2, v3, v4,v5):

    c00 = .67*v0 + .33 * v1
    c01 = .33*v0 + .67*v1
    
    cp0 = .8 * (.65 * v5 + .35*v2) + .2 * (.8*v4 + .2*v3)
    cp1 = .8 * (.35 * v5 + .65*v2) + .2 * (.2*v4 + .8*v3)
    
    pole0 = .5 * (.5*c00 + .5*c01) + .5*cp0
    pole1 = .5 * (.5*c00 + .5*c01) + .5*cp1
    
    verts = [v0, c00, c01, v1, v2, v3, v4, v5, cp0, cp1, pole0, pole1]
    faces = [(0,1,10,8),
             (1,2,11,10),
             (2,3,9,11),
             (3,4,5,9),
             (5,6,8,9),
             (6,7,0,8),
             (8,10,11,9)]
    
    return verts, faces
    
    
def hex_prim_3(v0, v1, v2, v3, v4,v5):    
    c00 = .75 * v0 + .25 * v1
    c01 = .5 * v0 + .5 * v1
    c02 = .25 * v0 + .75 * v1
    
    c10 = .5*v1 + .5*v2
    
    
    cp0 = .4*v2 + .6*v5
    pole0 = .6*v2 + .4*v5
    
    pole1 = .5*(.75*v4 + .25*v3) + .5*cp0
    pole2 = .5*(.25*v4 + .75*v3) + .5*pole0
    
    pole3 = .334*pole0 + .333*c02 + .333*c10
    
    verts = [v0, c00, c01, c02, v1, c10, v2, v3, v4, v5, pole1, pole2, cp0, pole0, pole3]
    faces = [(0,1,12,9),
             (1,2,13,12),
             (2,3,14,13),
             (3,4,5,14),
             (5,6,13,14),
             (6,7,11,13),
             (7,8,10,11),
             (8,9,12,10),
             (10,12,13,11)]
    
    return verts, faces
       
def tri_geom_0(verts, L, p0, p1, p2):
    pass   
def tri_geom_1(verts, L, p0, p1, p2, x):
    pass    
def quad_geom_0(verts, L, p0, p1, p2):
    pass
def quad_geom_1(verts, L, p0, p1, p2):
    pass
def quad_geom_2(verts, L, p0, p1, p2):
    pass
def quad_geom_3(verts, L, p0, p1, p2):
    pass
def quad_geom_4(verts, L, p0, p1, p2):
    pass  
def pent_geom_0(verts, L, p0, p1, p2):
    pass
def pent_geom_1(verts, L, p0, p1, p2):
    pass
def pent_geom_2(verts, L, p0, p1, p2):
    pass    
def pent_geom_3(verts, L, p0, p1, p2):
    pass
def hex_geom_0(verts, L, p0, p1, p2):
    pass
def hex_geom_1(verts, L, p0, p1, p2):
    pass
def hex_geom_2(verts, L, p0, p1, p2):
    pass    
def hex_geom_3(verts, L, p0, p1, p2):
    pass