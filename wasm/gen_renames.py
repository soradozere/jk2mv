import re
import os

ROOT = os.path.join(os.path.dirname(__file__), "..", "src", "mvsdk", "code")

# In the real desktop build, jk2mv_cgame and jk2mv_ui compile into SEPARATE
# shared libraries (cgame_mp_x86_64.so, jk2mvmenu_x86_64.so) -- each gets its
# own isolated ELF symbol table, so name collisions between them are simply
# impossible there. Monolithically statically linking both into one WASM
# executable removes that isolation, so virtually every global either module
# defines needs a module-specific prefix. This mirrors wasm/CMakeLists.txt's
# CGameFiles/MenuFiles lists exactly -- keep them in sync if those change.
CGAME_C_FILES = [
    "cgame/cg_main.c", "cgame/cg_consolecmds.c", "cgame/cg_draw.c", "cgame/cg_drawtools.c",
    "cgame/cg_effects.c", "cgame/cg_ents.c", "cgame/cg_event.c", "cgame/cg_info.c",
    "cgame/cg_light.c", "cgame/cg_localents.c", "cgame/cg_marks.c", "cgame/cg_newDraw.c",
    "cgame/cg_players.c", "cgame/cg_playerstate.c", "cgame/cg_predict.c", "cgame/cg_saga.c",
    "cgame/cg_scoreboard.c", "cgame/cg_servercmds.c", "cgame/cg_snapshot.c", "cgame/cg_turret.c",
    "cgame/cg_view.c", "cgame/cg_weaponinit.c", "cgame/cg_weapons.c",
    "cgame/fx_blaster.c", "cgame/fx_bowcaster.c", "cgame/fx_bryarpistol.c", "cgame/fx_demp2.c",
    "cgame/fx_disruptor.c", "cgame/fx_flechette.c", "cgame/fx_force.c", "cgame/fx_heavyrepeater.c",
    "cgame/fx_rocketlauncher.c", "cgame/cg_multiversion.c", "cgame/cg_multiversion_syscalls.c",
    "game/bg_multiversion.c", "game/animMappingTable.c", "game/bg_misc.c", "game/bg_panimate.c",
    "game/bg_pmove.c", "game/bg_saber.c", "game/bg_slidemove.c", "game/bg_weapons.c",
    "game/q_math.c", "game/q_shared.c", "ui/ui_shared.c", "cgame/cg_syscalls.c",
]
UI_C_FILES = [
    "ui/ui_main.c", "ui/ui_atoms.c", "ui/ui_force.c", "ui/ui_gameinfo.c", "ui/ui_shared.c",
    "ui/ui_multiversion.c", "game/bg_misc.c", "game/bg_weapons.c", "game/q_math.c",
    "game/q_shared.c", "ui/ui_multiversion_syscalls.c", "game/bg_multiversion.c", "ui/ui_syscalls.c",
]

# Handled explicitly (not by the generic scan below): ui_shared.h declares these
# 6 as reassignable function-pointer VARIABLES (ui/ui_multiversion.c genuinely
# needs 1.02-vs-1.04 switching), while cgame/cg_syscalls.c defines them as plain
# FUNCTIONS -- a real function-vs-data type mismatch wasm-ld enforces strictly,
# not just a name collision a rename alone fixes. See cg_syscalls_pc_rename.h
# and cg_pc_trap_glue.c for the actual fix (rename cg_syscalls.c's functions,
# provide a real variable pointing at them, matching ui_multiversion.c's own
# pattern). These still need a per-module rename so cgame's and ui's variables
# don't collide with EACH OTHER -- done here by hand instead of the generic
# scan, so both modules stay consistent with the file-specific glue.
PC_TRAP_FUNCS = [
    "trap_PC_AddGlobalDefine", "trap_PC_LoadSource", "trap_PC_FreeSource",
    "trap_PC_ReadToken", "trap_PC_SourceFileAndLine", "trap_PC_LoadGlobalDefines",
]

C_KEYWORDS = {
    'if', 'else', 'while', 'for', 'do', 'switch', 'case', 'default', 'break', 'continue',
    'return', 'goto', 'sizeof', 'typedef', 'struct', 'union', 'enum',
    'int', 'void', 'char', 'float', 'double', 'long', 'short', 'signed', 'unsigned',
    'const', 'static', 'extern', 'register', 'volatile', 'auto', 'qboolean',
    'with', 'WITHOUT', 'is',
}

# Names that exist as BOTH a real function/variable in one of the scanned files
# AND a function-like macro in q_shared.h -- the macro shadows the other form
# via text substitution everywhere both are visible (making the shadowed form
# effectively dead code), but renaming it collides with the header's own
# #define at compile time. Exclude anything already #define'd as a macro.
with open(os.path.join(ROOT, "game", "q_shared.h"), "r", encoding="latin-1") as f:
    macro_names = set(re.findall(r'^#define\s+([a-zA-Z0-9_]+)', f.read(), re.MULTILINE))


IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def _last_ident_before(text):
    """Strip pointer stars (just token noise for our purposes -- 'char *foo',
    'char* foo', and 'char * QDECL foo' all reduce to the same token list once
    stars are blanked out) and return the last whitespace-separated identifier,
    which is the declared name regardless of how many type/qualifier/
    calling-convention words (unsigned, const, QDECL, ...) precede it."""
    tokens = text.replace('*', ' ').split()
    if not tokens:
        return None
    name = tokens[-1]
    return name if IDENT_RE.match(name) else None


