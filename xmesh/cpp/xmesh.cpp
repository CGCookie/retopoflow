#include <cstdint>
#include <cstdlib>
#include <iterator>
#include <limits>
#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/eval.h>
#include <nanobind/stl/vector.h>
// #include <nanobind/stl/bind_vector.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/tuple.h>
#include <nanobind/stl/string.h>
#include <algorithm>
#include <tuple>
#include <unordered_map>

namespace nb = nanobind;
using namespace nb::literals;

using vec3f_ndarray = nb::ndarray<nb::numpy, float, nb::ndim<1>>;

using mat4f = nb::ndarray<float, nb::shape<4,4>, nb::device::cpu>;
using vec3f = nb::ndarray<float, nb::shape< -1, 3 >, nb::device::cpu>;
using inds2 = nb::ndarray<uint32_t, nb::shape< -1, 3 >, nb::device::cpu>;
using inds3 = nb::ndarray<uint32_t, nb::shape< -1, 3 >, nb::device::cpu>;

using Float3 = std::tuple<float,float,float>;
using Int2 = std::tuple<int,int>;
using Int3 = std::tuple<int,int,int>;
using Float3List = std::vector<Float3>;
using Int2List = std::vector<Int2>;
using Int3List = std::vector<Int3>;
using FloatArray3 = std::array<float, 3>;



// struct Matrix4f { float data[4][4] {}; };

struct Blender_MPoly {
    // see source/blender/makesdna/DNA_meshdata_types.h
    int loopstart;
    int totloop;
    short mat_nr_legacy;
    char flag_legacy;
    char _pad;
};

struct Blender_MLoop {
    // see source/blender/makesdna/DNA_meshdata_types.h
    unsigned int iv; // vert index
    unsigned int ie; // edge index
};


struct HighResMesh {
    std::string name = {};

    bool hide = false;
    bool snap = true;

    float matrix_world[4][4] = {
        { 1, 0, 0, 0 },
        { 0, 1, 0, 0 },
        { 0, 0, 1, 0 },
        { 0, 0, 0, 1 }
    };

    size_t n_verts = 0, n_edges = 0, n_faces = 0, n_loops = 0;
    std::vector<std::tuple<float, float, float>> verts;
    std::vector<std::tuple<uint32_t, uint32_t>> edges;
    std::vector<std::vector<uint32_t>> faces;
    std::vector<uint32_t> loop_starts;
    std::vector<uint32_t> loop_totals;
    std::vector<uint32_t> loop_iverts;

    size_t n_tris = 0;
    std::vector<float>    verts_world;
    std::vector<float>    vert_colors;
    std::vector<uint32_t> tris;

    uint32_t n_accel = 0;
    float bbox_x_min = std::numeric_limits<float>::infinity();
    float bbox_y_min = std::numeric_limits<float>::infinity();
    float bbox_z_min = std::numeric_limits<float>::infinity();
    float bbox_x_max = -std::numeric_limits<float>::infinity();
    float bbox_y_max = -std::numeric_limits<float>::infinity();
    float bbox_z_max = -std::numeric_limits<float>::infinity();
    float bbox_x_size = -1.0f;
    float bbox_y_size = -1.0f;
    float bbox_z_size = -1.0f;
    std::unordered_map<uint32_t, std::vector<uint32_t>> accel_verts;

