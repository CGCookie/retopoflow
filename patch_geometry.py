'''
Created on Jul 18, 2015

@author: Patrick
'''
from itertools import chain

def tri_prim_0(v0, v1, v2):
    
    pole0 = .5*v0 + .5*v1
    verts = [v0, pole0, v1, v2]
    faces = [(0,1,2,3)]
    
    return verts, faces

def tri_prim_1(v0,v1,v2, x=0, q1 = 0, q2 = 0):
    p0 = .5*v0 + .5*v1 
    p1 = .5*v2 + .5*p0
    c00 = .5*v0 + .5*p0
    c01 = .5*p0 + .5*v1

    #verts = [v0, c00, pole0, c01, v1, v2, pole1]
    #faces= [(0,1,6,5),
    #        (1,2,3,6),
    #        (3,4,5,6)]
    
    V00 = quadrangulate_verts(v0, c00, p1, v2, q1, x)
    V01 = quadrangulate_verts(v2, p1, c01, v1, q2, x, y_off =1)
    
    verts= []

        
    for i in range(0,x+2):
        verts += chain(V00[i*(q1+2):i*(q1+2)+q1+2], V01[i*(q2+1):i*(q2+1)+q2+1])
    
    
    #add in the bottom verts
    vs = quadrangulate_verts(p1, c00, p0, c01,q2,q1, x_off=1, y_off=1)
    verts += vs
    
    faces = []
    for i in range(0,x+1):
        for j in range(0, q2+q1+2):
            A =i*(q1+q2+3) + j
            B =(i+1)*(q1+q2+3) + j
            faces += [(A, B, B+1, A+1)]
            print((i,j,A,B, B+1, A+1))
    
    #make the bottom faces
    alpha = (x+1)*(q1+q2+3)
    n_p1 = alpha + q1 + 1 #index of the pole
    n_beta = n_p1 + q2+1
    N = (7 +3*q1 + 3*q2 + 3*x + q1*x + q2*x + q1*q2)

    for i in range(0,q1+1):
        for j in range(0, q2):
            A = n_p1 + j + 1 + i*(q2 + 1)
            B = A + 1
            C = A + (q2 +1)
            D = C + 1
            faces += [(C,D,B,A)]
        
        a = alpha + i
        b = N-(i+1)*(q2+1)
        c = b - q2-1
        d = a + 1           
        faces += [(a,b,c,d)]
        
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


def quad_prim_3(v0, v1, v2, v3, x = 0, q = 0):
    
    c00 = .67 * v0 + .33 * v1
    c01 = .33 * v0 + .67 * v1
    
    pole0 = .67 * (.5*v0 + .5*v3) + .33 * (.5*v1 + .5*v2) 
    pole1 = .33 * (.5*v0 + .5*v3) + .67 * (.5*v1 + .5*v2)
    
    verts = []
    
    for i in range(0, x+2):
        A = (i)/(x+1)
        B =  (x-i+1)/(x+1)  
        verts += [A*c00 + B*v0]
        
        vlow  = A*pole0 + B*v3
        vhigh = A*pole1 + B*v2
        
        for j in range(0, q + 2):
           
            C = (j)/(q+1)
            D =  (q-j+1)/(q+1)
            verts += [D*vlow + C*vhigh]

        verts += [A*c01 + B*v1]
    
            
    for m in range(0,q):
        E = (m+1)/(q+1)
        F =  (q-m)/(q+1)
        verts += [F*c01 + E*c00] 
        
        
    faces = []
    for i in range(0, x+1):
        for j in range(0,q+3):
            A =i*(q+4) + j
            B =(i+1)*(q+4) + j  #x + 3 to q+4
            faces += [(A, B, B+1, A+1)]
    N = 8 + 4*x + 3*q + x*q
    beta = (4+q)*(x+1)  #This is the corner of the last face
    sigma = (4+q)*(x+2)-1
    for c in range(0, q):
        a = sigma + c
        b = sigma - 2 - c
        faces += [(a, b+1, b, a+1)]
            
    faces += [(beta+2, beta +1, beta, N-1)]        
     
    return verts, faces

