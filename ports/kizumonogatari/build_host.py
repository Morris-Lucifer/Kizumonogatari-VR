"""Build an isolated CUSA09079 experiment with the verified FGO 0.2.0 runtime.

The Android application ID is independent. Java JNI class names deliberately stay
unchanged for the rebuilt input host. Diagnostic builds require a matching core
and Android host. No game files are packaged; FGO's installation is separate.
"""
import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'evidence/kizu-quest-20261015'
TOOLS = EVIDENCE / 'toolchain'
HOST = ROOT / 'source_snapshot/quest/quest-host'
BASE_APK = Path(os.environ.get('KIZU_BASE_APK', str(ROOT / 'evidence/runtime-base/FGO-VR-0.2.0-Quest3.apk')))
BASE_SHA256 = '4a2864ba007c98f50379dc0f4d57cbc7b95b72104d4544cb66f12802f30ca754'
PACKAGE = 'com.kizuvr.quest'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def change_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Source precondition failed: ' + old[:100])
    return text.replace(old, new, 1)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--core', type=Path, help='Locally compiled ARM64/glibc ELF core')
    parser.add_argument('--native-manifest', type=Path, help='Build provenance for --core')
    parser.add_argument('--host-library', type=Path, help='Compiled Android Touch-to-Move host')
    parser.add_argument('--host-manifest', type=Path, help='Provenance for --host-library')
    args = parser.parse_args()
    if bool(args.core) != bool(args.native_manifest):
        parser.error('--core and --native-manifest must be supplied together')
    if bool(args.host_library) != bool(args.host_manifest) or (args.host_library and not args.core):
        parser.error('A host library requires its manifest and a matching compiled core')
    if args.core and not args.host_library:
        parser.error('The Move-enabled diagnostic APK requires the matching Android host library')
    native = None
    if args.core:
        native = json.loads(args.native_manifest.read_text(encoding='utf-8'))
        if sha(args.core) != native['core_sha256']:
            raise RuntimeError('Core does not match native build manifest')
        with args.core.open('rb') as stream:
            header = stream.read(20)
        if header[:6] != b'\x7fELF\x02\x01' or int.from_bytes(header[18:20], 'little') != 183:
            raise RuntimeError('Expected a 64-bit little-endian AArch64 ELF')
    if sha(BASE_APK) != BASE_SHA256:
        raise RuntimeError('Unexpected baseline APK')
    native_host = None
    if args.host_library:
        native_host = json.loads(args.host_manifest.read_text(encoding='utf-8'))
        if sha(args.host_library) != native_host['library_sha256']:
            raise RuntimeError('Host library does not match its manifest')
        if native_host['protocol_sha256'] != native.get('vr_protocol_sha256'):
            raise RuntimeError('Host and emulator protocol headers do not match')
    out = EVIDENCE / ('build-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    java = TOOLS / 'jdk/bin'
    bt = TOOLS / 'build-tools'
    platform = TOOLS / 'platform/android.jar'
    for needed in (java / 'javac.exe', bt / 'aapt2.exe', platform):
        if not needed.is_file():
            raise RuntimeError('Build tool missing: ' + str(needed))

    def run(name, command):
        command = [str(arg) for arg in command]
        print(name, flush=True)
        (out / (name + '.command.json')).write_text(json.dumps(command, indent=2), encoding='utf-8')
        with (out / (name + '.log')).open('w', encoding='utf-8') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            print((out / (name + '.log')).read_text(encoding='utf-8', errors='replace')[-12000:])
            raise SystemExit(result.returncode)

    source = out / 'source'
    source.mkdir()
    for path in sorted((HOST / 'java').rglob('*.java')):
        text = path.read_text(encoding='utf-8')
        text = text.replace('CUSA09078', 'CUSA09079').replace('/data/local/tmp/fgovr/', '/data/local/tmp/kizuvr/')
        text = text.replace('FGO VR Quest 3', 'Kizumonogatari VR Quest')
        text = text.replace('deleteRecursively', 'archiveExisting')
        if path.name == 'MainActivity.java':
            text = change_once(text,
                'int eyeWidth = fgoRenderScale == 125 ? 1792 : fgoRenderScale == 110 ? 1536 : 1408;',
                'int eyeWidth = 1440;')
            text = change_once(text,
                'int eyeHeight = fgoRenderScale == 125 ? 1890 : fgoRenderScale == 110 ? 1663 : 1512;',
                'int eyeHeight = 1536;')
            text = change_once(text, 'env.add("SHADPS4_FGO_RENDER_SCALE=" + fgoRenderScale);',
                               'env.add("SHADPS4_FGO_RENDER_SCALE=100");')
            if native:
                text = change_once(text, 'env.addAll(extraEnv);',
                    'env.add("BACHATA_FEX_FLIGHT_RECORDER=1");\n'
                    '            env.add("SHADPS4_UNITY_LOG=1");\n'
                    '            env.addAll(extraEnv);')
            text = change_once(text, 'previous.delete();',
                'if (previous.exists()) previous.renameTo(new File(previous.getPath() + "." + System.nanoTime()));')
        elif path.name == 'RuntimeInstaller.java':
            start = text.index('    static void archiveExisting(File file) {')
            text = text[:start] + '''    static void archiveExisting(File file) throws IOException {
        if (!file.exists()) return;
        File archive = new File(file.getParentFile(), file.getName() + ".previous-" + System.nanoTime());
        if (!file.renameTo(archive)) throw new IOException("Cannot preserve previous directory: " + file);
    }
}
'''
        elif path.name == 'SandboxShell.java':
            text = change_once(text, 'private String runSelfTest(int seconds) {',
                               'private String runSelfTest(int seconds) throws java.io.IOException {')
            text = change_once(text,
                'new File(getTargetContext().getExternalFilesDir(null), "status-" + number + ".png")\n                    .delete();',
                'RuntimeInstaller.archiveExisting(new File(getTargetContext().getExternalFilesDir(null), "status-" + number + ".png"));')
            text = change_once(text, 'new File(runtime, ".stamp").delete();',
                               'RuntimeInstaller.archiveExisting(new File(runtime, ".stamp"));')
        (source / path.name).write_text(text, encoding='utf-8')

    manifest = (HOST / 'AndroidManifest.xml').read_text(encoding='utf-8')
    manifest = manifest.replace('package="com.fgovr.quest"', 'package="' + PACKAGE + '"')
    manifest = manifest.replace('android:targetPackage="com.fgovr.quest"', 'android:targetPackage="' + PACKAGE + '"')
    manifest = manifest.replace('android:versionCode="2"', 'android:versionCode="1"')
    manifest = manifest.replace('android:versionName="0.2.0-fgo-resolution"', 'android:versionName="0.1.0-kizu-experimental"')
    if native:
        manifest = manifest.replace('android:versionCode="1"', 'android:versionCode="8"')
        manifest = manifest.replace('0.1.0-kizu-experimental', '0.1.7-kizu-diagnostics')
    (source / 'AndroidManifest.xml').write_text(manifest, encoding='utf-8')
    res = source / 'res/values'
    res.mkdir(parents=True)
    (res / 'strings.xml').write_text('<?xml version="1.0" encoding="utf-8"?>\n<resources><string name="app_name">Kizumonogatari VR (Test)</string></resources>\n', encoding='utf-8')

    assets = out / 'assets'
    libs = out / 'lib/arm64-v8a'
    assets.mkdir()
    libs.mkdir(parents=True)
    with zipfile.ZipFile(BASE_APK) as archive:
        for name in ('assets/runtime.zip', 'assets/runtime.stamp',
                     'lib/arm64-v8a/libfgo_ld.so', 'lib/arm64-v8a/libfgovr.so',
                     'lib/arm64-v8a/libopenxr_loader.so'):
            target = out / name
            target.write_bytes(archive.read(name))
    if native_host:
        (libs / 'libfgovr.so').write_bytes(args.host_library.read_bytes())
    if native:
        # Rewrite the runtime archive exactly once, retaining each other member's
        # bytes/permissions. Change the stamp so RuntimeInstaller refreshes it.
        original = (assets / 'runtime.zip').read_bytes()
        rewritten = io.BytesIO()
        replaced = 0
        with zipfile.ZipFile(io.BytesIO(original)) as old, zipfile.ZipFile(rewritten, 'w') as new:
            for info in old.infolist():
                payload = old.read(info.filename)
                if info.filename == 'host/shadps4-arm64-fex':
                    payload = args.core.read_bytes()
                    replaced += 1
                new.writestr(info, payload)
        if replaced != 1:
            raise RuntimeError('Unexpected runtime core member layout')
        (assets / 'runtime.zip').write_bytes(rewritten.getvalue())
        (assets / 'runtime.stamp').write_text(sha(assets / 'runtime.zip') + '\n', encoding='ascii')
    provenance = dict(package=PACKAGE, title_id='CUSA09079', game_assets_embedded=False,
                      baseline_apk_sha256=BASE_SHA256, native_core='unmodified FGO 0.2.0 / AstroQuest',
                      device_acceptance='unverified experiment', game_version='01.00',
                      java_jni_namespace='com.fgovr.quest', application_id_is_independent=True)
    if native:
        provenance.update(native_core='locally compiled diagnostic overlay',
                          native_build=native, recorder_environment='BACHATA_FEX_FLIGHT_RECORDER=1')
    if native_host:
        provenance['android_host_build'] = native_host
    (assets / 'kizu-build.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    classes = out / 'classes'
    dex = out / 'dex'
    classes.mkdir()
    dex.mkdir()
    run('javac', [java / 'javac.exe', '-J-Duser.language=en', '-J-Dfile.encoding=UTF-8', '-encoding', 'UTF-8', '-Xlint:-options', '-source', '11', '-target', '11',
                  '-classpath', platform, '-d', classes, *sorted(source.glob('*.java'))])
    run('dex', [java / 'java.exe', '-cp', bt / 'lib/d8.jar', 'com.android.tools.r8.D8',
                '--lib', platform, '--min-api', '32', '--output', dex, *sorted(classes.rglob('*.class'))])
    run('resources', [bt / 'aapt2.exe', 'compile', '--dir', source / 'res', '-o', out / 'res.zip'])
    run('link', [bt / 'aapt2.exe', 'link', '-o', out / 'base.apk', '-I', platform,
                 '--manifest', source / 'AndroidManifest.xml', '-A', assets, '--debug-mode',
                 '--min-sdk-version', '32', '--target-sdk-version', '32', out / 'res.zip'])
    with zipfile.ZipFile(out / 'base.apk', 'a', zipfile.ZIP_DEFLATED) as archive:
        archive.write(dex / 'classes.dex', 'classes.dex')
        for path in sorted(libs.glob('*.so')):
            archive.write(path, 'lib/arm64-v8a/' + path.name)
    run('align', [bt / 'zipalign.exe', '-p', '4', out / 'base.apk', out / 'aligned.apk'])
    key = EVIDENCE / 'kizu-local.keystore'
    if not key.exists():
        run('key', [java / 'keytool.exe', '-genkeypair', '-noprompt', '-keystore', key,
                    '-alias', 'kizu-local', '-storepass', 'android', '-keypass', 'android',
                    '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000',
                    '-dname', 'CN=Kizu VR Local Experiment'])
    signer = [java / 'java.exe', '-jar', bt / 'lib/apksigner.jar']
    apk = out / ('Kizumonogatari-VR-0.1.7-Quest3-Diagnostics.apk' if native else 'Kizumonogatari-VR-0.1.0-Quest3-Test.apk')
    run('sign', [*signer, 'sign', '--ks', key, '--ks-key-alias', 'kizu-local',
                 '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--out', apk, out / 'aligned.apk'])
    run('verify-signature', [*signer, 'verify', '--verbose', '--print-certs', apk])
    run('verify-alignment', [bt / 'zipalign.exe', '-c', '-p', '4', apk])
    run('badging', [bt / 'aapt2.exe', 'dump', 'badging', apk])
    provenance.update(apk=str(apk), apk_sha256=sha(apk))
    (out / 'manifest.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    (EVIDENCE / 'latest-build.json').write_text(json.dumps(provenance, indent=2), encoding='utf-8')
    print('Built: ' + str(apk), flush=True)


if __name__ == '__main__':
    main()
