#!/usr/bin/python3

import os
import shutil
import subprocess
import sys
import venv
from contextlib import contextmanager
from importlib.util import find_spec
from os.path import getmtime
from pathlib import Path
from subprocess import CompletedProcess

# try:
#     import bpy
#     assert False, f'xmesh: Cannot run from within Blender, because it does not have includes'
# except ModuleNotFoundError:
#     # expected!
#     pass



path_here = Path(__file__).parent

path_shell_python = Path(sys.executable)
path_system_python = shutil.which('python3')

path_source      = path_here / 'cpp'
path_subprojects = path_source / 'subprojects'
path_main        = path_source / 'xmesh.cpp'

path_venv = path_source / '.venv'
path_venv_python = path_venv / 'bin' / 'python'
path_venv_meson  = path_venv / 'bin' / 'meson'
path_venv_cmake  = path_venv / 'bin' / 'cmake'

path_cmake_build = path_source / 'build'
path_meson_build = path_source / 'builddir'


@contextmanager
def chdir_temp(path : Path):
    path_previous = os.getcwd()
    try:
        os.chdir(path)
        yield None
    finally:
        os.chdir(path_previous)

def rmtree_if_exists(path : Path):
    if path.exists():
        shutil.rmtree(path)

def rm_if_exists(path : Path):
    if path.exists():
        path.unlink()

def unlink_glob(path : Path, glob_files : str):
    for p in path.glob(glob_files):
        p.unlink()

def copy_file(src : Path, dst : Path):
    assert src.exists(), f'xmesh: Could not copy from {src} as it does not exist'
    if dst.is_dir():
        # dst is a folder, so update it to the final dst path
        dst = dst / src.name

    if dst.exists() and src.samefile(dst):
        print('xmesh: same file!  touching...')
        dst.touch()
    else:
        _ = shutil.copy2(src, dst)
    # try:
    #     _ = shutil.copy(src, dst)
    # except shutil.SameFileError:
    #     pass

def subprocess_run(
    command : str | list[str],
    *,
    from_path : Path | None = None,
    assert_returncode : int | None = 0,
    debug_print : bool = False,
) -> CompletedProcess[str]:
    def run() -> CompletedProcess[str]:
        # print(f'xmesh: executing {command}')
        res = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf8',
        )
        if debug_print:
            if res.stdout.strip():
                print(f'xmesh: stdout {res.stdout.rstrip("\n")}')
            if res.stderr.strip():
                print(f'xmesh: stderr {res.stderr.rstrip("\n")}')
        return res

    if not from_path:
        from_path = path_source
    with chdir_temp(from_path):
        res = run()

    if assert_returncode is not None:
        assert res.returncode == assert_returncode, f'xmesh: Expected return code {assert_returncode} but got {res.returncode}\nPath: {from_path}\nCommand: {command}\n{res.stdout}\n{res.stderr}'

    return res

def python_run(
    cmd : str,
    *,
    from_path : Path | None = None,
    assert_returncode : int | None = 0,
    debug_print : bool = False,
) -> CompletedProcess[str]:
    res = subprocess_run(f'"{path_venv_python}" {cmd}', from_path=from_path, assert_returncode=assert_returncode, debug_print=debug_print)
    return res

def meson_run(args : str, *, from_path : Path | None = None, assert_returncode : int | None = 0) -> CompletedProcess[str]:
    res = subprocess_run(f'"{path_venv_meson}" {args}', from_path=from_path, assert_returncode=assert_returncode)
    return res

def cmake_run(args : str, *, from_path : Path | None = None, assert_returncode : int | None = 0) -> CompletedProcess[str]:
    res = subprocess_run(f'"{path_venv_cmake}" {args}', from_path=from_path, assert_returncode=assert_returncode)
    return res

# def get_module_path(module_name : str, *, from_path : Path | None = None) -> Path | None:
#     # IMPORTANT: do not import, because the module might change!
#     # path = str(from_path) if from_path else None
#     try:
#         if from_path:
#             sys.path.append(str(from_path))
#         spec = find_spec(module_name)
#         # if not spec:
#         #     print(f'xmesh: could not find module {module_name} under {from_path}')
#         # else:
#         #     print(f'xmesh: found module {module_name} under {from_path} as {spec.origin}')
#         return Path(spec.origin) if spec and spec.origin else None
#     except ModuleNotFoundError:
#         # print(f'xmesh: could not find module {module_name} under {from_path}')
#         return None
#     finally:
#         if from_path:
#             sys.path.remove(str(from_path))