def quad_prim_4(v0, v1, v2, v3, x=0, y=0, q=0):
    
    c00 = .75 * v0 + .25 * v1
    c01 = .5 * v0 + .5 * v1
    c02 = .25 * v0 + .75 * v1
    c10 = .5*v1 + .5*v2
    
    pole0 = .4 * c00 + .6*(.25*v2 + .75*v3)
    pole1 = .6 * c02 + .4*(.75*v2 + .25*v3)
    cp01 = .5*pole0 + .5*pole1
    
    '''
    verts = [v0, c00, c01, c02, v1, c10, v2, v3, pole0, cp01, pole1]
    faces  = [(0,1,8,7),
              (1,2,9,8),
              (2,3,10,9),
              (3,4,5,10),
              (5,6,9,10),
              (8,9,6,7)]
    '''
    verts = []
    for i in range(0, x+2):
        A = (i)/(x+1)  #small to big  -> right side on my paper
        B =  (x-i+1)/(x+1)  #big to small  -> left side on my paper
        verts += [A*c00 + B*v0]
        
        vlow  = A*pole0 + B*v3
        vhigh = A*cp01 + B*v2
        
        for j in range(0, q + 2):
           
            C = (j)/(q+1)  #small to big - top vert component
            D =  (q-j+1)/(q+1)  #big to small - bottom vert component
            verts += [D*vlow + C*vhigh]
            
        vlow = vhigh
        vhigh = A*pole1 + B*c10
        
        for j in range(1, y + 2): #<---starts at 1 the, the top edge of last segment is the bottom edge here
            C = (j)/(y+1)  #small to big - top vert component
            D =  (y-j+1)/(y+1)  #big to small - bottom vert component
            verts += [D*vlow + C*vhigh]
    
        verts += [(B*v1 + A*c02)]
        
    #now add in blue region    
    for j in range(1, y + 2): #<---starts at 1 the, the top prev vert already added, however the middle vert has not
        C = (j)/(y+1)  #small to big - top vert component
        D =  (y-j+1)/(y+1)  #big to small - bottom vert component
        verts += [D*c02 + C*c01]

    for j in range(1, q + 1):  #don't need to add in bordres so these start at 1 and end at N-1
        C = (j)/(q+1)  #small to big - top vert component
        D =  (q-j+1)/(q+1)  #big to small - bottom vert component
        verts += [D*c01 + C*c00]

        
        
    faces = []
    for i in range(0, x+1):
        for j in range(0,q+y+5 -1):
            A =i*(q+ y + 5) + j
            B =(i+1)*(q+y+5) + j
            faces += [(A, B, B+1, A+1)]
    
    N = 11 + 5*x + 3*q + 3*y + q*x + x*y
    beta = (5+q+y)*(x+1)  #This is the corner of the last face to be added
    sigma = (5+q+y)*(x+2)-1  #this is the corner of the first face in the leftover segment
    for c in range(0, y+q+1):
        a = sigma + c
        b = sigma - 2 - c
        faces += [(a, b+1, b, a+1)]
            
    faces += [(beta+2, beta +1, beta, N-1)]
    
    
        
    return verts, faces


def pent_prim_0(v0, v1, v2, v3, v4):  #TODO!!!
    
    c0 = .5*v0 + .5*v1
    verts = [v0,c0,v1,v2,v3,v4]
    faces = [(0,1,4,5),(1,2,3,4)]
    
    return verts, faces
    
def pent_prim_1(v0, v1, v2, v3, v4, x=0, q4=0):
    pole0 = .5*v0 + .5*v1
    
    #verts = [v0,pole0,v1,v2,v3,v4]
    #faces = [(0,1,2,3),(0,3,4,5)]
    
    verts = []
    for i in range(0,q4+2):
        A = (i)/(q4+1)
        B =  (q4-i+1)/(q4+1) 
    
        verts += [B*v3 + A*v4]
        
        vlow  = B*v2 + A*v0
        vhigh = B*v1 + A*pole0
        
        for j in range(0,x+2):
            C = (j)/(x+1)
            D =  (x-j+1)/(x+1)
            
            verts+= [D*vlow + C*vhigh]
            
    faces = []
    N = 6 + 2*x + 3*q4 + x*q4
    for i in range(0, q4+1):
        for j in range(0,x+2):
            A =i*(x+3) + j
            B =(i + 1) * (x+3) + j
            faces += [(A, B, B+1, A+1)]
    
    return verts, faces



