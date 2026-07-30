#============================================================================
# JK2MV WASM Build — Monolithic single-executable for Emscripten
# Modeled directly on pdewilde/openjk-wasm's proven wasm/CMakeLists.txt
# (same GL4ES/monolithic-link/main-loop/module-stub patterns), adapted for
# JK2MV's two-repo layout: engine in ../src, game/cgame/ui in ../src/mvsdk.
#============================================================================

cmake_minimum_required(VERSION 3.13)
project(jk2mv_wasm C CXX)

set(CMAKE_CXX_STANDARD 11)
set(CMAKE_C_STANDARD 11)

# ============================================================================
# Paths
# ============================================================================
set(ProjectRoot "${CMAKE_SOURCE_DIR}/..")
set(JK2Dir "${ProjectRoot}/src")
set(SDKDir "${ProjectRoot}/src/mvsdk/code")
# Reuse the GL4ES already built for the OpenJK WASM port -- it's a generic
# OpenGL-1.x-to-GLES translator, not OpenJK-specific. Avoids a ~3min rebuild.
set(GL4ESDir "${ProjectRoot}/../openjk-wasm/lib/gl4es")

file(WRITE "${CMAKE_BINARY_DIR}/mv_setup.h"
    "#ifndef MV_SETUP_H\n"
    "#define MV_SETUP_H\n"
    "#define JK2MV_VERSION \"wasm-build\"\n"
    "#define Q3_VERSION \"JK2MV: v\" JK2MV_VERSION\n"
    "#endif\n"
)
file(WRITE "${CMAKE_BINARY_DIR}/mvsdk_setup.h"
    "#ifndef MVSDK_SETUP_H\n"
    "#define MVSDK_SETUP_H\n"
    "#define MVSDK_VERSION \"wasm-build\"\n"
    "#endif\n"
)

# ============================================================================
# Global compile definitions (mirrors GlobalDefines from jk2mv/CMakeLists.txt
# and mvsdk/CMakeLists.txt's standalone -- NOT InMV -- branch)
# ============================================================================
add_compile_definitions(
    __EMSCRIPTEN__
    __linux__
    NO_VM_COMPILED       # no x86/arm JIT bytecode compiler needed, native-linked only
    BOTLIB                # jk2mv/CMakeLists.txt sets this globally too -- botlib/*.cpp is
                           # #ifdef SCREWUP / #ifdef BOTLIB gated; without it, l_precomp.cpp
                           # et al compile essentially empty (no includes reached at all).
    USE_OPENAL=1          # a plain compiler define, NOT an emscripten -s setting
    MISSIONPACK
    GAME_EXPORTS
    _JK2
    DEFAULT_ES=2          # GL4ES: use GLES2 backend
)

# Emscripten ports (SDL2, GLES) need these -s flags at COMPILE time too, not
# just link time, so the compiler picks the port-provided headers instead of
# the "you forgot -sUSE_SDL" stub SDL.h in Emscripten's sysroot.
add_compile_options(
    -sUSE_SDL=2
    -sFULL_ES2=1
)

include_directories(
    "${CMAKE_BINARY_DIR}"
    "${JK2Dir}"
    "${GL4ESDir}/include"
    "${ProjectRoot}/libs/mp3"
    "${ProjectRoot}/libs/zlib"
    "${ProjectRoot}/libs/zlib/include"
    "${ProjectRoot}/libs/minizip/include/minizip"
    "${ProjectRoot}/libs/eax"
    "${ProjectRoot}/libs/libpng/include"
    "${ProjectRoot}/libs/jpeg-9a"
    "${ProjectRoot}/libs/jpeg-9a/include"
)