    void make(
        const std::string &name,
        bool hide, bool snap,
        const nb::ndarray<float, nb::shape<4,4>> &matrix_world,
        uintptr_t verts_ptr, size_t n_verts,
        uintptr_t edges_ptr, size_t n_edges,
        uintptr_t loop_starts_ptr, size_t n_faces,
        uintptr_t loops_ptr, size_t n_loops
    ) {
        this->name = name;
        this->hide = hide;
        this->snap = snap;

        for(int i = 0; i < 4; i++) {
            for(int j = 0; j < 4; j++) {
                this->matrix_world[i][j] = matrix_world(i,j);
            }
        }

        this->n_verts = n_verts;
        float *verts = reinterpret_cast<float*>(verts_ptr);
        this->verts.reserve(n_verts);
        for(size_t i = 0; i < n_verts; i++) {
            float x = verts[i*3+0];
            float y = verts[i*3+1];
            float z = verts[i*3+2];
            bbox_x_min = std::min(bbox_x_min, x);
            bbox_y_min = std::min(bbox_y_min, y);
            bbox_z_min = std::min(bbox_z_min, z);
            bbox_x_max = std::max(bbox_x_max, x);
            bbox_y_max = std::max(bbox_y_max, y);
            bbox_z_max = std::max(bbox_z_max, z);
            this->verts.push_back(std::make_tuple(x, y, z));
        }
        bbox_x_size = bbox_x_max - bbox_x_min;
        bbox_y_size = bbox_y_max - bbox_y_min;
        bbox_z_size = bbox_z_max - bbox_z_min;

        this->n_edges = n_edges;
        uint32_t *edges = reinterpret_cast<uint32_t*>(edges_ptr);
        this->edges.reserve(n_edges);
        for(size_t i = 0; i < n_edges; i++) {
            this->edges.push_back(std::make_tuple(edges[i*2+0], edges[i*2+1]));
        }

        this->n_loops = n_loops;
        uint32_t *loops = reinterpret_cast<uint32_t*>(loops_ptr);
        this->loop_iverts.assign(loops, loops + n_loops);

        this->n_faces = n_faces;
        uint32_t *loop_starts = reinterpret_cast<uint32_t*>(loop_starts_ptr);
        this->loop_starts.assign(loop_starts, loop_starts + n_faces);

        this->process();
    }

    void process() {
        float (&M)[4][4] = this->matrix_world;
        this->verts_world.reserve(n_verts*3);
        this->vert_colors.reserve(n_verts*4);
        for(size_t i = 0; i < n_verts; i++) {
            float x = std::get<0>(verts[i]);
            float y = std::get<1>(verts[i]);
            float z = std::get<2>(verts[i]);

            float w = M[3][0]*x + M[3][1]*y + M[3][2]*z + M[3][3];
            verts_world.push_back((M[0][0]*x + M[0][1]*y + M[0][2]*z + M[0][3]) / w);
            verts_world.push_back((M[1][0]*x + M[1][1]*y + M[1][2]*z + M[1][3]) / w);
            verts_world.push_back((M[2][0]*x + M[2][1]*y + M[2][2]*z + M[2][3]) / w);

            vert_colors.push_back((float)(rand()) / (float)(RAND_MAX));
            vert_colors.push_back((float)(rand()) / (float)(RAND_MAX));
            vert_colors.push_back((float)(rand()) / (float)(RAND_MAX));
            vert_colors.push_back(1.0);
        }

        this->loop_totals.reserve(n_faces);
        for(size_t i_face = 0; i_face < n_faces; i_face++) {
            size_t i_loop_start = loop_starts[i_face];
            size_t i_loop_end = i_face+1<n_faces ? loop_starts[i_face+1] : n_loops;
            this->loop_totals.push_back(i_loop_end - i_loop_start);
        }

        this->faces.resize(n_faces);
        for(size_t i_face = 0; i_face < n_faces; i_face++) {
            std::vector<uint32_t> &face = this->faces[i_face];
            size_t loop_total = loop_totals[i_face];
            size_t i_loop_start = loop_starts[i_face];
            size_t i_loop_end = i_loop_start + loop_total;
            face.reserve(loop_total);
            for(uint32_t i = i_loop_start; i < i_loop_end; i++) {
                face.push_back(i);
            }
        }

        tris.reserve((n_loops - n_faces) * 3);
        for(size_t i_face = 0; i_face < n_faces; i_face++) {
            size_t i_loop_start = loop_starts[i_face];
            size_t i_loop_end = i_loop_start + loop_totals[i_face];
            size_t i_vert0 = loop_iverts[i_loop_start];
            for(size_t i_loop = i_loop_start + 1; i_loop < i_loop_end -1; i_loop++) {
                size_t i_vert1 = loop_iverts[i_loop+0];
                size_t i_vert2 = loop_iverts[i_loop+1];
                tris.push_back(i_vert0);
                tris.push_back(i_vert1);
                tris.push_back(i_vert2);
            }
        }
        n_tris = tris.size() / 3;

        n_accel = std::max((size_t) 1, (size_t) std::sqrt(std::sqrt((float)n_verts)));
        for(size_t i_vert = 0; i_vert < n_verts; i_vert++) {
            uint32_t i_accel = to_accel_index(verts[i_vert]);
            accel_verts[i_accel].push_back(i_vert);
        }
        printf("bbox: [%0.3f %0.3f %0.3f] - [%0.3f %0.3f %0.3f]\n", bbox_x_min, bbox_y_min, bbox_z_min, bbox_x_max, bbox_y_max, bbox_z_max);
        printf("accel: N=%u, size=%lu\n", n_accel, accel_verts.size());
    }

