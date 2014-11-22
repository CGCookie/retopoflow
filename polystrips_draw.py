'''
Copyright (C) 2014 CG Cookie
http://cgcookie.com
hello@cgcookie.com

Created by Jonathan Denning, Jonathan Williamson, and Patrick Moore

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

####class definitions####

import bpy
import math
import time
import copy
from mathutils import Vector, Quaternion, Matrix
from mathutils.geometry import intersect_point_line, intersect_line_plane
from bpy_extras.view3d_utils import location_3d_to_region_2d, region_2d_to_vector_3d, region_2d_to_location_3d, region_2d_to_origin_3d
import bmesh
import blf
import bgl
import itertools

from lib import common_utilities
from lib import common_drawing
from lib.common_utilities import iter_running_sum, dprint, get_object_length_scale, profiler, AddonLocator

from polystrips_utilities import *


#Make the addon name and location accessible
AL = AddonLocator()

def draw_gedge_text(gedge,context, text):
    l = len(gedge.cache_igverts)
    if l > 4:
        n_quads = math.floor(l/2) + 1
        mid_vert_ind = math.floor(l/2)
        mid_vert = gedge.cache_igverts[mid_vert_ind]
        position_3d = mid_vert.position + 1.5 * mid_vert.tangent_y * mid_vert.radius
    else:
        position_3d = (gedge.gvert0.position + gedge.gvert3.position)/2
    
    position_2d = location_3d_to_region_2d(context.region, context.space_data.region_3d,position_3d)
    txt_width, txt_height = blf.dimensions(0, text)
    blf.position(0, position_2d[0]-(txt_width/2), position_2d[1]-(txt_height/2), 0)
    blf.draw(0, text)

def draw_gedge_info(gedge,context):
    '''
    helper draw module to display info about the Gedge
    '''
    l = len(gedge.cache_igverts)
    if l > 4:
        n_quads = math.floor(l/2) + 1
    else:
        n_quads = 3
    draw_gedge_text(gedge, context, str(n_quads))
