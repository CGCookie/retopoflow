'''
Copyright (C) 2018 CG Cookie
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

import bgl
import bpy
import math
from mathutils import Vector, Matrix
from mathutils.geometry import intersect_line_line_2d
from .rftool import RFTool
from ..common.debug import dprint
from ..common.maths import Point,Point2D,Vec2D,Vec, Normal, clamp
from ..common.bezier import CubicBezierSpline, CubicBezier
from ..common.utils import iter_pairs

from ..ext.icp import best_fit_transform
import numpy as np


def process_stroke_filter(stroke, min_distance=1.0, max_distance=2.0):
    ''' filter stroke to pts that are at least min_distance apart '''
    nstroke = stroke[:1]
    for p in stroke[1:]:
        v = p - nstroke[-1]
        l = v.length
        if l < min_distance: continue
        d = v / l
        while l > 0:
            q = nstroke[-1] + d * min(l, max_distance)
            nstroke.append(q)
            l -= max_distance
    return nstroke


def process_stroke_source(stroke, raycast, Point_to_Point2D=None, is_point_on_mirrored_side=None, mirror_point=None, clamp_point_to_symmetry=None):
    ''' filter out pts that don't hit source on non-mirrored side '''
    pts = [(pt, raycast(pt)[0]) for pt in stroke]
    pts = [(pt, p3d) for (pt, p3d) in pts if p3d]
    if Point_to_Point2D and mirror_point:
        pts_ = [Point_to_Point2D(mirror_point(p3d)) for (_, p3d) in pts]
        pts = [(pt, raycast(pt)[0]) for pt in pts_]
        pts = [(pt, p3d) for (pt, p3d) in pts if p3d]
    if Point_to_Point2D and clamp_point_to_symmetry:
        pts_ = [Point_to_Point2D(clamp_point_to_symmetry(p3d)) for (_, p3d) in pts]
        pts = [(pt, raycast(pt)[0]) for pt in pts_]
        pts = [(pt, p3d) for (pt, p3d) in pts if p3d]
    if is_point_on_mirrored_side:
        pts = [(pt, p3d) for (pt, p3d) in pts if not is_point_on_mirrored_side(p3d)]
    return [pt for (pt, _) in pts]

def scale_match(A, B):
    Avecs,Ascale = scale(A)
    Bvecs,Bscale = scale(B)
    v0,v1 = Avecs
    as0,as1 = Ascale
    bs0,bs1 = Bscale
    avg = Point2D.average(A)
    s0 = 1.0 # bs0 / as0
    s1 = bs1 / as1
    def move(v):
        nonlocal avg, v0, v1, s0, s1
        v_avg = v - avg
        return avg + v0 * (v0.dot(v_avg) * s0) + v1 * (v1.dot(v_avg) * s1)
    return move

def icp(A, B, fn_nearestneighbor, max_iterations=20, tolerance=0.001):
    '''
    XXX: OLD COMMENTS
    The Iterative Closest Point method: finds best-fit transform that maps points A on to points B
    Input:
        A: Nxm numpy array of source mD points
        B: Nxm numpy array of destination mD point
        init_pose: (m+1)x(m+1) homogeneous transformation
        max_iterations: exit algorithm after max_iterations
        tolerance: convergence criteria
    Output:
        T: final homogeneous transformation that maps A on to B
        distances: Euclidean distances (errors) of the nearest neighbor
        i: number of iterations to converge
    '''

    origA = A
    n = len(A)
    fn_move = scale_match(A, B)
    A = [fn_move(a) for a in A]

    orig = np.ones((2, len(A)))
    src = np.ones((3, len(A)))
    dst = np.ones((3, len(A)))
    for i,a in enumerate(A):
        orig[:,i] = a
        src[:2,i] = a
    distances = np.zeros((1, len(A)))

    prev_error = 0

    for iteration in range(max_iterations):
        for i in range(n):
            a = Point2D((src[0][i], src[1][i]))
            b = fn_nearestneighbor(a)
            dst[:2,i] = b
            distances[0,i] = (a - b).length

        # compute the transformation between src and nearest dst points
        T,R,t = best_fit_transform(src[:2,:].T, dst[:2,:].T)

        # update src
        src = np.dot(T, src)

        # check error
        mean_error = np.mean(distances)
        if np.abs(prev_error - mean_error) < tolerance:
            break
        prev_error = mean_error

    # calculate final transformation
    T,_,_ = best_fit_transform(orig[:2,:].T, src[:2,:].T)
    newA = [Point2D(src[:2,i].T) for i in range(n)]
    fn_move = scale_match(origA, newA)
    def move(v):
        nonlocal T, fn_move
        a = fn_move(v)  # rescale
        b = Point2D((T[0][0] * a.x + T[0][1] * a.y + T[0][2], T[1][0] * a.x + T[1][1] * a.y + T[1][2]))
        return b
    return move

def scale(vs):
    # make numpy array of points
    all_samples = np.array(vs).T
    # compute covariance matrix
    cov_mat = np.cov([all_samples[0,:], all_samples[1,:]])
    # compute eigenvectors and corresponding eigenvalues
    eig_val_cov, eig_vec_cov = np.linalg.eig(cov_mat)
    eigvecs = [Vec2D(eig_vec_cov[:,i].reshape(1,2).T) for i in range(2)]
    # compute scaling factors
    avg = Point2D.average(vs)
    scalings = [
        (max(eigvec.dot(v) for v in vs) - min(eigvec.dot(v) for v in vs))
        for eigvec in eigvecs
    ]
    return (eigvecs, scalings)

# https://sebastianraschka.com/Articles/2014_pca_step_by_step.html
def pca(vs):
    print('PCA', len(vs))
    # make numpy array of points
    all_samples = np.array(vs).T
    # compute mean vector
    mean_x = np.mean(all_samples[0,:])
    mean_y = np.mean(all_samples[1,:])
    mean_vector = np.array([[mean_x],[mean_y]])
    # compute scatter matrix
    scatter_matrix = np.zeros((2,2))
    for i in range(all_samples.shape[1]):
        scatter_matrix += (all_samples[:,i].reshape(2,1) - mean_vector).dot((all_samples[:,i].reshape(2,1) - mean_vector).T)
    # compute covariance matrix
    cov_mat = np.cov([all_samples[0,:], all_samples[1,:]])
    # compute eigenvectors and corresponding eigenvalues
    eig_val_sc, eig_vec_sc = np.linalg.eig(scatter_matrix)
    eig_val_cov, eig_vec_cov = np.linalg.eig(cov_mat)
    eigvecs,eigvals,eigcovvals,scale = [],[],[],[]
    for i in range(len(eig_val_sc)):
        eigvec_sc = eig_vec_sc[:,i].reshape(1,2).T
        eigvec_cov = eig_vec_cov[:,i].reshape(1,2).T
        assert eigvec_sc.all() == eigvec_cov.all()
        eigvecs.append(Vec2D(eigvec_sc))
        eigvals.append(eig_val_sc[i])
        eigcovvals.append(eig_val_cov[i])
        scale.append(eig_val_sc[i] / eig_val_cov[i])
        print(eigvecs[-1], eigvals[-1], eigcovvals[-1], scale[-1])
