#!/usr/bin/python3

import os
import re
import sys
import codecs

re_keymap = re.compile(r'{{(?P<key>.*?)}}')
re_options = re.compile(r'{\[(?P<key>.*?)\]}')
re_table = re.compile(r'\|(?P<pre> +)(?P<dashes>--+)(?P<post> +)\|')

def read_file(filename):
    try: return codecs.open(filename, encoding='utf-8').read()
    except: pass
    try: return codecs.open(filename, encoding='utf-16').read()
    except: pass
    return None


if len(sys.argv) != 2:
    print(f'Usage: {sys.argv[0]} [file.md]')
    sys.exit(1)

fn = sys.argv[1]
f = read_file(fn)

# convert keymaps {{something foo, bar}}  ==>  <var_something_foo/>, <var_bar/>
nf = []
for l in f.splitlines():
    while True:
        m = re_keymap.search(l)
        if not m: break
        keys = m.group('key').split(',')
        nkeys = []
        for key in keys:
            key = key.strip()
            key = key.replace(' ','_')
            key = f'<var_{key}/>'
            nkeys += [key]
        keys = ', '.join(nkeys)
        l = l[:m.start()] + keys + l[m.end():]
    nf += [l]
f = '\n'.join(nf)

# convert options  {[something foo]}  ==>  <var_something_foo/>
nf = []
for l in f.splitlines():
    while True:
        m = re_options.search(l)
        if not m: break
        key = m.group('key')
        key = key.strip()
        key = key.replace(' ', '_')
        key = f'<var_{key}/>'
        l = l[:m.start()] + key + l[m.end():]
    nf += [l]
f = '\n'.join(nf)

# convert tables | --- | --- | --- |  ==>  | :--- | :--- | :--- |
nf = []
for l in f.splitlines():
    while True:
        m = re_table.search(l)
        if not m: break
        l = l[:m.start()] + '|' + m.group('pre') + ':' + m.group('dashes') + m.group('post') + '|' + l[m.end():]
    nf += [l]
f = '\n'.join(nf)

f = f + '\n\n'

# print(type(f))
# print(f)

with open(fn, 'w') as fo:
    fo.write(f) #.encode('utf8'))
