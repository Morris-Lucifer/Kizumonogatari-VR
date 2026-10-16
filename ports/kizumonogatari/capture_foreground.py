"""Read-only capture of a wearer session. Never launches, stops, or inputs to the game."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import time

from device import ROOT, PACKAGE, add_device_arguments, adb_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_device_arguments(parser)
    parser.add_argument('--seconds', type=int, default=300)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('Expected 1..600 seconds')
    out = ROOT / 'evidence/kizu-native' / ('wearer-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    out.mkdir(parents=True)
    base = adb_command(args)
    external = f'/sdcard/Android/data/{PACKAGE}/files'

    def capture(name, command, required=True):
        result = subprocess.run([*base, 'exec-out', command], capture_output=True, timeout=15)
        if result.returncode:
            if required:
                raise RuntimeError(result.stderr.decode(errors='replace'))
            (out / (name + '.unavailable.txt')).write_bytes(result.stdout + result.stderr)
            return ''
        (out / name).write_bytes(result.stdout)
        return result.stdout.decode('utf-8', errors='replace')

    print('Read-only evidence: ' + str(out), flush=True)
    capture('vrhost.txt', f'cat {external}/vrhost.txt')
    started = time.monotonic()
    prior = ''
    try:
        while True:
            host = capture('host.log', f'cat {external}/host.log')
            capture('core.log', f'cat {external}/core.log')
            lines = [line for line in host.splitlines()
                     if 'pacing:' in line or 'stopped by signal' in line or 'core: failed' in line]
            if lines and lines[-1] != prior:
                prior = lines[-1]
                print(prior, flush=True)
            remaining = args.seconds - (time.monotonic() - started)
            if remaining <= 0:
                break
            time.sleep(min(15, remaining))
    finally:
        for name, command in (
            ('core.prev.log', f'cat {external}/core.prev.log'),
            ('host.prev.log', f'cat {external}/host.prev.log'),
            ('processes.txt', 'ps -A -o PID,PPID,NAME,ARGS'),
            ('logcat-crash.txt', 'logcat -b crash -d -t 300'),
        ):
            try:
                capture(name, command, required=False)
            except (OSError, subprocess.TimeoutExpired) as error:
                print(f'Optional capture unavailable: {name}: {error}', flush=True)
        core = (out / 'core.log').read_text(encoding='utf-8', errors='replace')
        failures = re.findall(r'.*(?:NoExec instruction|Unhandled access violation|FATAL).*', core)
        metadata = dict(directory=str(out), duration_seconds=round(time.monotonic()-started, 1),
                        mode='read-only foreground observation', fatal_lines=failures,
                        wearer_confirmation_required=True)
        (out / 'capture.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
        (ROOT / 'evidence/kizu-native/latest-foreground.json').write_text(
            json.dumps(metadata, indent=2), encoding='utf-8')
        print('Capture saved; app left running: ' + str(out), flush=True)


if __name__ == '__main__':
    main()
