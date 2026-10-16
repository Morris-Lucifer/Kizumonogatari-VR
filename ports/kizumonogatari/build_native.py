"""Windows-hosted, pinned ARM64/glibc core build. No Android NDK is needed here."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'evidence/kizu-native'
SOURCE = WORK / 'src/shadps4-arm64-main'
FEX = SOURCE / 'runtime/sources/fex'
LLVM = WORK / 'llvm/bin'
SYSROOT = WORK / 'sysroot'
VS = Path(r'C:\Program Files\Microsoft Visual Studio\2022\Community')
CMAKE = Path(os.environ.get('KIZU_CMAKE') or shutil.which('cmake') or
             str(VS / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'))
NINJA = Path(os.environ.get('KIZU_NINJA') or shutil.which('ninja') or
             str(VS / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe'))
TOOLCHAIN = WORK / 'arm64.cmake'


def run(stage, args):
    log = WORK / (datetime.now().strftime('%Y%m%d-%H%M%S-') + stage + '.log')
    command = [str(x) for x in args]
    log.with_suffix('.command.json').write_text(json.dumps(command, indent=2))
    env = os.environ.copy()
    env.pop('INCLUDE', None)
    env.pop('LIB', None)
    shims = WORK / 'shims'
    shims.mkdir(exist_ok=True)
    (shims / 'python3.cmd').write_text('@echo off\n"' + sys.executable + '" %*\n')
    env['PATH'] = os.pathsep.join([str(shims), str(LLVM), str(NINJA.parent), str(Path(sys.executable).parent), env['PATH']])
    print(f'{stage}: {log}', flush=True)
    with log.open('w', encoding='utf-8') as out:
        result = subprocess.run(command, stdout=out, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        print(log.read_text(encoding='utf-8', errors='replace')[-12000:], flush=True)
        raise SystemExit(result.returncode)
    print(stage + ': passed', flush=True)


def toolchain():
    template = (ROOT / 'build_reference/FGO-Quest/scripts/fgo-arm64.cmake').read_text()
    template = template.replace('set(CMAKE_SYSROOT "${FGO_QUEST_ROOT}/tools/sysroot-arm64")',
                                f'set(CMAKE_SYSROOT "{SYSROOT.as_posix()}")')
    template = template.replace('set(FGO_LLVM_BIN "${FGO_WORK_ROOT}/tools/llvm-21.1.8/bin")',
                                f'set(FGO_LLVM_BIN "{LLVM.as_posix()}")')
    TOOLCHAIN.write_text(template, encoding='utf-8')


def configure(source, build, args):
    run(build.name + '-configure', [CMAKE, '-S', source, '-B', build, '-G', 'Ninja',
        f'-DCMAKE_MAKE_PROGRAM={NINJA}', f'-DCMAKE_TOOLCHAIN_FILE={TOOLCHAIN}',
        '-DCMAKE_BUILD_TYPE=RelWithDebInfo', '-DCMAKE_CXX_SCAN_FOR_MODULES=OFF',
        '-DCMAKE_POLICY_VERSION_MINIMUM=3.5', f'-DPython_EXECUTABLE={sys.executable}',
        f'-DPython3_EXECUTABLE={sys.executable}', *args])


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def export_core(build):
    candidates = [p for p in build.rglob('shadps4') if p.is_file()]
    if len(candidates) != 1:
        raise RuntimeError(f'Expected exactly one core executable, found {candidates}')
    out = WORK / ('artifact-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    symbols = out / 'shadps4-arm64-fex.unstripped'
    core = out / 'shadps4-arm64-fex'
    shutil.copyfile(candidates[0], symbols)
    run('strip-core', [LLVM / 'llvm-strip.exe', '--strip-unneeded', '-o', core, symbols])
    run('inspect-core', [LLVM / 'llvm-readobj.exe', '--file-headers', '--needed-libs', '--notes', core])
    inputs = [ROOT / 'upstream/arm64-sysroot-lock.json',
              ROOT / 'patches/fgo-resolution-quest-complete.patch',
              ROOT / 'patches/build-support/fex-fexcore-only.patch',
              *sorted((ROOT / 'ports/kizumonogatari/native').glob('*.h')),
              *sorted((ROOT / 'ports/kizumonogatari/native').glob('*.patch'))]
    record = dict(core=str(core), core_sha256=sha(core), symbols=str(symbols),
                  symbols_sha256=sha(symbols), architecture='AArch64 Linux glibc',
                  astro_commit='9f42c44d4e838e3a0df67913e350c4f098110862',
                  fex_commit='f2b679f6028ce1c38875233aecfcf5d3f8ebecec', llvm='21.1.8',
                  configuration='RelWithDebInfo', device_validation='not run',
                  vr_protocol_sha256=sha(SOURCE / 'src/core/vr/vr_protocol.h'),
                  inputs={str(p.relative_to(ROOT)): sha(p) for p in inputs})
    (out / 'manifest.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    (WORK / 'latest-native.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('Exported native core: ' + str(core), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['fex', 'harness', 'core', 'font'])
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    toolchain()
    fex_build = WORK / 'build-fex'
    font = WORK / 'font-embed.exe'
    if args.stage == 'font':
        run('font', [LLVM / 'clang++.exe', '-O2',
            SOURCE / 'externals/dear_imgui/misc/fonts/binary_to_compressed_c.cpp', '-o', font])
        return
    if args.stage in ('fex', 'harness'):
        build = fex_build
        harness = [SOURCE / path for path in (
            'src/core/fex/fex_guest_engine.cpp', 'src/core/guest_cpu/fex_guest_cpu.cpp',
            'src/core/guest_cpu/hle_call_adapter.cpp', 'src/core/guest_cpu/fex_hle_bridge.cpp',
            'runtime/probes/fexcore-guest-harness.cpp')]
        configure(FEX, build, [
            '-DBUILD_FEXCORE_ONLY=ON', f'-DFEXCORE_SMOKE_SOURCE={SOURCE / "runtime/probes/fexcore-smoke.cpp"}',
            f'-DFEXCORE_PROJECT_SOURCE_DIR={SOURCE / "src"}',
            '-DFEXCORE_GUEST_HARNESS_SOURCES=' + ';'.join(x.as_posix() for x in harness),
            '-DTUNE_CPU=none', '-DBUILD_TESTING=OFF', '-DBUILD_FEX_LINUX_TESTS=OFF',
            '-DBUILD_THUNKS=OFF', '-DBUILD_FEXCONFIG=OFF', '-DENABLE_GDB_SYMBOLS=OFF',
            '-DENABLE_LTO=OFF', '-DENABLE_JEMALLOC_GLIBC_ALLOC=OFF',
            '-DENABLE_OFFLINE_TELEMETRY=OFF', '-DENABLE_VIXL_DISASSEMBLER=OFF',
            '-DENABLE_VIXL_SIMULATOR=OFF', '-DENABLE_ZYDIS=OFF', '-DENABLE_FEXCORE_PROFILER=OFF'])
        target = 'fexcore-guest-harness' if args.stage == 'harness' else 'fexcore-smoke'
    else:
        build = WORK / 'build-core'
        configure(SOURCE, build, [
            f'-DCMAKE_C_FLAGS=--target=aarch64-linux-gnu --gcc-toolchain={SYSROOT.as_posix()}/usr',
            '-DENABLE_BACHATA_RUNTIME=ON', '-DENABLE_FEX_GUEST_CPU=ON',
            f'-DFEXCORE_GUEST_CPU_SOURCE_DIR={FEX}', f'-DFEXCORE_GUEST_CPU_BUILD_DIR={fex_build}',
            f'-DIMGUI_FONT_EMBED_EXECUTABLE={font}',
            f'-DX11_Xext_LIB:FILEPATH={SYSROOT / "usr/lib/aarch64-linux-gnu/libXext.so"}',
            f'-DXEXT_LIB:FILEPATH={SYSROOT / "usr/lib/aarch64-linux-gnu/libXext.so"}',
            '-DENABLE_USERFAULTFD=OFF', '-DENABLE_DISCORD_RPC=OFF', '-DENABLE_UPDATER=OFF',
            '-DENABLE_TESTS=OFF', '-DSDL_X11_XCURSOR=OFF', '-DSDL_X11_XDBE=OFF',
            '-DALSOFT_UPDATE_BUILD_VERSION=OFF', '-DSDL_X11_XINPUT=OFF', '-DSDL_X11_XFIXES=OFF',
            '-DSDL_X11_XRANDR=OFF', '-DSDL_X11_XSCRNSAVER=OFF', '-DSDL_X11_XSHAPE=OFF',
            '-DSDL_X11_XSYNC=OFF', '-DSDL_X11_XTEST=OFF', '-DSDL_WAYLAND=OFF'])
        target = 'shadps4'
    run(args.stage + '-build', [CMAKE, '--build', build, '--target', target, '--parallel', args.jobs])
    if args.stage == 'core':
        export_core(build)


if __name__ == '__main__':
    main()
