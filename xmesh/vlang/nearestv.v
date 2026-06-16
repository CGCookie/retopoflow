module nearestv

import py

const size = 8

struct Vec3 {
pub:
    x f64
    y f64
    z f64
}

@[heap; py_module:'nearestv']
struct NearestModuleContext {
    points []Vec3
    indices []int
    inds [size]int
    offset int
}

@[export: 'PyInit_nearestv'; unsafe]
pub fn py_init_module() &C.PyObject {
    return py.init_module<NearestModuleContext>(&NearestModuleContext{})
}



fn init() {
    clear()
}

@[export: 'clear']
fn clear() {
    points.clear()
    clearinds()
}

fn clearinds() {
    indices.clear()
    for i in 0..size { inds[i] = -1 }
    offset = 0
}

@[export: 'add']
fn add(x f64, y f64, z f64) {
    points << Vec3{ x y z }
}

@[export: 'size']
fn get_size() int {
    return size
}

@[export: 'find']
fn find(x f64, y f64, z f64, r f64) int {
    clearinds()
    r2 := r * r
    println(r2)
    for i, point in points {
        d2 := (point.x - x) * (point.x - x) + (point.y - y) * (point.y - y) + (point.z - z) * (point.z - z)
        if d2 <= r2 {
            indices << i
        }
    }
    return indices.len
}

@[export: 'hasnext']
fn has_next() bool {
    return offset < indices.len
}

@[export: 'next']
fn next() [size]int {
    for i in 0..size {
        inds[i] = if offset < indices.len { indices[offset] } else { -1 }
        offset = offset + 1
    }
    return inds
}
