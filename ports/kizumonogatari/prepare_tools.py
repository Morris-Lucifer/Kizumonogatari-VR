"""Download portable Android/Java build tools from their official publishers."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'evidence/kizu-quest-20261015/toolchain'


def install(spec):
    target = OUT / 'downloads' / spec['filename']
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or hashlib.new(spec['algorithm'], target.read_bytes()).hexdigest() != spec['checksum']:
        print('Downloading ' + spec['filename'], flush=True)
        for attempt in range(3):
            try:
                request = urllib.request.Request(spec['url'], headers={'User-Agent': 'KizuVR-local-build'})
                with urllib.request.urlopen(request, timeout=30) as response, target.open('wb') as stream:
                    shutil.copyfileobj(response, stream, 1024 * 1024)
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(2)
    if hashlib.new(spec['algorithm'], target.read_bytes()).hexdigest() != spec['checksum']:
        raise RuntimeError('Publisher checksum mismatch: ' + spec['filename'])
    destination = OUT / spec['directory']
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            relative = entry.filename.split('/', 1)[1]
            path = (destination / relative).resolve()
            if not path.is_relative_to(destination.resolve()):
                raise RuntimeError('Archive path escapes destination')
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as source, path.open('wb') as stream:
                shutil.copyfileobj(source, stream)
    spec['sha256'] = hashlib.sha256(target.read_bytes()).hexdigest()
    print('Ready: ' + str(destination), flush=True)
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    specs = json.loads((ROOT / 'upstream/android-tools-lock.json').read_text(encoding='utf-8'))
    (OUT / 'packages.json').write_text(json.dumps(specs, indent=2), encoding='utf-8')
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(install, specs))
    (OUT / 'manifest.json').write_text(json.dumps(records, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
