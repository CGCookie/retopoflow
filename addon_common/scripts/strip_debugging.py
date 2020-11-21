#!/usr/bin/python3

import os
import re
import sys
import glob

if len(sys.argv) < 2 or sys.argv[1] != 'YES!':
    print('CAUTION: running this will alter **ALL** .py files in every subdirectory!')
    print('To ensure you are certain you want to run it, call %s again with the argument "YES!"' % sys.argv[0])
    sys.exit(1)


re_function = re.compile(r'\n(?P<indent> *)(?P<pr>@profiler\.function)\n')
re_add_note = re.compile(r'\n(?P<indent> *)(?P<pr>profiler\.add_note\(.*?\))\n')
re_withcode = re.compile(r'\n(?P<indent> *)(?P<pr>with profiler\.code\(.*?\)( +as +.*?)?:)\n')
re_dprint   = re.compile(r'\n(?P<indent> *)(?P<dp>(Debugger\.)?dprint\(.*?\))\n')

ignore_pyfiles = {
    'profiler.py',
    'debug.py',
}
ignore_folders = {
    '__pycache__',
}

def go(root):
    for fn in glob.glob('*.py'):
        if fn in ignore_pyfiles: continue
        f = open(fn, 'rt').read()
        of = str(f)
        while True:
            m = re_function.search(f)
            if not m: break
            replace = '\n%s# %s\n' % (m.group('indent'), m.group('pr'))
            f = f[:m.start()] + replace + f[m.end():]
        while True:
            m = re_add_note.search(f)
            if not m: break
            replace = '\n%s# %s\n' % (m.group('indent'), m.group('pr'))
            f = f[:m.start()] + replace + f[m.end():]
        while True:
            m = re_withcode.search(f)
            if not m: break
            replace = '\n%sif True: # %s\n' % (m.group('indent'), m.group('pr'))
            f = f[:m.start()] + replace + f[m.end():]
        while True:
            m = re_dprint.search(f)
            if not m: break
            replace = '\n%s# %s\n%spass\n' % (m.group('indent'), m.group('dp'), m.group('indent'))
            f = f[:m.start()] + replace + f[m.end():]
        if f == of: continue
        open(fn, 'wt').write(f)

    for fn in glob.glob('*'):
        if not os.path.isdir(fn): continue
        if fn in ignore_folders: continue
        os.chdir(fn)
        go(os.path.join(root, fn))
        os.chdir('..')

go('.')