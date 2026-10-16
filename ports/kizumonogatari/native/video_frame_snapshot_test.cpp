// SPDX-License-Identifier: GPL-2.0-or-later
#include "video_frame_snapshot.h"

#include <algorithm>
#include <atomic>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <thread>

static void Check(bool value, const char* why) {
    if (!value) throw std::runtime_error(why);
}

static std::shared_ptr<const Core::VideoFrameSnapshot> Picture(std::uint8_t value) {
    auto frame = std::make_shared<Core::VideoFrameSnapshot>();
    frame->pixels.assign(6144, value);
    frame->timestamp = value;
    return frame;
}

int main() {
    try {
        auto& store = Core::VideoFrameSnapshotStore::Instance();
        constexpr std::uintptr_t address = 0x200000000ULL;
        std::vector<std::uint8_t> guest(6144, 0x11);
        store.Publish(address, Picture(0x11));
        auto retained = store.Find(address, guest.size());
        Check(retained.has_value(), "whole NV12 frame unavailable");
        // Model the observed hazard: the decoder clears and rewrites the old
        // pointer while the render thread uploads a previously submitted draw.
        std::fill(guest.begin(), guest.begin() + 4096, 0);
        auto during_write = store.Find(address, guest.size());
        Check(during_write->frame->pixels[0] == 0x11 &&
              during_write->frame->pixels[4096] == 0x11,
              "upload saw a partially rewritten Y/UV frame");
        auto decoded_ahead = Picture(0x22);
        Check(store.Find(address, 1)->frame->timestamp == 0x11,
              "decode-ahead picture became visible before delivery");
        store.Publish(address, decoded_ahead);
        Check(retained->frame->pixels[0] == 0x11, "publishing mutated an active upload");
        auto uv = store.Find(address + 4096, 2048);
        Check(uv && uv->offset == 4096 && uv->frame->timestamp == 0x22,
              "UV subrange selected the wrong picture");
        Check(!store.Find(address - 1, 16) && !store.Find(address, 6145) &&
              !store.Find(address + 6144, 1) && !store.Find(address, 0) &&
              !store.Find(address + 1, std::numeric_limits<std::size_t>::max()),
              "out-of-range upload accepted");
        store.Forget(address);
        Check(!store.Find(address, 1), "freed guest allocation still registered");
        Check(retained->frame->pixels[0] == 0x11, "free invalidated an in-flight upload");

        store.Publish(address, Picture(0));
        std::atomic<bool> done{false}, bad{false};
        std::thread decoder([&] {
            for (unsigned i = 1; i <= 10000; ++i) store.Publish(address, Picture(i % 251));
            done.store(true);
        });
        unsigned reads = 0;
        do {
            const auto view = store.Find(address, 6144);
            const auto expected = std::uint8_t(view->frame->timestamp);
            if (!std::all_of(view->frame->pixels.begin(), view->frame->pixels.end(),
                             [expected](auto v) { return v == expected; })) bad.store(true);
            ++reads;
        } while (!done.load());
        decoder.join();
        Check(!bad.load(), "concurrent publication mixed frame generations");
        store.Forget(address);
        std::cout << "Published-frame snapshots: decoder overwrite, deferred publication, "
                     "Y/UV ranges, retained lifetime, bounds and 10000 concurrent publications "
                     "passed (" << reads << " reads)\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
