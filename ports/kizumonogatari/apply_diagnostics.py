"""Apply the reviewable native overlay to an already prepared Quest source tree."""
import argparse
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path, nargs='?', default=ROOT / 'evidence/kizu-native/src')
    args = parser.parse_args()
    command = ['git', '-C', str(args.source), 'apply']
    for patch in sorted((HERE / 'native').glob('*.patch')):
        applied = subprocess.run([*command, '--reverse', '--check', str(patch)], capture_output=True)
        if applied.returncode:
            subprocess.run([*command, '--check', str(patch)], check=True)
            subprocess.run([*command, str(patch)], check=True)
    for name in ('fex_flight_recorder.h', 'fex_fault_snapshot.h', 'fex_signal_context.h'):
        shutil.copyfile(HERE / 'native' / name, args.source / 'shadps4-arm64-main/src/core/fex' / name)
    shutil.copyfile(HERE / 'native/video_frame_snapshot.h',
                    args.source / 'shadps4-arm64-main/src/core/video_frame_snapshot.h')
    print('Native diagnostics overlay ready:', args.source)


if __name__ == '__main__':
    main()
