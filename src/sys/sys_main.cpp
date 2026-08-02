#include <csignal>
#include <cstdlib>
#include <cstdarg>
#include <cstdio>
#include <sys/stat.h>
#define __STDC_FORMAT_MACROS
#if (defined(_MSC_VER) && _MSC_VER < 1800)
#include <stdint.h>
#else
#include <inttypes.h>
#endif
#ifdef WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif
#ifndef DEDICATED
#include "SDL.h"
#endif
#ifdef __EMSCRIPTEN__
#include <emscripten.h>
extern "C" void initialize_gl4es();
#endif
#include "../qcommon/qcommon.h"
#include "../sys/sys_local.h"
#include "../sys/sys_public.h"
#include "con_local.h"

cvar_t *com_minimized;
cvar_t *com_unfocused;
cvar_t *com_maxfps;
cvar_t *com_maxfpsMinimized;
cvar_t *com_maxfpsUnfocused;

static volatile sig_atomic_t sys_signal = 0;

/*
==================
Sys_GetClipboardData
==================
*/
char *Sys_GetClipboardData(void) {
#ifdef DEDICATED
	return NULL;
#else
	if (!SDL_HasClipboardText())
		return NULL;

	char *cbText = SDL_GetClipboardText();
	size_t len = strlen(cbText) + 1;

	char *buf = (char *)Z_Malloc(len, TAG_CLIPBOARD);
	Q_strncpyz(buf, cbText, len);

	SDL_free(cbText);
	return buf;
#endif
}

/*
=================
Sys_ConsoleInput

Handle new console input
=================
*/
char *Sys_ConsoleInput(void) {
	return CON_Input();
}

void Sys_Print(const char *msg, qboolean extendedColors) {
	// TTimo - prefix for text that shows up in console but not in notify
	// backported from RTCW
	if (!Q_strncmp(msg, "[skipnotify]", 12)) {
		msg += 12;
	}
	if (msg[0] == '*') {
		msg += 1;
	}
	ConsoleLogAppend(msg);
	CON_Print(msg, (extendedColors ? true : false));
}

/*
================
Sys_Init

Called after the common systems (cvars, files, etc)
are initialized
================
*/
void Sys_Init(void) {
	Cmd_AddCommand("in_restart", IN_Restart);
	Cvar_Get("arch", ARCH_STRING, CVAR_ROM);
	Cvar_Get("username", Sys_GetCurrentUser(), CVAR_ROM);

	com_unfocused = Cvar_Get("com_unfocused", "0", CVAR_ROM);
	com_minimized = Cvar_Get("com_minimized", "0", CVAR_ROM);
	com_maxfps = Cvar_Get("com_maxfps", "125", CVAR_ARCHIVE | CVAR_GLOBAL);
	com_maxfpsUnfocused = Cvar_Get("com_maxfpsUnfocused", "0", CVAR_ARCHIVE | CVAR_GLOBAL);
	com_maxfpsMinimized = Cvar_Get("com_maxfpsMinimized", "50", CVAR_ARCHIVE | CVAR_GLOBAL);
}