    uint32_t to_accel_index(const std::tuple<float, float, float> &co) {
        float x = (std::get<0>(co) - bbox_x_min) / (bbox_x_size + std::numeric_limits<float>::epsilon());
        uint32_t ix = std::clamp((uint32_t)(x * (float)n_accel), (uint32_t)0, (uint32_t)n_accel-1);
        float y = (std::get<1>(co) - bbox_y_min) / (bbox_y_size + std::numeric_limits<float>::epsilon());
        uint32_t iy = std::clamp((uint32_t)(y * (float)n_accel), (uint32_t)0, (uint32_t)n_accel-1);
        float z = (std::get<2>(co) - bbox_z_min) / (bbox_z_size + std::numeric_limits<float>::epsilon());
        uint32_t iz = std::clamp((uint32_t)(z * (float)n_accel), (uint32_t)0, (uint32_t)n_accel-1);
        return ix + n_accel * (iy + n_accel * iz);
    }

    void debug_print() {
        printf("HighResMesh %s\n", name.c_str());
        printf("  hide:%d   snap:%d\n", hide, snap);
        printf("  matrix_world:\n");
        printf("    %0.3f %0.3f %0.3f %0.3f\n", matrix_world[0][0], matrix_world[0][1], matrix_world[0][2], matrix_world[0][3]);
        printf("    %0.3f %0.3f %0.3f %0.3f\n", matrix_world[1][0], matrix_world[1][1], matrix_world[1][2], matrix_world[1][3]);
        printf("    %0.3f %0.3f %0.3f %0.3f\n", matrix_world[2][0], matrix_world[2][1], matrix_world[2][2], matrix_world[2][3]);
        printf("    %0.3f %0.3f %0.3f %0.3f\n", matrix_world[3][0], matrix_world[3][1], matrix_world[3][2], matrix_world[3][3]);
        printf("  counts: %ld %ld %ld\n", n_verts, n_edges, n_tris);
        printf("  verts[:10]\n");
        for(size_t i = 0; i < std::min<size_t>(n_verts, 8); i++) {
            float x = std::get<0>(verts[i]);
            float y = std::get<1>(verts[i]);
            float z = std::get<2>(verts[i]);
            printf("    %ld: [ %f %f %f ]\n", i, x, y, z);
        }
        printf("  edges[:10]\n");
        for(size_t i = 0; i < std::min<size_t>(n_edges, 10); i++) {
            uint32_t u = std::get<0>(edges[i]);
            uint32_t v = std::get<1>(edges[i]);
            printf("    %ld: [ %u %u ]\n", i, u, v);
        }
        printf("  tris[:10]\n");
        for(size_t i = 0; i < std::min<size_t>(n_tris, 10); i++) {
            printf("    %ld: [ %u %u %u ]\n", i, tris[i*3+0], tris[i*3+1], tris[i*3+2]);
        }
        printf("  faces[:10].loop_start, .loop_total\n");
        for(size_t i = 0; i < std::min<size_t>(n_faces, 6); i++) {
            uint32_t count = (i+1<n_faces ? loop_starts[i+1] : n_loops) - loop_starts[i];
            printf("    %ld: %u %u\n", i, loop_starts[i], count);
        }
        printf("  loops[:10].vert_index\n");
        for(size_t i = 0; i < std::min<size_t>(n_loops, 10); i++) {
            printf("    %ld: %u\n", i, loop_iverts[i]);
        }
    }
};