set(LibPNGFiles
    "${ProjectRoot}/libs/libpng/png.c"
    "${ProjectRoot}/libs/libpng/pngerror.c"
    "${ProjectRoot}/libs/libpng/pngget.c"
    "${ProjectRoot}/libs/libpng/pngmem.c"
    "${ProjectRoot}/libs/libpng/pngpread.c"
    "${ProjectRoot}/libs/libpng/pngread.c"
    "${ProjectRoot}/libs/libpng/pngrio.c"
    "${ProjectRoot}/libs/libpng/pngrtran.c"
    "${ProjectRoot}/libs/libpng/pngrutil.c"
    "${ProjectRoot}/libs/libpng/pngset.c"
    "${ProjectRoot}/libs/libpng/pngtrans.c"
    "${ProjectRoot}/libs/libpng/pngwio.c"
    "${ProjectRoot}/libs/libpng/pngwrite.c"
    "${ProjectRoot}/libs/libpng/pngwtran.c"
    "${ProjectRoot}/libs/libpng/pngwutil.c"
)
set(LibJPEGFiles
    "${ProjectRoot}/libs/jpeg-9a/jaricom.c"
    "${ProjectRoot}/libs/jpeg-9a/jcapimin.c"
    "${ProjectRoot}/libs/jpeg-9a/jcapistd.c"
    "${ProjectRoot}/libs/jpeg-9a/jcarith.c"
    "${ProjectRoot}/libs/jpeg-9a/jccoefct.c"
    "${ProjectRoot}/libs/jpeg-9a/jccolor.c"
    "${ProjectRoot}/libs/jpeg-9a/jcdctmgr.c"
    "${ProjectRoot}/libs/jpeg-9a/jchuff.c"
    "${ProjectRoot}/libs/jpeg-9a/jcinit.c"
    "${ProjectRoot}/libs/jpeg-9a/jcmainct.c"
    "${ProjectRoot}/libs/jpeg-9a/jcmarker.c"
    "${ProjectRoot}/libs/jpeg-9a/jcmaster.c"
    "${ProjectRoot}/libs/jpeg-9a/jcomapi.c"
    "${ProjectRoot}/libs/jpeg-9a/jcparam.c"
    "${ProjectRoot}/libs/jpeg-9a/jcprepct.c"
    "${ProjectRoot}/libs/jpeg-9a/jcsample.c"
    "${ProjectRoot}/libs/jpeg-9a/jctrans.c"
    "${ProjectRoot}/libs/jpeg-9a/jdapimin.c"
    "${ProjectRoot}/libs/jpeg-9a/jdapistd.c"
    "${ProjectRoot}/libs/jpeg-9a/jdarith.c"
    "${ProjectRoot}/libs/jpeg-9a/jdatadst.c"
    "${ProjectRoot}/libs/jpeg-9a/jdatasrc.c"
    "${ProjectRoot}/libs/jpeg-9a/jdcoefct.c"
    "${ProjectRoot}/libs/jpeg-9a/jdcolor.c"
    "${ProjectRoot}/libs/jpeg-9a/jddctmgr.c"
    "${ProjectRoot}/libs/jpeg-9a/jdhuff.c"
    "${ProjectRoot}/libs/jpeg-9a/jdinput.c"
    "${ProjectRoot}/libs/jpeg-9a/jdmainct.c"
    "${ProjectRoot}/libs/jpeg-9a/jdmarker.c"
    "${ProjectRoot}/libs/jpeg-9a/jdmaster.c"
    "${ProjectRoot}/libs/jpeg-9a/jdmerge.c"
    "${ProjectRoot}/libs/jpeg-9a/jdpostct.c"
    "${ProjectRoot}/libs/jpeg-9a/jdsample.c"
    "${ProjectRoot}/libs/jpeg-9a/jdtrans.c"
    "${ProjectRoot}/libs/jpeg-9a/jerror.c"
    "${ProjectRoot}/libs/jpeg-9a/jfdctflt.c"
    "${ProjectRoot}/libs/jpeg-9a/jfdctfst.c"
    "${ProjectRoot}/libs/jpeg-9a/jfdctint.c"
    "${ProjectRoot}/libs/jpeg-9a/jidctflt.c"
    "${ProjectRoot}/libs/jpeg-9a/jidctfst.c"
    "${ProjectRoot}/libs/jpeg-9a/jidctint.c"
    "${ProjectRoot}/libs/jpeg-9a/jmemmgr.c"
    "${ProjectRoot}/libs/jpeg-9a/jmemnobs.c"
    "${ProjectRoot}/libs/jpeg-9a/jquant1.c"
    "${ProjectRoot}/libs/jpeg-9a/jquant2.c"
    "${ProjectRoot}/libs/jpeg-9a/jutils.c"
    "${ProjectRoot}/libs/jpeg-9a/rdbmp.c"
    "${ProjectRoot}/libs/jpeg-9a/rdcolmap.c"
    "${ProjectRoot}/libs/jpeg-9a/rdgif.c"
    "${ProjectRoot}/libs/jpeg-9a/rdppm.c"
    "${ProjectRoot}/libs/jpeg-9a/rdrle.c"
    "${ProjectRoot}/libs/jpeg-9a/rdswitch.c"
    "${ProjectRoot}/libs/jpeg-9a/rdtarga.c"
    "${ProjectRoot}/libs/jpeg-9a/wrbmp.c"
    "${ProjectRoot}/libs/jpeg-9a/wrgif.c"
    "${ProjectRoot}/libs/jpeg-9a/wrppm.c"
    "${ProjectRoot}/libs/jpeg-9a/wrrle.c"
    "${ProjectRoot}/libs/jpeg-9a/wrtarga.c"
)
set_source_files_properties(${LibPNGFiles} ${LibJPEGFiles} PROPERTIES COMPILE_FLAGS "-w")

