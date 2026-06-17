"""xmesh, a wrapper for blender mesh, emesh, bmesh"""

from collections.abc import Sequence
from typing import Annotated

import numpy
from numpy.typing import NDArray


def inspect(arg0: int, arg1: int, /) -> None: ...

class HighResMesh:
    @property
    def name(self) -> str:
        """Name of high-res mesh object"""

    @property
    def hide(self) -> bool:
        """Disable rendering in viewport"""

    @hide.setter
    def hide(self, arg: bool, /) -> None: ...

    @property
    def snap(self) -> bool:
        """Disable snapping"""

    @snap.setter
    def snap(self, arg: bool, /) -> None: ...

    @property
    def n_verts(self) -> int: ...

    @property
    def n_edges(self) -> int: ...

    @property
    def n_tris(self) -> int: ...

    @property
    def n_loops(self) -> int: ...

    @property
    def n_faces(self) -> int: ...

    @property
    def verts(self) -> list[tuple[float, float, float]]: ...

    @property
    def edges(self) -> list[tuple[int, int]]: ...

    @property
    def faces(self) -> list[list[int]]: ...

    def set_vert(self, arg0: int, arg1: tuple[float, float, float], /) -> None: ...

    def verts_array(self) -> ArrayLike[dtype=float32]: ...

    def edges_array(self) -> ArrayLike[dtype=uint32]: ...

    def loops_array(self) -> ArrayLike[dtype=uint32]: ...

    def loop_starts_array(self) -> ArrayLike[dtype=uint32]: ...

    def loop_totals_array(self) -> ArrayLike[dtype=uint32]: ...

    def verts_numpy(self) -> NDArray[numpy.float32]: ...

    def verts_world_numpy(self) -> NDArray[numpy.float32]: ...

    def vert_colors_numpy(self) -> NDArray[numpy.float32]: ...

    def edges_numpy(self) -> NDArray[numpy.uint32]: ...

    def tris_numpy(self) -> NDArray[numpy.uint32]: ...

    def debug_print(self) -> None: ...

class Scene:
    def __init__(self) -> None: ...

    def add_highresmesh(self, name: str, hide: bool, snap: bool, matrix_world: Annotated[NDArray[numpy.float32], dict(shape=(4, 4))], verts_pointer: int, n_verts: int, edges_pointer: int, n_edges: int, faces_pointer: int, n_faces: int, loops_pointer: int, n_loops: int) -> HighResMesh:
        """Adds new high-res mesh to scene"""

    def discard_highresmesh(self, hrmesh: HighResMesh) -> None:
        """Discards given high-res mesh from scene"""

    @property
    def n_highresmeshes(self) -> int: ...

    def set_view(self, position: Sequence[float], backward: Sequence[float], ortho: bool) -> None:
        """Sets viewing position, backward, and orthographic projection"""

    @property
    def view_position(self) -> list[float]:
        """Position of view"""

    @view_position.setter
    def view_position(self, arg: Sequence[float], /) -> None: ...

    @property
    def view_backward(self) -> list[float]:
        """Backward direction of view"""

    @view_backward.setter
    def view_backward(self, arg: Sequence[float], /) -> None: ...

    @property
    def view_ortho(self) -> bool:
        """Orthographic (vs perspective) projection of view"""

    @view_ortho.setter
    def view_ortho(self, arg: bool, /) -> None: ...

    def add_geometry_pointer(self, arg0: Annotated[NDArray[numpy.float32], dict(shape=(4, 4))], arg1: int, arg2: int, arg3: int, arg4: int, arg5: Annotated[NDArray[numpy.uint32], dict(shape=(None,))], /) -> None:
        """Adds geometry to scene that will be raycasted snapped"""

    def add_geometry_buffer(self, points: Annotated[NDArray[numpy.float32], dict(shape=(None,))], edges: Annotated[NDArray[numpy.uint32], dict(shape=(None,))], triangles: Annotated[NDArray[numpy.uint32], dict(shape=(None,))]) -> None:
        """Adds geometry to scene that will be raycasted snapped"""

    def add_geometry_list(self, points: Sequence[tuple[float, float, float]], edges: Sequence[tuple[int, int]], triangles: Sequence[tuple[int, int, int]]) -> None:
        """Adds geometry to scene that will be raycasted snapped"""

    def clear(self) -> None:
        """Clear all geometry from scene"""

    @property
    def point_count(self) -> int:
        """Number of points added"""

    @property
    def edge_count(self) -> int:
        """Number of edges added"""

    @property
    def triangle_count(self) -> int:
        """Number of triangles added"""

    def debug_print(self) -> None: ...
