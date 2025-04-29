from setuptools import setup, Extension, find_packages
from Cython.Build import cythonize
import numpy as np
import sys
import platform
import os
import subprocess
import shutil
from pathlib import Path
import argparse


# Structure of the compiled files to support multiple Blender versions:
'''
retopoflow/
├── compiled/
│   ├── b430/
│   │   └── retopoflow/
│   │       └── cy/
│   │           ├── target_accel.pyd
│   │           ├── rfmesh_accel.pyd
│   │           └── bl_types/
│   │               └── __init__.pyd
│   ├── b440/
│   │   └── retopoflow/
│   │       └── cy/
│   │           ├── target_accel.pyd
│   │           ├── rfmesh_accel.pyd
│   │           └── bl_types/
│   │               └── __init__.pyd
'''

# check if script was run with --dev flag.
DEV_BUILD = '--dev' in sys.argv
FORCE_BUILD = '--force' in sys.argv

# Parse known arguments before passing to setup
parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--dev', '-d', action='store_true', help='Enable development build features (like annotations)')
parser.add_argument('--force', '-f', action='store_true', help='Force clean before build')
parser.add_argument('--blender-version', '-b', type=str, required=True, help='Target Blender version (e.g., "4.3")')

# Use parse_known_args to separate our args from setup args
args, remaining_argv = parser.parse_known_args()
sys.argv = [sys.argv[0]] + remaining_argv

# Calculate BLENDER_VERSION_INT and OUTPUT_SUFFIX from args.blender_version
try:
    major_str, minor_str = args.blender_version.split('.')[:2]
    BLENDER_VERSION_INT = int(major_str) * 10 + int(minor_str)
    OUTPUT_SUFFIX = f"{major_str}{minor_str}"
    print(f"--- Detected Blender target version: {args.blender_version} -> Compile-time int: {BLENDER_VERSION_INT}, Output Suffix: {OUTPUT_SUFFIX} ---")
except ValueError:
    print(f"Error: Invalid Blender version format: {args.blender_version}. Expected X.Y (e.g., 4.3)")
    sys.exit(1)

if args.dev:
    addon_module_prefix = 'bl_ext.vscode_development'
else:
    addon_module_prefix = 'bl_ext.user_default'

numpy_extra_compile_args = {
    "include_dirs": [np.get_include()],
    "define_macros": [('NPY_NO_DEPRECATED_API', 'NPY_1_7_API_VERSION')]
}

# Define the compile-time environment for Cython (Kept for potential other uses, but not strictly needed for version anymore)
cython_compile_time_env = {
    'BLENDER_VERSION': BLENDER_VERSION_INT
}