set(ZLibFiles
    "${ProjectRoot}/libs/zlib/adler32.c"
    "${ProjectRoot}/libs/zlib/compress.c"
    "${ProjectRoot}/libs/zlib/crc32.c"
    "${ProjectRoot}/libs/zlib/deflate.c"
    # gzclose/gzlib/gzread/gzwrite.c omitted: the gzopen()-style convenience API
    # for standalone .gz files, not called anywhere -- minizip's unzip.c reads
    # pk3s via zlib's raw inflate() primitives directly, not this layer.
    "${ProjectRoot}/libs/zlib/infback.c"
    "${ProjectRoot}/libs/zlib/inffast.c"
    "${ProjectRoot}/libs/zlib/inflate.c"
    "${ProjectRoot}/libs/zlib/inftrees.c"
    "${ProjectRoot}/libs/zlib/trees.c"
    "${ProjectRoot}/libs/zlib/uncompr.c"
    "${ProjectRoot}/libs/zlib/zutil.c"
)
set(MinizipFiles
    "${ProjectRoot}/libs/minizip/ioapi.c"
    "${ProjectRoot}/libs/minizip/unzip.c"
)
set_source_files_properties(${ZLibFiles} ${MinizipFiles} PROPERTIES COMPILE_FLAGS "-w")

# ============================================================================
# Engine sources (client + qcommon + botlib + server + ghoul2 + renderer + sys + sdl)
# ============================================================================
set(EngineBotlibFiles
    "${JK2Dir}/botlib/be_aas_bspq3.cpp"
    "${JK2Dir}/botlib/be_aas_cluster.cpp"
    "${JK2Dir}/botlib/be_aas_debug.cpp"
    "${JK2Dir}/botlib/be_aas_entity.cpp"
    "${JK2Dir}/botlib/be_aas_file.cpp"
    "${JK2Dir}/botlib/be_aas_main.cpp"
    "${JK2Dir}/botlib/be_aas_move.cpp"
    "${JK2Dir}/botlib/be_aas_optimize.cpp"
    "${JK2Dir}/botlib/be_aas_reach.cpp"
    "${JK2Dir}/botlib/be_aas_route.cpp"
    "${JK2Dir}/botlib/be_aas_routealt.cpp"
    "${JK2Dir}/botlib/be_aas_sample.cpp"
    "${JK2Dir}/botlib/be_ai_char.cpp"
    "${JK2Dir}/botlib/be_ai_chat.cpp"
    "${JK2Dir}/botlib/be_ai_gen.cpp"
    "${JK2Dir}/botlib/be_ai_goal.cpp"
    "${JK2Dir}/botlib/be_ai_move.cpp"
    "${JK2Dir}/botlib/be_ai_weap.cpp"
    "${JK2Dir}/botlib/be_ai_weight.cpp"
    "${JK2Dir}/botlib/be_ea.cpp"
    "${JK2Dir}/botlib/be_interface.cpp"
    "${JK2Dir}/botlib/l_crc.cpp"
    "${JK2Dir}/botlib/l_libvar.cpp"
    "${JK2Dir}/botlib/l_log.cpp"
    "${JK2Dir}/botlib/l_memory.cpp"
    "${JK2Dir}/botlib/l_precomp.cpp"
    "${JK2Dir}/botlib/l_script.cpp"
    "${JK2Dir}/botlib/l_struct.cpp"
)

