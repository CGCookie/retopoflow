#!/usr/bin/python3

import os
import sys
import json

if len(sys.argv) != 2:
    print(f'Usage: {sys.argv[0]} key')
    sys.exit(1)

hive_path = os.path.join(os.path.dirname(__file__), '..', 'hive.json')
hive = json.load(open(hive_path, 'rt'))

print(hive[sys.argv[1]])
