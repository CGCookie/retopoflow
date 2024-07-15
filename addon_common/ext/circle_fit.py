"""
The MIT License (MIT)

Copyright (c) 2022 Michael Klear

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.


see:
- https://pypi.org/project/circle-fit/
- https://github.com/AlliedToasters/circle-fit
"""

"""
A collection of circle fitting algorithms.

Some are based on MATLAB implementations by Nikolai Chernov:
https://people.cas.uab.edu/~mosya/cl/MATLABcircle.html

Implemented algorithms:

hyperLSQ()      : Least squares circle fit with "hyperaccuracy" by Kenichi Kanatani, Prasanna Rangarajan
standardLSQ()   : Least squares circle fit
riemannSWFLa()  : Riemann circle fit, SWFL version A
lm()            : Levenberg-Marquardt in the full (a,b,R) parameter space
prattSVD()      : Algebraic circle fit by V. Pratt
taubinSVD()     : Algebraic circle fit by G. Taubin
hyperSVD()      : Algebraic circle fit with "hyperaccuracy"
kmh()           : Consistent circle fit by A. Kukush, I. Markovsky, S. Van Huffel

"""
from itertools import combinations
from typing import Union, List, Tuple

import numpy as np
import numpy.typing as npt
# from scipy import optimize  # type: ignore[import]
# from scipy.linalg import svd  # type: ignore[import]


def convert_input(coords: Union[npt.NDArray, List]) -> Tuple[npt.NDArray, ...]:
    """
    Converts the input coordinates from a 2D List or 2D np.ndarray to 2 separate 1D np.ndarrays.

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.

    Returns
    -------
    x   : np.ndarray. X point coordinates.
    y   : np.ndarray. Y point coordinates.
    """
    if isinstance(coords, np.ndarray):
        assert coords.ndim == 2, "'coords' must be a (n, 2) array"
        assert coords.shape[1] == 2, "'coords' must be a (n, 2) array"
        x = coords[:, 0]
        y = coords[:, 1]
    elif isinstance(coords, list):
        x = np.array([point[0] for point in coords])
        y = np.array([point[1] for point in coords])
    else:
        raise Exception("Parameter 'coords' is an unsupported type: " + str(type(coords)))
    return x, y


def center_data(x: npt.NDArray, y: npt.NDArray) -> Tuple[npt.NDArray, ...]:
    """
    Computes the centroid of points (x, y) and subtracts the centroid from the points to center them.
    Parameters
    ----------
    x   : np.ndarray. X point coordinates.
    y   : np.ndarray. Y point coordinates.

    Returns
    -------
    xc      : np.ndarray. x points centered on the computed centroid.
    yc      : np.ndarray. y points centered on the computed centroid.
    centroid: np.ndarray. [x, y] centers.
    """
    centroid = np.array([x.mean(), y.mean()])
    xc = x - centroid[0]
    yc = y - centroid[1]
    return xc, yc, centroid


def mldivide(A: npt.NDArray, b: npt.NDArray) -> npt.NDArray:
    num_vars = A.shape[1]
    rank = np.linalg.matrix_rank(A)
    if rank == num_vars:
        sol: npt.NDArray = np.linalg.lstsq(A, b, rcond=None)[0]  # not under-determined
    else:
        sol = np.zeros((num_vars, 1))
        for nz in combinations(range(num_vars), rank):  # the variables not set to zero
            sol[nz, :] = np.asarray(np.linalg.solve(A[:, nz], b))
    return sol


def calc_R(x: npt.NDArray, y: npt.NDArray, xc: float, yc: float) -> npt.NDArray:
    """
    Calculate the distance of each 2D point (x, y) from the center (xc, yc)
    Parameters
    ----------
    x   : np.ndarray. X point coordinates.
    y   : np.ndarray. Y point coordinates.
    xc  : float. Center X coordinate.
    yc  : float. Center Y coordinate.

    Returns
    -------
    distances : np.ndarray. Distances from (xc, yc) to (x, y).
    """
    return np.sqrt((x - xc) ** 2 + (y - yc) ** 2)


def lsq_fun(c: npt.NDArray, x: npt.NDArray, y: npt.NDArray) -> npt.NDArray:
    """
    Calculate the mean algebraic distance between the 2D points (x, y)  and the circle centered at (xc, yc)
    ----------
    c  : np.ndarray. Center coordinates.
    x   : np.ndarray. X point coordinates.
    y   : np.ndarray. Y point coordinates.

    Returns
    -------
    distance : float. Mean distance from (xc, yc) to (x, y).
    """
    Ri = calc_R(x, y, c[0], c[1])
    mean: float = Ri.mean()
    return Ri - mean


