#!/usr/bin/python3

import bpy
import gpu
from bpy.types import Object, Mesh
from gpu_extras.batch import batch_for_shader

import time
import numpy as np

from ..xmesh.build import build_module
build_module()

from . import xmesh


timings : list[tuple[str, float]] = []
def add_timing(label : str):
    global timings
    timings.append((label, time.time()))


# obj_name = 'Cube'
# obj_name = 'Cube.001'
obj_name = 'Icosphere'


o : Object = bpy.data.objects[obj_name]
assert isinstance(o.data, Mesh)
m : Mesh = o.data
m.calc_loop_triangles()
n_verts = len(m.vertices)
n_edges = len(m.edges)
n_triangles = len(m.loop_triangles)

def add_highresmesh_byname(scene : xmesh.Scene, object_name : str) -> xmesh.HighResMesh:
    obj : Object = bpy.data.objects[object_name]
    assert isinstance(obj.data, Mesh)
    mesh : Mesh = obj.data
    print(obj.matrix_world)
    hrmesh = scene.add_highresmesh(
        object_name,
        obj.hide_viewport, True,
        np.array(obj.matrix_world),
        mesh.vertices[0].as_pointer(), len(mesh.vertices),
        mesh.edges[0].as_pointer(), len(mesh.edges),
        mesh.polygons[0].as_pointer(), len(mesh.polygons),
        mesh.loops[0].as_pointer(), len(mesh.loops),
    )
    print(obj.matrix_world)
    return hrmesh

def update_mesh(hrmesh : xmesh.HighResMesh):
    verts = np.from_dlpack(hrmesh.verts_array())
    o : Object = bpy.data.objects[hrmesh.name]
    assert isinstance(o.data, Mesh)
    m : Mesh = o.data
    m.vertices.foreach_set('co', verts)


s = xmesh.Scene()


print(f'\n{"="*100}\n')


if False:
    add_timing('list')
    p = [tuple(v.co) for v in m.vertices]
    e = [tuple(e.vertices) for e in m.edges]
    t = [tuple(tri.vertices) for tri in m.loop_triangles]
    s.add_geometry_list(p, e, t)
    print('list')
    print(f'  points:    {s.point_count}')
    print(f'  edges:     {s.edge_count}')
    print(f'  triangles: {s.triangle_count}')
    # s.debug_print()
    s.clear()
    print(f'\n{"="*100}\n')



if False:
    add_timing('buffer')
    p = np.empty(n_verts * 3, dtype=np.float32)
    e = np.empty(n_edges * 2, dtype=np.uint32)
    t = np.empty(n_triangles * 3, dtype=np.uint32)
    m.vertices.foreach_get('co', p)
    m.edges.foreach_get('vertices', e)
    m.loop_triangles.foreach_get('vertices', t)
    s.add_geometry_buffer(p, e, t)
    print('buffer')
    print(f'  points:    {s.point_count}')
    print(f'  edges:     {s.edge_count}')
    print(f'  triangles: {s.triangle_count}')
    # s.debug_print()
    s.clear()
    print(f'\n{"="*100}\n')


if False:
    add_timing('buffer with attributes')
    p = np.empty(n_verts * 3, dtype=np.float32)
    e = np.empty(n_edges * 2, dtype=np.uint32)
    t = np.empty(n_triangles * 3, dtype=np.uint32)
    m.attributes['position'].data.foreach_get('vector', p)
    m.edges.foreach_get('vertices', e)
    m.loop_triangles.foreach_get('vertices', t)
    s.add_geometry_buffer(p, e, t)
    print('buffer with attributes')
    print(f'  points:    {s.point_count}')
    print(f'  edges:     {s.edge_count}')
    print(f'  triangles: {s.triangle_count}')
    # s.debug_print()
    s.clear()
    print(f'\n{"="*100}\n')


