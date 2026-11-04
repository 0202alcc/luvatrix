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

/* os_signpost bridge — called from Python via ctypes */
void luvatrix_signpost_init(void);
void luvatrix_sp_nextdrawable_begin(void);
void luvatrix_sp_nextdrawable_end(void);
void luvatrix_sp_encode_begin(void);
void luvatrix_sp_encode_end(void);
void luvatrix_sp_text_begin(void);
void luvatrix_sp_text_end(void);
void luvatrix_sp_overlay_begin(void);
void luvatrix_sp_overlay_end(void);

#ifdef __cplusplus
}
#endif
