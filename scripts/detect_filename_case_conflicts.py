#!/usr/bin/python3

import os
import sys
import glob

issue = False

def check(path):
    global issue
    pwd = os.getcwd()
    os.chdir(path)
    filenames = set(glob.glob('*'))
    lfilenames = {}
    for f in filenames:
        lfilenames.setdefault(f.lower(), [])
        lfilenames[f.lower()].append(f)
    if any(len(v)>1 for k,v in lfilenames.items()):
        issue = True
        print(f'Issues detected in {path}')
        for k,v in lfilenames.items():
            if len(v) == 1: continue
            for f in v: print(f'  {f}')
    for f in filenames:
        if not os.path.isdir(f): continue
        check(os.path.join(path, f))
    os.chdir(pwd)

check(os.path.abspath('.'))

sys.exit(1 if issue else 0)
