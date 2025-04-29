# distutils: language=c++
# cython: language_level=3

# This file makes bl_types a Cython package.
# The actual C definitions are handled by __init__.pxd,
# which conditionally imports from v430.pxd or v440.pxd
# based on the BLENDER_VERSION compile-time environment variable
# set during the build process in cy_setup.py.

# No runtime code or explicit cimports are needed here.
pass
