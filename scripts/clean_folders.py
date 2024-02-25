#!/usr/bin/python3

import os
import sys
import glob
import pathlib

# delete python cache files
for p in pathlib.Path('.').rglob('*.py[co]'):
    p.unlink()
for p in pathlib.Path('.').rglob('__pycache__'):
    p.rmdir()

# delete empty folders
def isempty(path):
    # use os.scandir to see hidden files
    # in python 3.12, glob has inclued_hidden argument!
    return len(list(os.scandir(path))) == 0
def crawl(path):
    for fn in glob.glob(os.path.join(path, '*')):
        if not os.path.isdir(fn): continue
        if isempty(fn):
            # print(f'Empty {fn}')
            os.rmdir(fn)
        else:
            crawl(fn)
crawl('.')