def build_for_architecture(arch):
    """Build extensions for a specific architecture"""
    print(f"Building for architecture: {arch or 'default'}")

    output_base_dir = Path(f"retopoflow/compiled/b{OUTPUT_SUFFIX}")
    output_base_dir.mkdir(parents=True, exist_ok=True)

    # Symlink retopoflow/cy into the output dir so .pyd files follow the same structure
    compiled_target = output_base_dir / "retopoflow" / "cy"
    compiled_target.mkdir(parents=True, exist_ok=True)

    # add __init__.py file to the compiled target module.
    (compiled_target / '__init__.py').touch(exist_ok=True)

    # Base compiler flags for all platforms
    compiler_flags = {
        'Windows': ['/O2', '/std:c++17', '/EHsc'],  # Added /EHsc for Windows
        'Darwin': ['-O3', '-std=c++17'],
        'Linux': ['-O3', '-std=c++17']
    }

    # Get base optimization flag for current platform
    system = platform.system()
    extra_compile_args = compiler_flags.get(system, ['-O3', '-std=c++17'])
    extra_link_args = []

    # Add debug output
    print(f"System: {system}")
    print(f"Compiler flags: {extra_compile_args}")

    # Add architecture flags only for macOS
    if platform.system() == 'Darwin' and arch:
        # Let ARCHFLAGS environment variable handle the architecture
        # Don't add -arch flag directly to compile/link args
        if 'ARCHFLAGS' not in os.environ:
            os.environ['ARCHFLAGS'] = f'-arch {arch}'
        # Set platform tag for proper naming
        os.environ['PLAT_NAME'] = f'darwin-{arch}'

    # Create a *copy* of the shared args for this architecture build
    current_extra_compile_args = list(extra_compile_args) # Use list() to copy
    current_extra_link_args = list(extra_link_args) # Use list() to copy

    # Keep language specifier separate for clarity
    lang = 'c++'

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

    # Function to check if a .pyx file uses atomic.
    def uses_atomic(file_path):
        with open(file_path, 'r') as f:
            # Only check first 50 lines where imports typically are
            for i, line in enumerate(f):
                if i > 50:  # Stop after checking first 50 lines
                    break
                if any(atomic_import in line for atomic_import in [
                    'from libcpp.atomic',
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
            ext_kwargs = {
                'extra_compile_args': list(current_extra_compile_args), # Copy args for this specific extension
                'extra_link_args': list(current_extra_link_args),
                'define_macros': [], # Start with version macro
                'language': lang
            }

            # Add numpy kwargs only if the file uses numpy.
            if uses_numpy(file_path):
                ext_kwargs['include_dirs'] = numpy_extra_compile_args["include_dirs"]
                # Add numpy define macros to the existing list
                ext_kwargs['define_macros'].extend(numpy_extra_compile_args["define_macros"])

            if uses_atomic(file_path):
                if system == 'Windows':
                    # For Windows, only add /openmp to compiler flags
                    # The compiler (MSVC) takes care of linking to the OpenMP library automatically
                    ext_kwargs['extra_compile_args'].append('/openmp')
                else:
                    # For non-Windows platforms, add -fopenmp to both
                    flag = '-fopenmp'
                    ext_kwargs['extra_compile_args'].append(flag)
                    ext_kwargs['extra_link_args'].append(flag)

            ext_modules.append(
                Extension(
                    module_name,
                    sources=[module_path],
                    **ext_kwargs
                )
            )

    create_extensions_from_pyx_files()

    # Build extensions
    setup(
        name="retopoflow",
        packages=[
            "retopoflow.cy",
            "retopoflow.cy.bl_types",
        ],
        ext_modules=cythonize(ext_modules,
                            annotate=args.dev, # Use parsed arg
                            compiler_directives={
                                'language_level': 3,
                                'boundscheck': False,
                                'wraparound': False,
                            },
                            compile_time_env=cython_compile_time_env,
                            force=args.force, # Use parsed arg
                            ),
        zip_safe=False,
    )

    if platform.system() == 'Darwin':
        # find all compiled files and rename them to include the platform tag
        for file in os.listdir("retopoflow/cy"):
            if file.endswith('darwin.so'):
                os.rename(f"retopoflow/cy/{file}", f"retopoflow/cy/{file.split('.')[0]}-{os.environ['PLAT_NAME']}.so")

    print(f"Moving compiled files to {compiled_target}")
    for ext in ['.so', '.pyd']:
        for file in Path("retopoflow/cy").rglob(f'*{ext}'):
            rel_path = file.relative_to("retopoflow/cy")
            dest = compiled_target / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(file), str(dest))
            print(f"Moved {file} -> {dest}")



def clean_cython_cache(cy_dir):
    """Clean Cython cache and build files for --inplace builds.

    Removes intermediate files (.c, .cpp, .h, __pycache__) from the source cy_dir.
    Removes compiled files (.so, .pyd) ONLY from the target version's compiled directory.
    Does NOT remove the top-level 'build' directory as it's not typically used with --inplace.
    """
    if not os.path.exists(cy_dir) or not os.path.isdir(cy_dir):
        return

    # Remove intermediate C/C++ files from source directories
    print("Removing intermediate C/C++ files from source...")
    for ext in ['.c', '.cpp', '.h']:
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

def switch_bl_types_pxd(blender_version_str):
    """Switch the bl_types/__init__.pxd file to the correct version for the given Blender version."""
    major, minor = blender_version_str.split('.')
    version_key = f"b{major}{minor}"
    version_file = Path(f"retopoflow/cy/bl_types/{version_key}.pxd")
    shared_file = Path("retopoflow/cy/bl_types/_shared.pxd")
    init_pxd = Path("retopoflow/cy/bl_types/__init__.pxd")

    if not version_file.exists():
        raise FileNotFoundError(f"Missing version-specific .pxd: {version_file}")

    print(f"[bl_types] Using versioned .pxd: {version_file.name}")
    with init_pxd.open("w") as f:
        # Write the shared .pxd first, then the version-specific .pxd.
        f.write(shared_file.read_text())
        f.write(version_file.read_text())


def main():
    cy_dir = os.path.abspath("retopoflow/cy")
    compiled_version_dir = os.path.abspath(f"retopoflow/compiled/b{OUTPUT_SUFFIX}")
    print(f"Cython directory: {cy_dir}")

    # Clean cache if --force flag is present
    if args.force:
        clean_cython_cache(cy_dir)
        clean_cython_cache(compiled_version_dir)

    # Create missing __init__.pyx files if needed
    for module_dir in ["retopoflow/cy", "retopoflow/cy/bl_types"]:
        init_pyx = os.path.join(module_dir, "__init__.pyx")
        if not os.path.exists(init_pyx):
            with open(init_pyx, "w") as f:
                f.write("# distutils: language=c++\n# cython: language_level=3\n")
            print(f"Created {init_pyx}")

    # Set the correct bl_types/__init__.pxd for this Blender version
    switch_bl_types_pxd(args.blender_version)
    
    # Build the cython modules for the current Blender version and architecture
    system = platform.system()

    if system == 'Darwin':  # macOS
        # Check if specific architecture is requested
        target_arch = os.environ.get('TARGET_ARCH')

        if target_arch:
            # Build for specific architecture
            build_for_architecture(target_arch)
        else:
            # This block is likely NOT executed when run via the GitHub Action,
            # because the action sets TARGET_ARCH. Commenting out to avoid confusion.
            # # Build for both architectures on Apple Silicon Mac
            # if platform.machine() == 'arm64':
            #     print("Building universal binaries (arm64 + x86_64)")
            #     build_for_architecture('arm64')
            #     build_for_architecture('x86_64')
            # else:
            #     print("Building only x86_64 binary (Intel Mac)")
            #     build_for_architecture('x86_64')
            # If TARGET_ARCH is not set, default to native architecture (or handle error)
            print("Warning: TARGET_ARCH not set, building for native architecture only.")
            native_arch = platform.machine() # e.g., 'arm64' or 'x86_64'
            build_for_architecture(native_arch)
    else:
        # For non-macOS platforms, use regular build without arch flags
        build_for_architecture(None)

if __name__ == '__main__':
    try:
        main()
        print("--- cy_setup.py finished successfully ---")
    except Exception as e:
        print(f"Error during build process: {e}")
        # Optional: Add traceback print here if needed for debugging setup() errors
        # import traceback
        # traceback.print_exc()
        sys.exit(1)
