// Provides the actual trap_PC_* variables that ui_shared.h declares as extern
// (see cg_syscalls_pc_rename.h for the full explanation). cg_syscalls.c's
// implementations were renamed to the _impl names below; this file wires them
// up as the function-pointer variables the rest of cgame (via ui_shared.h)
// expects to call through -- same pattern ui_multiversion.c uses for its own
// version-switched trap_ functions, just with only one implementation to pick.
#include "q_shared.h" // mvsdk/code/game/q_shared.h -- defines pc_token_t

extern int CG_PC_AddGlobalDefine_impl( char *define );
extern int CG_PC_LoadSource_impl( const char *filename );
extern int CG_PC_FreeSource_impl( int handle );
extern int CG_PC_ReadToken_impl( int handle, pc_token_t *pc_token );
extern int CG_PC_SourceFileAndLine_impl( int handle, char *filename, int *line );
extern int CG_PC_LoadGlobalDefines_impl( const char *filename );

int (*trap_PC_AddGlobalDefine)( char *define ) = CG_PC_AddGlobalDefine_impl;
int (*trap_PC_LoadSource)( const char *filename ) = CG_PC_LoadSource_impl;
int (*trap_PC_FreeSource)( int handle ) = CG_PC_FreeSource_impl;
int (*trap_PC_ReadToken)( int handle, pc_token_t *pc_token ) = CG_PC_ReadToken_impl;
int (*trap_PC_SourceFileAndLine)( int handle, char *filename, int *line ) = CG_PC_SourceFileAndLine_impl;
int (*trap_PC_LoadGlobalDefines)( const char *filename ) = CG_PC_LoadGlobalDefines_impl;
