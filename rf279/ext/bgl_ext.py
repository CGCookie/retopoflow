# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

# Contact for more information about the Addon:
# Email:    germano.costa@ig.com.br
# Twitter:  wii_mano @mano_wii

# modified by Jon Denning (@gfxcoder)
# note: this file must stay in sync with BPY implementation!  :(
# we are using this file only as a workaround for
#    bgl.glVertexAttribPointer
#    bgl.glDrawElements

import bgl
import ctypes
import numpy as np

# figure out size of _Py_ssize_t
_Py_ssize_t = ctypes.c_int64 if hasattr(ctypes.pythonapi, 'Py_InitModule4_64') else ctypes.c_int

class _PyObject(ctypes.Structure): pass
_PyObject._fields_ = [                      # cannot define inside _PyObject,
    ('ob_refcnt', _Py_ssize_t),             # because _PyObject is referenced
    ('ob_type', ctypes.POINTER(_PyObject)), # <-- here
]

if object.__basicsize__ != ctypes.sizeof(_PyObject):
    # python with trace
    class _PyObject(ctypes.Structure):
        _fields_ = [
            ('_ob_next', ctypes.POINTER(_PyObject)),
            ('_ob_prev', ctypes.POINTER(_PyObject)),
            ('ob_refcnt', _Py_ssize_t),
            ('ob_type', ctypes.POINTER(_PyObject)),
        ]

class _PyVarObject(_PyObject):
    _fields_ = [
        ('ob_size', _Py_ssize_t),
    ]

class C_Buffer(_PyVarObject):
    _fields_ = [
        ("parent", ctypes.py_object),
        ("type", ctypes.c_int),
        ("ndimensions", ctypes.c_int),
        ("dimensions", ctypes.POINTER(ctypes.c_int)),
        ("buf", ctypes.c_void_p),
    ]

assert ctypes.sizeof(C_Buffer) == bgl.Buffer.__basicsize__


class VoidBufValue():
    def __init__(self, value):
        self.buf = bgl.Buffer(bgl.GL_BYTE, 1)

        self._buf_addr = ctypes.pointer(ctypes.c_void_p.from_address(id(self.buf) + C_Buffer.buf.offset))
        self._allocated_buf = self._buf_addr[0]
        self._buf_addr[0] = value

    def __del__(self):
        self._buf_addr[0] = self._allocated_buf
        #del self._allocated_buf
        #del self._buf_addr
        del self.buf


def np_array_as_bgl_Buffer(array):
    type = array.dtype
    if   type == np.int8:    type = bgl.GL_BYTE
    elif type == np.int16:   type = bgl.GL_SHORT
    elif type == np.int32:   type = bgl.GL_INT
    elif type == np.float32: type = bgl.GL_FLOAT
    elif type == np.float64: type = bgl.GL_DOUBLE
    else: raise

    _decref = ctypes.pythonapi.Py_DecRef
    _incref = ctypes.pythonapi.Py_IncRef

    _decref.argtypes = _incref.argtypes = [ctypes.py_object]
    _decref.restype = _incref.restype = None

    buf = bgl.Buffer(bgl.GL_BYTE, (1, *array.shape))[0]
    c_buf = C_Buffer.from_address(id(buf))

    _decref(c_buf.parent)
    _incref(array)

    c_buf.parent = array # Prevents MEM_freeN
    c_buf.type = type
    c_buf.buf = array.ctypes.data
    return buf


def bgl_Buffer_reshape(buf, shape):
    assert np.prod(buf.dimensions) == np.prod(shape)

    c_buf = C_Buffer.from_address(id(buf))
    c_buf.ndimensions = len(shape)

    tmp_buf = bgl.Buffer(c_buf.type, (1,) * len(shape))
    c_tmp_buf = C_Buffer.from_address(id(tmp_buf))
    for i, v in enumerate(shape):
        c_tmp_buf.dimensions[i] = v

    offset = C_Buffer.dimensions.offset
    a = ctypes.pointer(ctypes.c_void_p.from_address(id(tmp_buf) + offset))
    b = ctypes.pointer(ctypes.c_void_p.from_address(id(buf) + offset))

    a[0], b[0] = b[0], a[0]

    del c_buf
    del c_tmp_buf
    del tmp_buf


def get_clip_planes(rv3d):
    #(int)(&((struct RegionView3D *)0)->rflag) == 842
    #(int)(&((struct RegionView3D *)0)->clip) == 464
    rv3d_ptr = rv3d.as_pointer()
    rflag = ctypes.c_short.from_address(rv3d_ptr + 842).value
    if rflag & 4: # RV3D_CLIPPING
        clip = (6 * (4 * ctypes.c_float)).from_address(rv3d_ptr + 464)
        return bgl.Buffer(bgl.GL_FLOAT, (6, 4), clip)

