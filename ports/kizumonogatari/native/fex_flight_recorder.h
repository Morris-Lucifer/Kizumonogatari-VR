// SPDX-License-Identifier: MIT
#pragma once

// Opt-in, bounded diagnostics for normal HLE/FEX execution boundaries only.
// None of these functions may be called from a POSIX signal handler.
#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <mutex>
#include <string_view>
#include <time.h>
#include <sys/syscall.h>
#include <unistd.h>

namespace Core::Fex::Diagnostics {

inline bool Enabled() {
    static const bool enabled = [] {
        const auto* value = std::getenv("BACHATA_FEX_FLIGHT_RECORDER");
        return value && std::strcmp(value, "1") == 0;
    }();
    return enabled;
}

// Copy through the kernel: an unmapped guest address must not crash diagnostics.
// Each call owns its pipe, so partial writes/EINTR cannot poison a later read or
// deadlock another thread. Small bounded reads stay below PIPE_BUF.
inline bool ReadMemory(uint64_t address, void* output, size_t size) {
    const int saved_errno = errno;
    if (!address || !size || size > 512 || address > UINT64_MAX - size) return false;
    int ends[2];
    if (pipe(ends) != 0) { errno = saved_errno; return false; }
    ssize_t written;
    do { written = write(ends[1], reinterpret_cast<const void*>(address), size); }
    while (written < 0 && errno == EINTR);
    bool ok = written == static_cast<ssize_t>(size);
    if (ok) {
        size_t done = 0;
        while (done < size) {
            const auto count = read(ends[0], static_cast<char*>(output) + done, size - done);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) { ok = false; break; }
            done += static_cast<size_t>(count);
        }
    }
    close(ends[0]);
    close(ends[1]);
    errno = saved_errno;
    return ok;
}

struct Event {
    uint64_t sequence{}, call{}, parent{}, time_ns{};
    uint64_t operation{}, rip{}, rsp{}, rbp{}, rax{}, caller{}, detail{};
    bool caller_valid{};
    char kind[24]{};
    char name[64]{};
};

template<size_t Capacity> class Ring {
public:
    void Push(const Event& event) {
        events[next] = event;
        next = (next + 1) % Capacity;
        count = std::min(count + 1, Capacity);
        ++total;
    }
    template<class Visitor> void Visit(Visitor visit) const {
        const auto first = (next + Capacity - count) % Capacity;
        for (size_t index = 0; index < count; ++index)
            visit(events[(first + index) % Capacity]);
    }
    size_t Count() const { return count; }
    uint64_t Total() const { return total; }
private:
    static_assert(Capacity > 0);
    std::array<Event, Capacity> events{};
    size_t next{}, count{};
    uint64_t total{};
};

constexpr size_t MaxThreads = 128;
constexpr size_t EventsPerThread = 256;
struct ThreadTrace {
    std::mutex mutex;
    int tid{};
    Ring<EventsPerThread> events;
};
struct Recorder {
    std::array<ThreadTrace, MaxThreads> threads;
    std::atomic<size_t> claimed{};
    std::atomic<uint64_t> sequence{};
    std::atomic<uint64_t> dropped{};
};
inline Recorder& GetRecorder() {
    // Intentionally process-lifetime; TLS users may outlive static destructors.
    static auto* recorder = new Recorder;
    return *recorder;
}
inline thread_local uint64_t ActiveCall{};
inline thread_local uint64_t BoundaryRip{};

inline uint64_t Record(Event event) {
    if (!Enabled()) return 0;
    auto& recorder = GetRecorder();
    static thread_local ThreadTrace* trace = [&]() -> ThreadTrace* {
        const auto slot = recorder.claimed.fetch_add(1, std::memory_order_relaxed);
        if (slot >= MaxThreads) return nullptr;
        auto& item = recorder.threads[slot];
        std::lock_guard lock(item.mutex);
        item.tid = static_cast<int>(syscall(SYS_gettid));
        return &item;
    }();
    if (!trace) { recorder.dropped.fetch_add(1, std::memory_order_relaxed); return 0; }
    const int saved_errno = errno;
    timespec time{};
    clock_gettime(CLOCK_MONOTONIC, &time);
    event.time_ns = uint64_t(time.tv_sec) * 1'000'000'000 + time.tv_nsec;
    std::lock_guard lock(trace->mutex);
    event.sequence = recorder.sequence.fetch_add(1, std::memory_order_relaxed) + 1;
    trace->events.Push(event);
    errno = saved_errno;
    return event.sequence;
}

inline Event MakeEvent(const char* kind, uint64_t rip, uint64_t rsp,
                       uint64_t rbp, uint64_t rax, uint64_t detail = 0) {
    Event event{};
    std::snprintf(event.kind, sizeof(event.kind), "%s", kind);
    event.rip = rip; event.rsp = rsp; event.rbp = rbp; event.rax = rax;
    event.detail = detail; event.parent = ActiveCall;
    return event;
}