def quadrangulate_verts(c0,c1,c2,c3,x,y, x_off = 0, y_off = 0):
    
    verts = []
    
    for i in range(x_off,y+2):
        A= i/(y+1)
        B = 1- A
        
        for j in range(y_off,x+2):
            C = j/(x+1)
            D = 1-C
            v = B*D*c0 + A*D*c1 + A*C*c2 + B*C*c3
            verts += [v]

    return verts
        
def pent_prim_2(v0, v1, v2, v3, v4, x = 0, q0=0, q1 =0, q4 = 0):
    
    c00 = .75*v0 + .25*v1
    p0 = .5*v0 + .5*v1
    c01 = .25*v0 + .75*v1
    p1 = .75*p0 + .25*v3
    cp0 = .5*p1 + .5*v3
    
    V00 = quadrangulate_verts(v4, v0, cp0, v3, q4, q0)
    V01 = quadrangulate_verts(v3, cp0, v1, v2, q1, q0, y_off = 1)
    V10 = quadrangulate_verts(v0, c00, p1, cp0, q4, x, x_off = 1)
    V11 = quadrangulate_verts(cp0, p1, c01, v1, q1, x, x_off =1, y_off =1)
    
    verts= []
    #slice these lists together so the verts are coherent for making faces
    for i in range(0,q0+2):
        verts += chain(V00[i*(q4+2):i*(q4+2)+q4+2],V01[i*(q1+1):i*(q1+1)+q1+1])
        
    for i in range(0,x+1):
        verts += chain(V10[i*(q4+2):i*(q4+2)+q4+2], V11[i*(q1+1):i*(q1+1)+q1+1])
    
    
    #add in the bottom verts
    vs = quadrangulate_verts(p1, c00, p0, c01,q1,q4, x_off=1, y_off=1)
    verts += vs
    
    faces = []
    for i in range(0,x+q0+2):
        for j in range(0, q1+q4+2):
            A =i*(q1+q4+3) + j
            B =(i+1)*(q1+q4+3) + j
            faces += [(A, B, B+1, A+1)]
    
    #make the bottom faces
    alpha = (q0+x+2)*(q1+q4+3)
    n_p1 = alpha + q4 + 1 #index of the pole
    n_beta = n_p1 + q1+1
    N = (10 + 
         3*x   + 3*q0  + 4*q1  + 4*q4  + 
         q0*q1 + q1*x  + q1*q4 + q4*q0 + x*q4)
    print('Total verts %i' % N)
    print(alpha)
    for i in range(0,q4+1):
        for j in range(0,q1):
            A = n_p1 + j + 1 + i*(q1 + 1)
            B = A + 1
            C = A + (q1 +1)
            D = C + 1
            faces += [(C, D, B, A)]
    
        a = alpha + i
        b = N-(i+1)*(q1+1)
        c = b - q1-1
        d = a + 1
        faces += [(a,b,c,d)]
              
    

    return verts, faces