if False:
    add_timing('pointer')
    M = np.matrix(o.matrix_world)
    t = np.empty(n_triangles * 3, dtype=np.uint32)
    m.loop_triangles.foreach_get('vertices', t)  # loop_triangles are funny. cannot use as_pointer directly
    s.add_geometry_pointer(
        M,
        m.vertices[0].as_pointer(), n_verts,
        m.edges[0].as_pointer(), n_edges,
        t,
    )
    print('pointer')
    print(f'  points:    {s.point_count}')
    print(f'  edges:     {s.edge_count}')
    print(f'  triangles: {s.triangle_count}')
    # s.debug_print()
    s.clear()
    print(f'\n{"="*100}\n')


if False:
    add_timing('pointer all')
    M = np.matrix(o.matrix_world)
    s.add_geometry_pointer_all(
        M,
        m.vertices[0].as_pointer(), n_verts,
        m.edges[0].as_pointer(), n_edges,
        m.loop_triangles.data.vertices[0].as_pointer(), len(m.loop_triangles),
    )
    print('pointer all')
    print(f'  points:    {s.point_count}')
    print(f'  edges:     {s.edge_count}')
    print(f'  triangles: {s.triangle_count}')
    s.debug_print()
    s.clear()
    print(f'\n{"="*100}\n')


if False:
    def add_object(scene : xmesh.Scene, object_name : str):
        obj = bpy.data.objects[object_name]
        mesh, mat = obj.data, obj.matrix_world
        verts, edges, looptris = mesh.vertices, mesh.edges, mesh.loop_triangles
        # loop_triangles are funny. cannot use as_pointer directly
        # mesh.calc_loop_triangles()
        triangles = np.empty(len(looptris) * 3, dtype=np.uint32)
        looptris.foreach_get('vertices', triangles)
        scene.add_geometry_pointer(
            np.array(mat),
            verts[0].as_pointer(), len(verts),
            edges[0].as_pointer(), len(edges),
            triangles,
        )

    add_timing('pointer through function')
    add_object(s, obj_name)
    print('pointer through function')
    print(f'  points:    {s.point_count}')
    print(f'  edges:     {s.edge_count}')
    print(f'  triangles: {s.triangle_count}')
    # s.debug_print()
    s.clear()
    print(f'\n{"="*100}\n')



# def add_highresmesh(scene : xmesh.Scene, object_name : str) -> xmesh.HighResMesh:
#     obj = bpy.data.objects[object_name]
#     mesh, mat = obj.data, obj.matrix_world
#     hide, snap = obj.hide_viewport, True
#     # loop_triangles are funny. cannot use as_pointer directly
#     mesh.calc_loop_triangles()
#     verts, edges, looptris = mesh.vertices, mesh.edges, mesh.loop_triangles
#     p = np.empty(len(verts) * 3, dtype=np.float32)
#     e = np.empty(len(edges) * 2, dtype=np.uint32)
#     t = np.empty(len(looptris) * 3, dtype=np.uint32)
#     mesh.attributes['position'].data.foreach_get('vector', p)
#     edges.foreach_get('vertices', e)
#     looptris.foreach_get('vertices', t)
#     hrmesh = scene.add_highresmesh(object_name, hide, snap, mat, p, e, t)
#     return hrmesh

add_timing('highresmesh object')
hrmesh = add_highresmesh_byname(s, obj_name)
print('highresmesh object')
print(f'  n_verts: {hrmesh.n_verts}')
print(f'  n_edges: {hrmesh.n_edges}')
print(f'  n_tris:  {hrmesh.n_tris}')
hrmesh.debug_print()
print(f'\n{"="*100}\n')


if True:
    add_timing('highresmesh manipulation test')
    print('highresmesh manipulation test')
    verts = np.from_dlpack(hrmesh.verts_array())
    hrmesh.debug_print()
    verts[0] = 42
    hrmesh.set_vert(1, (-3.14, 3.14, 0.0))
    hrmesh.debug_print()
    update_mesh(hrmesh)
    print(m.vertices[0].co)
    hrmesh.debug_print()
    print(f'\n{"="*100}\n')


