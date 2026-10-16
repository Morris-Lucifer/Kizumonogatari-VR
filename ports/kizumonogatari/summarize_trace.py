"""Summarize a captured diagnostic core.log without requiring a connected Quest."""
import argparse
import json
from pathlib import Path
import re


def fields(line):
    result = {}
    for key, value in re.findall(r'(\w+)=(.*?)(?=\s+\w+=|$)', line):
        if key not in ('bytes', 'raw') and re.fullmatch(r'-?(?:0x[0-9a-fA-F]+|[0-9]+)', value):
            result[key] = int(value, 16 if '0x' in value else 10)
        else:
            result[key] = value
    return result


def summarize(path):
    fault, recent, errors, states, threads = None, [], [], [], []
    registers, stack, memory, code, selected = {}, [], [], [], {}
    complete = False
    with path.open(encoding='utf-8-sig', errors='replace') as stream:
        for line in stream:
            line = line.strip()
            if 'BACHATA_FEX_ERROR' in line:
                errors.append(line)
            elif 'BACHATA_FEX_FAULT_BEGIN' in line:
                fault = fields(line)
            elif 'BACHATA_FEX_REGISTER' in line:
                registers.update(fields(line))
            elif 'BACHATA_FEX_STACK' in line:
                stack.append(fields(line))
            elif 'BACHATA_FEX_MEMORY' in line:
                memory.append(fields(line))
            elif 'BACHATA_FEX_CODE' in line:
                code.append(fields(line))
            elif 'BACHATA_FEX_SELECTED_BEGIN' in line:
                item = fields(line)
                selected[item['call']] = item
            elif 'BACHATA_FEX_SELECTED_END' in line:
                item = fields(line)
                selected.setdefault(item['call'], {}).update(item)
            elif 'BACHATA_FEX_RECORDER_THREAD' in line:
                threads.append(fields(line))
            elif 'BACHATA_FEX_RECENT' in line:
                item = fields(line)
                recent.append(item)
                if str(item.get('kind', '')).startswith('signal-'):
                    states.append(item)
            elif 'BACHATA_FEX_FAULT_END' in line:
                complete = True
    recent.sort(key=lambda event: event.get('seq', 0))
    fault_tid = fault.get('tid') if fault else None
    current = [event for event in recent if event.get('tid') == fault_tid]
    return dict(log=str(path.resolve()), fault=fault, dump_complete=complete,
                errors=errors[-20:], registers=registers, stack=stack, memory=memory, code=code,
                selected_calls=list(selected.values()),
                threads=threads, fault_thread_last_events=current[-40:],
                signals=states, retained_events=len(recent),
                interpretation='Recorded state and ordering are evidence, not a confirmed root cause.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('log', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = summarize(args.log)
    encoded = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(encoded, encoding='utf-8')
        print(f'Summary: {args.output}; complete dump: {result["dump_complete"]}; events: {result["retained_events"]}')
    else:
        print(encoded)


if __name__ == '__main__':
    main()