def sigma(x: npt.NDArray, y: npt.NDArray, xc: float, yc: float, r: float) -> float:
    """
    Computes the sigma (RMS error) of a circle fit (xc, yc, r) to a set of 2D points (x, y).
    ----------
    x   : np.ndarray. X point coordinates.
    y   : np.ndarray. Y point coordinates.
    xc  : float. Circle center X coordinate.
    yc  : float. Circle center Y coordinate.
    r   : float. Circle radius.

    Returns
    -------
    sigma : float. Root Mean Square of error (distance) between points (x, y) and circle (xc, yc, r).
    """
    dx = x - xc
    dy = y - yc
    s: float = np.sqrt(np.mean((np.sqrt(dx ** 2 + dy ** 2) - r) ** 2))
    return s


def riemannSWFLa(coords: Union[npt.NDArray, List]) -> Tuple[float, ...]:
    """
    Based on original MATLAB code by Nikolai Chernov: https://people.cas.uab.edu/~mosya/cl/RiemannSWFL.m.

    Riemann circle fit, the SWFL version A. Strandlie, J. Wroldsen, R. Fruhwirth, and B. Lillekjendlie,
    "Particle tracks fitted on the Riemann sphere",
    Computer Physics Commun., Vol. 131, pp. 95-108,  (2000)

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """

    from scipy.linalg import svd  # type: ignore[import]

    x, y = convert_input(coords)
    X, Y, centroid = center_data(x, y)
    Z = X * X + Y * Y
    factor = 2 * np.sqrt(np.mean(Z))
    X /= factor
    Y /= factor
    Z /= factor ** 2
    Zp = Z + 1
    Zm = Z - 1
    Zpt = Zp.transpose()
    Zpp = np.matmul(Zpt, Zp)
    Zpm = np.matmul(Zpt, Zm)
    ZpX = np.matmul(Zpt, X)
    ZpY = np.matmul(Zpt, Y)
    A1 = (Zm * Zpp - Zp * Zpm) / 2
    A2 = X * Zpp - Zp * ZpX
    A3 = Y * Zpp - Zp * ZpY
    AAA = np.array([A1, A2, A3]).transpose()
    U, S, V = svd(AAA, full_matrices=False)
    V = V.transpose()
    P = V[:, 2]
    Q = -2 * (P[0] * Zpm / 2 + P[1] * ZpX + P[2] * ZpY) / Zpp
    A = (P[0] + Q) / 2
    D = (Q - P[0]) / 2

    c = factor * (-P[1:3] / A / 2) + centroid
    xc = c[0]
    yc = c[1]
    r = factor * (np.sqrt(np.matmul(P[1:3].transpose(), P[1:3]) - 4 * A * D) / 2 / np.abs(A))
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def lm(coords: Union[npt.NDArray, List], par_ini: npt.NDArray, iter_max: int = 50, lambda_ini: float = 1,
       epsilon: float = 0.00001) -> Tuple[float, ...]:
    """
    Based on original MATLAB code by Nikolai Chernov: https://people.cas.uab.edu/~mosya/cl/LM.m.

    Geometric circle fit (minimizing orthogonal distances) based on the standard Levenberg-Marquardt scheme in the full
    (a,b,R) parameter space. This is perhaps the best geometric circle fit.

    Parameters
    ----------
    coords      : 2D List or 2D np.ndarray of shape (n,2). x,Y point coordinates.
    par_ini     : 1D np.ndarray. Array of [xc, yc, r] initial guess.
    iter_max    : Optional int. Maximum number of iterations for the iterative fitting algorithm.
    lambda_ini  : Optional float. Initial value of the correction factor lambda.
    epsilon     : Optional float. Iteration stops when the improvement becomes less than this value.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """
    x, y = convert_input(coords)

    def iterate(par: npt.NDArray, _x: npt.NDArray, _y: npt.NDArray) -> Tuple[npt.NDArray, npt.NDArray, float]:
        Dx = _x - par[0]
        Dy = _y - par[1]
        D = np.sqrt(Dx ** 2 + Dy ** 2)
        _j = np.array([-Dx / D, -Dy / D, -np.ones(len(x))]).transpose()
        _g: npt.NDArray = D - par[2]
        _f = float(np.linalg.norm(_g) ** 2)
        return _j, _g, _f

    lambda_sqrt = np.sqrt(lambda_ini)
    Par = par_ini

    J, g, F = iterate(Par, x, y)

    for i in np.arange(iter_max):
        while True:
            DelPar = mldivide(np.vstack((J, lambda_sqrt * np.identity(3))), np.hstack([g, np.zeros(3)]))
            progress = np.linalg.norm(DelPar) / (np.linalg.norm(Par) + epsilon)
            ParTemp = Par - DelPar.transpose()
            JTemp, gTemp, FTemp = iterate(ParTemp, x, y)
            if progress < epsilon:
                break

            if FTemp < F and ParTemp[2] > 0:
                lambda_sqrt /= 2
                break
            else:
                lambda_sqrt *= 2
        if progress < epsilon:
            break
        Par = ParTemp
        J = JTemp
        g = gTemp
        F = FTemp

    xc = Par[0]
    yc = Par[1]
    r = Par[2]
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def prattSVD(coords: Union[npt.NDArray, List]) -> Tuple[float, ...]:
    """
    Based on original MATLAB code by Nikolai Chernov: https://people.cas.uab.edu/~mosya/cl/PrattSVD.m.

    Algebraic circle fit by Pratt
    V. Pratt, "Direct least-squares fitting of algebraic surfaces",
    Computer Graphics, Vol. 21, pages 145-152 (1987)

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """

    from scipy.linalg import svd  # type: ignore[import]

    x, y = convert_input(coords)
    X, Y, centroid = center_data(x, y)
    Z = X * X + Y * Y
    ZXY1 = np.array([Z, X, Y, np.ones(len(Z))]).transpose()
    U, S, V = svd(ZXY1, full_matrices=False)
    S = np.diag(S)
    V = V.transpose()
    if S[3, 3] / S[0, 0] < 1e-12:  # singular case
        A = V[:, 3]
    else:
        W = np.matmul(V, S)
        Binv = np.array([[0, 0, 0, -0.5], [0, 1, 0, 0], [0, 0, 1, 0], [-0.5, 0, 0, 0]])
        D, E = np.linalg.eig(np.matmul(np.matmul(np.transpose(W), Binv), W))
        sorter = np.argsort(D)
        A = E[:, sorter[1]]
        for i in range(4):
            S[i, i] = 1 / S[i, i]
        A = np.matmul(np.matmul(V, S), A)
    c = -(A[1:3]).transpose() / A[0] / 2 + centroid
    xc = c[0]
    yc = c[1]
    r = np.sqrt(A[1] ** 2 + A[2] ** 2 - 4 * A[0] * A[3]) / abs(A[0]) / 2
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def kmh(coords: Union[npt.NDArray, List], iter_max: int = 99, epsilon: float = 1E-9) -> Tuple[float, ...]:
    """
    Based on original MATLAB code by Nikolai Chernov: https://people.cas.uab.edu/~mosya/cl/KMvH.m.

    Consistent circle fit (Kukush-Markovsky-van Huffel)
    A. Kukush, I. Markovsky, S. Van Huffel,
    "Consistent estimation in an implicit quadratic measurement error model",
    Comput. Statist. Data Anal., Vol. 47, pp. 123-147, (2004)

    Parameters
    ----------
    coords      : 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.
    iter_max    : Optional int. Maximum number of iterations for the iterative fitting algorithm.
    epsilon     : Optional float. Iteration stops when the improvement becomes less than this value.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """
    assert iter_max > 0
    x, y = convert_input(coords)

    Z = x * x + y * y
    n = len(Z)
    ZXY1 = np.array([Z, x, y, np.ones(n)]).transpose()
    M0 = np.matmul(ZXY1.transpose(), ZXY1)
    M1 = np.array([[8 * M0[0, 3], 4 * M0[1, 3], 4 * M0[2, 3], 2 * n], [4 * M0[1, 3], n, 0, 0], [4 * M0[2, 3], 0, n, 0],
                   [2 * n, 0, 0, 0]])
    M2 = np.array([[8 * n, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]])

    Vmin = 0
    X, Y, centroid = center_data(x, y)
    XYcent = np.array([X, Y]).transpose()
    scatter = np.matmul(XYcent.transpose(), XYcent)
    D, _ = np.linalg.eig(scatter)
    Vmax = min(D)
    _epsilon = epsilon * Vmax

    def eval():
        V = (Vmin + Vmax) / 2
        M = M0 - V * (M1 - V * M2)
        Eval, Evec = np.linalg.eig(M)
        return Eval, Evec, V

    for i in range(iter_max):
        Eval, Evec, V = eval()
        if np.min(Eval) > 0:
            Vmin = V
        else:
            Vmax = V
        if Vmax - Vmin <= _epsilon:
            break

    min_idx = np.argmin(Eval)
    Evecmin = Evec[:, min_idx]
    P = Evecmin[1:4] / Evecmin[0]
    xc = -P[0] / 2
    yc = -P[1] / 2
    r: float = np.mean(calc_R(x, y, xc, yc))
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def taubinSVD(coords: Union[npt.NDArray, List]) -> Tuple[float, ...]:
    """
    Based on original MATLAB code by Nikolai Chernov: https://people.cas.uab.edu/~mosya/cl/TaubinSVD.m.

    Algebraic circle fit by Taubin
    G. Taubin, "Estimation Of Planar Curves, Surfaces And Nonplanar Space Curves Defined By Implicit Equations, With
                  Applications To Edge And Range Image Segmentation",
    IEEE Trans. PAMI, Vol. 13, pages 1115-1138, (1991)

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """

    from scipy.linalg import svd  # type: ignore[import]

    x, y = convert_input(coords)
    X, Y, centroid = center_data(x, y)
    Z = X * X + Y * Y
    Zmean = np.mean(Z)
    Z0 = (Z - Zmean) / (2 * np.sqrt(Zmean))
    ZXY = np.array([Z0, X, Y]).transpose()
    U, S, V = svd(ZXY, full_matrices=False)
    V = V.transpose()
    A = V[:, 2]
    A[0] /= 2 * np.sqrt(Zmean)
    A = np.hstack((A, -Zmean * A[0]))

    c = -(A[1:3]).transpose() / A[0] / 2 + centroid
    xc = c[0]
    yc = c[1]
    r = np.sqrt(A[1] * A[1] + A[2] * A[2] - 4 * A[0] * A[3]) / abs(A[0]) / 2
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def hyperSVD(coords: Union[npt.NDArray, List]) -> Tuple[float, ...]:
    """
    Based on original MATLAB code by Nikolai Chernov: https://people.cas.uab.edu/~mosya/cl/HyperSVD.m.

    Algebraic circle fit with "hyperaccuracy" (with zero essential bias).

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """

    from scipy.linalg import svd  # type: ignore[import]

    x, y = convert_input(coords)
    X, Y, centroid = center_data(x, y)
    Z = X * X + Y * Y
    ZXY1 = np.array([Z, X, Y, np.ones(len(Z))]).transpose()
    U, S, V = svd(ZXY1, full_matrices=False)
    V = V.transpose()
    S = np.diag(S)
    if (S[3, 3] / S[0, 0] < 1e-12):  # singular case
        A = V[:, 3]
    else:
        R = np.mean(ZXY1, axis=0)
        N = np.array([[8 * R[0], 4 * R[1], 4 * R[2], 2], [4 * R[1], 1, 0, 0], [4 * R[2], 0, 1, 0], [2, 0, 0, 0]])
        W = np.matmul(np.matmul(V, S), V.transpose())
        D, E = np.linalg.eig(np.matmul(np.matmul(W, np.linalg.inv(N)), W))
        sorter = np.argsort(D)
        Astar = E[:, sorter[1]]
        A = mldivide(W, Astar)
    c = -(A[1:3]).transpose() / A[0] / 2 + centroid
    xc = c[0]
    yc = c[1]
    r = np.sqrt(A[1] * A[1] + A[2] * A[2] - 4 * A[0] * A[3]) / abs(A[0]) / 2
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def hyper_fit(coords: Union[npt.NDArray, List], IterMax: int = 99) -> Tuple[float, ...]:
    DeprecationWarning("hyper_fit() is deprecated. Please use hyperLSQ().")
    return hyperLSQ(coords, IterMax)


