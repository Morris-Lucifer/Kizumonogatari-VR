"""Compile the Kizu Touch-to-Move host with the pinned Android NDK r29."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from build_host import ROOT, BASE_APK, BASE_SHA256, sha


def main():
    work = ROOT / 'evidence/kizu-native'
    ndk = work / 'android-ndk-r29'
    compiler = ndk / 'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    archive = work / 'android-ndk-r29-windows.zip'
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha1').hexdigest()
    if digest != 'ab3bb30fbb9e6903666d60c55d11e78b04e07472':
        raise RuntimeError('Official NDK archive hash mismatch')
    if not compiler.is_file() or sha(BASE_APK) != BASE_SHA256:
        raise RuntimeError('Compiler missing or unexpected baseline APK')
    out = work / ('android-host-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    source = out / 'cpp'
    source.mkdir(parents=True)
    # The snapshot contains changed FGO host files; common GL/log helpers are pinned upstream.
    for path in (work / 'src/quest-host/cpp').glob('*'):
        if path.is_file():
            shutil.copyfile(path, source / path.name)
    for path in (ROOT / 'source_snapshot/quest/quest-host/cpp').glob('*'):
        if path.is_file():
            shutil.copyfile(path, source / path.name)
    # Make patch application independent of the developer's Git CRLF settings.
    for path in source.glob('*'):
        if path.suffix in ('.cpp', '.h'):
            path.write_bytes(path.read_text(encoding='utf-8').encode('utf-8'))
    patch = ROOT / 'ports/kizumonogatari/host/move-input.patch'
    subprocess.run(['git', '-C', str(out), 'apply', '--check', str(patch)], check=True)
    subprocess.run(['git', '-C', str(out), 'apply', str(patch)], check=True)
    with zipfile.ZipFile(BASE_APK) as apk:
        (out / 'libopenxr_loader.so').write_bytes(apk.read('lib/arm64-v8a/libopenxr_loader.so'))
    core = work / 'src/shadps4-arm64-main'
    protocol = core / 'src/core/vr/vr_protocol.h'
    output = out / 'libfgovr.so'
    command = [compiler, '--target=aarch64-linux-android32', '-std=c++20', '-O2',
               '-g', '-fPIC', '-fvisibility=hidden', '-Wall', '-Wextra',
               '-Wno-unused-parameter', '-Wno-missing-field-initializers',
               '-I', core / 'externals/openxr-sdk/include',
               '-I', protocol.parent, *sorted(source.glob('*.cpp')),
               '-shared', '-static-libstdc++', '-Wl,--no-undefined',
               '-Wl,-soname,libfgovr.so', '-L', out, '-lopenxr_loader',
               '-lEGL', '-lGLESv3', '-landroid', '-lnativewindow', '-laaudio',
               '-llog', '-lz', '-o', output]
    command = [str(x) for x in command]
    (out / 'command.json').write_text(json.dumps(command, indent=2), encoding='utf-8')
    print('Compiling Android host: ' + str(out), flush=True)
    with (out / 'build.log').open('w', encoding='utf-8') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        print((out / 'build.log').read_text(encoding='utf-8')[-10000:])
        raise SystemExit(result.returncode)
    manifest = dict(library=str(output), library_sha256=sha(output),
                    protocol_sha256=sha(protocol), patch_sha256=sha(patch),
                    baseline_apk_sha256=BASE_SHA256, ndk='r29',
                    ndk_archive_sha1=digest,
                    inputs={p.name: sha(p) for p in sorted(source.glob('*')) if p.is_file()},
                    acceptance='compiled; device input validation pending')
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    (work / 'latest-android-host.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Built: ' + str(output), flush=True)


if __name__ == '__main__':
    main()
