#include <Python/Python.h>
#include "PythonBridge.h"

void LuvatrixPyInitialize(void) {
    Py_Initialize();
}

int LuvatrixPyRunSimpleString(const char *script) {
    return PyRun_SimpleString(script);
}

void LuvatrixPyErrPrint(void) {
    PyErr_Print();
}

int LuvatrixPyGILStateEnsure(void) {
    return (int)PyGILState_Ensure();
}

void LuvatrixPyGILStateRelease(int state) {
    PyGILState_Release((PyGILState_STATE)state);
}

void LuvatrixPyEvalSaveThread(void) {
    (void)PyEval_SaveThread();
}