if True:
    add_timing('highresmesh manipulation test 2')
    print('highresmesh manipulation test 2')
    hrmesh.set_vert(1, (-3.14, 3.14, 0.0))

    t0 = time.time()

    mesh = bpy.data.meshes.new('FOO')

    mesh.vertices.add(hrmesh.n_verts)
    mesh.vertices.foreach_set('co', np.from_dlpack(hrmesh.verts_array()))

    mesh.edges.add(hrmesh.n_edges)
    mesh.edges.foreach_set('vertices', np.from_dlpack(hrmesh.edges_array()))

    mesh.loops.add(hrmesh.n_loops)
    mesh.loops.foreach_set('vertex_index', np.from_dlpack(hrmesh.loops_array()))

    mesh.polygons.add(hrmesh.n_faces)
    mesh.polygons.foreach_set('loop_start', np.from_dlpack(hrmesh.loop_starts_array()))
    mesh.polygons.foreach_set('loop_total', np.from_dlpack(hrmesh.loop_totals_array()))

    t1 = time.time()

    import bmesh
    eo : Object | None = bpy.context.edit_object
    assert eo
    assert isinstance(eo.data, Mesh)
    em : Mesh = eo.data
    bm = bmesh.from_edit_mesh(em)

    t2 = time.time()

    bm.from_mesh(mesh)

    t3 = time.time()

    bmesh.update_edit_mesh(em)

    t4 = time.time()

    print(f'{t1-t0:0.3f} new mesh with geometry')
    print(f'{t2-t1:0.3f} create new bmesh from edit mesh')
    print(f'{t3-t2:0.3f} call from_mesh()')
    print(f'{t4-t3:0.3f} call update_edit_mesh')
    print(f'{t4-t0:0.3f} total time')

    # bpy.data.objects[obj_name].data.clear_geometry()
    # bpy.data.objects[obj_name].data.from_pydata(
    #     hrmesh.verts_numpy(),
    #     [], #hrmesh.edges_list(),
    #     hrmesh.faces_list(),
    # )
    # hrmesh.debug_print()
    # verts[0] = 42
    # hrmesh.debug_print()
    # update_mesh(hrmesh)
    # print(m.vertices[01].co)
    hrmesh.debug_print()
    print(f'\n{"="*100}\n')


if False:
    add_timing('discard test')
    print('discard test')
    print(f'  hrmeshes: {s.n_highresmeshes}')
    s.discard_highresmesh(hrmesh)
    print(f'  hrmeshes: {s.n_highresmeshes}')
    print(f'\n{"="*100}\n')



add_timing('shader test')

shader = gpu.shader.from_builtin('SMOOTH_COLOR')
verts = hrmesh.verts_world_numpy()
tris = hrmesh.tris_numpy()
color = hrmesh.vert_colors_numpy()
batch = batch_for_shader(
    shader, 'TRIS',
    {'pos': verts, 'color': color},
    indices=tris
)

# add_timing('assertion')
# im = -1
# for i in range(hrmesh.n_tris):
#     i0,i1,i2 = map(int, tris[i,:])
#     j0,j1,j2 = m.loop_triangles[i].vertices
#     im = max(i0,i1,i2,im)
#     if i0 != j0 or i1 != j1 or i2 != j2:
#         print(i, (i0,i1,i2), (j0,j1,j2), (k0,k1,k2))
# print(im)



# add_timing('tests')
# p = np.empty(len(m.polygons), dtype=np.uint32)
# m.polygons.foreach_get('loop_total', p)
# ps = sum(p)
# print(ps)
# # print(p[:20])

add_timing('done')

print()
print(f'Timings...')
for (label, t0), (_, t1) in zip(timings, timings[1:]):
    print(f'  {t1 - t0:0.3f}s {label}')
