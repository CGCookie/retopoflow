#!/usr/bin/python3

import re
from datetime import date
from pathlib  import Path


year = f'{date.today().year:04d}'

ignore_dirs = {'.git', 'ext'}
update_exts = {'.py', '.glsl', '.css'}
ignore_exts = {'.ttf', '.exr', '.blend', '.pack', '.mtl', '.json', '.m4v', '.md', '.LICENSE', '.jpg', '.html', '.blend1', '.png', '.pyc', '.yml', '.gitignore', '.lock', '.scss', '.txt', '.obj', '', '.sh'}
unhandled_exts = set()
unhandled_paths = []


def process(p):
    global year, update_exts, unhandled_exts, unhandled_paths, ignore_exts, ignore_dirs
    if p.is_file():
        if p.stem.startswith('.'): return
        if p.suffix not in update_exts:
            if p.suffix in ignore_exts: return
            if p.suffix in unhandled_exts: return
            unhandled_exts.add(p.suffix)
            unhandled_paths.append(p)
            return
        orig = p.read_text()
        updated = re.sub(r'Copyright \(C\) (?P<year>\d+)', f'Copyright (C) {year}', orig)
        if orig == updated: return
        print(f'Updating: {p}')
        # print(updated)
        p.write_text(updated)
    elif p.is_dir():
        if p.stem in ignore_dirs: return
        for np in p.glob('*'):
            process(np)
    else:
        unhandled_paths.append(p)

process(Path('.'))
print()
print(f'Unhandled Extensions: {unhandled_exts}')
print(f'Unhandled Paths:')
print('\n'.join(f'- {p}' for p in unhandled_paths))