def pent_prim_3(v0, v1, v2, v3, v4,x=4,y=0,q1=0,q4=0):
    
    c00 = .8*v0 + .2*v1
    c01 = .6*v0 + .4*v1
    c02 = .4*v0 + .6*v1
    c03 = .2*v0 + .8*v1
    
    c10 = .5*v1 + .5*v2
    
    p0 = .6*c00 + .4*(.5*v3 + .5*v4)
    cp0 = .35 * c01 + .65*v3
    cp1 = .65 * (.33*v2 + .67*v3) + .35*c02
    p1 = .7 * c03 + .3*(.67*v2 + .33*v3)
    
    
    V00 = quadrangulate_verts(v0, c00, p0, v4, 0,  x,y_off = 0)
    V01 = quadrangulate_verts(v4, p0, cp0, v3, q4, x,y_off = 1)
    V02 = quadrangulate_verts(v3, cp0,cp1, v2, q1, x,y_off = 1)
    V03 = quadrangulate_verts(v2, cp1, p1, c10, y,  x, y_off = 1)
    V04 = quadrangulate_verts(c10, p1, c03, v1, 0,  x, y_off = 1)
    
    verts = []
    for i in range(0,x+2):
        verts += chain(V00[i*2:i*2 + 2],
                       V01[i*(q4+1):i*(q4+1)+q4+1],
                       V02[i*(q1+1):i*(q1+1)+q1+1],
                       V03[i*(y+1):i*(y+1)+y+1],
                       V04[i:i+1])

    V10 = quadrangulate_verts(p1, cp1, c02, c03, 0, y, x_off=1, y_off=1)
    V11 = quadrangulate_verts(cp1, cp0, c01, c02, 0, q1, x_off=1, y_off=1)
    V12 = quadrangulate_verts(cp0, p0, c00, c01, 0, q4, x_off=1, y_off=1)
    V12.pop()  #duplicate of the corner where it meets.
    
    verts += V10 + V11 + V12
    faces = []
    for i in range(0,x+1):
        for j in range(0, 5+q4+q1+y):
            A =i*(6+q4+q1+y) + j
            B =(i+1)*(6+q4+q1+y) + j
            faces += [(A, B, B+1, A+1)]
    
    alpha = (x+2)*(6+q4+q1+y)-1
    sigma = (x+1)*(6+q4+q1+y)
    print((alpha, sigma))
    
    N = 14 + 6*x + 3*q4 + 3*q1 + 3*y + x*(q4 + q1+y)
    print(N)
    for i in range(0,2+q4+q1+y):
        a = alpha - i- 2
        b = alpha +1 + i
        c = b-1
        d = a + 1
        faces += [(a,b,c,d)]
    
    faces += [(sigma + 2, sigma + 1, sigma, N-1)]  
    #verts = [v0,c00,c01,c02,c03,v1,c10,v2,v3,v4, pole0, cp0, cp1, pole1]
    #faces = [(0,1,10,9), (1,2,11,10),(2,3,12,11),(3,4,13,12),
    #         (4,5,6,13),(6,7,12,13),(7,8,11,12),(8,9,10,11)]
    return verts, faces
    
    
def hex_prim_0(v0, v1, v2, v3, v4,v5):  #TDOD!!
    
    verts = [v0,v1,v2,v3,v4,v5]
    faces = [(0,1,2,5), (2,3,4,5)]
    
    return verts, faces

def hex_prim_1(v0, v1, v2, v3, v4,v5, x=0, y=0, z=0, w=0):

    c0 = .5*v0  +.5*v1
    c1 = .5*v1 + .5*v2
    cp0 = .18*(v3 + v4 + v5) + .1533*(v0 + v1 + v2)
    p0 = .33*c0 + .33 * c1 + .34 * cp0
    #verts = [v0, c0, v1, c1, v2, v3, v4, v5, cp0, pole1]
    #faces = [(0,1,9,8),
    #         (1,2,3,9),
    #         (3,4,8,9),
    #         (4,5,6,8),
    #         (6,7,0,8)]
    
    V00 = quadrangulate_verts(v5, v0, cp0, v4, z, w)
    V01 = quadrangulate_verts(v4, cp0, v2, v3, y, w, y_off = 1)
    V10 = quadrangulate_verts(v0, c0, p0, cp0, z, x, x_off = 1)
    V11 = quadrangulate_verts(cp0, p0, c1, v2, y, x, x_off =1, y_off =1)
    
    verts= []
    #slice these lists together so the verts are coherent for making faces
    for i in range(0,w+2):
        verts += chain(V00[i*(z+2):i*(z+2)+z+2],V01[i*(y+1):i*(y+1)+y+1])
        
    for i in range(0,x+1):
        verts += chain(V10[i*(z+2):i*(z+2)+z+2], V11[i*(y+1):i*(y+1)+y+1])
    
    
    #add in the bottom verts 
    vs = quadrangulate_verts(p0, c0, v1, c1,y,z, x_off=1, y_off=1)
    verts += vs
    
    faces = []
    for i in range(0,x+w+2):
        for j in range(0, y+z+2):
            A =i*(y+z+3) + j
            B =(i+1)*(y+z+3) + j
            faces += [(A, B, B+1, A+1)]
    
    #make the bottom faces
    alpha = (w+x+2)*(y+z+3)
    n_p1 = alpha + z + 1 #index of the pole
    n_beta = n_p1 + y+1
    N = (10 + 
         3*x   + 3*w  + 4*y  + 4*z  + 
         w*y + y*x  + y*z + z*w + x*z)
    print('Total verts %i' % N)
    print(alpha)
    for i in range(0,z+1):
        for j in range(0,y):
            A = n_p1 + j + 1 + i*(y + 1)
            B = A + 1
            C = A + (y +1)
            D = C + 1
            faces += [(C, D, B, A)]
    
        a = alpha + i
        b = N-(i+1)*(y+1)
        c = b - y-1
        d = a + 1
        faces += [(a,b,c,d)]
    
    
    return verts, faces

