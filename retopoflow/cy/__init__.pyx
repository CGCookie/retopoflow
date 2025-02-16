# distutils: language=c++
# cython: language_level=3

import numpy as np
cimport numpy as np
np.import_array()  # Required for NumPy C-API

from .accel2d cimport Accel2D
