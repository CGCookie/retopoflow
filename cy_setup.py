from setuptools import setup, Extension, find_packages
from Cython.Build import cythonize
import numpy as np
import sys
import platform
import os

# Platform-specific compiler flags
compiler_flags = {
    'Windows': ['/O2'],
    'Darwin': ['-O3'],  # macOS
    'Linux': ['-O3'],
}

# Get the current platform
current_platform = platform.system()

# Base compiler flags
extra_compile_args = compiler_flags.get(current_platform, ['-O3'])

# Handle macOS cross-compilation
if current_platform == 'Darwin' and os.environ.get('ARCHFLAGS'):
    extra_compile_args.extend(os.environ['ARCHFLAGS'].split())

shared_ext_kwargs = {
    'extra_compile_args': extra_compile_args,
    'language': 'c++'
}

if current_platform == 'Darwin':
    shared_ext_kwargs['extra_link_args'] = extra_compile_args

np_ext_kwargs = {
    "include_dirs": [np.get_include()],
    "define_macros": [('NPY_NO_DEPRECATED_API', 'NPY_1_7_API_VERSION')],
}

ext_modules = [
    Extension(
        "retopoflow.cy.rfmesh_visibility",
        sources=["retopoflow/cy/rfmesh_visibility.pyx"],
        **shared_ext_kwargs,
        **np_ext_kwargs
    ),
    Extension(
        "retopoflow.cy.bmesh_utils",
        sources=["retopoflow/cy/bmesh_utils.pyx"],
        **shared_ext_kwargs
    )
]

try:
    setup(
        name="retopoflow",
        packages=find_packages(),
        ext_modules=cythonize(ext_modules, 
                            annotate=True,
                            compiler_directives={
                                'language_level': 3,
                                'boundscheck': False,
                                'wraparound': False,
                            }),
        zip_safe=False,
    )
except Exception as e:
    print(f"Error: {e}")