set(EngineServerFiles
    "${JK2Dir}/server/sv_bot.cpp"
    "${JK2Dir}/server/sv_ccmds.cpp"
    "${JK2Dir}/server/sv_client.cpp"
    "${JK2Dir}/server/sv_game.cpp"
    "${JK2Dir}/server/sv_init.cpp"
    "${JK2Dir}/server/sv_main.cpp"
    "${JK2Dir}/server/sv_net_chan.cpp"
    "${JK2Dir}/server/sv_snapshot.cpp"
    "${JK2Dir}/server/sv_world.cpp"
)

set(EngineGhoul2Files
    "${JK2Dir}/ghoul2/G2_API.cpp"
    "${JK2Dir}/ghoul2/G2_bolts.cpp"
    "${JK2Dir}/ghoul2/G2_bones.cpp"
    "${JK2Dir}/ghoul2/G2_misc.cpp"
    "${JK2Dir}/ghoul2/G2_surfaces.cpp"
)

set(EngineQCommonFiles
    "${JK2Dir}/qcommon/CNetProfile.cpp"
    "${JK2Dir}/qcommon/GenericParser2.cpp"
    "${JK2Dir}/qcommon/RoffSystem.cpp"
    "${JK2Dir}/qcommon/cm_load.cpp"
    "${JK2Dir}/qcommon/cm_patch.cpp"
    "${JK2Dir}/qcommon/cm_polylib.cpp"
    "${JK2Dir}/qcommon/cm_test.cpp"
    "${JK2Dir}/qcommon/cm_trace.cpp"
    "${JK2Dir}/qcommon/cmd.cpp"
    "${JK2Dir}/qcommon/common.cpp"
    "${JK2Dir}/qcommon/cvar.cpp"
    "${JK2Dir}/qcommon/files.cpp"
    "${JK2Dir}/qcommon/hstring.cpp"
    "${JK2Dir}/qcommon/huffman.cpp"
    "${JK2Dir}/qcommon/md4.cpp"
    "${JK2Dir}/qcommon/msg.cpp"
    "${JK2Dir}/qcommon/net_chan.cpp"
    "${JK2Dir}/qcommon/net_ip.cpp"
    "${CMAKE_SOURCE_DIR}/net_http_stub.cpp" # real net_http.cpp needs mongoose (HTTP server lib) -- irrelevant to demo playback
    "${JK2Dir}/qcommon/q_math.cpp"
    "${JK2Dir}/qcommon/q_shared.cpp"
    "${JK2Dir}/qcommon/strip.cpp"
    "${JK2Dir}/qcommon/vm.cpp"
    "${JK2Dir}/qcommon/vm_interpreted.cpp"
)

set(EngineRendererFiles
    "${JK2Dir}/renderer/matcomp.c"
    "${JK2Dir}/renderer/tr_backend.cpp"
    "${JK2Dir}/renderer/tr_ghoul2.cpp"
    "${JK2Dir}/renderer/tr_image.cpp"
    "${JK2Dir}/renderer/tr_init.cpp"
    "${JK2Dir}/renderer/tr_main.cpp"
    "${JK2Dir}/renderer/tr_mesh.cpp"
    "${JK2Dir}/renderer/tr_model.cpp"
    "${JK2Dir}/renderer/tr_shader.cpp"
    "${JK2Dir}/renderer/tr_WorldEffects.cpp"
    "${JK2Dir}/renderer/tr_animation.cpp"
    "${JK2Dir}/renderer/tr_bsp.cpp"
    "${JK2Dir}/renderer/tr_cmds.cpp"
    "${JK2Dir}/renderer/tr_curve.cpp"
    "${JK2Dir}/renderer/tr_flares.cpp"
    "${JK2Dir}/renderer/tr_font.cpp"
    "${JK2Dir}/renderer/tr_light.cpp"
    "${JK2Dir}/renderer/tr_marks.cpp"
    "${JK2Dir}/renderer/tr_noise.cpp"
    "${JK2Dir}/renderer/tr_quicksprite.cpp"
    "${JK2Dir}/renderer/tr_scene.cpp"
    "${JK2Dir}/renderer/tr_shade.cpp"
    "${JK2Dir}/renderer/tr_shade_calc.cpp"
    "${JK2Dir}/renderer/tr_shadows.cpp"
    "${JK2Dir}/renderer/tr_sky.cpp"
    "${JK2Dir}/renderer/tr_surface.cpp"
    "${JK2Dir}/renderer/tr_surfacesprites.cpp"
    "${JK2Dir}/renderer/tr_world.cpp"
)

