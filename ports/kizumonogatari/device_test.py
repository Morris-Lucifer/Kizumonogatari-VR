"""Capture a bounded Kizu background test; all prior device logs are archived by the host."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess

from device import ROOT, PACKAGE, add_device_arguments, adb_command


def main():
    parser = argparse.ArgumentParser()
    add_device_arguments(parser)
    parser.add_argument('--seconds', type=int, default=30)
    parser.add_argument('--refresh-runtime', action='store_true')
    parser.add_argument('--env', default='BACHATA_FEX_FLIGHT_RECORDER=1 SHADPS4_UNITY_LOG=1 HOST_DISPLAY=90')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('Expected 1..600 seconds')
    if any(ch in args.env for ch in '\"\'\n\r;$`\\'):
        parser.error('Environment must be simple space-separated KEY=value entries')
    base = adb_command(args)
    subprocess.run([*base, 'get-state'], check=True)
    running = subprocess.run([*base, 'shell', 'pidof', PACKAGE],
                             capture_output=True, text=True, timeout=15)
    if running.returncode == 0 and running.stdout.strip():
        parser.error('Kizu is already running. Use capture_foreground.py for a wearer session. '
                     'Background tests require the app to be stopped and the headset left idle.')
    if running.returncode not in (0, 1):
        raise RuntimeError('Cannot verify that the Kizu app is stopped: ' + running.stderr)
    out = ROOT / 'evidence/kizu-native' / ('device-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    print('Evidence: ' + str(out), flush=True)
    command = f'am instrument -w -e selftest {args.seconds} -e game /data/local/tmp/kizuvr/games/CUSA09079/eboot.bin -e mic off'
    if args.refresh_runtime:
        command += ' -e install 1'
    command += f' -e env "{args.env}" {PACKAGE}/com.fgovr.quest.SandboxShell'
    (out / 'command.json').write_text(json.dumps([*base, 'shell', command], indent=2), encoding='utf-8')
    try:
        with (out / 'selftest.log').open('wb') as log:
            result = subprocess.run([*base, 'shell', command], stdout=log, stderr=subprocess.STDOUT,
                                    timeout=args.seconds + 60)
        print('Instrumentation exit: ' + str(result.returncode), flush=True)
    finally:
        for name, remote in (
            ('core.log', f'run-as {PACKAGE} cat files/selftest/core.log'),
            ('host.log', f'run-as {PACKAGE} cat files/selftest/host.log'),
            ('unity_debug.log', f'run-as {PACKAGE} cat files/selftest/data/shadPS4/log/unity_debug.log'),
            ('runtime-hash.txt', f'run-as {PACKAGE} sha256sum files/runtime/host/shadps4-arm64-fex'),
            ('package.txt', f'dumpsys package {PACKAGE}'),
        ):
            with (out / name).open('wb') as log:
                subprocess.run([*base, 'exec-out', remote], stdout=log, stderr=subprocess.STDOUT, timeout=15)
        listing = subprocess.run([*base, 'shell', 'run-as', PACKAGE, 'ls', 'files/selftest'],
                                 capture_output=True, text=True, timeout=15)
        pictures = [name for name in listing.stdout.splitlines()
                    if re.fullmatch(r'frame_[0-9]+_[0-9]+\.png', name)]
        for name in pictures[:24]:
            with (out / name).open('wb') as image:
                subprocess.run([*base, 'exec-out', 'run-as', PACKAGE, 'cat', 'files/selftest/' + name],
                               stdout=image, check=True, timeout=15)
        subprocess.run([*base, 'shell', 'am', 'force-stop', PACKAGE], timeout=15)
    (ROOT / 'evidence/kizu-native/latest-device.json').write_text(json.dumps(dict(directory=str(out)), indent=2))
    report = (out / 'selftest.log').read_text(encoding='utf-8', errors='replace')
    print(report[-6500:], flush=True)
    # am instrument can exit 0 even when Android reports that its process died.
    if (result.returncode or 'shortMsg=' in report or 'the core ended after ' in report
            or 'frames received (last id ' not in report):
        raise SystemExit('Background test did not complete; preserve logs and inspect the cause.')


if __name__ == '__main__':
    main()
