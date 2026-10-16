"""Run actual Move HLE and extracted production Runtime methods on the Linux host."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
CORE = ROOT / 'evidence/kizu-native/src/shadps4-arm64-main/src'


def linux(path):
    path = path.resolve().as_posix()
    return '/mnt/' + path[0].lower() + path[2:]


def function(text, signature):
    start = text.index(signature)
    begin = text.index('{', start)
    depth = 0
    for i in range(begin, len(text)):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError(signature)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    args = parser.parse_args()
    out = ROOT / 'evidence/kizu-native/move-input-20261016' / (
        ('baseline-test-' if args.baseline else 'fixed-test-') + datetime.now().strftime('%H%M%S'))
    out.mkdir(parents=True)
    stubs = out / 'stubs'
    for name, data in {
        'common/logging/log.h': '#pragma once\n#define LOG_INFO(...) ((void)0)\n#define LOG_WARNING(...) ((void)0)\n#define LOG_DEBUG(...) ((void)0)\n#define LOG_TRACE(...) ((void)0)\n',
        'core/libraries/libs.h': '#pragma once\n#define LIB_FUNCTION(...) ((void)0)\n',
    }.items():
        p = stubs / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding='utf-8')
    runtime = (CORE / 'core/vr/vr_runtime.cpp').read_text(encoding='utf-8')
    methods = ['Quat Multiply(', 'Quat Conjugate(', 'Quat Normalize(', 'Vec3 Rotate(',
               'Quat FromYawPitch(', 'Quat YawOnly(', 'float Length(',
               'Runtime& Runtime::Instance()', 'Vec3 Runtime::PositionToTracker(',
               'Vec3 Runtime::DirectionToTracker(', 'void Runtime::PlaceHead()',
               'void Runtime::RecenterSeatLocked()', 'void Runtime::RecenterSeat()',
               'void Runtime::UpdateHead(', 'void Runtime::UpdateMove(',
               'MoveState Runtime::GetMove(', 'void Runtime::SetMoveVibration(',
               'void Runtime::SetMoveFeedbackListener(']
    extracted = '\n\n'.join(function(runtime, name) for name in methods)
    move_file = CORE / 'core/libraries/move/move.cpp'
    if args.baseline:
        baseline = ROOT / 'tests/fixtures/move_baseline.cpp'
        move_file = out / 'baseline_move.cpp'
        move_file.write_text(baseline.read_text(encoding='utf-8').replace('#include "move.h"', ''), encoding='utf-8')
    fixture = r'''
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <thread>
#include "common/logging/log.h"
#include "core/vr/vr_runtime.h"
#include "core/vr/vr_protocol.h"
namespace Core::Vr {
Runtime::Runtime() = default;
EXTRACTED
}
#include "MOVE_FILE"
using namespace Core::Vr;
using namespace Libraries::Move;
void check(bool ok, const char* what) { if (!ok) throw std::runtime_error(what); }
bool near(float a, float b) { return std::abs(a-b) < .0001f; }
int main() {
  try {
    static_assert(sizeof(OrbisMoveData) == 64);
    static_assert(offsetof(OrbisMoveData, timestamp) == 48);
    static_assert(offsetof(OrbisMoveData, button_data) == 24);
    auto& r = Runtime::Instance();
    DeviceState head; head.tracked=true; head.pose.position={10,2,3};
    r.UpdateHead(head);
    MoveState left, right;
    left.connected=right.connected=true;
    left.device.tracked=right.device.tracked=true;
    left.device.pose.position={9.7f,1.5f,2.5f};
    right.device.pose.position={10.3f,1.5f,2.5f};
    left.buttons=0x800; left.trigger=.5f; left.timestamp=100;
    right.buttons=0x40; right.timestamp=110;
    r.UpdateMove(0,left); r.UpdateMove(1,right);
    check(sceMoveInit()==0,"init");
    // Kizu uses the first Move slot as its interactive right hand.
    int h=sceMoveOpen(1,0,0), l=sceMoveOpen(1,0,1);
    check(l>0 && h>0 && l!=h,"two distinct handles");
#ifndef BASELINE_MOVE
    check(HandForHandle(h)==1 && HandForHandle(l)==0,"Kizu slot 0 must use physical right, slot 1 physical left");
#endif
    OrbisMoveData data{};
    check(sceMoveReadStateLatest(l,&data)==0,"connected left Move must be readable");
    check(data.button_data.button_data==0x800 && data.button_data.trigger_data==128,"left buttons and analog trigger");
    check(sceMoveReadStateLatest(h,&data)==0 && data.button_data.button_data==0x40,"right input independent");
    OrbisMoveDeviceInfo info{};
    check(sceMoveGetDeviceInfo(l,&info)==0 && info.sphere_radius>0,"connected device info");
    check(sceMoveOpen(1,0,0)==ORBIS_MOVE_ERROR_ALREADY_OPENED,"duplicate hand rejected");
    check(sceMoveOpen(1,0,2)==ORBIS_MOVE_ERROR_INVALID_ARG,"invalid index rejected");
    auto a=r.GetMove(0), b=r.GetMove(1);
    check(near(a.device.pose.position.x,-.3f)&&near(b.device.pose.position.x,.3f),"independent positions relative to head");
#ifndef BASELINE_MOVE
    check(near(r.GetMove(*HandForHandle(h)).device.pose.position.x,.3f),"right tracker handle follows physical right pose");
    check(near(r.GetMove(*HandForHandle(l)).device.pose.position.x,-.3f),"left tracker handle follows physical left pose");
#endif
    check(near(a.device.pose.position.z,1.0f),"tracker camera origin");
    head.pose.orientation=FromYawPitch(1.57079632679f,0); r.UpdateHead(head); r.RecenterSeat();
    a=r.GetMove(0); b=r.GetMove(1);
    check(near(a.device.pose.position.x,.5f) && near(a.device.pose.position.z,1.2f),"left transforms on recenter without a new packet");
    check(near(b.device.pose.position.x,.5f) && near(b.device.pose.position.z,1.8f),"right uses same recenter");
    int count=-1; data.count=-99;
    check(sceMoveReadStateRecent(l,100,&data,&count)==0 && count==0 && data.count==-99,"recent read does not repeat unchanged sample");
    check(sceMoveReadStateRecent(l,99,&data,&count)==0 && count==1 && data.timestamp==100,"recent read returns one new sample");
    left.connected=false; r.UpdateMove(0,left);
    a=r.GetMove(0);
    check(!a.connected && !a.device.tracked && a.buttons==0 && a.trigger==0,"disconnect clears held controls");
    check(sceMoveReadStateLatest(l,&data)==ORBIS_MOVE_ERROR_NO_CONTROLLER_CONNECTED,"disconnected read status");
    check(r.GetMove(1).connected,"left disconnect does not release right");
    left.connected=true; left.device.tracked=false; r.UpdateMove(0,left);
    check(r.GetMove(0).connected && !r.GetMove(0).device.tracked,"connection and tracking are separate");
    bool feedback=false; u32 feedback_hand=99; u8 feedback_level=255;
    r.SetMoveFeedbackListener([&](u32 hand,u8 level){ feedback_hand=hand; feedback_level=level; feedback=(hand==1 && level==123 && r.GetMove(1).connected); });
    check(sceMoveSetVibration(h,123)==0 && feedback,"feedback is per-hand and callback runs without runtime lock");
    std::this_thread::sleep_for(std::chrono::milliseconds{270});
    check(!r.GetMove(1).connected && r.GetMove(1).buttons==0,"stale transport cannot leave a ghost hand or held button");
    check(sceMoveClose(l)==0 && sceMoveReadStateLatest(l,&data)==ORBIS_MOVE_ERROR_INVALID_HANDLE,"close invalidates handle");
    check(feedback_hand==0 && feedback_level==0,"closing slot 1 stops physical left vibration");
    check(sceMoveTerm()==0 && sceMoveInit()==0,"terminate then reinitialize");
    int replacement=sceMoveOpen(1,0,0);
    check(replacement!=l && sceMoveReadStateLatest(l,&data)==ORBIS_MOVE_ERROR_INVALID_HANDLE,"old handle never aliases reopened hand");
    left.buttons=0; r.UpdateMove(0,left);
    std::thread writer([&]{ for(int i=0;i<10000;++i){left.buttons=i&1;left.timestamp=i;r.UpdateMove(0,left);} });
    for(int i=0;i<10000;++i) check(r.GetMove(0).buttons<=1,"concurrent publication consistent");
    writer.join();
    std::cout<<"PASS actual Move HLE, independent poses, recenter, buttons, disconnect, timeout, handles and feedback\n";
  } catch (const std::exception& e) { std::cerr<<"FAIL "<<e.what()<<"\n"; return 1; }
}
'''.replace('EXTRACTED', extracted).replace('MOVE_FILE', linux(move_file))
    source = out / 'test.cpp'
    source.write_text(fixture, encoding='utf-8')
    binary = out / 'move_controller_test'
    command = ['wsl', '--exec', 'g++', '-std=c++20', '-O2', '-pthread',
               '-I' + linux(stubs), '-I' + linux(CORE), linux(source), '-o', linux(binary)]
    if args.baseline:
        command.append('-DBASELINE_MOVE')
    compile_result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (out / 'compile.log').write_text(compile_result.stdout + compile_result.stderr, encoding='utf-8')
    if compile_result.returncode:
        print(compile_result.stderr[-6000:])
        raise SystemExit(compile_result.returncode)
    result = subprocess.run(['wsl', '--exec', linux(binary)], capture_output=True, text=True, timeout=20)
    (out / 'result.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    expected = result.returncode != 0 if args.baseline else result.returncode == 0
    (out / 'validation.json').write_text(json.dumps(dict(baseline=args.baseline,
        expected_result=expected, exit_code=result.returncode,
        runtime_sha256=hashlib.sha256(runtime.encode()).hexdigest()), indent=2), encoding='utf-8')
    print(result.stdout + result.stderr)
    print(out)
    if not expected:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
