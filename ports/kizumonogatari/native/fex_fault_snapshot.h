// SPDX-License-Identifier: MIT
#pragma once
#include "fex_flight_recorder.h"
#include <FEXCore/Core/CoreState.h>
#include <FEXCore/Core/X86Enums.h>

namespace Core::Fex::Diagnostics {
inline void RecordState(const char* kind, const FEXCore::Core::CPUState& state, uint64_t detail = 0) {
    if (!Enabled()) return;
    using namespace FEXCore::X86State;
    Record(MakeEvent(kind, state.rip, state.gregs[REG_RSP], state.gregs[REG_RBP],
                     state.gregs[REG_RAX], detail));
}

// Compare only named architectural fields, never padding or FEX host pointers.
struct SignalState {
    uint8_t flags[48]{};
    std::array<unsigned char, sizeof(FEXCore::Core::CPUState::xmm)> xmm{};
    uint32_t pf{}, af{}, mxcsr{};
    uint64_t fs{}, gs{}, callret{};
    void Save(const FEXCore::Core::CPUState& state) {
        if (!Enabled()) return;
        std::memcpy(flags, state.flags, sizeof(flags));
        std::memcpy(xmm.data(), &state.xmm, xmm.size());
        pf = state.pf_raw; af = state.af_raw; mxcsr = state.mxcsr;
        fs = state.fs_cached; gs = state.gs_cached; callret = state.callret_sp;
    }
    uint64_t Changes(const FEXCore::Core::CPUState& state) const {
        if (!Enabled()) return 0;
        return ((std::memcmp(flags, state.flags, sizeof(flags)) || pf != state.pf_raw || af != state.af_raw) ? 1 : 0)
            | (std::memcmp(xmm.data(), &state.xmm, xmm.size()) ? 2 : 0)
            | (fs != state.fs_cached ? 4 : 0) | (gs != state.gs_cached ? 8 : 0)
            | (callret != state.callret_sp ? 16 : 0) | (mxcsr != state.mxcsr ? 32 : 0);
    }
};

inline void DumpCode(uint64_t address) {
    unsigned char bytes[32]{};
    if (!ReadMemory(address, bytes, sizeof(bytes))) return;
    std::fprintf(stderr, "BACHATA_FEX_CODE address=%#llx bytes=", (unsigned long long)address);
    for (auto byte : bytes) std::fprintf(stderr, "%02x", byte);
    std::fputc('\n', stderr);
}

// Keep fault-only heap inspection bounded and use the guarded reader for every
// address. These bytes let us distinguish a null indirect-call slot in guest
// memory from an incorrectly translated load without changing guest execution.
inline void DumpMemory(const char* label, int depth, uint64_t address, size_t size) {
    for (size_t offset = 0; offset < size && address <= UINT64_MAX - offset; offset += 64) {
        unsigned char bytes[64]{};
        const uint64_t current = address + offset;
        if (!ReadMemory(current, bytes, sizeof(bytes))) break;
        std::fprintf(stderr, "BACHATA_FEX_MEMORY label=%s depth=%d address=%#llx bytes=",
                     label, depth, (unsigned long long)current);
        for (auto byte : bytes) std::fprintf(stderr, "%02x", byte);
        std::fputc('\n', stderr);
    }
}

inline void DumpFault(const FEXCore::Core::CPUState& state, uint64_t callback_return) {
    if (!Enabled()) return;
    // The known NoExec log originates in normal translation. Do not wire this
    // allocator/stdio/mutex code into the asynchronous POSIX signal handler.
    static std::atomic_flag dumped = ATOMIC_FLAG_INIT;
    if (dumped.test_and_set()) return;
    using namespace FEXCore::X86State;
    char name[64]{};
    if (auto* file = std::fopen("/proc/thread-self/comm", "r")) {
        if (std::fgets(name, sizeof(name), file)) name[std::strcspn(name, "\n")] = 0;
        std::fclose(file);
    }
    std::fprintf(stderr, "BACHATA_FEX_FAULT_BEGIN tid=%ld thread=%s frame_rip=%#llx "
        "fs=%#llx gs=%#llx callret_sp=%#llx callback_return=%#llx state=last-spilled\n",
        syscall(SYS_gettid), name, (unsigned long long)state.rip,
        (unsigned long long)state.fs_cached, (unsigned long long)state.gs_cached,
        (unsigned long long)state.callret_sp, (unsigned long long)callback_return);
    constexpr const char* names[] = {"rax", "rcx", "rdx", "rbx", "rsp", "rbp", "rsi", "rdi",
                                    "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"};
    for (size_t i = 0; i < 16; ++i)
        std::fprintf(stderr, "BACHATA_FEX_REGISTER %s=%#llx\n", names[i], (unsigned long long)state.gregs[i]);
    for (size_t i = 0; i < 16; ++i) {
        const uint64_t address = state.gregs[i];
        if (address < 0x10000) continue;
        DumpMemory(names[i], 0, address, 0x300);
        uint64_t pointers[4]{};
        if (!ReadMemory(address, pointers, sizeof(pointers))) continue;
        for (size_t j = 0; j < 4; ++j) {
            if (pointers[j] < 0x10000 || pointers[j] == address) continue;
            bool duplicate = false;
            for (size_t k = 0; k < j; ++k) duplicate |= pointers[k] == pointers[j];
            if (!duplicate) DumpMemory(names[i], 1, pointers[j], 128);
        }
    }
    std::fprintf(stderr, "BACHATA_FEX_FLAGS pf_raw=%#x af_raw=%#x mxcsr=%#x raw=", state.pf_raw, state.af_raw, state.mxcsr);
    for (auto flag : state.flags) std::fprintf(stderr, "%02x", flag);
    std::fputc('\n', stderr);
    const uint64_t rsp = state.gregs[REG_RSP];
    uint64_t top_return{};
    if (ReadMemory(rsp, &top_return, sizeof(top_return)) && top_return >= 16)
        DumpCode(top_return - 16);
    const uint64_t begin = rsp >= 128 ? rsp - 128 : 0;
    for (size_t i = 0; i < 48 && begin <= UINT64_MAX - (i * 8); ++i) {
        const uint64_t address = begin + i * 8;
        uint64_t value{};
        const bool valid = ReadMemory(address, &value, sizeof(value));
        std::fprintf(stderr, "BACHATA_FEX_STACK address=%#llx value=%#llx valid=%d\n",
                     (unsigned long long)address, (unsigned long long)value, valid);
    }
    uint64_t frame = state.gregs[REG_RBP];
    for (int depth = 0; depth < 16 && frame && !(frame & 7) && frame <= UINT64_MAX - 16; ++depth) {
        uint64_t pair[2]{};
        if (!ReadMemory(frame, pair, sizeof(pair))) break;
        std::fprintf(stderr, "BACHATA_FEX_FRAME depth=%d rbp=%#llx return=%#llx\n",
                     depth, (unsigned long long)frame, (unsigned long long)pair[1]);
        if (pair[1] >= 16) DumpCode(pair[1] - 16);
        if (pair[0] <= frame || pair[0] - frame > 1024 * 1024) break;
        frame = pair[0];
    }
    if (state.rip >= 16) DumpCode(state.rip - 16);
    // Includes the host mapping's file/offset, when file backed. Anonymous guest
    // modules must be correlated with the emulator's existing module-load log.
    if (auto* maps = std::fopen("/proc/self/maps", "r")) {
        char line[1024];
        for (int count = 0; count < 1024 && std::fgets(line, sizeof(line), maps); ++count)
            std::fprintf(stderr, "BACHATA_FEX_MAP %s", line);
        std::fclose(maps);
    }
    Dump(stderr);
    std::fprintf(stderr, "BACHATA_FEX_FAULT_END\n");
    std::fflush(stderr);
}
} // namespace Core::Fex::Diagnostics
