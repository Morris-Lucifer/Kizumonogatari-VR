"""Prepare the pinned native dependencies without changing system installations.

All downloads/build inputs stay in ignored evidence/kizu-native. Existing files
are preserved; failed downloads have separate .part files and are hash checked.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import posixpath
import shutil
import subprocess
import tarfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'evidence/kizu-native'
SOURCE = WORK / 'src/shadps4-arm64-main'
LLVM_URL = 'https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/LLVM-21.1.8-win64.exe'
LLVM_SHA = '7a5386c26497db1691f320121e5b113364dd0274b98e55f15f4dbc00c0450113'
FEX_COMMIT = 'f2b679f6028ce1c38875233aecfcf5d3f8ebecec'
ASTRO_COMMIT = '9f42c44d4e838e3a0df67913e350c4f098110862'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download(url, expected):
    path = WORK / 'downloads' / url.rsplit('/', 1)[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if sha(path) == expected:
            return path
        raise RuntimeError(f'Existing download has wrong hash (preserved): {path}')
    partial = path.with_name(path.name + '.part')
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response, partial.open('wb') as out:
                shutil.copyfileobj(response, out)
            if sha(partial) != expected:
                raise RuntimeError(f'Download hash mismatch: {url}')
            partial.rename(path)
            return path
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2)


def run(*command):
    subprocess.run([str(x) for x in command], check=True)


def llvm():
    archive = download(LLVM_URL, LLVM_SHA)
    target = WORK / 'llvm'
    if not (target / 'bin/clang.exe').exists():
        run(r'C:\Program Files\7-Zip\7z.exe', 'x', archive, '-o' + str(target), '-aos')
    run(target / 'bin/clang.exe', '--version')
    (WORK / 'llvm.json').write_text(json.dumps(dict(url=LLVM_URL, sha256=LLVM_SHA), indent=2))


def ffmpeg():
    url = 'https://github.com/shadps4-emu/ext-ffmpeg-core/releases/download/94dde08/ffmpeg-linux-arm64.zip'
    digest = 'fb73ddbd77af11c8acb79ae7b67b23be4b9760771cf498e71dc91e4a2b4d40c4'
    archive = download(url, digest)
    target = WORK / 'build-core/externals/ffmpeg-94dde08.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and sha(target) != digest:
        raise RuntimeError('Existing FFmpeg download differs; preserved')
    shutil.copyfile(archive, target)
    (WORK / 'ffmpeg.json').write_text(json.dumps(dict(url=url, sha256=digest), indent=2))


def sysroot():
    # Reuse the documented archive parser/path normalization, but use every
    # locked version and hash, never the mutable Debian package index.
    spec = importlib.util.spec_from_file_location('sysroot_reference',
        ROOT / 'build_reference/FGO-Quest/scripts/prepare_arm64_sysroot.py')
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    lock = json.loads((ROOT / 'upstream/arm64-sysroot-lock.json').read_text())
    target = WORK / 'sysroot'
    target.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        archives = list(pool.map(lambda p: download(p['url'], p['sha256']), lock['packages']))
    links = []
    for package, archive in zip(lock['packages'], archives):
        payload = next(data for name, data in reference.ar_members(archive.read_bytes())
                       if name.startswith('data.tar'))
        with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
            for member in tar:
                relative = reference.normalized(member.name)
                if not relative or relative.startswith('usr/share/'):
                    continue
                out = (target / relative).resolve()
                if not out.is_relative_to(target.resolve()):
                    raise RuntimeError('Archive path outside sysroot: ' + member.name)
                if member.isdir():
                    out.mkdir(parents=True, exist_ok=True)
                elif member.isreg():
                    out.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as source, out.open('wb') as dest:
                        shutil.copyfileobj(source, dest)
                elif member.issym() or member.islnk():
                    origin = member.linkname if member.islnk() or member.linkname.startswith('/') else posixpath.join(posixpath.dirname(member.name), member.linkname)
                    links.append((relative, reference.normalized(origin)))
        print('Extracted ' + package['package'], flush=True)
    for _ in range(12):
        pending = []
        for relative, origin in links:
            dest, source = target / relative, target / origin
            if not source.exists():
                pending.append((relative, origin))
            elif source.is_file() and source.resolve() != dest.resolve():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
            elif source.is_dir() and not dest.exists():
                shutil.copytree(source, dest)
        if len(pending) == len(links):
            links = pending
            break
        links = pending
    for name in ('lib', 'lib64', 'include'):
        if (target / 'usr' / name).exists():
            shutil.copytree(target / 'usr' / name, target / name, dirs_exist_ok=True)
    lock.update(sysroot=str(target), unresolved_links=links)
    (WORK / 'sysroot.json').write_text(json.dumps(lock, indent=2), encoding='utf-8')
    print(f'Sysroot ready; unresolved links: {len(links)}', flush=True)


def fex():
    lock = json.loads((SOURCE / 'runtime/locks/components.lock.json').read_text())
    item = next(x for x in lock['components'] if x['name'] == 'fex')
    if item['revision'] != FEX_COMMIT:
        raise RuntimeError('Unexpected FEX baseline')
    target = SOURCE / 'runtime/sources/fex'
    if not (target / '.git').exists():
        target.mkdir(parents=True, exist_ok=True)
        run('git', 'init', target)
        run('git', '-C', target, 'remote', 'add', 'origin', item['url'])
    head = subprocess.run(['git', '-C', str(target), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    if head.returncode:
        run('git', '-C', target, 'fetch', '--depth=1', 'origin', FEX_COMMIT)
        run('git', '-C', target, 'checkout', '--detach', FEX_COMMIT)
    elif head.stdout.strip() != FEX_COMMIT:
        raise RuntimeError('Existing FEX checkout is a different revision; preserved')
    run('git', '-C', target, 'submodule', 'update', '--init', '--depth=1', '--jobs=6', '--',
        'External/unordered_dense', 'External/rpmalloc', 'External/xxhash', 'External/fmt',
        'External/range-v3', 'Source/Common/cpp-optparse')
    patch = ROOT / 'patches/build-support/fex-fexcore-only.patch'
    applied = subprocess.run(['git', '-C', str(target), 'apply', '--ignore-space-change', '--reverse', '--check', str(patch)], capture_output=True)
    if applied.returncode:
        run('git', '-C', target, 'apply', '--ignore-space-change', '--check', patch)
        run('git', '-C', target, 'apply', '--ignore-space-change', patch)
    (WORK / 'fex.json').write_text(json.dumps(item, indent=2), encoding='utf-8')


def source():
    target = SOURCE.parent
    if not (target / '.git').exists():
        target.mkdir(parents=True, exist_ok=True)
        run('git', 'init', target)
        run('git', '-C', target, 'remote', 'add', 'origin', 'https://github.com/bigmak94/AstroQuest.git')
        run('git', '-C', target, 'fetch', '--depth=1', 'origin', ASTRO_COMMIT)
        run('git', '-C', target, 'checkout', '--detach', ASTRO_COMMIT)
    actual = subprocess.check_output(['git', '-C', str(target), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != ASTRO_COMMIT:
        raise RuntimeError('Existing source revision differs; preserved')
    listing = subprocess.check_output(['git', '-C', str(target), 'config', '-f', '.gitmodules',
                                      '--get-regexp', r'submodule\..*\.path'], text=True)
    paths = [line.split(' ', 1)[1] for line in listing.splitlines()]
    for relative in paths:
        module = target / relative
        if (module / '.git').exists():
            head = subprocess.run(['git', '-C', str(module), 'rev-parse', '--verify', 'HEAD'], capture_output=True)
            if head.returncode:
                entry = subprocess.check_output(['git', '-C', str(target), 'ls-tree', 'HEAD', relative], text=True)
                revision = entry.split()[2]
                run('git', '-C', module, '-c', 'http.lowSpeedLimit=1024', '-c', 'http.lowSpeedTime=60',
                    'fetch', '--depth=1', 'origin', revision)
                run('git', '-C', module, 'checkout', '--detach', revision)
    run('git', '-C', target, 'submodule', 'update', '--init', '--depth=1', '--jobs=8')
    for relative in paths:
        module = target / relative
        status = subprocess.check_output(['git', '-C', str(module), 'status', '--porcelain=v1'], text=True)
        # An interrupted `clone --no-checkout` can leave HEAD set but the index
        # empty. Materialize its missing tracked files only; never reset edits.
        if status and all(line.startswith('D  ') for line in status.splitlines()):
            run('git', '-C', module, 'read-tree', 'HEAD')
            run('git', '-C', module, 'checkout-index', '--all')
    # The macOS Mesa backend and Android host/driver are not rebuilt by this
    # overlay. Avoid recursively fetching their unrelated graphics source trees.
    skip = {'mesa-kosmickrisp', 'bachata-xserver', 'libadrenotools'}
    needed = [path for path in paths if path.rsplit('/', 1)[1] not in skip]
    run('git', '-C', target, 'submodule', 'update', '--init', '--recursive', '--depth=1', '--jobs=8', '--', *needed)
    patch = ROOT / 'patches/fgo-resolution-quest-complete.patch'
    applied = subprocess.run(['git', '-C', str(target), 'apply', '--ignore-space-change', '--reverse', '--check', str(patch)], capture_output=True)
    if applied.returncode:
        run('git', '-C', target, 'apply', '--ignore-space-change', '--check', patch)
        run('git', '-C', target, 'apply', '--ignore-space-change', patch)
    print('Pinned Quest source prepared', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['source', 'llvm', 'sysroot', 'fex', 'ffmpeg'])
    args = parser.parse_args()
    globals()[args.stage]()
