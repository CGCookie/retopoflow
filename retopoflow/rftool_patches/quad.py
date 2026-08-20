from mathutils import Vector
import math

auto_pvert_type = 'topo'

merge = [True, True, True, True, True, True, True, True, True, True, True]
graph_positioned : bool = False
relax_enabled : bool = True

def quad(
    co0 : Vector,
    co1 : Vector,
    no1 : Vector,
    co2 : Vector,
    radius : float,
    angle : float,
) -> Vector:
    v10, v12 = co0 - co1, co2 - co1
    v13 = v10 + v12

    # final direction will be weighted sum of these two directions based
    # on angle between co0-co1-co2
    # - fully d13 when angle is 90 (right angle)
    # - fully din when angle is 0 or 180
    d13 = v13.normalized()
    din = (co0 - co2).cross(no1).normalized()

    # make sure d13 is pointing toward center of patch
    if d13.dot(din) < 0:
        d13.negate()

    d10, d12 = v10.normalized(), v12.normalized()
    weight = abs(d10.dot(d12))

    d13 = (d13 * (1 - weight) + din * weight).normalized()
    # rad = (radius * 0.5) * (1-weight) + v13.length * (weight)
    rad = min(radius, (v10.length + v12.length) / 2 * (1 - weight) + v13.length * (weight))
    # rad = (radius + (v10.length + v12.length) / 2 * (weight) + v13.length * (1 - weight)) / 2
    ang = angle * (1 - weight)

    d_x = d13
    d_z = no1
    d_y = d_z.cross(d_x).normalized()

    center = co1 + d13 * rad
    offset = (d_x * math.cos(ang) + d_y * math.sin(ang)) * (rad * 0.5)
    co3 = center + offset

    return co3
