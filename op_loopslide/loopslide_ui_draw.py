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


class loopslide_UI_Draw():
    
    def draw_postview(self, context):
        ''' Place post view drawing code in here '''
        settings = common_utilities.get_settings()
        color_active = settings.theme_colors_active[settings.theme]
        lpoints = self.loopslide.vert_snaps_world
            
        color_border = (color_active[0], color_active[1], color_active[2], 1.00)
        color_right = (color_active[2], color_active[1], color_active[0], .75)
        
        if len(lpoints) == 0: return

        if self.loopslide.cyclic:
            common_drawing_view.draw3d_closed_polylines(context, [lpoints], color_border, 2, 'GL_LINES')
            #common_drawing_view.draw3d_closed_polylines(context, [rpoints], color_right, 2, 'GL_LINES')
        else:
            common_drawing_view.draw3d_polyline(context, lpoints, color_border, 2, 'GL_LINES')
            
            if self.loopslide.pole0 != -1 and self.loopslide.pole0world:
                common_drawing_view.draw3d_polyline(context, [self.loopslide.pole0world, lpoints[0]], (1,0,0,1), 2, 'GL_LINES')
                common_drawing_view.draw3d_points(context, [self.loopslide.pole0world], (1,0,0,1), 2)
            if self.loopslide.pole1 != -1 and self.loopslide.pole1world:
                common_drawing_view.draw3d_polyline(context,[lpoints[-1], self.loopslide.pole1world],(1,0,0,1), 2, 'GL_LINES')
                common_drawing_view.draw3d_points(context, [self.loopslide.pole1world], (1,0,0,1), 2)
                
            #common_drawing_view.draw3d_polyline(context, rpoints, color_right, 2, 'GL_LINES')
        return
    
    