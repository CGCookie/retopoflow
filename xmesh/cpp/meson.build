project(
    'xmesh',
    'cpp',
    version: '0.0.1',
    meson_version: '>=1.0.0',
    default_options: ['cpp_std=c++17', 'd_ndebug=if-release'],
)

python = import('python').find_installation()
nanobind_dep = dependency('nanobind')
mod = python.extension_module(
    'xmesh',
    sources: ['xmesh.cpp'],
    dependencies: [nanobind_dep],
    install: true,
)

stubgen  = nanobind_dep.get_variable('stubgen')
custom_target(
    output: 'xmesh.pyi',
    depends: mod,
    command: [python, stubgen, '-m', 'xmesh', '-M', 'py.typed'],
    build_by_default: true
)
