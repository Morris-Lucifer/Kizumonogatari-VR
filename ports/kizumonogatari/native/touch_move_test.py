"""Exercise the compiled Android host's actual TouchInput source with an OpenXR fixture."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
from move_controller_test import ROOT, CORE, linux


def main():
    manifest = json.loads((ROOT / 'evidence/kizu-native/latest-android-host.json').read_text(encoding='utf-8'))
    host = Path(manifest['library']).parent / 'cpp'
    out = ROOT / 'evidence/kizu-native/move-input-20261016' / ('touch-test-' + datetime.now().strftime('%H%M%S'))
    stub = out / 'stubs/android'
    stub.mkdir(parents=True)
    (stub / 'log.h').write_text('#define ANDROID_LOG_INFO 4\n#define ANDROID_LOG_WARN 5\n#define ANDROID_LOG_ERROR 6\n', encoding='utf-8')
    code = r'''
#include <cassert>
#include <cmath>
#include <map>
#include <string>
#include <iostream>
#include "touch_input.h"
using namespace Core::Vr::Protocol;
std::map<XrPath,std::string> paths;
std::map<XrAction,std::string> actions;
std::map<XrSpace,XrPath> spaces;
std::map<std::string,bool> buttons;
bool connected[2]{true,true}, tracked[2]{true,true}, focused=true;
float trigger[2]{.25f,.75f}, grip[2]{1,0};
MoveInput moves[2]; PadState last_pad;
template<class T> T handle() {static uintptr_t value=100;return reinterpret_cast<T>(++value);}
int hand(XrPath path){return paths[path].find("/left")!=std::string::npos?0:1;}
void HostLog(int,const char*,...) {}
CoreProcess::~CoreProcess() = default;
void CoreProcess::SetTouchPad(const PadState& pad,bool){last_pad=pad;}
void CoreProcess::SendMoveInput(const MoveInput& input){assert(input.hand<2);moves[input.hand]=input;}
XrResult xrStringToPath(XrInstance,const char* text,XrPath* path){
  for(auto& [key,value]:paths)if(value==text){*path=key;return XR_SUCCESS;}
  *path=paths.size()+1;paths[*path]=text;return XR_SUCCESS;
}
XrResult xrCreateActionSet(XrInstance,const XrActionSetCreateInfo*,XrActionSet* out){*out=handle<XrActionSet>();return XR_SUCCESS;}
XrResult xrCreateAction(XrActionSet,const XrActionCreateInfo* info,XrAction* out){*out=handle<XrAction>();actions[*out]=info->actionName;return XR_SUCCESS;}
XrResult xrSuggestInteractionProfileBindings(XrInstance,const XrInteractionProfileSuggestedBinding*){return XR_SUCCESS;}
XrResult xrAttachSessionActionSets(XrSession,const XrSessionActionSetsAttachInfo*){return XR_SUCCESS;}
XrResult xrCreateActionSpace(XrSession,const XrActionSpaceCreateInfo* info,XrSpace* out){*out=handle<XrSpace>();spaces[*out]=info->subactionPath;return XR_SUCCESS;}
XrResult xrDestroySpace(XrSpace){return XR_SUCCESS;}
XrResult xrDestroyActionSet(XrActionSet){return XR_SUCCESS;}
XrResult xrSyncActions(XrSession,const XrActionsSyncInfo*){return focused?XR_SUCCESS:XR_SESSION_NOT_FOCUSED;}
XrResult xrGetActionStateBoolean(XrSession,const XrActionStateGetInfo* info,XrActionStateBoolean* out){
 out->isActive=true;auto key=actions[info->action];
 if(info->subactionPath)key+=std::to_string(hand(info->subactionPath));
 out->currentState=buttons[key];return XR_SUCCESS;
}
XrResult xrGetActionStateFloat(XrSession,const XrActionStateGetInfo* info,XrActionStateFloat* out){
 int h=hand(info->subactionPath);out->isActive=connected[h];
 out->currentState=actions[info->action]=="triggers"?trigger[h]:grip[h];return XR_SUCCESS;
}
XrResult xrGetActionStateVector2f(XrSession,const XrActionStateGetInfo*,XrActionStateVector2f* out){out->isActive=true;out->currentState={};return XR_SUCCESS;}
XrResult xrGetActionStatePose(XrSession,const XrActionStateGetInfo* info,XrActionStatePose* out){out->isActive=connected[hand(info->subactionPath)];return XR_SUCCESS;}
XrResult xrLocateSpace(XrSpace space,XrSpace,XrTime,XrSpaceLocation* out){
 int h=hand(spaces[space]);out->locationFlags=tracked[h]?XR_SPACE_LOCATION_POSITION_VALID_BIT|XR_SPACE_LOCATION_ORIENTATION_VALID_BIT:0;
 out->pose.position={h?.2f:-.2f,-.3f,-.4f};out->pose.orientation={0,0,0,1};
 auto* v=static_cast<XrSpaceVelocity*>(out->next);v->velocityFlags=XR_SPACE_VELOCITY_ANGULAR_VALID_BIT|XR_SPACE_VELOCITY_LINEAR_VALID_BIT;
 v->linearVelocity={};v->angularVelocity={0,1,0};return XR_SUCCESS;
}
XrResult xrApplyHapticFeedback(XrSession,const XrHapticActionInfo*,const XrHapticBaseHeader*){return XR_SUCCESS;}
XrResult xrStopHapticFeedback(XrSession,const XrHapticActionInfo*){return XR_SUCCESS;}
bool near(float a,float b){return std::abs(a-b)<.0001f;}
int main(){
 TouchInput input;CoreProcess core;
 assert(input.Initialize(handle<XrInstance>(),handle<XrSession>(),handle<XrSpace>()));
 buttons["circle"]=true; // physical X, the left primary button
 PadPose pad;assert(input.Read(1000,core,pad));
 assert(moves[0].flags==3&&moves[1].flags==3);
 assert(near(moves[0].position[0],-.2f)&&near(moves[1].position[0],.2f));
 assert(near(moves[0].position[2],-.52f));
 assert(near(moves[0].orientation[0],0)&&near(moves[0].orientation[3],1));
 assert(near(moves[0].linear_velocity[0],-.12f));
 assert(moves[0].buttons==(0x800|0x40)&&moves[1].buttons==0x1000);
 assert(near(moves[0].trigger,.25f)&&near(moves[1].trigger,.75f));
 tracked[0]=false;pad={};input.Read(2000,core,pad);
 assert(moves[0].flags==1&&moves[1].flags==3);
 connected[1]=false;pad={};input.Read(3000,core,pad);
 assert(moves[1].flags==0&&moves[1].buttons==0&&moves[1].trigger==0);
 connected[0]=connected[1]=tracked[0]=true;
 buttons["clicks0"]=buttons["clicks1"]=true;
 pad={};input.Read(4000,core,pad);assert(pad.flags&PadPose::RecenterSeat);
 assert(!(moves[0].buttons&0x80)&&!(moves[1].buttons&0x80));
 pad={};input.Read(5000,core,pad);assert(!(pad.flags&PadPose::RecenterSeat));
 focused=false;input.Read(6000,core,pad);
 assert(moves[0].flags==0&&moves[1].flags==0&&last_pad.buttons==0);
 input.Destroy();
 std::cout<<"PASS actual TouchInput: independent grip poses, sphere axis, angular offset velocity, analog/digital inputs, tracking loss, disconnect, focus loss and recenter\n";
}
'''
    source = out / 'test.cpp'
    source.write_text(code, encoding='utf-8')
    binary = out / 'touch_move_test'
    cmd = ['wsl', '--exec', 'g++', '-std=c++20', '-O2', '-pthread',
           '-I' + linux(stub.parent), '-I' + linux(host),
           '-I' + linux(CORE / 'core/vr'),
           '-I' + linux(CORE.parent / 'externals/openxr-sdk/include'),
           linux(host / 'touch_input.cpp'), linux(source), '-o', linux(binary)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (out / 'compile.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        print(result.stderr[-7000:])
        raise SystemExit(result.returncode)
    result = subprocess.run(['wsl', '--exec', linux(binary)], capture_output=True, text=True, timeout=20)
    (out / 'result.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    print(result.stdout + result.stderr)
    print(out)
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
