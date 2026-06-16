import ctypes
from ctypes import c_double, c_int
import os
import subprocess
from pathlib import Path
import shutil

path_v = shutil.which('v')
assert path_v
path_here = Path(__file__).parent
path_source = path_here / 'nearestv.v'
path_module = path_here / 'nearestv.so'

if not path_module.exists() or True:
    # v -os windows ...
    # v -os linux   ...
    # v -os freebsd ...
    subprocess.run(f'{path_v} -enable-globals -cg -shared -o "{path_module}" "{path_source}"', shell=True)

#so_file = os.path.join(os.path.split(__file__)[0], 'nearestv.dll' if os.name == 'nt' else 'nearestv.so')
lib = ctypes.CDLL(str(path_module))
size = lib.size()
lib.next.restype = ctypes.POINTER(c_int * size)

class Nearest:
    @staticmethod
    def clear():
        lib.clear()

    @staticmethod
    def add(co):
        x,y,z = co
        lib.add(c_double(x), c_double(y), c_double(z))

    @staticmethod
    def find(co, radius):
        x,y,z = co
        found = lib.find(c_double(x), c_double(y), c_double(z), c_double(radius))
        print(found)
        indices = []
        while lib.hasnext():
            indices.extend(i for i in lib.next() if i != -1)
        print(indices)
