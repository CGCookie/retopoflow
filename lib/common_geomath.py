'''
Created on Jan 31, 2016

@author: Patrick
'''

import math
import time
import random
import numpy as np

from mathutils import Vector, Quaternion, Matrix
from mathutils.geometry import intersect_point_line, intersect_line_plane


def generic_axes_from_plane_normal(p_pt, no):
    '''
    will take a point on a plane and normal vector
    and return two orthogonal vectors which create
    a right handed coordinate system with z axist aligned
    to plane normal
    '''
    
    #get the equation of a plane ax + by + cz = D
    #Given point P, normal N ...any point R in plane satisfies
    # Nx * (Rx - Px) + Ny * (Ry - Py) + Nz * (Rz - Pz) = 0
    #now pick any xy, yz or xz and solve for the other point
    
    a = no[0]
    b = no[1]
    c = no[2]
    
    Px = p_pt[0]
    Py = p_pt[1]
    Pz = p_pt[2]
    
    D = a * Px + b * Py + c * Pz
    
    #generate a randomply perturbed R from the known p_pt
    R = p_pt + Vector((random.random(), random.random(), random.random()))
    
    #z = D/c - a/c * x - b/c * y
    if c != 0:
        Rz =  D/c - a/c * R[0] - b/c * R[1]
        R[2] = Rz
       
    #y = D/b - a/b * x - c/b * z 
    elif b!= 0:
        Ry = D/b - a/b * R[0] - c/b * R[2] 
        R[1] = Ry
    #x = D/a - b/a * y - c/a * z
    elif a != 0:
        Rx = D/a - b/a * R[1] - c/a * R[2]
        R[0] = Rz
    else:
        print('undefined plane you wanker!')
        return(False)
    
    #now R represents some other point in the plane
    #we will use this to define an arbitrary local
    #x' y' and z'
    X_prime = R - p_pt
    X_prime.normalize()
    
    Y_prime = no.cross(X_prime)
    Y_prime.normalize()
    
    return (X_prime, Y_prime)       
        
def fit_line_to_points3D(pts):
    
    #modified from stack exchange
    #http://stackoverflow.com/questions/2298390/fitting-a-line-in-3d
        
    #x = [pt[0] for pt in pts]
    #y = [pt[1] for pt in pts]
    #z = [pt[2] for pt in pts]

    data = np.array(pts)


    # Calculate the mean of the points, i.e. the 'center' of the cloud
    datamean = data.mean(axis=0)

    # Do an SVD on the mean-centered data.
    uu, dd, vv = np.linalg.svd(data - datamean)

    # Now vv[0] contains the first principal component, i.e. the direction
    # vector of the 'best fit' line in the least squares sense.
    quality = dd[0]**2 / (dd[1]**2 + dd[2]**2)
    
    return (datamean, vv[0], quality)
    
    

def fit_circle_to_points3D(pts, ppt, no):
    '''
    #assumes the points are relatively planaer to pt and no
    
    fits a line first, if line fits really well
    addapted from here
    '''
    
    center, slope, qual = fit_line_to_points3D(pts)
    
    print('quality of line fit %f' % qual)
    if qual > 75:
        print('qual seems like its a line %f' % qual)
        return (center, center[0], center[1], -1)
    
    
    (X_prime, Y_prime) = generic_axes_from_plane_normal(ppt, no)
    
    
    xs = []
    ys = []
    for v in pts:
        v_trans = v - ppt
        xs += [v_trans.dot(X_prime)]
        ys += [v_trans.dot(Y_prime)]
    
    x = np.array(xs)
    y = np.array(ys)
    
    # coordinates of the barycenter
    x_m = np.mean(x)
    y_m = np.mean(y)
    
    # calculation of the reduced coordinates
    u = x - x_m
    v = y - y_m
    
    # linear system defining the center (uc, vc) in reduced coordinates:
    #    Suu * uc +  Suv * vc = (Suuu + Suvv)/2
    #    Suv * uc +  Svv * vc = (Suuv + Svvv)/2
    Suv  = np.sum(u*v)
    Suu  = np.sum(u**2)
    Svv  = np.sum(v**2)
    Suuv = np.sum(u**2 * v)
    Suvv = np.sum(u * v**2)
    Suuu = np.sum(u**3)
    Svvv = np.sum(v**3)
    
    # Solving the linear system
    A = np.array([ [ Suu, Suv ], [Suv, Svv]])
    B = np.array([ Suuu + Suvv, Svvv + Suuv ])/2.0
    uc, vc = np.linalg.solve(A, B)
    
    xc_1 = x_m + uc
    yc_1 = y_m + vc
    
    # Calcul des distances au centre (xc_1, yc_1)
    Ri_1     = np.sqrt((x-xc_1)**2 + (y-yc_1)**2)
    R_1      = np.mean(Ri_1)
    residu_1 = sum((Ri_1-R_1)**2)
    
    print(xc_1)
    print(yc_1)
    print(X_prime)
    print(Y_prime)
    print(ppt)
    wrld_pt = ppt + X_prime*xc_1 + Y_prime*yc_1
    return (wrld_pt, xc_1, yc_1, R_1)