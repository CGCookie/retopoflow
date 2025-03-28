'''
Copyright (C) 2023 CG Cookie
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

from math import sqrt, ceil, isfinite, floor
import ctypes
from itertools import chain
import numpy as np
from typing import List, Set, Dict, Tuple, Optional, Union, Any

from .maths import zero_threshold, BBox2D, Point2D, clamp, Vec2D, Vec, mid
from .profiler import profiler, time_it, timing
from ..terminal import term_printer


BM_VERT = 0
BM_EDGE = 1
BM_FACE = 2

class AccelPointCtypes(ctypes.Structure):
    _fields_ = [
        ('type', ctypes.c_int),
        ('index', ctypes.c_int),
        ('screen_pos', ctypes.c_float * 2),
        ('depth', ctypes.c_float),
        ('elem', ctypes.c_longlong)
    ]


class GridCell:
    """A cell in the spatial grid that stores elements by type"""
    def __init__(self):
        self.elements = [
            [],  # BM_VERT
            [],  # BM_EDGE
            []   # BM_FACE
        ]

    def add(self, accel_point: AccelPointCtypes):
        if accel_point.type < 0 or accel_point.type > 2:
            raise ValueError(f'Invalid element type: {accel_point.type}, {accel_point.index}')
        self.elements[accel_point.type].append(accel_point)

    def get_all(self):
        return chain(*self.elements)

    def get_by_type(self, elem_type: int):
        return self.elements[elem_type]


class Accel2DOptimized:
    @profiler.function
    def __init__(self,
                 accel_verts: list,
                 accel_edges: list,
                 accel_faces: list,
                 bm_wrapper: tuple,
                 accel_points,
                 num_points: int,
                 bbox: list[float],
                 region_width: int,
                 region_height: int):
        self.accel_geom = (
            accel_verts,
            accel_edges,
            accel_faces
        )
        self.bm_wrapper = bm_wrapper
        '''with time_it("DEBUG accel_points", enabled=True):
            print("sizeof AccelPointCtypes:", ctypes.sizeof(AccelPointCtypes))
            print(bbox)
            print(num_points)
            print(accel_points[0].type, accel_points[0].index)
            print(accel_points[1].type, accel_points[1].index)
            print(accel_points[2].type, accel_points[2].index)
            print(accel_points[3].type, accel_points[3].index))'''
        self._init_with_accel_points(accel_points, num_points, region_width, region_height, bbox)

    def _init_with_accel_points(self, accel_points: ctypes.Array[AccelPointCtypes], num_points, region_width, region_height, bbox):
        """Initialize with the new ctypes array approach"""
        self.region_width = region_width
        self.region_height = region_height

        # Set up bounding box
        self.min = Point2D((bbox[0], bbox[2]))
        self.max = Point2D((bbox[1], bbox[3]))

        self.size = self.max - self.min
        self.sizex, self.sizey = self.size
        self.minx, self.miny = self.min
        
        # Determine grid size based on point density
        # Use square root of number of points for grid size, with a minimum size
        grid_size = max(16, min(256, int(sqrt(num_points) * 1.5)))
        self.grid_size_x = grid_size
        self.grid_size_y = grid_size

        # Create grid cells
        self.grid: Dict[Tuple[int, int], GridCell] = {}

        if self.sizex <= 0 or self.sizey <= 0:
            return

        # Process points and insert into grid
        for accel_point in accel_points:
            # Insert into grid
            cell_key = self._point_to_cell(accel_point.screen_pos[0], accel_point.screen_pos[1])
            
            if cell_key not in self.grid:
                self.grid[cell_key] = GridCell()
            
            # Add element to the cell
            self.grid[cell_key].add(accel_point)

    def _point_to_cell(self, x, y):
        """Convert a point to grid cell coordinates"""
        if self.sizex <= 0 or self.sizey <= 0:
            return 0, 0
        
        cell_i = clamp(int(self.grid_size_x * (x - self.minx) / self.sizex), 0, self.grid_size_x - 1)
        cell_j = clamp(int(self.grid_size_y * (y - self.miny) / self.sizey), 0, self.grid_size_y - 1)
        return cell_i, cell_j

    @profiler.function
    def get(self, v2d, within: float, elem_type: int):
        """Get elements within a certain distance of a point"""
        if v2d is None or not (isfinite(v2d.x) and isfinite(v2d.y)):
            return set()

        # Early rejection test - check if point is outside bounding box plus margin
        if (v2d.x < self.minx - within or v2d.x > self.minx + self.sizex + within or
            v2d.y < self.miny - within or v2d.y > self.miny + self.sizey + within):
            return set()
        
        # Determine cells to check
        min_x, min_y = v2d.x - within, v2d.y - within
        max_x, max_y = v2d.x + within, v2d.y + within
        
        min_cell_i, min_cell_j = self._point_to_cell(min_x, min_y)
        max_cell_i, max_cell_j = self._point_to_cell(max_x, max_y)
        
        # Collect elements from cells
        result = set()
        
        within_sq = within * within

        for i in range(min_cell_i, max_cell_i + 1):
            for j in range(min_cell_j, max_cell_j + 1):
                cell_key = (i, j)
                if cell_key not in self.grid:
                    # No grid, aka no elements in that square space.
                    continue

                # Get elements from cell
                for cell_elem in self.grid[cell_key].get_by_type(elem_type):
                    # Check if elem screen_pos is within distance fron origin in v2d.
                    dist_sq = (cell_elem.screen_pos[0] - v2d.x)**2 + (cell_elem.screen_pos[1] - v2d.y)**2
                    if dist_sq > within_sq:
                        # Outside of distance.
                        continue
                    
                    # We supose indices are updated!
                    rf_elem = self.accel_geom[cell_elem.type][cell_elem.index]
                    if rf_elem.is_valid:
                        result.add(self.bm_wrapper[cell_elem.type](rf_elem))

        return result

    @profiler.function
    def get_verts(self, v2d, within):
        """Get vertices within a certain distance of a point"""
        return self.get(v2d, within, BM_VERT)

    @profiler.function
    def get_edges(self, v2d, within):
        """Get edges within a certain distance of a point"""
        return self.get(v2d, within, BM_EDGE)

    @profiler.function
    def get_faces(self, v2d, within):
        """Get faces within a certain distance of a point"""
        return self.get(v2d, within, BM_FACE)


class Accel2D_CyWrapper:
    def __init__(self, target_accel) -> None:
        self.accel = target_accel

    @profiler.function
    def get(self, v2d, within, nearest_fn, *, fn_filter=None) -> set:
        if v2d is None or not (isfinite(v2d.x) and isfinite(v2d.y)): return set()
        res = nearest_fn(v2d.x, v2d.y, 0.0, within, wrapped=True)
        if res is None:
            return set()
        if len(res) == 0:
            return set()
        return {
            nearest['elem'] for nearest in res if fn_filter is None or fn_filter(nearest['elem'])
        }

    @timing
    def get_verts(self, v2d, within):
        return self.get(v2d, within, nearest_fn=self.accel.find_k_nearest_verts)

    @timing
    def get_edges(self, v2d, within):
        return self.get(v2d, within, nearest_fn=self.accel.find_k_nearest_edges)

    @timing
    def get_faces(self, v2d, within):
        return self.get(v2d, within, nearest_fn=self.accel.find_k_nearest_faces)
