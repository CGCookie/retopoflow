"""
Converts all .png files in local folder to a format that does not require any extra libs
"""

from PIL import Image
import json
import glob

if __name__ == '__main__':
    data_lib = {}
    for fn in glob.glob('*.png'):
        im = Image.open(fn)
        pixels = im.load()
        w,h = im.size
        data = []
        for y in range(h):
            row = []
            for x in range(w):
                r,g,b,a = pixels[x,y]
                # row.append((r/255.0,g/255.0,b/255.0,a/255.0))
                row.append((r,g,b,a))
            data.append(row)
        data_lib[fn] = data

    with open('images.py','wt') as f:
        f.write('images = {}\n')
        for k,v in data_lib.items():
            j = json.dumps(v, separators=(',',':'))
            f.write('images["%s"] = %s\n' % (k,j))
        # f.write(json.dumps(data_lib, separators=(',',':')))
