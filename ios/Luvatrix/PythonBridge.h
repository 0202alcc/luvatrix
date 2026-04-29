#pragma once

#ifdef __cplusplus
extern "C" {
#endif

void LuvatrixPyInitialize(void);
int LuvatrixPyRunSimpleString(const char *script);
void LuvatrixPyErrPrint(void);
int LuvatrixPyGILStateEnsure(void);
void LuvatrixPyGILStateRelease(int state);
void LuvatrixPyEvalSaveThread(void);

#ifdef __cplusplus
}
#endif