#ifdef __EMSCRIPTEN__
/*
================
Playback control bridge

The demo player's UI lives in the page rather than in the game, so it needs a
way to drive the engine and read state back. Everything the controls touch
(cl_freezeDemo, timescale, cg_fov, cg_thirdPerson*) is already a cvar, so a
console-command bridge plus a cvar getter covers the whole surface without
needing a bespoke export per control.
================
*/
extern "C" {

// Queue a console command. EXEC_APPEND rather than EXEC_NOW because this is
// called from DOM event handlers, which can land between frames -- appending
// keeps execution on the engine's own Cbuf pass instead of re-entering the
// engine partway through one.
EMSCRIPTEN_KEEPALIVE void JKD_Exec( const char *cmd ) {
	if ( !cmd || !cmd[0] ) {
		return;
	}
	Cbuf_ExecuteText( EXEC_APPEND, cmd );
	// Cbuf_AddText appends verbatim -- it does NOT terminate the command. Two
	// calls in one frame otherwise run together onto a single line, so
	// "cg_thirdPerson 0" + "cg_demoCam 1" arrives as "cg_thirdPerson 0cg_demoCam 1"
	// and the second cvar is never set at all. The first still half-works, since
	// the value it gets ("0cg_demoCam") reads as 0 -- which is what disguised
	// this as a bug in whatever the second command happened to be.
	Cbuf_ExecuteText( EXEC_APPEND, "\n" );
}

// Read a cvar back, so the UI can initialise its controls from the engine's
// actual values rather than assuming defaults.
EMSCRIPTEN_KEEPALIVE float JKD_GetCvar( const char *name ) {
	if ( !name || !name[0] ) {
		return 0.0f;
	}
	return Cvar_VariableValue( name );
}

}
#endif

static void Q_NORETURN Sys_Exit(int ex) {
	IN_Shutdown();
#ifndef DEDICATED
	SDL_Quit();
#endif

	NET_Shutdown();

	Sys_PlatformExit();

	Com_ShutdownZoneMemory();

	CON_Shutdown();

	exit(ex);
}

#if !defined(DEDICATED)
static void Sys_ErrorDialog(const char *error) {
	time_t rawtime;
	char timeStr[32] = {}; // should really only reach ~19 chars
	char crashLogPath[MAX_OSPATH];

	time(&rawtime);
	strftime(timeStr, sizeof(timeStr), "%Y-%m-%d_%H-%M-%S", localtime(&rawtime)); // or gmtime
	Com_sprintf(crashLogPath, sizeof(crashLogPath),
		"%s%cerrorlog-%s.txt",
		Sys_DefaultHomePath(), PATH_SEP, timeStr);

	Sys_Mkdir(Sys_DefaultHomePath());

	FILE *fp = fopen(crashLogPath, "w");
	if (fp) {
		ConsoleLogWriteOut(fp);
		fclose(fp);

		const char *errorMessage = va("%s\n\nThe error log was written to %s", error, crashLogPath);
		if (SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Error", errorMessage, NULL) < 0) {
			fprintf(stderr, "%s", errorMessage);
		}
	} else {
		// Getting pretty desperate now
		ConsoleLogWriteOut(stderr);
		fflush(stderr);

		const char *errorMessage = va("%s\nCould not write the error log file, but we printed it to stderr.\n"
			"Try running the game using a command line interface.", error);
		if (SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_ERROR, "Error", errorMessage, NULL) < 0) {
			// We really have hit rock bottom here :(
			fprintf(stderr, "%s", errorMessage);
		}
	}
}
#endif

void Q_NORETURN QDECL Sys_Error(const char *error, ...) {
	va_list argptr;
	char    string[1024];

	va_start(argptr, error);
	Q_vsnprintf(string, sizeof(string), error, argptr);
	va_end(argptr);

	Sys_Print(string,qfalse);
	Sys_PrintBacktrace();

	// Only print Sys_ErrorDialog for client binary. The dedicated
	// server binary is meant to be a command line program so you would
	// expect to see the error printed.
#if !defined(DEDICATED)
	Sys_ErrorDialog(string);
#endif

	Sys_Exit(3);
}

void Q_NORETURN Sys_Quit(void) {
	Sys_Exit(0);
}

/*
============
Sys_FileTime

returns -1 if not present
============
*/
time_t Sys_FileTime(const char *path) {
	struct stat buf;

	if (stat(path, &buf) == -1)
		return -1;

	return buf.st_mtime;
}

/*
=================
Sys_SigHandler
=================
*/
void Sys_SigHandler(int signal) {
	sys_signal = signal;
}

#if defined(_MSC_VER) && !defined(_DEBUG)
LONG WINAPI Sys_NoteException(EXCEPTION_POINTERS* pExp, DWORD dwExpCode);
void Sys_WriteCrashlog();
#endif

