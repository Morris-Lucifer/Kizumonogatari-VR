// SPDX-License-Identifier: MIT
#include "fex_signal_context.h"
#include <cassert>
#include <iostream>

int main() {
    using namespace FEXCore::X86State;
    FEXCore::Core::CPUState interrupted;
    for (size_t i = 0; i < 16; ++i) interrupted.gregs[i] = 0x200001000 + i * 0x100;
    interrupted.rip = 0x808374350;
    interrupted.fs_cached = 0x201234000;
    interrupted.fs_idx = 0x43;
    interrupted.flags[3] = 9;
    interrupted.pf_raw = 0xab;
    interrupted.af_raw = 0xcd;
    interrupted.xmm.sse.data[7][0] = 0x12345678;
    interrupted.avx_high[12][1] = 0xaabbccdd;
    interrupted.mm[3][0] = 0x56473829;
    interrupted.mxcsr = 0x1fc0;
    interrupted.FCW = 0x37f;
    interrupted.AbridgedFTW = 0x55;
    interrupted.callret_sp = 0x456000;

    Libraries::Kernel::Ucontext ctx{};
    Core::Fex::FillSignalContext(ctx.uc_mcontext, interrupted, 0x29957f478, 0x202);
    // A collector examining the Orbis ABI sees every register-only root,
    // including the thread-start parameter held in r15 across sem_wait.
    const uint64_t roots[] = {ctx.uc_mcontext.mc_rax, ctx.uc_mcontext.mc_rcx,
        ctx.uc_mcontext.mc_rdx, ctx.uc_mcontext.mc_rbx, ctx.uc_mcontext.mc_rsp,
        ctx.uc_mcontext.mc_rbp, ctx.uc_mcontext.mc_rsi, ctx.uc_mcontext.mc_rdi,
        ctx.uc_mcontext.mc_r8, ctx.uc_mcontext.mc_r9, ctx.uc_mcontext.mc_r10,
        ctx.uc_mcontext.mc_r11, ctx.uc_mcontext.mc_r12, ctx.uc_mcontext.mc_r13,
        ctx.uc_mcontext.mc_r14, ctx.uc_mcontext.mc_r15};
    for (size_t i = 0; i < 16; ++i)
        assert(roots[i] == (i == REG_RSP ? 0x29957f478 : interrupted.gregs[i]));
    assert(reinterpret_cast<const unsigned char*>(&ctx.uc_mcontext.mc_rsp)
           - reinterpret_cast<const unsigned char*>(&ctx) == 0xf8);
    assert(ctx.uc_mcontext.mc_fs == 0x43 && ctx.uc_mcontext.mc_fsbase == 0x201234000);
    assert(ctx.uc_mcontext.mc_rip == interrupted.rip && ctx.uc_mcontext.mc_rflags == 0x202);

    FEXCore::Core::CPUState returned;
    returned.L1Pointer = 0x987654;
    returned.InlineJITBlockHeader = 0x765432;
    Core::Fex::RestoreSignalState(returned, interrupted);
    assert(!std::memcmp(returned.gregs, interrupted.gregs, sizeof(returned.gregs)));
    assert(!std::memcmp(returned.flags, interrupted.flags, sizeof(returned.flags)));
    assert(!std::memcmp(&returned.xmm, &interrupted.xmm, sizeof(returned.xmm)));
    assert(!std::memcmp(returned.avx_high, interrupted.avx_high, sizeof(returned.avx_high)));
    assert(!std::memcmp(returned.mm, interrupted.mm, sizeof(returned.mm)));
    assert(returned.pf_raw == 0xab && returned.af_raw == 0xcd);
    assert(returned.mxcsr == 0x1fc0 && returned.AbridgedFTW == 0x55);
    assert(returned.callret_sp == 0x456000 && returned.rip == interrupted.rip);
    assert(returned.L1Pointer == 0x987654 && returned.InlineJITBlockHeader == 0x765432);
    std::cout << "Signal roots, ABI offsets, state restoration, and host bookkeeping passed\n";
}
