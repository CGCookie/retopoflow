#!/usr/bin/python3

import os
import sys
import glob
import subprocess

w,h = 120,120

for fn in glob.glob('*.png'):
    if fn.endswith('.thumb.png'): continue
    nfn = f'{os.path.splitext(fn)[0]}.thumb.png'
    subprocess.call(f'convert "{fn}" -resize {w}x{h} "{nfn}"', shell=True)