int main(int argc, char* argv[]) {
	int		i;
	char	commandLine[MAX_STRING_CHARS] = { 0 };
	int		missingFuncs = Sys_FindFunctions();

#if defined(_MSC_VER) && !defined(_DEBUG)
	__try {
#endif

	Sys_PlatformInit(argc, argv);

#if defined(DEBUG) && !defined(DEDICATED)
	CON_CreateConsoleWindow();
#endif
	CON_Init();

#ifdef __EMSCRIPTEN__
	// GL4ES must be initialised before any GL call. Its context setup normally
	// runs from its own EGL/GLX layer, which we bypass by taking SDL2's GL
	// context directly -- without this, GL4ES's global `glstate` stays NULL and
	// every entry point dereferences NULL+offset, silently reading and writing
	// over the bottom of linear memory.
	setenv("LIBGL_VSYNC", "1", 1);
	initialize_gl4es();
#endif

	// get the initial time base
	Sys_Milliseconds();

#ifdef MACOS_X
	// This is passed if we are launched by double-clicking
	if (argc >= 2 && Q_strncmp(argv[1], "-psn", 4) == 0)
		argc = 1;
#endif

#if defined(DEBUG_SDL) && !defined(DEDICATED)
	SDL_LogSetAllPriority(SDL_LOG_PRIORITY_VERBOSE);
#endif

	// Concatenate the command line for passing to Com_Init
	for (i = 1; i < argc; i++) {
		const bool containsSpaces = (strchr(argv[i], ' ') != NULL);
		if (containsSpaces)
			Q_strcat(commandLine, sizeof(commandLine), "\"");

		Q_strcat(commandLine, sizeof(commandLine), argv[i]);

		if (containsSpaces)
			Q_strcat(commandLine, sizeof(commandLine), "\"");

		Q_strcat(commandLine, sizeof(commandLine), " ");
	}

	Com_Init(commandLine);

	if ( missingFuncs ) {
		static const char *missingFuncsError =
			"Your system is missing functions this application relies on.\n"
			"\n"
			"Some features may be unavailable or their behavior may be incorrect.";

		// Set the error cvar (the main menu should pick this up and display an error box to the user)
		Cvar_Get( "com_errorMessage", missingFuncsError, CVAR_ROM );
		Cvar_Set( "com_errorMessage", missingFuncsError );

		// Print the error into the console, because we can't always display the main menu (dedicated servers, ...)
		Com_Printf( "********************\n" );
		Com_Printf( "ERROR: %s\n", missingFuncsError );
		Com_Printf( "********************\n" );
	}

	// main game loop
#ifdef __EMSCRIPTEN__
	// Tell the page the engine is up. This can't be Module.postRun, because
	// main() never returns here -- the loop below is driven by rAF instead.
	// Signalling from this side also guarantees the cvars the UI reads actually
	// exist by the time it asks for them.
	EM_ASM({ if (window.JKD_ready) { window.JKD_ready(); } });

	// A blocking while(true) loop stalls the browser's JS thread forever.
	// Yield to the browser each frame instead, driven by requestAnimationFrame.
	emscripten_set_main_loop(Com_Frame, 0, 1);
#else
	while (!sys_signal) {
		if (com_busyWait->integer) {
			bool shouldSleep = false;

			if (com_dedicated->integer) {
				shouldSleep = true;
			}

			if (com_minimized->integer) {
				shouldSleep = true;
			}

			if (shouldSleep) {
				Sys_Sleep(5);
			}
		}

		// run the game
		Com_Frame();
	}

	Com_Quit(sys_signal);
#endif

#if defined(_MSC_VER) && !defined(_DEBUG)
	} __except(Sys_NoteException(GetExceptionInformation(), GetExceptionCode())) {
		Sys_WriteCrashlog();
		return 1;
	}
#endif

	// never gets here
	return 0;
}
