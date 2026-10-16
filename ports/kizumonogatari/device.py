"""Select an explicitly requested or uniquely connected authorized ADB device."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = 'com.kizuvr.quest'


def add_device_arguments(parser):
    parser.add_argument('--adb', default=os.environ.get('KIZU_ADB'),
                        help='ADB executable; defaults to KIZU_ADB or adb on PATH')
    parser.add_argument('--serial', default=os.environ.get('ANDROID_SERIAL'),
                        help='Device serial; required when more than one device is connected')


def adb_command(args):
    executable = args.adb or shutil.which('adb')
    if not executable:
        raise RuntimeError('ADB not found. Install platform-tools and use --adb or add adb to PATH.')
    result = subprocess.run([str(executable), 'devices'], capture_output=True,
                            text=True, check=True, timeout=15)
    devices = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] != 'List' and not line.startswith('*'):
            devices[fields[0]] = fields[1]
    if args.serial:
        if devices.get(args.serial) != 'device':
            raise RuntimeError('Requested device is absent or has not authorized USB debugging.')
        selected = args.serial
    else:
        if len(devices) != 1 or next(iter(devices.values()), None) != 'device':
            raise RuntimeError('Connect exactly one authorized headset, or select it with --serial.')
        selected = next(iter(devices))
    return [str(executable), '-s', selected]
