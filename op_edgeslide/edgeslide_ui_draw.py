'''
Copyright (C) 2015 CG Cookie
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

# Common imports
from ..lib import common_utilities
from ..lib import common_drawing_view


class EdgeSlide_UI_Draw():
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        settings = common_utilities.get_settings()
        color_active = settings.theme_colors_active[settings.theme]
        lpoints = self.edgeslide.vert_snaps_world
        rpoints = self.edgeslide.world_right
        color_border = (color_active[0], color_active[1], color_active[2], 1.00)
        color_right = (color_active[2], color_active[1], color_active[0], .75)
        
        if len(lpoints) == 0: return
        if self.edgeslide.cyclic:
            common_drawing_view.draw3d_closed_polylines(context, [lpoints], color_border, 2, 'GL_LINES')
            #common_drawing_view.draw3d_closed_polylines(context, [rpoints], color_right, 2, 'GL_LINES')
        else:
            common_drawing_view.draw3d_polyline(context, lpoints, color_border, 2, 'GL_LINES')
            #common_drawing_view.draw3d_polyline(context, rpoints, color_right, 2, 'GL_LINES')
        return
    
    