struct Scene {
    std::vector<HighResMesh*> meshes;

    vec3f geo_verts;

    Float3List geo_points;
    Int2List geo_edges;
    Int3List geo_triangles;

    FloatArray3 view_position;
    FloatArray3 view_backward;
    bool view_ortho;

    void view_set(const FloatArray3 &position, const FloatArray3 &backward, const bool &ortho) {
        view_position = position;
        view_backward = backward;
        view_ortho = ortho;
    }

    HighResMesh* add_highresmesh(
        const std::string &name,
        bool hide,
        bool snap,
        const nb::ndarray<float, nb::shape<4,4>> &matrix_world,
        uintptr_t verts_ptr, size_t n_verts,
        uintptr_t edges_ptr, size_t n_edges,
        uintptr_t faces_ptr, size_t n_faces,
        uintptr_t loops_ptr, size_t n_loops
    ) {
        HighResMesh *mesh = new HighResMesh();
        mesh->make(
            name,
            hide, snap,
            matrix_world,
            verts_ptr, n_verts,
            edges_ptr, n_edges,
            faces_ptr, n_faces,
            loops_ptr, n_loops
        );
        meshes.push_back(mesh);
        return mesh;
    }

    void discard_highreshmesh(HighResMesh *mesh) {
        for(size_t i = 0; i < meshes.size(); i++) {
            if(mesh->name.compare(meshes[i]->name) == 0) {
                meshes[i] = meshes[meshes.size() - 1];
                meshes.pop_back();
                i--;
            }
        }
    }

    void geo_add_pointer(
        const nb::ndarray<float, nb::shape<4,4>> &M,
        uintptr_t points_ptr, size_t n_points,
        uintptr_t edges_ptr, size_t n_edges,
        const nb::ndarray<uint32_t, nb::shape< -1>> &triangles
    ) {
        float * points = reinterpret_cast<float*>(points_ptr);
        uint32_t * edges = reinterpret_cast<uint32_t*>(edges_ptr);

        size_t o_points = geo_points.size();
        size_t o_edges = geo_edges.size();
        size_t o_triangles = geo_triangles.size();
        size_t n_triangles = triangles.size() / 3;

        geo_points.reserve(o_points + n_points);
        for(size_t i = 0; i < n_points; i++) {
            float x = points[i*3+0], y = points[i*3+1], z = points[i*3+2];
            float nx = M(0,0)*x + M(0,1)*y + M(0,2)*z + M(0,3);
            float ny = M(1,0)*x + M(1,1)*y + M(1,2)*z + M(1,3);
            float nz = M(2,0)*x + M(2,1)*y + M(2,2)*z + M(2,3);
            float nw = M(3,0)*x + M(3,1)*y + M(3,2)*z + M(3,3);
            geo_points.emplace_back( nx / nw, ny / nw, nz / nw );
        }

        geo_edges.reserve(o_edges + n_edges);
        for(size_t i = 0; i < n_edges; i++) {
            geo_edges.emplace_back(
                edges[i*2+0] + o_points,
                edges[i*2+1] + o_points
            );
        }

        geo_triangles.reserve(o_triangles + n_triangles);
        for(size_t i = 0; i < n_triangles; i++) {
            geo_triangles.emplace_back(
                triangles(i*3+0) + o_points,
                triangles(i*3+1) + o_points,
                triangles(i*3+2) + o_points
            );
        }
    }

    // void geo_add_pointer_all(
    //     const nb::ndarray<float, nb::shape<4,4>> &M,
    //     uintptr_t verts_ptr, size_t n_verts,
    //     uintptr_t edges_ptr, size_t n_edges,
    //     uintptr_t faces_ptr, size_t n_faces,
    //     uintptr_t loops_ptr, size_t n_loops
    // ) {
    //     float    *verts = reinterpret_cast<float   *>(verts_ptr);
    //     uint32_t *edges = reinterpret_cast<uint32_t*>(edges_ptr);
    //     uint32_t *faces = reinterpret_cast<uint32_t*>(faces_ptr);
    //     uint32_t *loops = reinterpret_cast<uint32_t*>(loops_ptr);

