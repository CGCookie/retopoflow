import os
import pickle
from ..ext import png

path_icons = os.path.join(os.path.dirname(__file__), '..', 'icons')

def get_image_path(fn, ext=''):
    if ext: fn = '%s.%s' % (fn,ext)
    return os.path.join(path_icons, fn)

def load_image_png(fn):
    #import png
    # assuming 4 channels per pixel!
    w,h,d,m = png.Reader(get_image_path(fn)).read()
    return [[r[i:i+4] for i in range(0,w*4,4)] for r in d]
    return icon

def write_image_bin(fn, image):
    path = get_image_path(fn, 'bin')
    pickle.dump(image, open(path, 'wb'))

def load_image_bin(fn):
    path = get_image_path(fn, 'bin')
    return pickle.load(open(path, 'rb'))


if __name__ == '__main__':
    '''
    Run this program if any of the icons/*.png files are modified
    > python3 load_image.py
    '''
    import glob
    fns = glob.glob(os.path.join(path_icons, '*.png'))
    for fn in fns:
        fn = os.path.basename(fn)
        print('processing: %s' % fn)
        img = load_image_png(fn)
        write_image_bin(fn, img)