inline bool TraceName(std::string_view name) {
    static const char* filter = std::getenv("BACHATA_FEX_TRACE_NAMES");
    if (!filter) return false;
    std::string_view remaining{filter};
    while (!remaining.empty()) {
        const auto end = remaining.find(',');
        if (remaining.substr(0, end) == name) return true;
        if (end == std::string_view::npos) break;
        remaining.remove_prefix(end + 1);
    }
    return false;
}

class HleScope {
public:
    HleScope(uint64_t operation, std::string_view name, uint64_t rsp, uint64_t rbp,
             const uint64_t* gprs = nullptr)
        : enabled(Enabled()), parent(ActiveCall) {
        if (!enabled) return;
        event = MakeEvent("hle-begin", BoundaryRip, rsp, rbp, operation);
        event.operation = operation;
        const auto length = std::min(name.size(), sizeof(event.name) - 1);
        std::memcpy(event.name, name.data(), length);
        event.caller_valid = ReadMemory(rsp, &event.caller, sizeof(event.caller));
        call = Record(event);
        ActiveCall = call;
        static std::atomic<unsigned> trace_count{};
        traced = TraceName(name) && trace_count.fetch_add(1, std::memory_order_relaxed) < 2048;
        if (traced && gprs) {
            std::fprintf(stderr, "BACHATA_FEX_SELECTED_BEGIN call=%llu tid=%ld name=%s caller=%#llx "
                "args=%#llx,%#llx,%#llx,%#llx,%#llx,%#llx\n", (unsigned long long)call,
                syscall(SYS_gettid), event.name, (unsigned long long)event.caller,
                (unsigned long long)gprs[7], (unsigned long long)gprs[6],
                (unsigned long long)gprs[2], (unsigned long long)gprs[1],
                (unsigned long long)gprs[8], (unsigned long long)gprs[9]);
        }
    }
    HleScope(const HleScope&) = delete;
    HleScope& operator=(const HleScope&) = delete;
    void Finish(uint64_t result, int error = 0) {
        if (!enabled || finished) return;
        std::snprintf(event.kind, sizeof(event.kind), "%s", error ? "hle-error" : "hle-end");
        event.call = call; event.parent = parent; event.rax = result;
        event.detail = static_cast<uint64_t>(error);
        Record(event);
        if (traced) std::fprintf(stderr, "BACHATA_FEX_SELECTED_END call=%llu result=%#llx error=%d\n",
                                 (unsigned long long)call, (unsigned long long)result, error);
        finished = true;
    }
    ~HleScope() {
        if (!enabled) return;
        if (!finished) {
            std::snprintf(event.kind, sizeof(event.kind), "hle-unwind");
            event.call = call;
            Record(event);
        }
        ActiveCall = parent;
    }
private:
    bool enabled{}, finished{}, traced{};
    uint64_t parent{}, call{};
    Event event{};
};

inline void Dump(FILE* out) {
    if (!Enabled()) return;
    auto& recorder = GetRecorder();
    std::fprintf(out, "BACHATA_FEX_RECORDER_BEGIN version=1 capacity=%zu threads=%zu dropped=%llu\n",
        EventsPerThread, std::min(recorder.claimed.load(), MaxThreads),
        static_cast<unsigned long long>(recorder.dropped.load()));
    for (size_t index = 0; index < std::min(recorder.claimed.load(), MaxThreads); ++index) {
        auto& trace = recorder.threads[index];
        // A fault in another path must never wait for a stopped thread's mutex.
        std::unique_lock lock(trace.mutex, std::try_to_lock);
        if (!lock.owns_lock()) {
            std::fprintf(out, "BACHATA_FEX_RECORDER_BUSY slot=%zu\n", index);
            continue;
        }
        std::fprintf(out, "BACHATA_FEX_RECORDER_THREAD tid=%d total=%llu retained=%zu\n",
                     trace.tid, static_cast<unsigned long long>(trace.events.Total()), trace.events.Count());
        trace.events.Visit([&](const Event& event) {
            std::fprintf(out, "BACHATA_FEX_RECENT seq=%llu tid=%d ns=%llu kind=%s call=%llu parent=%llu "
                "op=%llu name=%s rip=%#llx rsp=%#llx rbp=%#llx rax=%#llx caller=%#llx caller_valid=%d detail=%#llx\n",
                (unsigned long long)event.sequence, trace.tid, (unsigned long long)event.time_ns,
                event.kind, (unsigned long long)event.call, (unsigned long long)event.parent,
                (unsigned long long)event.operation, event.name, (unsigned long long)event.rip,
                (unsigned long long)event.rsp, (unsigned long long)event.rbp, (unsigned long long)event.rax,
                (unsigned long long)event.caller, event.caller_valid, (unsigned long long)event.detail);
        });
    }
    std::fprintf(out, "BACHATA_FEX_RECORDER_END\n");
}
} // namespace Core::Fex::Diagnostics