def get_module_path(from_path : Path, module_name : str) -> Path | None:
    # WARNING: does not work with built-in modules (ex: sys)
    # print(f'xmesh: Checking for module {module_name} from {from_path}')
    res = python_run(f'-c "import {module_name}; print({module_name}.__file__)"', from_path=from_path, assert_returncode=None)
    if res.returncode != 0:
        return None
    o = res.stdout.strip('\n')
    try:
        return Path(o)
    except Exception as e:
        assert False, f'xmesh: unexpected output "{o}"'

def get_python_include() -> Path | None:
    print('xmesh: searching for Python include folder...')

    if path_system_python:
        res = subprocess_run(
            f'''"{path_system_python}" -c "from sysconfig import get_paths; print(get_paths()['include'])"''',
            from_path=path_source,
        )
        print(f'xmesh: {path_system_python} -> {res.stdout.strip("\n")}')
        path = Path(res.stdout.strip('\n'))
        if path.exists():
            return path

    res = subprocess_run(
        f'''"{path_venv_python}" -c "from sysconfig import get_paths; print(get_paths()['include'])"''',
        from_path=path_source,
    )
    print(f'xmesh: {path_venv_python} -> {res.stdout.strip("\n")}')
    path = Path(res.stdout.strip('\n'))
    if path.exists():
        return path

    res = subprocess_run(
        f'''"{path_shell_python}" -c "from sysconfig import get_paths; print(get_paths()['include'])"''',
        from_path=path_source,
    )
    print(f'xmesh: {path_shell_python} -> {res.stdout.strip("\n")}')
    path = Path(res.stdout.strip('\n'))
    if path.exists():
        return path

    # path_or_none = next((path_venv / 'include').glob('python3*'), None)
    # if path_or_none:
    #     path = Path(path_or_none)
    #     if list(path.glob('*')):
    #         return path

    return None

def pip_install(module_name : str, package : str, *, assert_returncode : int | None = 0):
    # if module exists, nothing to do
    if get_module_path(path_source, module_name):
        # pip_upgrade(package)
        return

    print(f'xmesh: pip installing package {package} as module {module_name}')
    _ = python_run(f'-m pip install {package}', assert_returncode=assert_returncode)

    assert get_module_path(path_source, module_name), f'xmesh: Could not find {module_name} after installing {package}'

def pip_upgrade(package : str):
    print(f'xmesh: pip upgrading package {package}')
    _ = python_run(f'-m pip install --upgrade {package}')



def ensure_build_system(*, system : str = 'cmake'):
    print('xmesh: Checking build system...')

    # make sure Python virtual environment is ready
    if not path_venv.exists():
        print('xmesh: Building virtual environment...')
        builder = venv.EnvBuilder(system_site_packages=True, upgrade=True, with_pip=True, upgrade_deps=True, symlinks=True)
        builder.create(path_venv)

    # make sure nanobind, scikit-build-core, and meson are installed
    _ = python_run('-m pip install -r requirements.txt')

    match system:
        case 'cmake':
            if not path_cmake_build.exists():
                print('xmesh: setting up cmake build folder...')

                path_pyinclude_dirs = get_python_include()
                assert path_pyinclude_dirs, 'xmesh: Could not find Python include directories.  See first note https://nanobind.readthedocs.io/en/latest/basics.html#building-using-cmake'

                path_pylib_dir = next((path_venv / 'lib').glob('python3*'), None)
                assert path_pylib_dir, f'xmesh: Could not find Python lib folder under {path_venv / "lib"}/python3.*'

                path_pylib_nanobind = path_pylib_dir / 'nanobind' / 'cmake'

                command = ' '.join([
                    '-S .',
                    '-B build',
                    f'-DPython_EXECUTABLE="{path_venv_python}"',
                    f'-DPython_INCLUDE_DIRS="{path_pyinclude_dirs}/"',
                    f'-Dnanobind_DIR="{path_pylib_nanobind}/"',
                ])
                _ = cmake_run(command)

        case 'meson':
            # pip_install('mesonpy', 'meson-python')

            # make sure meson wrap packages are instelled
            # note: assuming that if subprojects folder exists, wrap packages are already installed
            if not path_subprojects.exists():
                print('xmesh: creating meson subprojects folder and installing wrap packages...')
                path_subprojects.mkdir()

                # not sure why, but certificates can get out-of-date
                # can try adding --allow-insecure cmd arg (dangerous!!)
                # _ = meson_run('wrap update-db') # --allow-insecure') # first, update list of projects
                _ = meson_run('wrap install robin-map')
                _ = meson_run('wrap install nanobind')


            # make sure build folder is set up
            if not path_meson_build.exists():
                print('xmesh: setting up meson build folder...')
                _ = meson_run('setup --buildtype release --python.install-env venv builddir')

        case _:
            assert False, f'xmesh: Unknown system {system}'

