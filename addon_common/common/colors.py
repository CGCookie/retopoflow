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

from mathutils import Vector, Color


#####################################################################################
# below are various token converters

# dictionary to convert color name to color values, either (R,G,B) or (R,G,B,a)
# https://www.quackit.com/css/css_color_codes.cfm

colorname_to_color = {
    'transparent': (0, 0, 0, 0),

    # https://www.quackit.com/css/css_color_codes.cfm
    'indianred': (205,92,92),
    'lightcoral': (240,128,128),
    'salmon': (250,128,114),
    'darksalmon': (233,150,122),
    'lightsalmon': (255,160,122),
    'crimson': (220,20,60),
    'red': (255,0,0),
    'firebrick': (178,34,34),
    'darkred': (139,0,0),
    'pink': (255,192,203),
    'lightpink': (255,182,193),
    'hotpink': (255,105,180),
    'deeppink': (255,20,147),
    'mediumvioletred': (199,21,133),
    'palevioletred': (219,112,147),
    'coral': (255,127,80),
    'tomato': (255,99,71),
    'orangered': (255,69,0),
    'darkorange': (255,140,0),
    'orange': (255,165,0),
    'gold': (255,215,0),
    'yellow': (255,255,0),
    'lightyellow': (255,255,224),
    'lemonchiffon': (255,250,205),
    'lightgoldenrodyellow': (250,250,210),
    'papayawhip': (255,239,213),
    'moccasin': (255,228,181),
    'peachpuff': (255,218,185),
    'palegoldenrod': (238,232,170),
    'khaki': (240,230,140),
    'darkkhaki': (189,183,107),
    'lavender': (230,230,250),
    'thistle': (216,191,216),
    'plum': (221,160,221),
    'violet': (238,130,238),
    'orchid': (218,112,214),
    'fuchsia': (255,0,255),
    'magenta': (255,0,255),
    'mediumorchid': (186,85,211),
    'mediumpurple': (147,112,219),
    'blueviolet': (138,43,226),
    'darkviolet': (148,0,211),
    'darkorchid': (153,50,204),
    'darkmagenta': (139,0,139),
    'purple': (128,0,128),
    'rebeccapurple': (102,51,153),
    'indigo': (75,0,130),
    'mediumslateblue': (123,104,238),
    'slateblue': (106,90,205),
    'darkslateblue': (72,61,139),
    'greenyellow': (173,255,47),
    'chartreuse': (127,255,0),
    'lawngreen': (124,252,0),
    'lime': (0,255,0),
    'limegreen': (50,205,50),
    'palegreen': (152,251,152),
    'lightgreen': (144,238,144),
    'mediumspringgreen': (0,250,154),
    'springgreen': (0,255,127),
    'mediumseagreen': (60,179,113),
    'seagreen': (46,139,87),
    'forestgreen': (34,139,34),
    'green': (0,128,0),
    'darkgreen': (0,100,0),
    'yellowgreen': (154,205,50),
    'olivedrab': (107,142,35),
    'olive': (128,128,0),
    'darkolivegreen': (85,107,47),
    'mediumaquamarine': (102,205,170),
    'darkseagreen': (143,188,143),
    'lightseagreen': (32,178,170),
    'darkcyan': (0,139,139),
    'teal': (0,128,128),
    'aqua': (0,255,255),
    'cyan': (0,255,255),
    'lightcyan': (224,255,255),
    'paleturquoise': (175,238,238),
    'aquamarine': (127,255,212),
    'turquoise': (64,224,208),
    'mediumturquoise': (72,209,204),
    'darkturquoise': (0,206,209),
    'cadetblue': (95,158,160),
    'steelblue': (70,130,180),
    'lightsteelblue': (176,196,222),
    'powderblue': (176,224,230),
    'lightblue': (173,216,230),
    'skyblue': (135,206,235),
    'lightskyblue': (135,206,250),
    'deepskyblue': (0,191,255),
    'dodgerblue': (30,144,255),
    'cornflowerblue': (100,149,237),
    'royalblue': (65,105,225),
    'blue': (0,0,255),
    'mediumblue': (0,0,205),
    'darkblue': (0,0,139),
    'navy': (0,0,128),
    'midnightblue': (25,25,112),
    'cornsilk': (255,248,220),
    'blanchedalmond': (255,235,205),
    'bisque': (255,228,196),
    'navajowhite': (255,222,173),
    'wheat': (245,222,179),
    'burlywood': (222,184,135),
    'tan': (210,180,140),
    'rosybrown': (188,143,143),
    'sandybrown': (244,164,96),
    'goldenrod': (218,165,32),
    'darkgoldenrod': (184,134,11),
    'peru': (205,133,63),
    'chocolate': (210,105,30),
    'saddlebrown': (139,69,19),
    'sienna': (160,82,45),
    'brown': (165,42,42),
    'maroon': (128,0,0),
    'white': (255,255,255),
    'snow': (255,250,250),
    'honeydew': (240,255,240),
    'mintcream': (245,255,250),
    'azure': (240,255,255),
    'aliceblue': (240,248,255),
    'ghostwhite': (248,248,255),
    'whitesmoke': (245,245,245),
    'seashell': (255,245,238),
    'beige': (245,245,220),
    'oldlace': (253,245,230),
    'floralwhite': (255,250,240),
    'ivory': (255,255,240),
    'antiquewhite': (250,235,215),
    'linen': (250,240,230),
    'lavenderblush': (255,240,245),
    'mistyrose': (255,228,225),
    'gainsboro': (220,220,220),
    'lightgray': (211,211,211),
    'lightgrey': (211,211,211),
    'silver': (192,192,192),
    'darkgray': (169,169,169),
    'darkgrey': (169,169,169),
    'gray': (128,128,128),
    'grey': (128,128,128),
    'dimgray': (105,105,105),
    'dimgrey': (105,105,105),
    'lightslategray': (119,136,153),
    'lightslategrey': (119,136,153),
    'slategray': (112,128,144),
    'slategrey': (112,128,144),
    'darkslategray': (47,79,79),
    'darkslategrey': (47,79,79),
    'black': (0,0,0),
}