def hex_prim_2(v0, v1, v2, v3, v4, v5, x=0, y=0, q3=0, q0=0):

    c00 = .67*v0 + .33 * v1
    c01 = .33*v0 + .67*v1
    
    cp0 = .8 * (.65 * v5 + .35*v2) + .2 * (.8*v4 + .2*v3)
    cp1 = .8 * (.35 * v5 + .65*v2) + .2 * (.2*v4 + .8*v3)
    
    p0 = .5 * (.5*c00 + .5*c01) + .5*cp0
    p1 = .5 * (.5*c00 + .5*c01) + .5*cp1
    
    #verts = [v0, c00, c01, v1, v2, v3, v4, v5, cp0, cp1, p0, p1]
    #faces = [(0,1,10,8),
    #         (1,2,11,10),
    #         (2,3,9,11),
    #         (3,4,5,9),
    #         (5,6,8,9),
    #         (6,7,0,8),
    #         (8,10,11,9)]
    
    
    verts = []
    V00 = quadrangulate_verts(v5, v0, cp0, v4, q3, q0, x_off = 0, y_off = 0)
    V01 = quadrangulate_verts(v4, cp0, cp1, v3, y, q0, x_off = 0, y_off = 1)
    V02 = quadrangulate_verts(v3, cp1, v1, v2, q3, q0, x_off = 0, y_off = 1)
    V10 = quadrangulate_verts(v0, c00, p0, cp0, q3, x, x_off = 1, y_off = 0)
    V11 = quadrangulate_verts(cp0, p0, p1, cp1, y, x, x_off = 1, y_off = 1)
    V12 = quadrangulate_verts(cp1, p1, c01, v1, q3, x, x_off = 1, y_off = 1)
    
    for i in range(0,q0+2):
        verts += chain(V00[i*(q3+2):i*(q3+2)+q3+2],V01[i*(y+1):i*(y+1)+y+1], V02[i*(q3+1):i*(q3+1)+q3+1])
        
    for i in range(0,x+1):
        verts += chain(V10[i*(q3+2):i*(q3+2)+q3+2],V11[i*(y+1):i*(y+1)+y+1], V12[i*(q3+1):i*(q3+1)+q3+1])
    
    #fill in q3/y patch
    V20 = quadrangulate_verts(p1, p0, c00, c01, q3, y, x_off = 1, y_off = 1)

    verts += V20[0:len(V20) - (q3 +1)]
    faces = []
    for i in range(0,x+q0+2):
        for j in range(0, 2*q3+y+3):
            A =i*(2*q3+y+4) + j
            B =(i+1)*(2*q3+y+4) + j
            faces += [(A, B, B+1, A+1)]
    
    n_p1 = (q0 + x + 3) * (2*q3 + y + 4) - (q3 + 1)        
    for i in range(0, y):
        for j in range(0, q3):
            A = n_p1  + i*(q3+1) + j
            B = n_p1  + (i+1)*(q3+1) + j
            faces += [(A, B, B+1, A+1)]
    
    #strip  c00 to p0
    n_c00 = (q0 + x + 2) * (2*q3 + y + 4)
    N = (q0 + x + 3) * (2*q3 + y + 4) + (q3 + 1)*(y)
    for i in range(0, q3):
        a = n_c00 + i
        b = N - i-1
        c = N - 1 - (i+1)
        d = a + 1
        faces += [(a,b,c,d)]
    
    #strip p1 to p0    
    for i in range(0, y):
        a = n_p1 -1 - i
        b = n_p1 + i*(q3+1)
        c = n_p1 + (i+1)*(q3+1)
        d = a -1
        faces += [(a,d,c,b)]
            
    #final quad at p0
    n_p0 = n_c00 + q3 + 1
    a = n_p0
    b = n_p0-1
    c = N - 1 - q3
    d = n_p0 + 1

    faces += [(a,b,c,d)]
    
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