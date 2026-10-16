"""Run the real GetVideoData method against deterministic decoder/poll interleavings."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = ROOT / 'evidence/kizu-native/src/shadps4-arm64-main/src/core/libraries/avplayer/avplayer_source.cpp'

FIXTURE = r'''
#include <array>
#include <atomic>
#include <cstdint>
#include <deque>
#include <iostream>
#include <optional>
#include <stdexcept>
#include <utility>
#include "video_frame_snapshot.h"
using u64 = uint64_t;
using u32 = uint32_t;
using VAddr = uintptr_t;
namespace Core::Memory {
struct FakeMemory {
    unsigned invalidations = 0;
    void InvalidateMemory(VAddr, size_t) { ++invalidations; }
};
FakeMemory* Instance() { static FakeMemory memory; return &memory; }
}
#define LOG_INFO(...)
#define LOG_WARNING(...)
bool ShouldTraceCount(u64) { return false; }
enum class AvPlayerAvSyncMode { Default };
struct State { AvPlayerAvSyncMode GetSyncMode() { return AvPlayerAvSyncMode::Default; } };
struct Buffer { unsigned char* data; };
struct AvPlayerFrameInfoEx { void* p_data; u64 timestamp; };
struct Frame {
    Buffer buffer;
    AvPlayerFrameInfoEx info;
    std::shared_ptr<const Core::VideoFrameSnapshot> video_snapshot{};
};
template<class T> struct Queue {
    std::deque<T> values;
    size_t Size() const { return values.size(); }
    T& Front() { return values.front(); }
    void Push(T&& t) { values.push_back(std::move(t)); }
    std::optional<T> Pop() {
        if (values.empty()) return {};
        auto v = std::move(values.front()); values.pop_front(); return v;
    }
};
struct CV { void Notify() {} };
// The fixture controls when a decoded frame becomes due; production sync logic
// is independent of this lifetime regression.
bool AvPlayerVideoBlockedByAudio(u64 video, u64 audio, bool, bool, u32) {
    return video > audio;
}
struct AvPlayerSource {
    bool GetVideoData(AvPlayerFrameInfoEx&);
    bool active = true;
    bool IsActive() { return active; }
    u64 CurrentTime() { return clock; }
    u64 clock = 100;
    State m_state;
    Queue<Buffer> m_video_buffers;
    Queue<Frame> m_video_frames;
    Queue<int> m_audio_frames;
    std::optional<Frame> m_current_video_frame;
    std::optional<int> m_audio_stream_index = 0;
    std::optional<u64> m_last_audio_ts = 100;
    std::atomic<u64> m_atomic_last_audio_ts{100};
    std::atomic<bool> m_is_paused{false}, m_is_eof{false}, m_is_looping{false};
    std::atomic<u64> m_trace_video_data_success_count{0}, m_trace_video_data_inactive_count{0},
        m_trace_video_data_empty_count{0}, m_trace_video_data_ahead_count{0};
    CV m_video_buffers_cv;
};
'''

CASES = r'''
void check(bool condition, const char* why) {
    if (!condition) throw std::runtime_error(why);
}
int main() {
    try {
        std::array<unsigned char, 2> pixels{0x11, 0x22};
        AvPlayerSource source;
        source.m_video_frames.Push(Frame{Buffer{&pixels[0]}, {&pixels[0], 100}});
        source.m_video_frames.Push(Frame{Buffer{&pixels[1]}, {&pixels[1], 142}});
        AvPlayerFrameInfoEx shown{};
        check(source.GetVideoData(shown), "first picture was not returned");
        check(shown.timestamp == 100, "incorrect first timestamp");
        for (int poll = 0; poll < 8; ++poll) {
            check(!source.GetVideoData(shown), "future picture returned before audio caught up");
            // Schedule the decoder immediately after a false guest poll. Any
            // buffer it can acquire is overwritten with a future picture.
            if (auto recycled = source.m_video_buffers.Pop()) *recycled->data = 0xee;
            check(*static_cast<unsigned char*>(shown.p_data) == 0x11,
                  "false poll recycled the displayed buffer; decoder overwrote the current picture");
        }
        source.m_last_audio_ts = 142;
        check(source.GetVideoData(shown) && shown.timestamp == 142, "replacement did not advance");
        check(source.m_video_buffers.Size() == 1, "old buffer not recycled after replacement");
        check(!source.GetVideoData(shown), "empty queue should return false");
        check(source.m_video_buffers.Size() == 1, "empty poll retired the displayed picture");
        source.m_is_paused = true;
        check(!source.GetVideoData(shown), "paused playback should return false");
        check(source.m_current_video_frame.has_value(), "pause released displayed picture");
        source.m_is_paused = false;
        source.active = false;
        check(!source.GetVideoData(shown), "inactive playback should return false");
        check(source.m_current_video_frame.has_value(), "inactive poll released displayed picture");
        source.active = true;
        auto next = source.m_video_buffers.Pop();
        check(next.has_value(), "two-buffer decoder starved");
        *next->data = 0x33;
        source.m_video_frames.Push(Frame{*next, {next->data, 184}});
        source.m_last_audio_ts = 184;
        check(source.GetVideoData(shown) && shown.timestamp == 184, "two-buffer playback stalled");
        check(*static_cast<unsigned char*>(shown.p_data) == 0x33, "replacement pixels incorrect");
        check(source.m_video_buffers.Size() == 1, "buffer ownership count changed");
        // When the immutable-upload path is present, publication must happen on
        // successful delivery, not on a false poll or when decoding ahead.
        if (EXPECT_SNAPSHOTS) {
            AvPlayerSource publishing;
            auto first = std::make_shared<Core::VideoFrameSnapshot>();
            first->pixels.assign(2, 0x44); first->timestamp = 100;
            auto second = std::make_shared<Core::VideoFrameSnapshot>();
            second->pixels.assign(2, 0x55); second->timestamp = 142;
            publishing.m_video_frames.Push(Frame{Buffer{pixels.data()}, {pixels.data(), 100}, first});
            publishing.m_video_frames.Push(Frame{Buffer{pixels.data()}, {pixels.data(), 142}, second});
            const auto address = reinterpret_cast<VAddr>(pixels.data());
            auto& snapshots = Core::VideoFrameSnapshotStore::Instance();
            check(publishing.GetVideoData(shown), "published first frame missing");
            const auto old = snapshots.Find(address, 2);
            check(old && old->frame->timestamp == 100, "delivered frame was not published");
            check(!publishing.GetVideoData(shown), "future snapshot delivered early");
            check(snapshots.Find(address, 2)->frame->timestamp == 100,
                  "false poll published decode-ahead pixels");
            publishing.m_last_audio_ts = 142;
            check(publishing.GetVideoData(shown), "replacement snapshot missing");
            check(snapshots.Find(address, 2)->frame->timestamp == 142 &&
                  old->frame->pixels[0] == 0x44, "replacement mutated an active upload");
            check(Core::Memory::Instance()->invalidations == 2,
                  "publication did not invalidate exactly the delivered frames");
            snapshots.Forget(address);
        }
        std::cout << "Actual GetVideoData: future/empty/paused/inactive polls retain pixels; "
                     "replacement and two-buffer progress passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    parser.add_argument('--label', default='fixed')
    args = parser.parse_args()
    if not args.label.replace('-', '').isalnum():
        parser.error('Use an alphanumeric label')
    source = args.source.read_text(encoding='utf-8')
    begin = source.index('bool AvPlayerSource::GetVideoData(AvPlayerFrameInfoEx& video_info) {')
    end = source.index('\nbool AvPlayerSource::GetAudioData(', begin)
    out = ROOT / 'evidence/kizu-native/video-lifetime-20261016'
    out.mkdir(exist_ok=True)
    cpp = out / f'actual-method-{args.label}.cpp'
    method = source[begin:end]
    expected = '#define EXPECT_SNAPSHOTS ' + ('1' if 'VideoFrameSnapshotStore' in method else '0') + '\n'
    cpp.write_bytes((expected + FIXTURE + method + CASES).encode('utf-8'))
    path = cpp.resolve().as_posix()
    wsl = '/mnt/' + path[0].lower() + path[2:]
    binary = wsl.removesuffix('.cpp')
    include = '/mnt/' + ROOT.as_posix()[0].lower() + ROOT.as_posix()[2:] + '/ports/kizumonogatari/native'
    subprocess.run(['wsl', '-d', 'Ubuntu', '--', 'g++', '-std=c++20', '-Wall', '-Wextra', '-I', include,
                    wsl, '-o', binary], check=True)
    result = subprocess.run(['wsl', '-d', 'Ubuntu', '--', binary], capture_output=True)
    (out / f'test-{args.label}.log').write_bytes(result.stdout + result.stderr)
    print((result.stdout + result.stderr).decode('utf-8', errors='replace'), end='')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
