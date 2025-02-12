from setuptools import setup, Extension, find_packages
from Cython.Build import cythonize
import numpy as np
import sys
import platform
import os
import subprocess


def build_for_architecture(arch):
    """Build extensions for a specific architecture"""
    print(f"Building for architecture: {arch}")
    
    # Base compiler flags for all platforms
    compiler_flags = {
        'Windows': ['/O2'],
        'Darwin': ['-O3'],  # macOS
        'Linux': ['-O3']
    }
    
    # Get base optimization flag for current platform
    extra_compile_args = compiler_flags.get(platform.system(), ['-O3'])
    extra_link_args = []
    
    # Add architecture flags only for macOS
    if platform.system() == 'Darwin' and arch:
        # Let ARCHFLAGS environment variable handle the architecture
        # Don't add -arch flag directly to compile/link args
        if 'ARCHFLAGS' not in os.environ:
            os.environ['ARCHFLAGS'] = f'-arch {arch}'

    shared_ext_kwargs = {
        'extra_compile_args': extra_compile_args,
        'extra_link_args': extra_link_args,
        'language': 'c++'
    }
    
    np_ext_kwargs = {
        "include_dirs": [np.get_include()],
        "define_macros": [('NPY_NO_DEPRECATED_API', 'NPY_1_7_API_VERSION')],
    }
    
    # Define extension modules
    ext_modules = [
        Extension(
            f"retopoflow.cy.rfmesh_visibility",
            sources=["retopoflow/cy/rfmesh_visibility.pyx"],
            **shared_ext_kwargs,
            **np_ext_kwargs
        ),
        Extension(
            f"retopoflow.cy.bmesh_utils",
            sources=["retopoflow/cy/bmesh_utils.pyx"],
            **shared_ext_kwargs
        )
    ]
    
    # Build extensions
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

def main():
    system = platform.system()
    
    if system == 'Darwin':  # macOS
        # Check if specific architecture is requested
        target_arch = os.environ.get('TARGET_ARCH')
        
        if target_arch:
            # Build for specific architecture
            build_for_architecture(target_arch)
        else:
            # Build for both architectures on Apple Silicon Mac
            if platform.machine() == 'arm64':
                print("Building universal binaries (arm64 + x86_64)")
                build_for_architecture('arm64')
                build_for_architecture('x86_64')
            else:
                print("Building only x86_64 binary (Intel Mac)")
                build_for_architecture('x86_64')
    else:
        # For non-macOS platforms, use regular build without arch flags
        build_for_architecture(None)

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