    //     size_t o_verts = geo_points.size();
    //     size_t o_edges = geo_edges.size();
    //     size_t o_triangles = geo_triangles.size();

    //     geo_points.reserve(o_points + n_points);
    //     for(size_t i = 0; i < n_points; i++) {
    //         float x = points[i*3+0], y = points[i*3+1], z = points[i*3+2];
    //         float nx = M(0,0)*x + M(0,1)*y + M(0,2)*z + M(0,3);
    //         float ny = M(1,0)*x + M(1,1)*y + M(1,2)*z + M(1,3);
    //         float nz = M(2,0)*x + M(2,1)*y + M(2,2)*z + M(2,3);
    //         float nw = M(3,0)*x + M(3,1)*y + M(3,2)*z + M(3,3);
    //         geo_points.emplace_back( nx / nw, ny / nw, nz / nw );
    //     }

    //     geo_edges.reserve(o_edges + n_edges);
    //     for(size_t i = 0; i < n_edges; i++) {
    //         geo_edges.emplace_back(
    //             edges[i*2+0] + o_points,
    //             edges[i*2+1] + o_points
    //         );
    //     }

    //     geo_triangles.reserve(o_triangles + n_tris);
    //     for(size_t i = 0; i < n_tris; i++) {
    //         geo_triangles.emplace_back(
    //             tris[i*3+0].iv + o_points,
    //             tris[i*3+1].iv + o_points,
    //             tris[i*3+2].iv + o_points
    //         );
    //     }
    // }

    void geo_add_buffer(const nb::ndarray<float, nb::shape< -1 >> &points, const nb::ndarray<uint32_t, nb::shape< -1 >> &edges, const nb::ndarray<uint32_t, nb::shape< -1>> &triangles) {
        size_t o_points = geo_points.size();
        size_t o_edges = geo_edges.size();
        size_t o_triangles = geo_triangles.size();
        size_t n_points = points.size() / 3;
        size_t n_edges = edges.size() / 2;
        size_t n_triangles = triangles.size() / 3;

        geo_points.reserve(o_points + n_points);
        for(size_t i = 0; i < n_points; i++) {
            geo_points.emplace_back(
                points(i*3+0),
                points(i*3+1),
                points(i*3+2)
            );
        }

        geo_edges.reserve(o_edges + n_edges);
        for(size_t i = 0; i < n_edges; i++) {
            geo_edges.emplace_back(
                edges(i*2+0) + o_points,
                edges(i*2+1) + o_points
            );
        }

        geo_triangles.reserve(o_triangles + n_triangles);
        for(size_t i = 0; i < n_triangles; i++) {
            geo_triangles.emplace_back(
                triangles(i*3+0) + o_points,
                triangles(i*3+1) + o_points,
                triangles(i*3+2) + o_points
            );
        }
    }

    void geo_add_list(const Float3List &points, const Int2List &edges, const Int3List &triangles) {
        int o_points = geo_points.size();
        int o_edges = geo_edges.size();
        int o_triangles = geo_triangles.size();
        // size_t n_points = points.size();
        size_t n_edges = edges.size();
        size_t n_triangles = triangles.size();

        geo_points.insert(geo_points.end(), points.begin(), points.end());

        geo_edges.reserve(o_edges + n_edges);
        for(const Int2 &edge : edges) {
            geo_edges.emplace_back(
                std::get<0>(edge) + o_points,
                std::get<1>(edge) + o_points
            );
        }

        geo_triangles.reserve(o_triangles + n_triangles);
        for(const Int3 &triangle : triangles) {
            geo_triangles.emplace_back(
                std::get<0>(triangle) + o_points,
                std::get<1>(triangle) + o_points,
                std::get<2>(triangle) + o_points
            );
        }
    }

