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



path_here = Path(__file__).parent

path_venv = path_here / '.venv'
if not path_venv.exists():
    print('xmesh: Building virtual environment...')
    builder = venv.EnvBuilder(with_pip=True)
    builder.create(path_venv)

path_python = path_venv / 'bin' / 'python'
path_meson  = path_venv / 'bin' / 'meson'

path_source = path_here / 'cpp'

path_subprojects = path_source / 'subprojects'
path_build       = path_source / 'builddir'
path_main        = path_source / 'xmesh.cpp'


@contextmanager
def chdir_temp(path : Path):
    path_previous = os.getcwd()
    try:
        os.chdir(path)
        yield None
    finally:
        os.chdir(path_previous)


def subprocess_run(command : str, *, assert_returncode : int | None = 0) -> CompletedProcess[str]:
    def run() -> CompletedProcess[str]:
        res = subprocess.run(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding='utf8',
        )
        return res

    with chdir_temp(path_source):
        res = run()

    if assert_returncode is not None:
        assert res.returncode == assert_returncode, f'xmesh: Expected return code {assert_returncode} but got {res.returncode}\nCommand: {command}\n{res.stdout}'

    return res


def pip_install(package : str, *, assert_returncode : int | None = 0):
    print(f'xmesh: pip installing {package}')
    _ = subprocess_run(
        f'{path_python} -m pip install "{package}"',
        assert_returncode=assert_returncode,
    )


def meson_run(args : str):
    # make sure meson build tool is installed
    if not path_meson.exists():
        pip_install('meson-python')
        assert path_meson.exists(), 'xmesh: Could not find meson'

    # assuming that if subprojects folder exists, wrap packages are already installed
    if not path_subprojects.exists():
        print('xmesh: creating meson subprojects folder...')
        path_subprojects.mkdir()

        print('xmesh: meson installing robin-map wrap package...')
        _ = subprocess_run(f'{path_meson} wrap install robin-map')

        print('xmesh: meson installing nanobind wrap package...')
        _ = subprocess_run(f'{path_meson} wrap install nanobind')

    _ = subprocess_run(f'{path_meson} {args}')


def get_module_path(module_name : str) -> Path | None:
    try:
        # don't import, because the module might change!
        sys.path.append(str(path_here))
        spec = find_spec(module_name)
        return Path(spec.origin) if spec and spec.origin else None
    except ModuleNotFoundError:
        return None
    finally:
        sys.path.remove(str(path_here))


def build_module(*, clean : bool = False):
    if not clean:
        path_module = get_module_path('xmesh')
        if path_module and getmtime(path_module) >= getmtime(path_main):
            # module has a timestamp later than source file!
            return

    # possibly clean before build

    if clean:
        print('xmesh: cleaning...')
        if path_build.exists(): shutil.rmtree(path_build)  # detele build folder
        for path in path_here.glob('*.so'):  path.unlink() # delete windows module
        for path in path_here.glob('*.pyd'): path.unlink() # delete linux/mac modules
        for path in path_here.glob('*.pyi'): path.unlink() # delete stubs

    # BUILD!!!

    # make sure nanobind is installed
    if not get_module_path('nanobind'):
        pip_install('nanobind')

    # make sure build folder is set up
    if not path_build.exists():
        print('xmesh: setting up meson build folder...')
        meson_run('setup --buildtype release builddir')

    print('xmesh: compiling python module...')
    meson_run('compile -C builddir')

    print('xmesh: copying python modules and stubs...')
    for path in path_build.glob('*.so'):  _ = shutil.copy(path, path_here) # copy windows module
    for path in path_build.glob('*.pyd'): _ = shutil.copy(path, path_here) # copy linux/mac modules
    for path in path_build.glob('*.pyi'): _ = shutil.copy(path, path_here) # copy stubs

    path_module = get_module_path('xmesh')
    assert path_module and path_module.exists() and getmtime(path_module) >= getmtime(path_main)

def clear_all():
    """
    rm -rf .venv cpp/builddir/ cpp/subprojects/ xmesh.pyi xmesh.cpython-313-x86_64-linux-gnu.so __pycache__/ cpp/__pycache__/
    """
    assert False, 'xmesh: clear_all() is not implemented yet'


if __name__ == '__main__':
    clean_build = ('clean' in sys.argv[1:])
    build_module(clean=clean_build)