def scan(rel_paths):
    symbols = set()
    for rel in rel_paths:
        # Old Windows-authored Quake3-lineage sources aren't reliably UTF-8
        # (some have stray high bytes in comments) -- latin-1 never fails to
        # decode and every identifier we care about is plain ASCII regardless.
        with open(os.path.join(ROOT, rel), "r", encoding="latin-1") as f:
            content = f.read()
        # Strip comments BEFORE splitting into lines and checking "does this
        # line start with something that looks like code" -- a per-line
        # leading-character check has no memory of being inside a multi-line
        # /* ... */ block, so a comment continuation line like "without
        # getting a sqrt(2) distortion in speed." (no leading marker of its
        # own) reads as ordinary top-level code and "sqrt" gets extracted as
        # if it were a real declared name -- which then shadows the real
        # libm sqrt() once renamed, breaking every actual call to it.
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        content = re.sub(r'//.*', '', content)
        for line in content.split('\n'):
            # Only top-level declarations, not indented code inside a function
            # body (which would false-positive on local vars, control-flow
            # keywords, etc) or preprocessor/brace lines.
            if not line or line[0] in ' \t#{}':
                continue
            # Function-pointer VARIABLE declarator: "TYPE (*name)(params);" --
            # e.g. "qboolean (*trap_Language_IsAsian)(void);" from the
            # multiversion redirect pattern. The name sits wrapped in its own
            # parens, which breaks both the "split on first (" function path
            # (grabs the return type instead, since "(*name)" IS the first
            # paren) and would break the plain variable path too. Handled as
            # its own case, checked first, since neither generic path copes
            # with the extra parens around the name itself.
            fp_match = re.search(r'\(\s*\*\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)', line)
            if fp_match:
                name = fp_match.group(1)
                if name not in C_KEYWORDS:
                    symbols.add(name)
                continue
            # Dispatch on whether '=' precedes the first '(' (or there's no
            # '(' before it), NOT merely on whether '(' appears anywhere --
            # "int scriptCommandCount = sizeof(commandList) / ...;" has a
            # paren from the sizeof() call inside the initializer, which isn't
            # a function declaration at all. Only treat it as one when the
            # paren comes first with no assignment in front of it.
            paren_idx = line.find('(')
            eq_idx = line.find('=')
            is_function = paren_idx != -1 and (eq_idx == -1 or paren_idx < eq_idx)
            if is_function:
                # A function definition/prototype: name is whatever sits right
                # before the FIRST '(' (the parameter list), however many type
                # words, pointer stars, or calling-convention macros (QDECL)
                # come before it -- "char *Info_ValueForKey(" and
                # "char	* QDECL va(" both reduce correctly this way.
                before = line.split('(', 1)[0]
                name = _last_ident_before(before)
                if name and name not in C_KEYWORDS:
                    symbols.add(name)
            else:
                # A variable declaration/definition. Three shapes: "TYPE name;"
                # (no initializer); "TYPE name = {1,2,3};" (initializer AND
                # terminator on this line -- colorDkBlue etc); "TYPE name[N] = {"
                # (a big constant table like bytedirs/g_color_table, initializer
                # spanning many following lines). "=" MUST be tried before ";" --
                # if both are present, splitting on ";" first grabs the whole
                # initializer as if it were the name (its last token is a
                # numeric literal, which fails the identifier check and the
                # declaration is silently dropped instead of misnamed, which is
                # how colorDkBlue and friends went missing).
                for sep in ('=', ';'):
                    if sep in line:
                        before = line.split(sep, 1)[0]
                        before = re.sub(r'\[[^\]]*\]', '', before)  # drop array subscript
                        name = _last_ident_before(before)
                        if name and name not in C_KEYWORDS:
                            symbols.add(name)
                        break
    return sorted(
        s for s in symbols
        if s not in macro_names and s not in PC_TRAP_FUNCS and not s[0].isdigit()
    )


def write_header(path, prefix, symbols):
    with open(path, "w") as f:
        f.write('// Auto-generated by gen_renames.py -- do not edit by hand\n')
        f.write(f'#define vmMain {prefix}_vmMain\n')
        f.write(f'#define dllEntry {prefix}_dllEntry\n')
        for sym in PC_TRAP_FUNCS:
            f.write(f'#define {sym} {prefix}_{sym}\n')
        for sym in symbols:
            f.write(f'#ifndef {sym}\n#define {sym} {prefix}_{sym}\n#endif\n')


cg_symbols = scan(CGAME_C_FILES)
ui_symbols = scan(UI_C_FILES)

write_header(os.path.join(os.path.dirname(__file__), "cg_rename.h"), "mvcg", cg_symbols)
write_header(os.path.join(os.path.dirname(__file__), "ui_rename.h"), "mvui", ui_symbols)

print(f"Done! cgame: {len(cg_symbols)} symbols across {len(CGAME_C_FILES)} files. "
      f"ui: {len(ui_symbols)} symbols across {len(UI_C_FILES)} files.")
