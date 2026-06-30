#include <Python/Python.h>
#include <os/signpost.h>
#include "PythonBridge.h"

static os_log_t _luvatrix_log = NULL;

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

void luvatrix_signpost_init(void) {
    _luvatrix_log = os_log_create("com.luvatrix.app", "Render");
}

void luvatrix_sp_nextdrawable_begin(void) {
    if (_luvatrix_log) os_signpost_interval_begin(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "nextDrawable");
}
void luvatrix_sp_nextdrawable_end(void) {
    if (_luvatrix_log) os_signpost_interval_end(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "nextDrawable");
}
void luvatrix_sp_encode_begin(void) {
    if (_luvatrix_log) os_signpost_interval_begin(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "encodeFrame");
}
void luvatrix_sp_encode_end(void) {
    if (_luvatrix_log) os_signpost_interval_end(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "encodeFrame");
}
void luvatrix_sp_text_begin(void) {
    if (_luvatrix_log) os_signpost_interval_begin(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "textDraw");
}
void luvatrix_sp_text_end(void) {
    if (_luvatrix_log) os_signpost_interval_end(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "textDraw");
}
void luvatrix_sp_overlay_begin(void) {
    if (_luvatrix_log) os_signpost_interval_begin(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "overlay");
}
void luvatrix_sp_overlay_end(void) {
    if (_luvatrix_log) os_signpost_interval_end(_luvatrix_log, OS_SIGNPOST_ID_EXCLUSIVE, "overlay");
}
