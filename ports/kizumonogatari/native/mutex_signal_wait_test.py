"""Compile the real TimedMutex and reproduce a collector/waiter suspend deadlock."""
import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / 'evidence/kizu-native/src/shadps4-arm64-main/src/core/libraries/kernel/sync'

TEST = r'''
#include "mutex.h"
#include <atomic>
#include <chrono>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <thread>
using namespace std::chrono_literals;
using Libraries::Kernel::TimedMutex;
thread_local std::function<void()> deferred;
thread_local unsigned delivered = 0;
namespace Core::Fex {
void FlushPendingGuestOrbisSignal() noexcept {
    if (deferred) {
        auto callback = std::move(deferred);
        deferred = {};
        ++delivered;
        callback();
    }
}
}
static void Check(bool ok, const char* why) {
    if (!ok) throw std::runtime_error(why);
}
static bool Wait(const std::atomic<bool>& flag, std::chrono::milliseconds timeout) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!flag.load() && std::chrono::steady_clock::now() < deadline)
        std::this_thread::sleep_for(1ms);
    return flag.load();
}
static void CollectorCase(bool timed) {
    TimedMutex mutex;
    mutex.lock(); // GC collector owns its lock while suspending the waiter.
    std::atomic<bool> started{false}, ack{false}, resume{false}, acquired{false};
    std::atomic<bool> callback_lock_free{false};
    std::thread waiter([&] {
        deferred = [&] {
            ack.store(true);
            while (!resume.load()) std::this_thread::sleep_for(1ms);
            // The collector has released the mutex. A callback must be able
            // to acquire it: the interrupted lock call must not own it yet.
            callback_lock_free.store(mutex.try_lock());
            if (callback_lock_free.load()) mutex.unlock();
        };
        started.store(true);
        bool locked = true;
        if (timed) locked = mutex.try_lock_for(2s);
        else mutex.lock();
        acquired.store(locked);
        if (locked) mutex.unlock();
        deferred = {};
    });
    Wait(started, 1s);
    const bool acknowledged_while_owned = Wait(ack, 500ms);
    // Always release and join even on the baseline failure, avoiding a hung
    // test process. A real collector waits indefinitely for this acknowledgment.
    mutex.unlock();
    resume.store(true);
    waiter.join();
    Check(acknowledged_while_owned, "blocked mutex never delivered GC suspend: collector deadlock reproduced");
    Check(callback_lock_free.load(), "guest callback ran while the waited mutex was owned");
    Check(acquired.load(), "lock did not resume after the collector released it");
}
int main() {
    try {
        CollectorCase(false);
        CollectorCase(true);
        TimedMutex mutex;
        deferred = [] {};
        const auto before = delivered;
        Check(mutex.try_lock_until(std::chrono::steady_clock::now() - 1s),
              "available mutex failed an expired deadline");
        Check(delivered == before, "successful acquisition delivered before owner registration");
        mutex.unlock();
        deferred = {};
        mutex.lock();
        std::atomic<bool> timed_out{false}, zero_failed{false}, callback_seen{false};
        std::thread timeout([&] {
            deferred = [&] { callback_seen.store(true); };
            zero_failed.store(!mutex.try_lock_for(0ms));
            const auto start = std::chrono::steady_clock::now();
            const auto deadline = std::chrono::time_point_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now()) + 100ms;
            const bool locked = mutex.try_lock_until(deadline);
            const auto elapsed = std::chrono::steady_clock::now() - start;
            timed_out.store(!locked && elapsed >= 75ms && elapsed < 1s);
            if (locked) mutex.unlock();
        });
        timeout.join();
        mutex.unlock();
        Check(timed_out && zero_failed && callback_seen, "timed wait or signal delivery changed semantics");
        std::cout << "Actual TimedMutex: collector/waiter GC suspend and resume passed; "
                     "callbacks run without the waited lock; relative/absolute/zero deadlines passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
'''


def wsl(path):
    path = path.resolve().as_posix()
    return '/mnt/' + path[0].lower() + path[2:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir', type=Path, default=SOURCE)
    parser.add_argument('--label', default='fixed')
    args = parser.parse_args()
    if not args.label.replace('-', '').isalnum():
        parser.error('Use an alphanumeric label')
    out = ROOT / 'evidence/kizu-native/mutex-signal-20261016' / args.label
    common = out / 'stubs/common'
    common.mkdir(parents=True, exist_ok=True)
    # These headers are unused by the Linux implementation except for types;
    # the class and all wait operations come from the actual production files.
    (common / 'types.h').write_bytes(b'#pragma once\n#include <cstdint>\nusing u64 = std::uint64_t;\n')
    (common / 'assert.h').write_bytes(b'#pragma once\n#include <cassert>\n#define ASSERT(x) assert(x)\n')
    test = out / 'test.cpp'
    test.write_bytes(TEST.encode())
    binary = out / 'test'
    subprocess.run(['wsl', '-d', 'Ubuntu', '--', 'g++', '-std=c++20', '-O2', '-Wall',
                    '-Wextra', '-Werror', '-pthread', '-DSHADPS4_ENABLE_FEX_GUEST_CPU',
                    '-I', wsl(out / 'stubs'), '-iquote', wsl(args.source_dir),
                    wsl(test), wsl(args.source_dir / 'mutex.cpp'), '-o', wsl(binary)], check=True)
    result = subprocess.run(['wsl', '-d', 'Ubuntu', '--', wsl(binary)], capture_output=True,
                            timeout=10)
    (out / 'result.log').write_bytes(result.stdout + result.stderr)
    print((result.stdout + result.stderr).decode(errors='replace'), end='')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
