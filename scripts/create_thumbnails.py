#!/usr/bin/python3

import os
import png
import sys
import glob
import shutil
import subprocess

w,h = 120,120
tempfn = '_temporary.thumb.png'

def same_pngs(fnA, fnB):
    wA, hA, dA, mA = png.Reader(filename=fnA).read()
    wB, hB, dB, mB = png.Reader(filename=fnB).read()
    if (wA, hA) != (wB, hB): return False  # different sizes
    for rowA, rowB in zip(dA, dB):
        for colA, colB in zip(rowA, rowB):
            if colA != colB: return False
    # not checking meta data (mA == mB)
    # for example: ignoring the creation timestamp
    return True

for fullfn in glob.glob('*.png'):
    if fullfn.endswith('.thumb.png'):
        # do not thumb the thumb files!
        continue
    fullbase, _ = os.path.splitext(fullfn)
    thumbfn = f'{fullbase}.thumb.png'
    subprocess.call(f'convert "{fullfn}" -resize {w}x{h} "{tempfn}"', shell=True)
    if os.path.exists(thumbfn) and same_pngs(tempfn, thumbfn):
        # pixel data did not change
        os.remove(tempfn)
    else:
        shutil.move(tempfn, thumbfn)