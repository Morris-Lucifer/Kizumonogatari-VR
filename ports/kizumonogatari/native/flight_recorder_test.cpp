// SPDX-License-Identifier: MIT
#include "fex_flight_recorder.h"
#include <cassert>
#include <string>
#include <thread>
#include <vector>
#include <sys/mman.h>

using namespace Core::Fex::Diagnostics;

int main(int argc, char**) {
    if (argc > 1) {
        assert(!Enabled());
        assert(Record(MakeEvent("disabled", 0, 0, 0, 0)) == 0);
        assert(GetRecorder().claimed.load() == 0);
        return 0;
    }
    setenv("BACHATA_FEX_FLIGHT_RECORDER", "1", 1);
    assert(Enabled());
    Ring<3> ring;
    for (uint64_t i = 1; i <= 100005; ++i) { Event e{}; e.sequence = i; ring.Push(e); }
    std::vector<uint64_t> values;
    ring.Visit([&](const Event& e) { values.push_back(e.sequence); });
    assert((values == std::vector<uint64_t>{100003, 100004, 100005}));
    assert(ring.Count() == 3 && ring.Total() == 100005);

    uint64_t caller = 0x808377110, copy{};
    errno = EDOM;
    assert(ReadMemory(reinterpret_cast<uint64_t>(&caller), &copy, 8));
    assert(copy == caller && errno == EDOM);
    assert(!ReadMemory(1, &copy, 8));
    assert(!ReadMemory(UINT64_MAX - 3, &copy, 8));
    const auto page = static_cast<size_t>(sysconf(_SC_PAGESIZE));
    auto* mapping = static_cast<char*>(mmap(nullptr, 2 * page, PROT_READ | PROT_WRITE,
                                          MAP_PRIVATE | MAP_ANONYMOUS, -1, 0));
    assert(mapping != MAP_FAILED);
    assert(mprotect(mapping + page, page, PROT_NONE) == 0);
    assert(!ReadMemory(reinterpret_cast<uint64_t>(mapping + page - 4), &copy, 8));
    assert(ReadMemory(reinterpret_cast<uint64_t>(&caller), &copy, 8));
    munmap(mapping, 2 * page);

    uint64_t outer_call{}, inner_call{};
    {
        HleScope outer(17, "outer", reinterpret_cast<uint64_t>(&caller), 0);
        outer_call = ActiveCall;
        {
            HleScope inner(18, "inner", 1, 0);
            inner_call = ActiveCall;
            assert(inner_call > outer_call);
            inner.Finish(0, EFAULT);
        }
        assert(ActiveCall == outer_call);
        outer.Finish(42);
    }
    assert(ActiveCall == 0);
    auto& trace = GetRecorder().threads[0];
    std::vector<Event> events;
    trace.events.Visit([&](const Event& e) { events.push_back(e); });
    assert(events.size() == 4);
    assert(events[0].caller_valid && events[0].caller == caller);
    assert(events[1].parent == outer_call && !events[1].caller_valid);
    assert(events[2].call == inner_call && events[2].detail == EFAULT);
    assert(events[3].call == outer_call && events[3].rax == 42);

    std::vector<std::thread> workers;
    for (int t = 0; t < 8; ++t) workers.emplace_back([] {
        for (int i = 0; i < 2000; ++i) Record(MakeEvent("worker", i, 0, 0, 0));
    });
    for (auto& worker : workers) worker.join();
    assert(GetRecorder().claimed.load() == 9);
    for (size_t i = 1; i < 9; ++i) {
        auto& item = GetRecorder().threads[i];
        assert(item.events.Total() == 2000 && item.events.Count() == EventsPerThread);
        uint64_t last{};
        item.events.Visit([&](const Event& e) { assert(e.sequence > last); last = e.sequence; });
    }
    auto* output = tmpfile();
    assert(output);
    // A busy/stopped writer cannot block a fault dump.
    std::atomic<bool> holding{}, release{};
    std::thread blocker([&] {
        std::lock_guard lock(trace.mutex);
        holding.store(true);
        while (!release.load()) std::this_thread::yield();
    });
    while (!holding.load()) std::this_thread::yield();
    Dump(output);
    release.store(true);
    blocker.join();
    rewind(output);
    char buffer[4096];
    const auto n = fread(buffer, 1, sizeof(buffer), output);
    assert(std::string(buffer, n).find("BACHATA_FEX_RECORDER_BUSY slot=0") != std::string::npos);
    fclose(output);
    std::puts("flight recorder: wraparound, nesting, unreadable memory, concurrency, nonblocking dump passed");
}