    int geo_points_size() {
        return geo_points.size();
    }
    int geo_edges_size() {
        return geo_edges.size();
    }
    int geo_triangles_size() {
        return geo_triangles.size();
    }
    void debug_print() {
        printf("points (%ld)\n", geo_points.size());
        for(size_t i = 0; i < std::min<size_t>(geo_points.size(), 10); i++) {
            printf("  %ld: [ %f %f %f ]\n", i, std::get<0>(geo_points[i]), std::get<1>(geo_points[i]), std::get<2>(geo_points[i]));
        }
        printf("edges (%ld)\n", geo_edges.size());
        for(size_t i = 0; i < std::min<size_t>(geo_edges.size(), 10); i++) {
            printf("  %ld: [ %d %d ]\n", i, std::get<0>(geo_edges[i]), std::get<1>(geo_edges[i]));
        }
        printf("triangles (%ld)\n", geo_triangles.size());
        for(size_t i = 0; i < std::min<size_t>(geo_triangles.size(), 10); i++) {
            printf("  %ld: [ %d %d %d ]\n", i, std::get<0>(geo_triangles[i]), std::get<1>(geo_triangles[i]), std::get<2>(geo_triangles[i]));
        }
    }

    void clear(void) {
        geo_points.clear();
        geo_edges.clear();
        geo_triangles.clear();
    }
};

struct Low {
    Float3 p;
    Float3 n;
};

int add(int a, int b = 1) { return a + b; }

