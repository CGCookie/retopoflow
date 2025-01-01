#!/usr/bin/python3

import os
import re
import sys
import ast
import json

if len(sys.argv) not in {2,3}:
    print(f'Usage: {sys.argv[0]} key <default>')
    sys.exit(1)

path = os.path.join(os.path.dirname(__file__), '..', '__init__.py')
init = open(path, 'rt').read()
p = ast.parse(init)

bl_info = next(
    b for b in p.body
    if isinstance(b, ast.Assign)
    and b.targets[0].id == 'bl_info'
    and isinstance(b.value, ast.Dict)
).value

for k,v in zip(bl_info.keys, bl_info.values):
    if k.value != sys.argv[1]: continue

    v = ast.unparse(v)
    v = re.sub(r'[ ()\']', '', v)
    v = re.sub(r',', '.', v)
    print(v)
    # if isinstance(v, ast.Constant):
    #     print(ast.unparse(v))
    # elif isinstance(v, ast.Tuple):
    #     print()
    break

else:
    # key did not exist
    if len(sys.argv) == 3:
        # print default
        print(sys.argv[2])
    else:
        assert False, f'Could not find key {k}'
