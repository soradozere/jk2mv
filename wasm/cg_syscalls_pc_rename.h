// Applied ONLY to cgame/cg_syscalls.c (see wasm/CMakeLists.txt set_source_files_properties).
//
// ui_shared.h -- included by cg_main.c -- declares these 6 trap_PC_* symbols as
// reassignable function-pointer VARIABLES (extern int (*trap_PC_LoadSource)(...)),
// because ui/ui_multiversion.c genuinely needs to switch implementations at
// runtime (1.02 vs 1.04 server). cgame doesn't do that switching -- cg_syscalls.c
// just defines them as plain FUNCTIONS with the same names. On a real desktop
// build (dynamic .so, cg_main.c.o + cg_syscalls.c.o linked together) this
// variable-vs-function mismatch apparently goes unchecked by the native linker.
// wasm-ld does NOT tolerate it -- WASM functions and data live in genuinely
// different address spaces, so "symbol type mismatch" is a hard link error, not
// a lenient warning. Fix: rename cg_syscalls.c's functions here, then
// wasm/cg_pc_trap_glue.c defines the actual variables ui_shared.h expects,
// initialized to point at these renamed functions -- the same pattern
// ui_multiversion.c already uses for its own version-switched functions.
#define trap_PC_AddGlobalDefine CG_PC_AddGlobalDefine_impl
#define trap_PC_LoadSource CG_PC_LoadSource_impl
#define trap_PC_FreeSource CG_PC_FreeSource_impl
#define trap_PC_ReadToken CG_PC_ReadToken_impl
#define trap_PC_SourceFileAndLine CG_PC_SourceFileAndLine_impl
#define trap_PC_LoadGlobalDefines CG_PC_LoadGlobalDefines_impl