def hyperLSQ(coords: Union[npt.NDArray, List], iter_max: int = 99) -> Tuple[float, ...]:
    """
    Kenichi Kanatani, Prasanna Rangarajan, "Hyper least squares fitting of circles and ellipses"
    Computational Statistics & Data Analysis, Vol. 55, pages 2197-2208, (2011)

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.
    iter_max    : Optional int. Maximum number of iterations for the iterative fitting algorithm.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """
    x, y = convert_input(coords)
    n = x.shape[0]

    Xi = x - x.mean()
    Yi = y - y.mean()
    Zi = Xi * Xi + Yi * Yi

    # compute moments
    Mxy = (Xi * Yi).sum() / n
    Mxx = (Xi * Xi).sum() / n
    Myy = (Yi * Yi).sum() / n
    Mxz = (Xi * Zi).sum() / n
    Myz = (Yi * Zi).sum() / n
    Mzz = (Zi * Zi).sum() / n

    # computing the coefficients of characteristic polynomial
    Mz = Mxx + Myy
    Cov_xy = Mxx * Myy - Mxy * Mxy
    Var_z = Mzz - Mz * Mz

    A2 = 4 * Cov_xy - 3 * Mz * Mz - Mzz
    A1 = Var_z * Mz + 4. * Cov_xy * Mz - Mxz * Mxz - Myz * Myz
    A0 = Mxz * (Mxz * Myy - Myz * Mxy) + Myz * (Myz * Mxx - Mxz * Mxy) - Var_z * Cov_xy
    A22 = A2 + A2

    # finding the root of the characteristic polynomial
    Y = A0
    X = 0.
    for i in range(iter_max):
        Dy = A1 + X * (A22 + 16. * (X ** 2))
        xnew = X - Y / Dy
        if xnew == X or not np.isfinite(xnew):
            break
        ynew = A0 + xnew * (A1 + xnew * (A2 + 4. * xnew * xnew))
        if abs(ynew) >= abs(Y):
            break
        X, Y = xnew, ynew

    det = X ** 2 - X * Mz + Cov_xy
    Xcenter = (Mxz * (Myy - X) - Myz * Mxy) / det / 2.
    Ycenter = (Myz * (Mxx - X) - Mxz * Mxy) / det / 2.

    xc: float = Xcenter + x.mean()
    yc: float = Ycenter + y.mean()
    r = np.sqrt(abs(Xcenter ** 2 + Ycenter ** 2 + Mz))
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def least_squares_circle(coords: Union[npt.NDArray, List]) -> Tuple[float, ...]:
    DeprecationWarning("least_squares_circle() is deprecated. Please use standardLSQ().")
    return standardLSQ(coords)