set(EngineClientFiles
    "${JK2Dir}/client/FXExport.cpp"
    "${JK2Dir}/client/FxPrimitives.cpp"
    "${JK2Dir}/client/FxScheduler.cpp"
    "${JK2Dir}/client/FxSystem.cpp"
    "${JK2Dir}/client/FxTemplate.cpp"
    "${JK2Dir}/client/FxUtil.cpp"
    "${JK2Dir}/client/cl_avi.cpp"
    "${JK2Dir}/client/cl_cgame.cpp"
    "${JK2Dir}/client/cl_cin.cpp"
    "${JK2Dir}/client/cl_console.cpp"
    "${JK2Dir}/client/cl_demos_auto.cpp"
    "${JK2Dir}/client/cl_input.cpp"
    "${JK2Dir}/client/cl_keys.cpp"
    "${JK2Dir}/client/cl_main.cpp"
    "${JK2Dir}/client/cl_net_chan.cpp"
    "${JK2Dir}/client/cl_parse.cpp"
    "${JK2Dir}/client/cl_scrn.cpp"
    "${JK2Dir}/client/cl_ui.cpp"
    "${JK2Dir}/client/snd_dma.cpp"
    "${JK2Dir}/client/snd_mem.cpp"
    "${JK2Dir}/client/snd_mix.cpp"
    "${JK2Dir}/client/snd_mp3.cpp"
)

set(EngineMP3Files
    "${ProjectRoot}/libs/mp3/cdct.c"
    "${ProjectRoot}/libs/mp3/csbt.c"
    "${ProjectRoot}/libs/mp3/csbtb.c"
    "${ProjectRoot}/libs/mp3/csbtl3.c"
    "${ProjectRoot}/libs/mp3/cup.c"
    "${ProjectRoot}/libs/mp3/cupini.c"
    "${ProjectRoot}/libs/mp3/cupl1.c"
    "${ProjectRoot}/libs/mp3/cupl3.c"
    "${ProjectRoot}/libs/mp3/cwin.c"
    "${ProjectRoot}/libs/mp3/cwinb.c"
    "${ProjectRoot}/libs/mp3/cwinm.c"
    "${ProjectRoot}/libs/mp3/hwin.c"
    "${ProjectRoot}/libs/mp3/l3dq.c"
    "${ProjectRoot}/libs/mp3/l3init.c"
    "${ProjectRoot}/libs/mp3/mdct.c"
    "${ProjectRoot}/libs/mp3/mhead.c"
    "${ProjectRoot}/libs/mp3/msis.c"
    # towave.c also defines C_MP3Stream_DecodeInit/Decode, which snd_mp3.cpp
    # DOES call (wrongly assumed dead code earlier -- checked for "towave"/
    # "ToWave" identifiers, not the actual decoder function names it needs).
    # Its dead sys/soundcard.h include (unused OSS device API, confirmed no
    # ioctl/SNDCTL call sites anywhere else in the file) is now excluded for
    # Emscripten specifically -- see the __EMSCRIPTEN__ check in the file itself.
    "${ProjectRoot}/libs/mp3/towave.c"
    "${ProjectRoot}/libs/mp3/uph.c"
    "${ProjectRoot}/libs/mp3/upsf.c"
    "${ProjectRoot}/libs/mp3/wavep.c"
)
set_source_files_properties(${EngineMP3Files} PROPERTIES COMPILE_FLAGS "-w")

