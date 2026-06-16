module py

#define PY_SSIZE_T_CLEAN
#include "Python.h"

pub struct C.PyFrameObject { }

pub struct C.PyModule { }

@[typedef]
pub struct C.PyCFunction { }

@[typedef]
pub struct C.Py_ssize_t { }

@[typedef]
pub struct C.PyTypeObject { }

pub type PyFunc = fn(&C.PyObject, &C.PyObject) &C.PyObject
pub type PyFuncWithKwargs = fn(&C.PyObject, &C.PyObject, &C.PyObject) &C.PyObject

pub struct C.PyModuleDef {
pub mut:
    m_base int
    m_name &char
    m_doc &char
    m_size &C.Py_ssize_t
    m_methods voidptr
    m_slots voidptr
    m_traverse voidptr
    m_clear voidptr
    m_free voidptr
}

pub struct C.PyMethodDef {
pub mut:
    ml_name &char
    ml_meth voidptr // C.PyCFunction
    ml_flags int
    ml_doc &char
}

pub interface Dispatcher {
    dispatch(m_name string, self &C.PyObject, args &C.PyObject) &C.PyObject
}

pub fn C.Py_DecodeLocale(&char, C.size_t) voidptr
pub fn C.Py_SetProgramName(&C.wchar_t)
pub fn C.Py_Initialize()
pub fn C.PyRun_SimpleString(&char) int
pub fn C.PyRun_String(&char, int, &C.PyObject, &C.PyObject) &C.PyObject
pub fn C.Py_FinalizeEx() int

pub fn C.PyMem_RawFree(voidptr)

pub fn C.PySys_SetObject(&char, &C.PyObject) int
pub fn C.PySys_GetObject(&char) &C.PyObject

// macros
pub fn C.Py_INCREF(&C.PyObject)
pub fn C.Py_XINCREF(&C.PyObject)
pub fn C.Py_DECREF(&C.PyObject)
pub fn C.Py_XDECREF(&C.PyObject)
pub fn C.PyModule_Create(&C.PyModuleDef) &C.PyObject
pub fn C.PyTuple_Check(&C.PyObject) int
pub fn C.PyCallable_Check(&C.PyObject) int
pub fn C.PyErr_PrintEx(int)
pub fn C.PyErr_Print()
pub fn C.PyErr_Occurred() &C.PyObject

// misc
pub fn C.PyUnicode_FromString(&char) &C.PyObject
pub fn C.PyUnicode_AsUTF8(&C.PyObject) &char
pub fn C.PyUnicode_AsEncodedString(&C.PyObject, &char, &char) &C.PyObject
pub fn C.PyUnicode_DecodeLocaleAndSize(&char, &C.Py_ssize_t, &char) &C.PyObject
pub fn C.PyUnicode_DecodeFSDefault(&char) &C.PyObject
pub fn C.PyImport_ImportModule(&char) &C.PyObject
pub fn C.PyImport_Import(&C.PyObject) &C.PyObject
pub fn C.PySys_SetPath(&u16)
pub fn C.PyBytes_AsString(&C.PyObject) &char

// moduleobject.h
pub fn C.PyModule_NewObject(&C.PyObject) &C.PyObject
pub fn C.PyModule_New(&char) &C.PyObject
pub fn C.PyModule_GetDict(&C.PyObject) &C.PyObject
pub fn C.PyModule_GetNameObject(&C.PyObject) &C.PyObject
pub fn C.PyModule_GetName(&C.PyObject) &char
pub fn C.PyModule_GetFilenameObject(&C.PyObject) &C.PyObject
pub fn C.PyModule_GetFilename(&C.PyObject) &char
pub fn C.PyModule_GetDef(&C.PyObject) &C.PyModuleDef
pub fn C.PyModule_GetState(&C.PyObject) &C.void
pub fn C.PyModuleDef_Init(&C.struct) &C.PyObject

// modsupport.h
pub fn C.Py_BuildValue(&char, ...&&C.PyObject) &C.PyObject
pub fn C.Py_VaBuildValue(&char, &C.va_list) &C.PyObject
pub fn C.PyModule_AddObjectRef(&C.PyObject, &char, &C.PyObject) int
pub fn C.PyModule_AddObject(&C.PyObject, &char, &C.PyObject) int
pub fn C.PyModule_AddIntConstant(&C.PyObject, &char, &C.long) int
pub fn C.PyModule_AddStringConstant(&C.PyObject, &char, &char) int
pub fn C.PyModule_AddType(&C.PyObject, &C.PyTypeObject) int
pub fn C.PyModule_SetDocString(&C.PyObject, &char) int
pub fn C.PyModule_AddFunctions(&C.PyObject, &C.PyMethodDef) int
pub fn C.PyModule_ExecDef(&C.PyObject, &C.PyModuleDef) int
pub fn C.PyModule_Create2(&C.struct, int) &C.PyObject
pub fn C.PyModule_FromDefAndSpec2(&C.PyModuleDef, &C.PyObject, int) &C.PyObject

@[inline]
pub fn py_none() &C.PyObject {
    C.Py_INCREF(C.Py_None)
    return &C.PyObject(C.Py_None)
}

@[unsafe]
pub fn init_module[T](mod Dispatcher) &C.PyObject {

    mut methods := []C.PyMethodDef{}

    $for method in T.methods {
        for attr in method.attrs {
            m_name := method.name
            mut method_export_name := method.name

            if attr.starts_with('py_method') == false {
                continue
            } else if attr.starts_with('py_method:') {
                method_export_name = attr.all_after('py_method:').trim_left(' ')
            }

            mut method_type := C.METH_VARARGS

            if method.args.len == 2 {
                $if method.args[0].typ is C.PyObject      // self
                && method.args[1].typ is C.PyObject {      // args

                    if method.args[1].name == 'args' {
                        method_type = C.METH_VARARGS
                    } else if method.args[1].name == 'ignore' {
                        method_type = C.METH_NOARGS
                    } else {
                        method_type = C.METH_O
                    }
                }
            }

            /*
            if method.args.len == 3 {
                $if method.args[0].typ is C.PyObject      // self
                && method.args[1].typ is C.PyObject         // args
                && method.args[2].typ is C.PyObject {    // kwargs
                    method_type = C.METH_VARARGS | C.METH_KEYWORDS
                }
            }
            */

            fp := fn[mod, m_name](self &C.PyObject, args &C.PyObject) &C.PyObject {
                return mod.dispatch(m_name, self, args)
            }

            methods << C.PyMethodDef {
                method_export_name.str,
                fp,
                method_type,
                C.NULL
            }

            break
        }
    }

    methods << C.PyMethodDef { C.NULL, C.NULL, 0, C.NULL} // sentinel, last method

    mut mod_name := '???'
    mut found := false

    $for attr in T.attributes {
        if found == false && attr.name == 'py_module' {
            mod_name = attr.arg
            found = true
        }
    }

    if found == false {
        error('dasdasd')
    }

    module_def := &C.PyModuleDef { // '&' to alloc on heap
        C.PyModuleDef_HEAD_INIT,
        mod_name.str
        C.NULL,
        -1,
        methods.data,
        C.NULL,
        C.NULL,
        C.NULL,
        C.NULL,
    }

    m := C.PyModule_Create(module_def)

    println("PyInit_${mod_name}(): DONE.")

    return m
}