class Color4(Vector):
    @staticmethod
    def from_ints(r, g, b, a=255):
        return Color4((r/255.0, g/255.0, b/255.0, a/255.0))

    @staticmethod
    def from_color(c:Color, *, a=1.0):
        return Color4((c.r, c.g, c.b, a))

    def as_color(self, *, premultiply=False):
        a = self.a if premultiply else 1.0
        return Color((self.r * a, self.g * a, self.b * a))

    def as_vector(self, *, length=4):
        return Vector(self) if length==4 else Vector(self[:length])

    def from_vector(self, v):
        if len(v) == 3: self.r, self.g, self.b = v
        else: self.r, self.g, self.b, self.a = v

    @staticmethod
    def HSL(hsl):
        # https://en.wikipedia.org/wiki/HSL_and_HSV
        # 0 <= H < 1 (circular), 0 <= S <= 1, 0 <= L <= 1
        if len(hsl) == 3: h,s,l,a = *hsl, 1.0
        else:             h,s,l,a = hsl

        h = (h % 1) * 6
        s = clamp(s, 0, 1)
        l = clamp(l, 0, 1)
        a = clamp(a, 0, 1)

        c = (1 - abs(2 * l - 1)) * s
        x = c * (1 - abs(h % 2 - 1))
        m = l - c / 2

        if   h < 1: r,g,b = c,x,0
        elif h < 2: r,g,b = x,c,0
        elif h < 3: r,g,b = 0,c,x
        elif h < 4: r,g,b = 0,x,c
        elif h < 5: r,g,b = x,0,c
        else:       r,g,b = c,0,x

        r += m
        g += m
        b += m

        return Color4((r, g, b, a))

    @property
    def r(self): return self.x
    @r.setter
    def r(self, v): self.x = v

    @property
    def g(self): return self.y
    @g.setter
    def g(self, v): self.y = v

    @property
    def b(self): return self.z
    @b.setter
    def b(self, v): self.z = v

    @property
    def a(self): return self.w
    @a.setter
    def a(self, v): self.w = v

    @property
    def hsl(self):
        # https://en.wikipedia.org/wiki/HSL_and_HSV#From_RGB
        # 0 <= H < 1 (circular), 0 <= S <= 1, 0 <= L <= 1
        r, g, b = self.x, self.y, self.z
        x_max, x_min = max(r, g, b), min(r, g, b)
        c = x_max - x_min
        l = (x_max + x_min) / 2.0
        h = 0
        if c > 0:
            if   x_max == r: h = (60 / 360) * (((g - b) / c) % 6)
            elif x_max == g: h = (60 / 360) * (((b - r) / c) + 2)
            else:            h = (60 / 360) * (((r - g) / c) + 4)
        s = (x_max - l) / min(l, 1 - l) if 0 < l < 1 else 0
        return (h, s, l)

    def rotated_hue(self, hue_add):
        h,s,l = self.hsl
        return Color4.HSL((h + hue_add, s, l))

    def __str__(self):
        # return '<Color (%0.4f, %0.4f, %0.4f, %0.4f)>' % (self.r, self.g, self.b, self.a)
        return f'Color4({self.r:0.2f}, {self.g:0.2f}, {self.b:0.2f}, {self.a:0.2f})'

    def __repr__(self):
        return self.__str__()

    def __mul__(self, other):
        t = type(other)
        if t is float or t is int:
            return Color4((other * self.r, other * self.g, other * self.b, self.a))
        if t is Color:
            return Color4((self.r * other.r, self.g * other.g, self.b * other.b, self.a))
        if t is Color4:
            return Color4((self.r * other.r, self.g * other.g, self.b * other.b, self.a * other.a))
        assert False, f"unhandled type of other: {other} ({t})"

    def __rmul__(self, other):
        return self.__mul__(other)

# set colornames in Color, ex: Color.white, Color.black, Color.transparent
for colorname in colorname_to_color.keys():
    c = colorname_to_color[colorname]
    c = (c[0]/255, c[1]/255, c[2]/255, 1.0 if len(c)==3 else c[3])
    setattr(Color4, colorname, Color4(c))
