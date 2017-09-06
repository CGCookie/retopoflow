import os
import png

def load_icon(fn):
    # assuming 4 channels per pixel!
    w,h,d,m = png.Reader(os.path.join(os.path.dirname(__file__), '..', 'icons', fn)).read()
    icon = [[r[i:i+4] for i in range(0,w*4,4)] for r in d]
    return icon
