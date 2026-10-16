"""Fetch the hash-pinned runtime base or Android NDK into ignored local directories."""
import argparse
from datetime import datetime
import hashlib
from pathlib import Path
import shutil
import urllib.request
import zipfile

from build_host import ROOT, BASE_APK, BASE_SHA256

BASE_URL = 'https://github.com/saberwatchmanga/FGO-VR/releases/download/v0.2.1/FGO-VR-0.2.0-Quest3.apk'
NDK_URL = 'https://dl.google.com/android/repository/android-ndk-r29-windows.zip'
NDK_SHA1 = 'ab3bb30fbb9e6903666d60c55d11e78b04e07472'
WORK = ROOT / 'evidence/kizu-native'


def digest(path, algorithm):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def fetch(url, path, algorithm, expected, verify_only):
    if path.exists():
        if digest(path, algorithm) != expected:
            raise RuntimeError('Existing file has an unexpected hash; preserved: ' + str(path))
        print('Verified: ' + str(path), flush=True)
        return
    if verify_only:
        raise RuntimeError('Missing dependency: ' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + '.part-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    request = urllib.request.Request(url, headers={'User-Agent': 'Kizumonogatari-VR-build'})
    print('Downloading: ' + url, flush=True)
    with urllib.request.urlopen(request, timeout=60) as response, partial.open('xb') as stream:
        shutil.copyfileobj(response, stream, 1024 * 1024)
    if digest(partial, algorithm) != expected:
        raise RuntimeError('Downloaded checksum mismatch; incomplete file preserved: ' + str(partial))
    partial.rename(path)
    print('Verified: ' + str(path), flush=True)


def prepare_ndk(verify_only):
    archive = WORK / 'android-ndk-r29-windows.zip'
    fetch(NDK_URL, archive, 'sha1', NDK_SHA1, verify_only)
    folder = WORK / 'android-ndk-r29'
    compiler = folder / 'toolchains/llvm/prebuilt/windows-x86_64/bin/clang++.exe'
    if compiler.is_file():
        print('NDK compiler present: ' + str(compiler))
        return
    if verify_only:
        raise RuntimeError('NDK has not been extracted')
    if folder.exists():
        raise RuntimeError('Existing incomplete NDK directory preserved: ' + str(folder))
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            target = (WORK / entry.filename).resolve()
            if not target.is_relative_to(folder.resolve()):
                raise RuntimeError('Unexpected NDK archive path: ' + entry.filename)
        for entry in bundle.infolist():
            target = (WORK / entry.filename).resolve()
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open('xb') as destination:
                    shutil.copyfileobj(source, destination)
    if not compiler.is_file():
        raise RuntimeError('NDK archive did not provide the expected compiler')
    print('NDK ready: ' + str(folder))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['base-apk', 'ndk', 'all'])
    parser.add_argument('--verify-only', action='store_true', help='Read-only dependency check; no downloads')
    args = parser.parse_args()
    if args.stage in ('base-apk', 'all'):
        fetch(BASE_URL, BASE_APK, 'sha256', BASE_SHA256, args.verify_only)
    if args.stage in ('ndk', 'all'):
        prepare_ndk(args.verify_only)


if __name__ == '__main__':
    main()
