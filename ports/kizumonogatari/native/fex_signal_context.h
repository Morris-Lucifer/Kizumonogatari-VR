// SPDX-License-Identifier: MIT
#pragma once
#include <cstring>
#include <FEXCore/Core/CoreState.h>
#include <FEXCore/Core/X86Enums.h>
#include "core/libraries/kernel/threads/exception.h"

namespace Core::Fex {
// The conservative collector scans the interrupted registers in this context.
// A root held only in a callee-saved register must survive a stop-the-world signal.
inline void FillSignalContext(Libraries::Kernel::Mcontext& mc,
                              const FEXCore::Core::CPUState& saved,
                              uint64_t stack, uint32_t eflags) {
    using namespace FEXCore::X86State;
    mc.mc_rax = saved.gregs[REG_RAX];
    mc.mc_rbx = saved.gregs[REG_RBX];
    mc.mc_rcx = saved.gregs[REG_RCX];
    mc.mc_rdx = saved.gregs[REG_RDX];
    mc.mc_rdi = saved.gregs[REG_RDI];
    mc.mc_rsi = saved.gregs[REG_RSI];
    mc.mc_rbp = saved.gregs[REG_RBP];
    mc.mc_rsp = stack;
    mc.mc_r8 = saved.gregs[REG_R8];
    mc.mc_r9 = saved.gregs[REG_R9];
    mc.mc_r10 = saved.gregs[REG_R10];
    mc.mc_r11 = saved.gregs[REG_R11];
    mc.mc_r12 = saved.gregs[REG_R12];
    mc.mc_r13 = saved.gregs[REG_R13];
    mc.mc_r14 = saved.gregs[REG_R14];
    mc.mc_r15 = saved.gregs[REG_R15];
    mc.mc_rip = saved.rip;
    mc.mc_rflags = eflags;
    mc.mc_fsbase = saved.fs_cached;
    mc.mc_gsbase = saved.gs_cached;
    mc.mc_fs = saved.fs_idx;
    mc.mc_gs = saved.gs_idx;
    mc.mc_cs = saved.cs_idx;
    mc.mc_ss = saved.ss_idx;
    mc.mc_ds = saved.ds_idx;
    mc.mc_es = saved.es_idx;
    mc.mc_len = sizeof(mc);
}

inline void RestoreSignalState(FEXCore::Core::CPUState& state,
                               const FEXCore::Core::CPUState& saved) {
    // Restore guest architectural state and the guest return stack, not FEX's
    // live caches, deferred-signal counter, or host dispatcher bookkeeping.
    std::memcpy(state.gregs, saved.gregs, sizeof(state.gregs));
    std::memcpy(state.flags, saved.flags, sizeof(state.flags));
    std::memcpy(&state.xmm, &saved.xmm, sizeof(state.xmm));
    std::memcpy(state.avx_high, saved.avx_high, sizeof(state.avx_high));
    std::memcpy(state.mm, saved.mm, sizeof(state.mm));
    state.rip = saved.rip;
    state.pf_raw = saved.pf_raw;
    state.af_raw = saved.af_raw;
    state.mxcsr = saved.mxcsr;
    state.FCW = saved.FCW;
    state.AbridgedFTW = saved.AbridgedFTW;
    state.callret_sp = saved.callret_sp;
    state.fs_cached = saved.fs_cached;
    state.gs_cached = saved.gs_cached;
    state.es_cached = saved.es_cached;
    state.cs_cached = saved.cs_cached;
    state.ss_cached = saved.ss_cached;
    state.ds_cached = saved.ds_cached;
    state.fs_idx = saved.fs_idx;
    state.gs_idx = saved.gs_idx;
    state.es_idx = saved.es_idx;
    state.cs_idx = saved.cs_idx;
    state.ss_idx = saved.ss_idx;
    state.ds_idx = saved.ds_idx;
}
} // namespace Core::Fex
