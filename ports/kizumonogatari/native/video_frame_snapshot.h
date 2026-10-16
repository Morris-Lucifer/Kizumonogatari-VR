// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <utility>
#include <vector>

namespace Core {

struct VideoFrameSnapshot {
    std::vector<std::uint8_t> pixels;
    std::uint64_t timestamp{};
};

// The decoder may reuse guest memory while a submitted draw still references it.
// Publish only frames delivered to the guest, never decode-ahead frames. Readers
// retain an immutable generation without holding this lock during a GPU upload.
// In particular, never hold it across guest-memory writes or cache invalidation:
// those can fault and acquire the texture-cache lock in the opposite order.
class VideoFrameSnapshotStore {
public:
    struct View {
        std::shared_ptr<const VideoFrameSnapshot> frame;
        std::uintptr_t address;
        std::size_t offset;
    };

    static VideoFrameSnapshotStore& Instance() {
        static VideoFrameSnapshotStore store;
        return store;
    }

    void Publish(std::uintptr_t address, std::shared_ptr<const VideoFrameSnapshot> frame) {
        std::scoped_lock lock{mutex};
        frames.insert_or_assign(address, std::move(frame));
    }

    std::optional<View> Find(std::uintptr_t address, std::size_t size) {
        std::scoped_lock lock{mutex};
        auto it = frames.upper_bound(address);
        if (it == frames.begin() || size == 0) {
            return std::nullopt;
        }
        --it;
        const auto offset = address - it->first;
        const auto available = it->second->pixels.size();
        if (offset >= available || size > available - offset) {
            return std::nullopt;
        }
        return View{it->second, it->first, offset};
    }

    void Forget(std::uintptr_t address) {
        std::scoped_lock lock{mutex};
        frames.erase(address);
    }

private:
    std::mutex mutex;
    std::map<std::uintptr_t, std::shared_ptr<const VideoFrameSnapshot>> frames;
};

} // namespace Core
