from setuptools import setup, Extension, find_packages
from Cython.Build import cythonize
import numpy as np
import sys
import platform
import os
import subprocess


numpy_extra_compile_args = {
    "include_dirs": [np.get_include()],
    "define_macros": [('NPY_NO_DEPRECATED_API', 'NPY_1_7_API_VERSION')]
}


def build_for_architecture(arch):
    """Build extensions for a specific architecture"""
    print(f"Building for architecture: {arch}")

    # Base compiler flags for all platforms
    compiler_flags = {
        'Windows': ['/O2', '/std:c++17'],  # MSVC flags
        'Darwin': ['-O3', '-std=c++17'],   # macOS/Clang flags
        'Linux': ['-O3', '-std=c++17']     # Linux/GCC flags
    }

    # Get base optimization flag for current platform
    extra_compile_args = compiler_flags.get(platform.system(), ['-O3', '-std=c++17'])
    extra_link_args = []

    # Add architecture flags only for macOS
    if platform.system() == 'Darwin' and arch:
        # Let ARCHFLAGS environment variable handle the architecture
        # Don't add -arch flag directly to compile/link args
        if 'ARCHFLAGS' not in os.environ:
            os.environ['ARCHFLAGS'] = f'-arch {arch}'
        # Set platform tag for proper naming
        os.environ['PLAT_NAME'] = f'darwin-{arch}'

    shared_ext_kwargs = {
        'extra_compile_args': extra_compile_args,
        'extra_link_args': extra_link_args,
        'language': 'c++'
    }

    # Function to check if a .pyx file uses numpy.
    def uses_numpy(file_path):
        with open(file_path, 'r') as f:
            # Only check first 50 lines where imports typically are
            for i, line in enumerate(f):
                if i > 50:  # Stop after checking first 50 lines
                    break
                if any(numpy_import in line for numpy_import in [
                    'cimport numpy',
                    'import numpy',
                    'from numpy'
                ]):
                    return True
        return False

    # Automatically discover all .pyx files.
    cy_dir = "retopoflow/cy"
    ext_modules = []
    print("Found .pyx files:", [f for f in os.listdir(cy_dir) if f.endswith('.pyx')])
    for file in os.listdir(cy_dir):
        if file.endswith('.pyx'):
            module_name = f"retopoflow.cy.{file[:-4]}"  # Remove .pyx extension.
            file_path = os.path.join(cy_dir, file)

            # Build extension kwargs.
            ext_kwargs = {**shared_ext_kwargs}

            # Add numpy kwargs only if the file uses numpy.
            if uses_numpy(file_path):
                ext_kwargs.update(numpy_extra_compile_args)

            ext_modules.append(
                Extension(
                    module_name,
                    sources=[file_path],
                    **ext_kwargs
                )
            )

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

    if platform.system() == 'Darwin':
        # find all compiled files and rename them to include the platform tag
        for file in os.listdir("retopoflow/cy"):
            if file.endswith('darwin.so'):
                os.rename(f"retopoflow/cy/{file}", f"retopoflow/cy/{file.split('.')[0]}-{os.environ['PLAT_NAME']}.so")


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