NB_MODULE(xmesh, m) {
    m.doc() = "xmesh, a wrapper for blender mesh, emesh, bmesh";

    // m.def("add", &add, "a"_a, "b"_a=1, "This function adds two numbers and increments if only one is provided.");

    m.def("inspect", [](uintptr_t ptr, size_t bytes){
        unsigned char *p = (unsigned char*)ptr;
        printf("inspecting %p\n", p);
        for(size_t i = 0; i < bytes; i++) {
            if(i % 8 == 0) printf("  %04zu: ", i);
            printf("%02x", p[i]);
            if(i % 8 == 7) printf("\n");
            else printf(" ");
        }
    });


    nb::class_<HighResMesh>(m, "HighResMesh")
        .def_ro("name", &HighResMesh::name, "Name of high-res mesh object")
        .def_rw("hide", &HighResMesh::hide, "Disable rendering in viewport")
        .def_rw("snap", &HighResMesh::snap, "Disable snapping")
        .def_ro("n_verts", &HighResMesh::n_verts)
        .def_ro("n_edges", &HighResMesh::n_edges)
        .def_ro("n_tris",  &HighResMesh::n_tris)
        .def_ro("n_loops", &HighResMesh::n_loops)
        .def_ro("n_faces", &HighResMesh::n_faces)
        .def_ro("verts", &HighResMesh::verts, nb::rv_policy::reference_internal)
        .def_ro("edges", &HighResMesh::edges, nb::rv_policy::reference_internal)
        .def_ro("faces", &HighResMesh::faces, nb::rv_policy::reference_internal)

        .def("set_vert", [](HighResMesh &mesh, int i, const std::tuple<float,float,float> &co){
            mesh.verts[i] = co;
        })

        // array's are needed for foreach_set
        .def(
            "verts_array",
            [](const HighResMesh &mesh) {
                return nb::ndarray<float, nb::array_api>(
                    (float *)mesh.verts.data(),
                    { mesh.n_verts * 3 }
                );
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "edges_array",
            [](const HighResMesh &mesh) {
                return nb::ndarray<uint32_t, nb::array_api>(
                    (uint32_t*)mesh.edges.data(),
                    { mesh.n_edges * 2 }
                );
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "loops_array",
            [](const HighResMesh &mesh) {
                return nb::ndarray<uint32_t, nb::array_api>(
                    (uint32_t*)mesh.loop_iverts.data(),
                    { mesh.n_loops }
                );
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "loop_starts_array",
            [](const HighResMesh &mesh) {
                return nb::ndarray<uint32_t, nb::array_api>(
                    (uint32_t*)mesh.loop_starts.data(),
                    { mesh.n_faces }
                );
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "loop_totals_array",
            [](const HighResMesh &mesh) {
                return nb::ndarray<uint32_t, nb::array_api>(
                    (uint32_t*)mesh.loop_totals.data(),
                    { mesh.n_faces }
                );
            },
            nb::rv_policy::reference_internal
        )

        // numpy's are needed for batch_for_shader
        .def(
            "verts_numpy",
            [](const HighResMesh &mesh) {
                return nb::ndarray<float, nb::numpy>(
                    (float*)mesh.verts.data(),
                    { mesh.n_verts, 3 }
                ).cast();
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "verts_world_numpy",
            [](const HighResMesh &mesh) {
                return nb::ndarray<float, nb::numpy>(
                    (float*)mesh.verts_world.data(),
                    { mesh.n_verts, 3 }
                ).cast();
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "vert_colors_numpy",
            [](const HighResMesh &mesh) {
                return nb::ndarray<float, nb::numpy>(
                    (float*)mesh.vert_colors.data(),
                    { mesh.n_verts, 4 }
                ).cast();
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "edges_numpy",
            [](const HighResMesh &mesh) {
                return nb::ndarray<uint32_t, nb::numpy>(
                    (uint32_t*)mesh.edges.data(),
                    { mesh.n_edges * 2 }
                ).cast();
            },
            nb::rv_policy::reference_internal
        )
        .def(
            "tris_numpy",
            [](const HighResMesh &mesh) {
                return nb::ndarray<uint32_t, nb::numpy>(
                    (uint32_t*)mesh.tris.data(),
                    { mesh.n_tris, 3 }
                ).cast();
            },
            nb::rv_policy::reference_internal
        )

        // expose debug printing
        .def("debug_print", &HighResMesh::debug_print)
    ;

    nb::class_<Scene>(m, "Scene", nb::dynamic_attr())
        .def(nb::init<>())

        .def("add_highresmesh", &Scene::add_highresmesh,
            "name"_a, "hide"_a, "snap"_a, "matrix_world"_a,
            "verts_pointer"_a, "n_verts"_a,
            "edges_pointer"_a, "n_edges"_a,
            "faces_pointer"_a, "n_faces"_a,
            "loops_pointer"_a, "n_loops"_a,
            "Adds new high-res mesh to scene"
        )
        .def("discard_highresmesh", &Scene::discard_highreshmesh, "hrmesh"_a, "Discards given high-res mesh from scene")
        .def_prop_ro("n_highresmeshes", [](const Scene &scene) { return scene.meshes.size(); })

        // view-related methods and properties
        .def(
            "set_view", &Scene::view_set,
            "position"_a, "backward"_a, "ortho"_a,
            "Sets viewing position, backward, and orthographic projection"
        )
        .def_rw("view_position", &Scene::view_position, "Position of view")
        .def_rw("view_backward", &Scene::view_backward, "Backward direction of view")
        .def_rw("view_ortho", &Scene::view_ortho, "Orthographic (vs perspective) projection of view")

        // geometry-related methods and properties
        .def(
            "add_geometry_pointer", &Scene::geo_add_pointer,
            //"points"_a, "edges"_a, "triangles"_a,
            "Adds geometry to scene that will be raycasted snapped"
        )
        // .def(
        //     "add_geometry_pointer_all", &Scene::geo_add_pointer_all,
        //     //"points"_a, "edges"_a, "triangles"_a,
        //     "Adds geometry to scene that will be raycasted snapped"
        // )
        .def(
            "add_geometry_buffer", &Scene::geo_add_buffer,
            "points"_a, "edges"_a, "triangles"_a,
            "Adds geometry to scene that will be raycasted snapped"
        )
        .def(
            "add_geometry_list", &Scene::geo_add_list,
            "points"_a, "edges"_a, "triangles"_a,
            "Adds geometry to scene that will be raycasted snapped"
        )
        .def("clear", &Scene::clear, "Clear all geometry from scene")
        .def_prop_ro("point_count", &Scene::geo_points_size, "Number of points added")
        .def_prop_ro("edge_count", &Scene::geo_edges_size, "Number of edges added")
        .def_prop_ro("triangle_count", &Scene::geo_triangles_size, "Number of triangles added")
        .def("debug_print", &Scene::debug_print)
    ;

}
