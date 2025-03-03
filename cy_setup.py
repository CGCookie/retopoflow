from setuptools import setup, Extension, find_packages
from Cython.Build import cythonize
import numpy as np
import sys
import platform
import os
import subprocess
import shutil
from pathlib import Path

# check if script was run with --dev flag.
DEV_BUILD = '--dev' in sys.argv

if DEV_BUILD:
    index = sys.argv.index('--dev')
    sys.argv.pop(index)
    addon_module_prefix = 'bl_ext.vscode_development'
else:
    addon_module_prefix = 'bl_ext.user_default'


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

    cy_dir = "retopoflow/cy"
    ext_modules = []

    # Find all .pyx files recursively
    cy_path = Path(cy_dir)
    pyx_files = [file for file in cy_path.glob('**/*.pyx')]
    print("Found .pyx files:", pyx_files)

    def create_extensions_from_pyx_files():
        for file_path in pyx_files:
            filename = file_path.stem
            dirname = file_path.parent.name
            if dirname == 'cy':
                path = f"retopoflow.cy"
            else:
                path = f"retopoflow.cy.{dirname}"
            module_name = f"{path}.{filename}"
            module_path = f"{path.replace('.', '/')}/{filename}.pyx"
            
            print("Info: New Extension from module:", module_name, module_path)

            # Build extension kwargs.
            ext_kwargs = {**shared_ext_kwargs}

            # Add numpy kwargs only if the file uses numpy.
            if uses_numpy(file_path):
                ext_kwargs.update(numpy_extra_compile_args)

            ext_modules.append(
                Extension(
                    module_name,
                    sources=[module_path],
                    **ext_kwargs
                )
            )

    create_extensions_from_pyx_files()

    # Build extensions
    failed = False
    try:
        setup(
            name="retopoflow",
            packages=[
                "retopoflow.cy", 
                "retopoflow.cy.bl_types",
            ],
            ext_modules=cythonize(ext_modules, 
                                annotate=DEV_BUILD,
                                compiler_directives={
                                    'language_level': 3,
                                    'boundscheck': False,
                                    'wraparound': False,
                                }),
            zip_safe=False,
        )
    except Exception as e:
        print(f"Error: {e}")
        failed = True

    if not failed:
        if platform.system() == 'Darwin':
            # find all compiled files and rename them to include the platform tag
            for file in os.listdir("retopoflow/cy"):
                if file.endswith('darwin.so'):
                    os.rename(f"retopoflow/cy/{file}", f"retopoflow/cy/{file.split('.')[0]}-{os.environ['PLAT_NAME']}.so")


def clean_cython_cache(cy_dir):
    """Clean Cython cache and build files"""
    # Remove .c and .cpp files
    for ext in ['.c', '.cpp']:
        for file in Path(cy_dir).rglob(f'*{ext}'):
            file.unlink()
            print(f"Removed {file}")
    
    # Remove compiled .so or .pyd files
    for ext in ['.so', '.pyd']:
        for file in Path(cy_dir).rglob(f'*{ext}'):
            file.unlink()
            print(f"Removed {file}")
    
    # Remove __pycache__ directories
    for cache_dir in Path(cy_dir).rglob('__pycache__'):
        shutil.rmtree(cache_dir)
        print(f"Removed {cache_dir}")
    
    # Remove build directory if it exists
    build_dir = Path('build')
    if build_dir.exists():
        shutil.rmtree(build_dir)
        print("Removed build directory")


def main():
    cy_dir = os.path.abspath("retopoflow/cy")
    print(f"Cython directory: {cy_dir}")

    # Clean cache if --force flag is present
    if '--force' in sys.argv:
        clean_cython_cache(cy_dir)

    # Create missing __init__.pyx files if needed
    for module_dir in ["retopoflow/cy", "retopoflow/cy/bl_types"]:
        init_pyx = os.path.join(module_dir, "__init__.pyx")
        if not os.path.exists(init_pyx):
            with open(init_pyx, "w") as f:
                f.write("# distutils: language=c++\n# cython: language_level=3\n")
            print(f"Created {init_pyx}")

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