def standardLSQ(coords: Union[np.ndarray, List]) -> Tuple[float, ...]:
    """
    Circle fitting using a simple least squares fitting algorithm.

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.

    Returns
    -------
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit
    s   : float. Sigma (RMS of error) of the circle fit
    """

    from scipy import optimize  # type: ignore[import]

    x, y = convert_input(coords)
    X, Y, centroid = center_data(x, y)
    ret = optimize.leastsq(lsq_fun, centroid, args=(x, y))
    center = ret[0]
    xc: float = center[0]
    yc: float = center[1]
    Ri = calc_R(x, y, *center)
    r: float = Ri.mean()
    s = sigma(x, y, xc, yc, r)
    return xc, yc, r, s


def plot_data_circle(coords: Union[npt.NDArray, List], xc: float, yc: float, r: float) -> None:
    """
    Plot data and a fitted circle.

    Parameters
    ----------
    coords: 2D List or 2D np.ndarray of shape (n,2). X,Y point coordinates.
    xc  : float. x coordinate of the circle fit
    yc  : float. y coordinate of the circle fit
    r   : float. Radius of the circle fit

    Returns
    -------
    """
    try:
        from matplotlib import pyplot as plt
    except ModuleNotFoundError:
        raise ModuleNotFoundError("You must install matplotlib to use this feature!")
    x, y = convert_input(coords)
    _ = plt.figure(facecolor='white')
    plt.axis('equal')

    theta_fit = np.linspace(-np.pi, np.pi, 180)

    x_fit = xc + r * np.cos(theta_fit)
    y_fit = yc + r * np.sin(theta_fit)
    plt.plot(x_fit, y_fit, 'b-', label="fitted circle", lw=2)
    plt.plot([xc], [yc], 'bD', mec='y', mew=1)
    plt.xlabel('x')
    plt.ylabel('y')
    # plot data
    plt.scatter(x, y, c='red', label='data')

    plt.legend(loc='best', labelspacing=0.1)
    plt.grid()
    plt.title('Fit Circle')
    plt.show()