set(EngineSysFiles
    "${JK2Dir}/sys/con_log.cpp"
    "${JK2Dir}/sys/con_tty.cpp"
    "${JK2Dir}/sys/sys_main.cpp"
    "${JK2Dir}/sys/sys_event.cpp"
    "${JK2Dir}/sys/sys_unix.cpp"
)

set(EngineSDLFiles
    "${JK2Dir}/sdl/sdl_input.cpp"
    "${JK2Dir}/sdl/sdl_sound.cpp"
    "${JK2Dir}/sdl/sdl_window.cpp"
)

# ============================================================================
# cgame + menu(ui) -- statically linked modules, symbol-renamed via -include
# so their duplicate copy of ui_shared.c (and their own vmMain/dllEntry) don't
# collide when linked into one monolithic binary. Same shape as OpenJK's
# cg_rename.h/ui_rename.h (wasm/gen_renames.py generates both here too).
# ============================================================================
set(CGameFiles
    "${SDKDir}/cgame/cg_main.c"
    "${SDKDir}/cgame/cg_consolecmds.c"
    "${SDKDir}/cgame/cg_draw.c"
    "${SDKDir}/cgame/cg_drawtools.c"
    "${SDKDir}/cgame/cg_effects.c"
    "${SDKDir}/cgame/cg_ents.c"
    "${SDKDir}/cgame/cg_event.c"
    "${SDKDir}/cgame/cg_info.c"
    "${SDKDir}/cgame/cg_light.c"
    "${SDKDir}/cgame/cg_localents.c"
    "${SDKDir}/cgame/cg_marks.c"
    "${SDKDir}/cgame/cg_newDraw.c"
    "${SDKDir}/cgame/cg_players.c"
    "${SDKDir}/cgame/cg_playerstate.c"
    "${SDKDir}/cgame/cg_predict.c"
    "${SDKDir}/cgame/cg_saga.c"
    "${SDKDir}/cgame/cg_scoreboard.c"
    "${SDKDir}/cgame/cg_servercmds.c"
    "${SDKDir}/cgame/cg_snapshot.c"
    "${SDKDir}/cgame/cg_turret.c"
    "${SDKDir}/cgame/cg_view.c"
    "${SDKDir}/cgame/cg_weaponinit.c"
    "${SDKDir}/cgame/cg_weapons.c"
    "${SDKDir}/cgame/fx_blaster.c"
    "${SDKDir}/cgame/fx_bowcaster.c"
    "${SDKDir}/cgame/fx_bryarpistol.c"
    "${SDKDir}/cgame/fx_demp2.c"
    "${SDKDir}/cgame/fx_disruptor.c"
    "${SDKDir}/cgame/fx_flechette.c"
    "${SDKDir}/cgame/fx_force.c"
    "${SDKDir}/cgame/fx_heavyrepeater.c"
    "${SDKDir}/cgame/fx_rocketlauncher.c"
    "${SDKDir}/cgame/cg_multiversion.c"
    "${SDKDir}/cgame/cg_multiversion_syscalls.c"
    "${SDKDir}/game/bg_multiversion.c"
    "${SDKDir}/game/animMappingTable.c"
    "${SDKDir}/game/bg_misc.c"
    "${SDKDir}/game/bg_panimate.c"
    "${SDKDir}/game/bg_pmove.c"
    "${SDKDir}/game/bg_saber.c"
    "${SDKDir}/game/bg_slidemove.c"
    "${SDKDir}/game/bg_weapons.c"
    "${SDKDir}/game/q_math.c"
    "${SDKDir}/game/q_shared.c"
    "${SDKDir}/ui/ui_shared.c"
    "${SDKDir}/cgame/cg_syscalls.c"
    "${CMAKE_SOURCE_DIR}/cg_pc_trap_glue.c"
)
add_library(jk2mv_cgame STATIC ${CGameFiles})
target_include_directories(jk2mv_cgame PRIVATE "${SDKDir}" "${SDKDir}/cgame" "${SDKDir}/game" "${SDKDir}/ui" "${SDKDir}/api" "${SDKDir}/qcommon" "${SDKDir}/ghoul2")
target_compile_definitions(jk2mv_cgame PRIVATE JK2_CGAME)
target_compile_options(jk2mv_cgame PRIVATE "-include" "${CMAKE_SOURCE_DIR}/cg_rename.h")
# cg_syscalls.c ALSO needs the trap_PC_* function-vs-variable rename (see
# cg_syscalls_pc_rename.h) -- applied only to this one file, on top of the
# target-wide cg_rename.h above (both -include flags apply together, in order).
set_source_files_properties("${SDKDir}/cgame/cg_syscalls.c" PROPERTIES
    COMPILE_OPTIONS "-include;${CMAKE_SOURCE_DIR}/cg_syscalls_pc_rename.h")