def clean(*, clean_all : bool = False):
    print(f'xmesh: Cleaning ({clean_all=})...')

    # remove build folder
    rmtree_if_exists(path_cmake_build) # detele build folder
    rmtree_if_exists(path_meson_build) # detele build folder

    # remove modules and stubs
    unlink_glob(path_here, '*.so') # windows module
    unlink_glob(path_here, '*.pyd') # linux/mac modules
    unlink_glob(path_here, '*.pyi') # stubs

    # remove python cache (just in case)
    rmtree_if_exists(path_here / '__pycache__')
    rmtree_if_exists(path_source / '__pycache__')

    if clean_all:
        # remove build system
        rmtree_if_exists(path_venv)
        rmtree_if_exists(path_subprojects)


def build_module(*, system : str = 'cmake'):
    # if module exists and has modified timestamp after source, do not need to build
    if path_module := get_module_path(path_here, 'xmesh'):
        if getmtime(path_module) >= getmtime(path_main):
            return

    if system == 'cmake':
        # IMPORTANT: CMAKE INSIDE BLENDER'S PYTHON DOES NOT WORK...
        try:
            import bpy
            print('cmesh: Detected running inside Blender, but cmake build does not work here.  Falling back to meson!')
            system = 'meson'
        except ModuleNotFoundError:
            pass



    # BUILD!!!
    ensure_build_system(system=system)

    print(f'xmesh: compiling python module using {system}...')
    match system:
        case 'cmake':
            _ = cmake_run('--build build')
        case 'meson':
            _ = meson_run('compile -C builddir')
        case _:
            assert False, f'xmesh: Unknown system {system}'

    print('xmesh: copying python modules...')
    match system:
        case 'cmake':
            path_module = get_module_path(path_cmake_build, 'xmesh')
            path_stubs = path_cmake_build / 'xmesh.pyi'
        case 'meson':
            path_module = get_module_path(path_meson_build, 'xmesh')
            path_stubs = path_meson_build / 'xmesh.pyi'
        case _:
            assert False, f'xmesh: Unknown system {system}'
    assert path_module and path_module.exists(), 'xmesh: Did not find newly-built module after compiling'
    # print(path_module)
    copy_file(path_module, path_here) # copy newly-built module
    copy_file(path_stubs,  path_here) # copy stubs

    path_module = get_module_path(path_here, 'xmesh')
    assert (
        path_module
        and path_module.exists()
        and getmtime(path_module) >= getmtime(path_main)
    ), 'xmesh: Did not find (updated) module after copying'



if __name__ == '__main__':
    if 'clean' in sys.argv[1:]:
        clean_all = ('all' in sys.argv[1:])
        clean(clean_all=clean_all)
        if 'build' not in sys.argv[1:]:
            sys.exit()

    if 'touch' in sys.argv[1:]:
        print('xmesh: touching main source...')
        path_main.touch()

    system = 'cmake' if 'meson' not in sys.argv[1:] else 'meson'

    build_module(system=system)

    res = python_run('-c "import xmesh; print(xmesh.__doc__)"', from_path=path_here)
    print(res.stdout)



"""
.venv/bin/cmake -S . -B build -DPython_EXECUTABLE=.venv/bin/python -DPython_INCLUDE_DIRS=.venv/include/python3.13 -Dnanobind_DIR=.venv/lib/python3.13/site-packages/nanobind/cmake
.venv/bin/cmake --build build
"""
