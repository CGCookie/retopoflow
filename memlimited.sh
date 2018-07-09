#!/bin/bash -e

# runs blender with limited memory (will crash if blender allocates too much)

ulimit -Sv 5000000
#shift
./blender $@