set(MenuFiles
    "${SDKDir}/ui/ui_main.c"
    "${SDKDir}/ui/ui_atoms.c"
    "${SDKDir}/ui/ui_force.c"
    "${SDKDir}/ui/ui_gameinfo.c"
    "${SDKDir}/ui/ui_shared.c"
    "${SDKDir}/ui/ui_multiversion.c"
    "${SDKDir}/game/bg_misc.c"
    "${SDKDir}/game/bg_weapons.c"
    "${SDKDir}/game/q_math.c"
    "${SDKDir}/game/q_shared.c"
    "${SDKDir}/ui/ui_multiversion_syscalls.c"
    "${SDKDir}/game/bg_multiversion.c"
    "${SDKDir}/ui/ui_syscalls.c"
)
add_library(jk2mv_ui STATIC ${MenuFiles})
target_include_directories(jk2mv_ui PRIVATE "${SDKDir}" "${SDKDir}/ui" "${SDKDir}/game" "${SDKDir}/api" "${SDKDir}/qcommon")
target_compile_definitions(jk2mv_ui PRIVATE JK2_UI)
target_compile_options(jk2mv_ui PRIVATE "-include" "${CMAKE_SOURCE_DIR}/ui_rename.h")

# ============================================================================
# Main executable
# ============================================================================
add_executable(jk2mv_wasm
    ${EngineBotlibFiles}
    ${EngineServerFiles}
    ${EngineGhoul2Files}
    ${EngineQCommonFiles}
    ${EngineRendererFiles}
    ${EngineClientFiles}
    ${EngineMP3Files}
    ${EngineSysFiles}
    ${EngineSDLFiles}
    ${ZLibFiles}
    ${MinizipFiles}
    ${LibPNGFiles}
    ${LibJPEGFiles}
)

target_link_libraries(jk2mv_wasm PRIVATE
    jk2mv_cgame
    jk2mv_ui
    "${GL4ESDir}/lib/libGL.a"
    "-lopenal"
)

set(EMS_LINK_FLAGS
    "-Wl,--error-limit=0" # see every duplicate/mismatch error in one pass instead of iterating on 20 at a time
    "-sUSE_SDL=2"
    "-sFULL_ES2=1"
    "-sALLOW_MEMORY_GROWTH=1"
    "-sINITIAL_MEMORY=134217728"
    "-sEXPORTED_RUNTIME_METHODS=['FS','run','callMain','ccall','cwrap']"
    "-sSTACK_SIZE=5MB"
    "-sASSERTIONS=1"
    "-sSTACK_OVERFLOW_CHECK=1" # this was firing for real: GL4ES writing through a NULL glstate was
                               # clobbering low memory including the stack cookie. Keep it enabled.
    "--profiling-funcs" # keep function names in the wasm binary so crash stack traces are symbolicated, not just addresses
    "--shell-file" "${CMAKE_SOURCE_DIR}/shell.html"
    "--preload-file" "${ProjectRoot}/GameData/base@base"
)
string(REPLACE ";" " " EMS_LINK_FLAGS_STR "${EMS_LINK_FLAGS}")
set_target_properties(jk2mv_wasm PROPERTIES
    LINK_FLAGS "${EMS_LINK_FLAGS_STR}"
    SUFFIX ".html"
    OUTPUT_NAME "jk2mv_wasm"
)
