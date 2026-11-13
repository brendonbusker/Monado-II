"""XCDE instruction patches (contract: docs/contracts/patch-format.md)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools", "lifter"))
from patchfmt import FunctionEntries, Patch  # noqa: E402,F401


# [XCDE] LINUX-041: the native bounded item-kind switch crosses generator
# partitions. Preserve all five legitimate native entries in dispatch; do not
# replace their code, change the BR, or redirect one kind through another case.
# The complete selected main build ID and dispatch/entry words fail closed.
FUNCTION_ENTRIES = (
    FunctionEntries(
        'main', '7e1df8e08d60544bbdca1e333c153c97',
        entries={
            0x7000183f4c: 0xb0005028,
            0x7000183f70: 0xb0005028,
            0x7000183f94: 0xb0005028,
            0x7000183fb8: 0xb0005028,
            0x7000183fdc: 0xb0005028,
        },
        guards={
            0x7000183f28: 0x7100101f,
            0x7000183f2c: 0x54000ec8,
            0x7000183f30: 0x2a0003e8,
            0x7000183f34: 0xd0004289,
            0x7000183f38: 0x910c9129,
            0x7000183f3c: 0x1000008a,
            0x7000183f40: 0x3868692b,
            0x7000183f44: 0x8b0b094a,
            0x7000183f48: 0xd61f0140,
        },
        req='LINUX-041', note='Native trade item-kind cases before partition discovery'),
)


def _hook_then_original(fn):
    """Call a runtime hook, then the original instruction (which must lift to plain C)."""
    def emit(gen, addr):
        ins = gen.lift(addr)
        if ins.kind != 'op':
            raise ValueError(f'{addr:#x}: hook patch needs a plain instruction, got {ins.kind}')
        return f'{{ extern void {fn}(void); {fn}(); }} {ins.code}'
    return emit


# T157: the game's frame limiter (nnMain+0x12150, f_70005bcfe0) busy-waits for the end of the 33.3 ms frame: a loop
# that reads the system tick through a vtable until enough time passed, no sleep (a dedicated core on the Switch). On
# PC that spin was ~0.3 of a core. Hooks: the loop head (sleep while the frame end is still far, runtime/hle/framepace.c)
# and the function's exit (a frame boundary: learns the frame interval).
PATCHES = {
    0x70005bd068: Patch(0x320003e0, _hook_then_original('xcde_limiter_spin'), 'T157', 'mov w0, #1 - limiter loop head'),
    0x70005bd168: Patch(0x6d4123e9, _hook_then_original('xcde_limiter_done'), 'T157', 'ldp d9, d8, [sp, #0x10] - limiter exit'),
}


# [XCDE] LINUX-011: the GUI update callback precedes animation traversal. Replace
# its fixed constructor timestep with the existing engine frame delta; leave the
# callback's registers/instruction and all GUI/node speed and pause logic intact.
# This is intentionally separate from world, skeletal and cutscene clocks.
def _gui_frame_delta(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'op':
        raise ValueError(f'{addr:#x}: GUI timing hook needs a plain instruction')
    return ('{ extern void xcde_gui_frame_delta(uint64_t gui); '
            'xcde_gui_frame_delta(c->x[0]); } ' + ins.code)


PATCHES[0x700074bfc0] = Patch(0xa9412001, _gui_frame_delta, 'LINUX-011',
                            'ldp x1, x8, [x0, #0x10] - GUI update entry')


# [XCDE] LINUX-012: all reference-period reads that advance held durations in
# the shared navigation updater. The repeat query already uses seconds; the
# original UpdateInfo+4 is a fixed 1/30 reference, not elapsed UpdateInfo+8.
# Retain the original load (including scalar upper-bit clearing), then replace
# just its result. No changes to raw input, edges, timer resets or repeat policy.
def _repeat_frame_delta(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'op':
        raise ValueError(f'{addr:#x}: repeat timing hook needs a plain instruction')
    return (ins.code + ' { extern uint32_t xcde_repeat_delta_bits(uint32_t reference); '
            'c->v[1] = xcde_repeat_delta_bits((uint32_t)c->v[1]); }')


REPEAT_STEP_SITES = (
    0x7000578ebc, 0x7000578eec, 0x7000578f18, 0x7000578f44, 0x7000578f70,
    0x7000578f9c, 0x7000578fc8, 0x7000578ff4, 0x7000579020, 0x700057904c,
    0x7000579078, 0x70005790a4, 0x70005790d0, 0x70005790fc, 0x7000579128,
    0x7000579154, 0x7000579180, 0x70005791ac, 0x70005791d8, 0x7000579204,
    0x7000579230, 0x700057925c, 0x7000579288, 0x70005792b4, 0x70005792e0,
    0x7000579308, 0x70005793b4,
)
for _site in REPEAT_STEP_SITES:
    PATCHES[_site] = Patch(0xbd400681, _repeat_frame_delta, 'LINUX-012',
                           'ldr s1, [x20, #4] - navigation held-duration step')


# [XCDE] LINUX-014: view-only navigation repeat preference. Keep the actual held
# timers in seconds; only these repeat consumers see an optional doubled view.
# Retain every scalar load and its upper-lane clearing, without changing raw
# input, non-repeat hold queries, or the shared shoulder/button repeat branches.
def _navigation_duration(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'op':
        raise ValueError(f'{addr:#x}: navigation repeat view needs a scalar load')
    reg = gen.word(addr) & 31
    return (ins.code + ' { extern uint32_t xcde_navigation_duration_bits(uint32_t duration); '
            f'c->v[{reg}] = xcde_navigation_duration_bits((uint32_t)c->v[{reg}]); }}')


NAVIGATION_DURATION_SITES = {
    0x7000164978: 0xbd4017e0, 0x7000164a18: 0xbd401be3,
    0x70001c22fc: 0xbd40e100, 0x70001c232c: 0xbd40e121,
    0x70001c23b4: 0xbd40d900, 0x70001c23e4: 0xbd40d921,
    0x70001c24bc: 0xbd409540, 0x70001c24d8: 0xbd409503,
    0x70001c2524: 0xbd408940, 0x70001c2540: 0xbd408903,
    0x70001c25b0: 0xbd409140, 0x70001c25cc: 0xbd409103,
    0x70001c2784: 0xbd408d40, 0x70001c27a0: 0xbd408d03,
}
for _site, _word in NAVIGATION_DURATION_SITES.items():
    PATCHES[_site] = Patch(_word, _navigation_duration, 'LINUX-014',
                           'scalar held-duration view - optional faster menu/arts navigation repeat')


# [XCDE] LINUX-013: passive, bounded developer diagnostics. The runtime helper
# is disabled unless built with --foley-trace; every original instruction runs.
def _foley_trace(kind):
    def emit(gen, addr):
        ins = gen.lift(addr)
        if ins.kind != 'op':
            raise ValueError(f'{addr:#x}: foley trace needs a plain instruction')
        return ('{ extern void xcde_foley_trace(Cpu *c, uint32_t kind); '
                f'xcde_foley_trace(c, {kind}); }} ' + ins.code)
    return emit


FOLEY_TRACE_SITES = {
    0x70003f4b90: (0x320007e8, 0, 'accepted effect marker'),
    0x70003f4c24: (0x320007e8, 1, 'accepted alternate effect marker'),
    0x7000466210: (0x6b18011f, 2, 'contact prior/current comparison'),
    0x7000482528: (0x2a0103f4, 3, 'terrain sound request'),
    0x70004822ec: (0xaa0103f3, 4, 'authored sound request'),
    0x70003f3048: (0x2a0103f4, 5, 'animation reset request'),
}
for _site, (_word, _kind, _note) in FOLEY_TRACE_SITES.items():
    PATCHES[_site] = Patch(_word, _foley_trace(_kind), 'LINUX-013', _note)


# [XCDE] LINUX-013: retain the phase-alignment seek and its exact guest-call
# effects, then synchronize the loop detector's previous-time clock origin.
# Ordinary seeks, transitions, sound/effect dispatch and genuine wraps retain
# their existing behavior. Capture arguments before the original call clobbers
# caller-saved registers. This callsite always seeks the base layer (x1 = 0).
def _animation_phase_rebase(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'bl' or ins.target != 0x70003f0740:
        raise ValueError(f'{addr:#x}: phase alignment needs the original animation seek call')
    return ('{ uint64_t animation_ = c->x[0]; uint32_t layer_ = (uint32_t)c->x[1]; '
            'extern void xcde_animation_phase_rebase(uint64_t animation, uint32_t layer); '
            'extern void f_70003f0740(Cpu *c); '
            'c->x[30] = 0x70003f446cull; f_70003f0740(c); '
            'xcde_animation_phase_rebase(animation_, layer_); }')


PATCHES[0x70003f4468] = Patch(0x97fff0b6, _animation_phase_rebase, 'LINUX-013',
                            'bl animation seek - rebase previous cursor after phase-preserving clip change')


# T210 (party mod session): frame-count thresholds at the game's own 30 fps above 30 fps (runtime/hle/party.c
# xcde_frames_gt: "more than n frames at 30 fps" -> the same time at the current frame rate). A field follower restarts
# its "follow while running" move once its movement component (+0x200) counted more than 9 frames of a condition; at
# 60 fps that happened every ~11 frames and the party fell behind walking (2 -> 17.5 m in 200 frames; 30 fps: a steady
# 6.5 m). Both checks of that counter (f_7000443760, f_70004439f0) are `cmp w8, #9`.
def _frames_gt(n):
    def emit(gen, addr):
        return ('{ extern uint32_t xcde_frames_gt(uint32_t n); '
                f'(void)(subs32(c, (uint32_t)c->x[8], xcde_frames_gt({n}))); }}')
    return emit


PATCHES[0x700044394c] = Patch(0x7100251f, _frames_gt(9), 'T210', 'cmp w8, #9 - follower move counter (f_7000443760)')
PATCHES[0x7000443b9c] = Patch(0x7100251f, _frames_gt(9), 'T210', 'cmp w8, #9 - follower move counter (f_70004439f0)')


# [XCDE] LINUX-013: the walk/run hysteresis predicate uses the SAME movement
# counter as T210, but its complementary <10 check was still unscaled. At high
# FPS it rejected running before the scaled >9 checks, forcing walk/run changes
# and their outgoing footstep-event flushes. Match the existing dynamic window:
# count < 10*k complements count > 10*k-1, including the exact native30 boundary.
def _locomotion_frames_lt(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'op':
        raise ValueError(f'{addr:#x}: locomotion counter needs a plain compare')
    return ('{ extern uint32_t xcde_frames_gt(uint32_t n); '
            '(void)subs32(c, (uint32_t)c->x[8], xcde_frames_gt(9) + 1u); }')


PATCHES[0x700045b370] = Patch(0x7100291f, _locomotion_frames_lt, 'LINUX-013',
                            'cmp w8, #10 - keep walk/run hysteresis in the T210 movement-counter window')


# T222 (party mod session): save / load list thumbnails. f_700057da00 copies a slot's loaded .tmb picture (320x180 RGB)
# into the buffer it maps (bl memcpy at 0x700057dab4: x0 destination, x1 source, x2 size) - only one of the slot's two
# alternating picture buffers. The hook records which buffer holds the game's own picture (runtime/nvn/vulkan/exec.c
# slot_thumb_fix copies it into the twin): the twin is not always empty - in-game its memory held leftovers, shown
# every other frame as pink / green garbage.
def _thumb_loaded(gen, addr):
    return ('c->x[30] = 0x700057dab8ull; { extern void xcde_thumb_loaded(uint64_t d, uint64_t n); '
            'uint64_t d_ = c->x[0], n_ = c->x[2]; f_70008b6b48(c); xcde_thumb_loaded(d_, n_); }')


PATCHES[0x700057dab4] = Patch(0x940ce425, _thumb_loaded, 'T222', 'bl memcpy - slot thumbnail picture loaded (f_700057da00)')


# [XCDE] LINUX-033: use the title controller's preallocated rows and native
# confirmation, retaining the game's own rendering, navigation and cleanup.
# These hooks describe the checked DE 2.0.0 ABI, not distributed game UI assets.
def _title_plain(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'op':
        raise ValueError(f'{addr:#x}: title hook requires a plain instruction')
    return ins.code


def _title_rows(gen, addr):
    original = _title_plain(gen, addr)
    return ('{ extern _Bool xcde_title_exit_configure(uint64_t ui); '
            'if (c->x[24] == 0) (void)xcde_title_exit_configure(c->x[19]); } ' + original)


def _title_render_action(gen, addr):
    original = _title_plain(gen, addr)
    return (original + ' { extern _Bool xcde_title_exit_row_is_exit(uint64_t ui, uint64_t row); '
            'if ((uint32_t)c->x[8] == 7 && xcde_title_exit_row_is_exit(c->x[19], c->x[25])) '
            'c->x[8] = 4; }')


def _title_label(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'bl' or ins.target != 0x700057c160:
        raise ValueError(f'{addr:#x}: title label requires the original native text setter')
    return ('{ extern _Bool xcde_title_exit_label(Cpu *c); '
            'extern void f_700057c160(Cpu *c); c->x[30] = 0x7000297c84ull; '
            'if (!xcde_title_exit_label(c)) f_700057c160(c); }')


def _title_confirm_action(gen, addr):
    original = _title_plain(gen, addr)
    return ('{ extern uint32_t xcde_title_exit_action(uint64_t sequence, uint32_t action); '
            'c->x[0] = xcde_title_exit_action(c->x[19], (uint32_t)c->x[0]); } ' + original)


def _title_force_prompt(gen, addr):
    original = _title_plain(gen, addr)
    return (original + ' { extern _Bool xcde_title_exit_pending(uint64_t sequence); '
            'if (xcde_title_exit_pending(c->x[19])) goto L_xcde_title_exit_prompt; }')


def _title_prompt_label(gen, addr):
    return 'L_xcde_title_exit_prompt:; ' + _title_plain(gen, addr)


def _title_dialog_text(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'bl' or ins.target != 0x70000f4520:
        raise ValueError(f'{addr:#x}: title confirmation requires the original native dialog call')
    return ('{ extern void xcde_title_exit_dialog(Cpu *c); '
            'extern void f_70000f4520(Cpu *c); c->x[30] = 0x70003c4ffcull; '
            'xcde_title_exit_dialog(c); f_70000f4520(c); }')


def _title_dialog_reply(gen, addr):
    original = _title_plain(gen, addr)
    return ('{ extern _Bool xcde_title_exit_reply(Cpu *c); '
            'if (xcde_title_exit_reply(c)) return; } ' + original)


def _title_dispatch_guard(gen, addr):
    original = _title_plain(gen, addr)
    return ('{ extern void xcde_title_exit_check_dispatch(uint64_t sequence, uint32_t action); '
            'xcde_title_exit_check_dispatch(c->x[19], (uint32_t)c->x[0]); } ' + original)


TITLE_EXIT_PATCHES = {
    0x70002979f8: (0xb8787b56, _title_rows, 'first native row-label iteration; insert into verified spare capacity'),
    0x7000297a50: (0xb9400328, _title_render_action, 'native label-render action; preserve stored Exit action'),
    0x7000297c80: (0x940b9138, _title_label, 'native row text setter; authored Exit label'),
    0x70003c48e0: (0x7100181f, _title_confirm_action, 'confirmed selection; enter existing native confirmation route'),
    0x70003c4be4: (0xaa0003f3, _title_force_prompt, 'checked title owner; Exit always asks, including Future Connected'),
    0x70003c4c54: (0x12800014, _title_prompt_label, 'native confirmation construction after original bypass conditions'),
    0x70003c4ff8: (0x97f4bd4a, _title_dialog_text, 'native dialog call; authored prompt with original localized choices'),
    0x70003c5ef0: (0xf9400408, _title_dialog_reply, 'native reply entry; ordinary Cancel bookkeeping then host exit on Yes'),
    0x70003c5248: (0x7100181f, _title_dispatch_guard, 'native action dispatch; Exit must not become a story-mode transition'),
}
for _site, (_word, _emit, _note) in TITLE_EXIT_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-033', _note)


# [XCDE] LINUX-033 r2: preserve all six System rows and attach the resource's
# unused seventh native widget. The authored helper owns extended guest storage;
# the original controller still owns selection, enabled permissions and cleanup.
def _system_prefix(helper, returns=False):
    def emit(gen, addr):
        original = _title_plain(gen, addr)
        if returns:
            return (f'{{ extern _Bool {helper}(Cpu *c); '
                    f'if ({helper}(c)) return; }} ' + original)
        return f'{{ extern void {helper}(Cpu *c); {helper}(c); }} ' + original
    return emit


def _system_call(gen, addr, target):
    ins = gen.lift(addr)
    if ins.kind != 'bl' or ins.target != target:
        raise ValueError(f'{addr:#x}: System hook requires its checked native call')
    return (f'extern void f_{target:x}(Cpu *c); '
            f'c->x[30] = 0x{addr + 4:x}ull; f_{target:x}(c); ')


def _system_construct(gen, addr):
    _system_call(gen, addr, 0x7000293c00)
    return ('{ extern void xcde_system_exit_construct(Cpu *c); '
            f'c->x[30] = 0x{addr + 4:x}ull; xcde_system_exit_construct(c); }}')


def _system_action(gen, addr):
    original = _system_call(gen, addr, 0x7000294680)
    return ('{ ' + original + 'extern uint32_t xcde_system_exit_action(uint64_t sequence, uint32_t action); '
            'c->x[0] = xcde_system_exit_action(c->x[19], (uint32_t)c->x[0]); }')


def _system_child(gen, addr):
    original = _system_call(gen, addr, 0x70002ef680)
    return ('{ ' + original + 'extern void xcde_system_exit_child(Cpu *c); '
            'xcde_system_exit_child(c); }')


def _system_dialog(gen, addr):
    original = _system_call(gen, addr, 0x7000331840)
    return ('{ extern void xcde_system_exit_dialog(Cpu *c); '
            'xcde_system_exit_dialog(c); ' + original + '}')


SYSTEM_EXIT_PATCHES = {
    0x70003b570c: (0x97fb793d, _system_construct, 'native System constructor; separate extended guest storage with seventh widget'),
    0x70002941e0: (0xf81e0ff3, _system_prefix('xcde_system_exit_destroy'), 'native System destructor; release seventh widget before original six'),
    0x7000294690: (0xa9be4ff4, _system_prefix('xcde_system_exit_update'), 'native System frame update; update seventh widget and mirror Title Screen permission'),
    0x7000294070: (0xd10103ff, _system_prefix('xcde_system_exit_help', True), 'native help setter; authored Exit help only when seventh row is selected'),
    0x7000294680: (0xb9402808, _system_prefix('xcde_system_exit_selected', True), 'native selected row getter; accept verified seventh row'),
    0x70003b5a18: (0x97fb7b1a, _system_action, 'confirmed System selection; route Exit through native Title Screen confirmation'),
    0x70003b5a48: (0x97fb7b0e, _system_action, 'native System action validation; temporary Exit action alias'),
    0x70003b5aac: (0x97fb7af5, _system_action, 'native System dispatch; retain original Title Screen enabled check'),
    0x70003b5d0c: (0x97fce65d, _system_child, 'native Title Screen confirmation child; bind pending Exit owner'),
    0x70003b6138: (0x97fdedc2, _system_dialog, 'native System confirmation; authored prompt, default No and bound Exit caption'),
    0x70003b6350: (0xf9400408, _system_prefix('xcde_system_exit_reply', True), 'native System confirmation reply; Cancel bookkeeping before host exit'),
    0x70002f1e08: (0x910043e0, _system_prefix('xcde_exit_caption_render'), 'native MsgInfo UI post-build; caption only the bound Exit confirmation'),
}
for _site, (_word, _emit, _note) in SYSTEM_EXIT_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-033', _note)


# [XCDE] LINUX-035: keep the native four-card viewport and async job identities;
# expand only logical metadata and the separately appended CPU thumbnail arena.
# Every ABI anchor is checked against the selected DE 2.0.0 input by Patch.
def _save_constant(register, value):
    def emit(gen, addr):
        _title_plain(gen, addr)
        return f'c->x[{register}] = {value}u;'
    return emit


def _save_prefix(helper, argument):
    def emit(gen, addr):
        original = _title_plain(gen, addr)
        parameter = 'Cpu *c' if argument == 'c' else 'uint64_t state'
        return (f'{{ extern void {helper}({parameter}); {helper}({argument}); }} '
                + original)
    return emit


def _save_initialize(gen, addr):
    _title_plain(gen, addr)
    return ('{ extern void xcde_expanded_saves_initialize(Cpu *c); '
            'xcde_expanded_saves_initialize(c); }')


def _save_legacy(helper, target):
    def emit(gen, addr):
        ins = gen.lift(addr)
        if ins.kind != 'bl' or ins.target != target:
            raise ValueError(f'{addr:#x}: expanded saves need the checked native slot helper')
        return (f'{{ extern void {helper}(Cpu *c); '
                f'c->x[30] = 0x{addr + 4:x}ull; {helper}(c); }}')
    return emit


def _save_auto_image(gen, addr):
    _title_plain(gen, addr)
    word = gen.word(addr)
    destination, source = word & 31, (word >> 5) & 31
    return f'c->x[{destination}] = (uint32_t)((uint32_t)c->x[{source}] + 99u);'


def _save_initial_max(gen, addr):
    _title_plain(gen, addr)
    return '(void)subs32(c, (uint32_t)c->x[20], 99u);'


EXPANDED_SAVE_PATCHES = {
    0x7000282ddc: (0x528e2a00, _save_constant(0, 0x1d50), 'extended native state allocation, low half'),
    0x7000282de0: (0x72a00b00, _save_constant(0, 0x1601d50), 'extended native state allocation, complete size'),
    0x70002836f0: (0x321e03e9, _save_constant(9, 100), '100 logical records; four visible cards stay unchanged'),
    0x7000283704: (0xaa1303e1, _save_initialize, 'initialize additional empty records and supply real record sort end'),
    0x70002822e0: (0xd100c3ff, _save_prefix('xcde_expanded_saves_forget', 'c->x[0]'), 'native state destructor; drop live ownership before free'),
    0x70002839e0: (0xb940a800, _save_prefix('xcde_expanded_saves_capture', 'c'), 'confirmed Save/Load selection; remember its stable logical identity'),
    0x700028286c: (0x97f7fc45, _save_legacy('xcde_expanded_saves_legacy_set', 0x7000081980), 'preserve original serialized slot nibble and neighboring flags'),
    0x7000396f18: (0x97f3aaae, _save_legacy('xcde_expanded_saves_default', 0x70000819d0), 'save dialog default; session extended selection or vanilla nibble'),
    0x7000396f80: (0x71000e9f, _save_initial_max, 'native default selection upper clamp is logical99'),
    0x7000396f84: (0x320007e9, _save_constant(9, 99), 'native default selection maximum is logical99'),
}

# [XCDE] LINUX-035: all seven old thumbnail-base constructions, including native
# constructor/reset fills, I/O destinations, missing images and visible binding.
for _low, _register in ((0x70002821ac, 8), (0x70002827dc, 9),
                        (0x70002829e4, 10), (0x7000282ab4, 9),
                        (0x7000283390, 10), (0x70002834f4, 8),
                        (0x70002835d4, 8)):
    EXPANDED_SAVE_PATCHES[_low] = (0x52886500 | _register,
                                  _save_constant(_register, 0x7150), 'relocated thumbnail base, low half')
    EXPANDED_SAVE_PATCHES[_low + 4] = (0x72a002a0 | _register,
                                      _save_constant(_register, 0x587150), 'relocated appended thumbnail base')

# [XCDE] LINUX-035: exactly the three whole-arena fills. Per-thumbnail transfer
# and fallback fill sizes remain the original 320*180*3 bytes.
for _low in (0x70002821b8, 0x70002834d4, 0x70002835b0):
    EXPANDED_SAVE_PATCHES[_low] = (0x52918002, _save_constant(2, 0xac00), '100-thumbnail arena fill, low half')
    EXPANDED_SAVE_PATCHES[_low + 4] = (0x72a00142, _save_constant(2, 0x107ac00), '100-thumbnail arena fill extent')

# [XCDE] LINUX-035: autosave remains logical row0 and filename00a; only its
# independent CPU picture-buffer index moves after the99 manual pictures.
for _site, _word in ((0x70002827c8, 0x11000d2a), (0x70002829d4, 0x11000d09),
                     (0x7000282a9c, 0x11000d2a), (0x7000283384, 0x11000d48)):
    EXPANDED_SAVE_PATCHES[_site] = (_word, _save_auto_image, 'autosave image follows99 manual thumbnail buffers')

for _site, (_word, _emit, _note) in EXPANDED_SAVE_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-035', _note)


# [XCDE] LINUX-035: title Continue and title-feature presence use separate native
# four-slot scanners. The adapter scans extra IDs through their existing async
# reader, with one stable job identity and one retained winning payload.
def _save_scan_hook(helper, argument, after=False):
    def emit(gen, addr):
        ins = gen.lift(addr)
        if ins.kind == 'bl':
            original = _system_call(gen, addr, ins.target)
        elif ins.kind == 'op':
            original = ins.code
        else:
            raise ValueError(f'{addr:#x}: expanded save scanner needs an instruction or native call')
        parameter = 'Cpu *c' if argument == 'c' else 'uint64_t owner'
        hook = f'{{ extern void {helper}({parameter}); {helper}({argument}); }} '
        return original + hook if after else hook + original
    return emit


def _save_scan_wait(gen, addr):
    original = _title_plain(gen, addr)
    return ('{ extern _Bool xcde_expanded_scan_continue_wait(Cpu *c); '
            'if (xcde_expanded_scan_continue_wait(c)) goto L_700039a0e0; } ' + original)


EXPANDED_SAVE_SCAN_PATCHES = {
    0x7000399d90: (0xd10103ff, _save_scan_hook('xcde_expanded_scan_continue_begin', 'c->x[0]'),
                   'Continue scan begins; bind the native reader owner'),
    0x7000399b20: (0xa9be4ff4, _save_scan_hook('xcde_expanded_scan_continue_drop', 'c->x[0]'),
                   'Continue owner cleanup; release retained extended winner'),
    0x7000399d30: (0xa9be4ff4, _save_scan_hook('xcde_expanded_scan_continue_drop', 'c->x[0]'),
                   'Continue owner destructor; release retained extended winner'),
    0x7000399f78: (0x39426268, _save_scan_wait,
                   'wait for serial extended reads before choosing Continue payload'),
    0x700039a048: (0xb82a6928, _save_scan_hook('xcde_expanded_scan_continue_selected', 'c', after=True),
                   'confirmed Continue selection; preserve full logical identity'),
    0x70003c3c8c: (0x97fffafd, _save_legacy('xcde_expanded_scan_presence', 0x70003c2880),
                   'title presence checker; aggregate extended main and Future Connected saves'),
    0x70003c2de0: (0xa9be4ff4, _save_scan_hook('xcde_expanded_scan_presence_drop', 'LD64(c->x[0] + 0x278)'),
                   'title owner destructor; remove checker ownership'),
    0x70003c2d94: (0x97f2c6bf, _save_scan_hook('xcde_expanded_scan_presence_drop', 'c->x[21]'),
                   'title checker replacement; drop old ownership before native free'),
    0x70003c31fc: (0x52880788, _save_scan_hook('xcde_expanded_scan_presence_reset', 'c->x[21]'),
                   'title recheck; drain any pending extended read before native reuse'),
}
for _site, (_word, _emit, _note) in EXPANDED_SAVE_SCAN_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-035', _note)


# [XCDE] LINUX-036: preserve the original update and its caller CPU results;
# only afterwards permit bounded extra cold metadata transitions. Rendering,
# thumbnail reads, writes and ordinary gameplay retain their native cadence.
def _save_metadata_pump(gen, addr):
    original = _system_call(gen, addr, 0x70002823a0)
    return ('{ uint64_t scan_ui_ = c->x[19], scan_state_ = c->x[0]; '
            + original +
            'extern void xcde_expanded_saves_pump(Cpu *c, uint64_t ui, uint64_t state); '
            'xcde_expanded_saves_pump(c, scan_ui_, scan_state_); }')


PATCHES[0x7000283200] = Patch(0x97fffc68, _save_metadata_pump, 'LINUX-036',
                            'native UI metadata update; original call then bounded owned cold-read work')


# [XCDE] LINUX-040: independently owned native Quick Step control and filtered
# native picker. The original six/eight/six indices and ordinary sockets stay intact.
def _quickstep_prefix(helper, parameter='Cpu *c', argument='c'):
    def emit(gen, addr):
        ins = gen.lift(addr)
        prefix = f'{{ extern void {helper}({parameter}); {helper}({argument}); }} '
        if ins.kind == 'op':
            return prefix + ins.code
        if ins.kind == 'bcond' and isinstance(ins.target, int):
            # Retain the original conditional branch and its already-discovered
            # native label; no return value or native success path is replaced.
            return prefix + f'if ({ins.cond}) goto L_{ins.target:x};'
        raise ValueError(f'{addr:#x}: Quick Step hook requires a plain/conditional instruction')
    return emit


def _quickstep_construct(gen, addr):
    original = _title_plain(gen, addr)
    return (original + ' { extern void quickstep_native_construct(Cpu *c); '
            'quickstep_native_construct(c); }')


def _quickstep_row_style(gen, addr):
    # Keep the genuine row's disabled-style call and link register. Only an
    # exactly owned eligible bonus row may replace its disabled W1 argument.
    original = _system_call(gen, addr, 0x700020b070)
    return ('{ extern void quickstep_native_picker_row_style(Cpu *c); '
            'quickstep_native_picker_row_style(c); ' + original + '}')


def _quickstep_background(gen, addr):
    original = _title_plain(gen, addr)
    # Only the private cloned row's baked wide background is omitted. Keep the
    # common native mask-release/frame cleanup; its caller draws child nodes.
    return ('{ extern _Bool quickstep_native_filter_background(Cpu *c); '
            'if (quickstep_native_filter_background(c)) goto L_700075e99c; } '
            + original)


def _quickstep_chain(*helpers):
    def emit(gen, addr):
        original = _title_plain(gen, addr)
        calls = ' '.join(f'{{ extern void {helper}(Cpu *c); {helper}(c); }}'
                         for helper in helpers)
        return calls + ' ' + original
    return emit


def _quickstep_input(gen, addr):
    original = _title_plain(gen, addr)
    # This is inside a live native stack frame, after child consumers declined.
    # Follow the native handled epilogue; a C return would strand its guest frame.
    return ('{ extern _Bool quickstep_native_input_event(Cpu *c); '
            'if (quickstep_native_input_event(c)) goto L_70002f9430; } ' + original)


def _quickstep_handled(helper):
    def emit(gen, addr):
        # These hooks are exclusively function entries, before frame allocation.
        original = _title_plain(gen, addr)
        return (f'{{ extern _Bool {helper}(Cpu *c); '
                f'if ({helper}(c)) return; }} ' + original)
    return emit


def _quickstep_picker_cancel(gen, addr):
    original = _title_plain(gen, addr)
    # Bounds belong to the runtime adapter: generated C intentionally includes
    # only the CPU contract, not host/HLE address-space policy definitions.
    return ('{ extern void quickstep_native_picker_cancel_callback(Cpu *c); '
            'quickstep_native_picker_cancel_callback(c); } ' + original)


def _quickstep_picker_closed(gen, addr):
    ins = gen.lift(addr)
    if ins.kind != 'b' or ins.target != 0x70002fea30:
        raise ValueError(f'{addr:#x}: Quick Step close requires its native tail call')
    # The native frame is already restored. Keep LR from its caller unchanged.
    return ('{ extern void quickstep_native_picker_closed(Cpu *c); '
            'quickstep_native_picker_closed(c); } '
            'extern void f_70002fea30(Cpu *c); f_70002fea30(c); return;')


QUICKSTEP_PATCHES = {
    0x70002f67f4: (0xf90e2674, _quickstep_construct, 'publish checked native equipment UI owner'),
    0x7000208d30: (0xf81e0ff3, _quickstep_chain('quickstep_native_tick', 'quickstep_stats_ui_tick'), 'native equipment update then owned effect-row layout/lifetime'),
    0x7000208530: (0xf81e0ff3, _quickstep_chain('quickstep_stats_ui_release_ui', 'quickstep_native_release'), 'release extra effect row before equipment owner destruction'),
    0x7000208590: (0xf81e0ff3, _quickstep_chain('quickstep_stats_ui_release_ui', 'quickstep_native_release'), 'idempotent extra-row cleanup before deleting equipment owner'),
    0x70002f6130: (0xf81b0ff9, _quickstep_chain('quickstep_stats_ui_release_sequence', 'quickstep_native_release_sequence'), 'restore native row vector before sequence resources/owner destruction'),
    0x70002f87ac: (0xb9400288, _quickstep_input, 'bonus control input after native child consumers; native handled epilogue'),
    0x7000183a60: (0xb94fb808, _quickstep_prefix('quickstep_native_picker_filter'), 'owned bonus list filter before native sorts and category rebuilds'),
    0x7000241b40: (0xb9002001, _quickstep_prefix('quickstep_native_picker_count'), 'native bonus row count and genuine No data state'),
    0x7000316604: (0x97fbd29b, _quickstep_row_style, 'owned bonus gem row styling independent of ordinary boot socket eligibility'),
    0x7000232e2c: (0x2a0003f4, _quickstep_prefix('quickstep_slot_native_marker'), 'LINUX-044 display-only native E state for validated bonus ownership; retain original row status move'),
    0x7000237898: (0xb943be68, _quickstep_prefix('quickstep_slot_native_portrait_owner'), 'LINUX-044 R2 display-only portrait owner after native lookup; retain native field load'),
    0x70002378d0: (0x6b00035f, _quickstep_prefix('quickstep_slot_native_portrait_owner'), 'LINUX-044 R2 gem portrait E compares genuine portrait character with validated bonus owner'),
    0x7000237940: (0x6b00035f, _quickstep_prefix('quickstep_slot_native_portrait_owner'), 'LINUX-044 R2 alternate portrait path retains original character comparison'),
    0x70002fa178: (0xf941f7e8, _quickstep_prefix('quickstep_native_picker_menu_item'), 'bonus Remove eligibility after native ordinary-socket checks; retain original load'),
    0x70002f8cd8: (0x37003ac0, _quickstep_prefix('quickstep_native_picker_menu_gate'), 'active bonus context menu ignores ordinary parent socket restriction; retain native branch'),
    0x70002f9970: (0x910b63e9, _quickstep_prefix('quickstep_native_picker_menu_item'), 'active-list bonus Remove item flag; retain native item pointer calculation'),
    0x70002f9a3c: (0x910a43e0, _quickstep_prefix('quickstep_native_picker_menu_opened'), 'bind exact completed native bonus context popup before restoring caller stack'),
    0x700075e868: (0xf941d268, _quickstep_background, 'private bonus row baked background only; native cleanup and child drawing retained'),
    0x7000302640: (0xd10643ff, _quickstep_handled('quickstep_native_picker_confirm'), 'bonus selection before native detach or staged socket writes'),
    0x70003020d0: (0xf81d0ff5, _quickstep_handled('quickstep_native_picker_remove'), 'remove exact owned bonus association only'),
    0x70003004e0: (0xf81d0ff5, _quickstep_handled('quickstep_native_picker_uid'), 'bonus UID for native selected-item actions'),
    0x70002ff870: (0xf81c0ffc, _quickstep_handled('quickstep_native_picker_details'), 'native gem details and comparison for actual bonus item'),
    0x70002fae60: (0xd10103ff, _quickstep_handled('quickstep_native_picker_preview'), 'bonus picker does not preview ordinary boots socket replacement'),
    0x70002fe000: (0xa9bb67fc, _quickstep_handled('quickstep_native_picker_commit'), 'suppress ordinary equipment commit while bonus picker owns selection'),
    0x70002ff5fc: (0x17fffd0d, _quickstep_picker_closed, 'restore original native pane before close tail call'),
    0x70002ffd90: (0x52914288, _quickstep_handled('quickstep_native_picker_eligible'), 'bonus-only native Remove eligibility; other queries unchanged'),
    0x70003035d0: (0xd10603ff, _quickstep_handled('quickstep_native_picker_submenu'), 'bonus Remove and safe handling of ordinary bulk/swap actions'),
    0x7000303270: (0xa9bd57f6, _quickstep_picker_cancel, 'cancel bonus picker before native character change and ordinary commit'),
    0x70003022b0: (0xa9bd57f6, _quickstep_picker_cancel, 'cancel bonus picker before native pane change'),
    0x700008c2bc: (0x710002bf, _quickstep_prefix('quickstep_slot_effects'), 'append owned Quick Step before native effect merge/caps'),
    0x700008c2e8: (0x3600031c, _quickstep_prefix('quickstep_slot_effects_end'), 'release effect scratch after native apply; retain original branch'),
    0x700008d57c: (0x910903ff, _quickstep_prefix('quickstep_slot_effects_finish'), 'final stats epilogue; repair playing effects after a temporary calculation'),
    # [XCDE] LINUX-040: BDEE0 changes favourite, not equipped ownership.
    # Intercept the actual accepted socket write, after all native reject paths.
    0x700017b81c: (0xb8296913, _quickstep_prefix('quickstep_slot_native_equip'), 'actual ordinary gem socket write clears matching bonus; retain native store'),
    0x70000bdf40: (0xd100c3ff, _quickstep_prefix('quickstep_slot_native_consume'), 'ordinary quantity use retains native behavior and clears matching bonus'),
    0x700009bbd0: (0xb40001e1, _quickstep_prefix('quickstep_slot_native_destroy'), 'actual item destruction clears matching bonus; retain null branch'),
}
for _site, (_word, _emit, _note) in QUICKSTEP_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-040', _note)


# [XCDE] LINUX-039: native payloads remain unchanged; optional character-slot
# metadata binds to exact serialized bytes and confirmed load intent.
_QUICKSTEP_CONTINUE_BASE = PATCHES[0x700039a048].emit


def _quickstep_continue_intent(gen, addr):
    return (_QUICKSTEP_CONTINUE_BASE(gen, addr)
            + ' { extern void quickstep_save_continue_intent(Cpu *c); '
            'quickstep_save_continue_intent(c); }')


QUICKSTEP_SAVE_PATCHES = {
    0x70000af760: (0xd10203ff, _quickstep_prefix('quickstep_save_serializing'), 'reconcile active character references before actual save serialization'),
    0x70000afa80: (0xfd400be8, _quickstep_prefix('quickstep_save_serialized'), 'bind optional metadata to completed native serialized payload'),
    0x70000afe10: (0xd102c3ff, _quickstep_prefix('quickstep_save_loading', 'void', ''), 'suspend old character references before actual playing-data load'),
    0x70000afe60: (0x910043e0, _quickstep_prefix('quickstep_save_adopt'), 'adopt only confirmed native playing-data decode'),
    0x700054df24: (0xa9497bfd, _quickstep_prefix('quickstep_save_loaded'), 'reconcile only after native story finalization'),
    0x7000087040: (0xd10503ff, _quickstep_prefix('quickstep_save_read_intent'), 'LINUX-044 actual native save read entry covers all Load and Continue callers; retain native stack frame'),
    0x70005c4234: (0xb9402a88, _quickstep_prefix('quickstep_save_header_copy'), 'LINUX-044 R2 bind actual split-read header copy to raw buffer; retain original loader field load'),
    0x700039a424: (0xaa1303e0, _quickstep_prefix('quickstep_save_cache_copy'), 'LINUX-044 R2 preserve validated save provenance after completed typed cache copy'),
    0x70003992b4: (0xb9400a68, _quickstep_prefix('quickstep_save_selected_copy'), 'LINUX-044 R2 preserve exact selected save provenance after typed constructor copy'),
    0x700039a048: (0xb82a6928, _quickstep_continue_intent, 'confirmed Continue; compose after extended-slot logical correction'),
    0x70000adcc0: (0xd10243ff, _quickstep_prefix('quickstep_save_newgame_begin'), 'actual New Game reset; suspend old references and load intent'),
    0x70000ae860: (0xa9487bfd, _quickstep_prefix('quickstep_save_newgame_end'), 'actual New Game completion; adopt empty slot state after story setup'),
}
for _site, (_word, _emit, _note) in QUICKSTEP_SAVE_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-039', _note)


# [XCDE] LINUX-040 r3: the native summaries have eight fixed records, while
# their renderer supports eleven lines. Supply an independently owned extra
# row at its local-copy boundary, never beyond the original summary allocation.
def _quickstep_stats_count(gen, addr):
    original = _title_plain(gen, addr)
    return (original + ' { extern void quickstep_stats_count(Cpu *c); '
            'quickstep_stats_count(c); }')


def _quickstep_stats_row(gen, addr):
    original = _title_plain(gen, addr)
    return ('{ extern int quickstep_stats_row(Cpu *c); '
            'int row_ = quickstep_stats_row(c); '
            'if (row_ > 0) goto L_70002393cc; '
            'if (row_ < 0) goto L_7000239508; } ' + original)


def _quickstep_stats_resume(gen, addr):
    # This address is not an original branch target, so its C label must be
    # explicit. The stale-frame path uses the original native cleanup label.
    return 'L_70002393cc:; ' + _title_plain(gen, addr)


QUICKSTEP_STATS_PATCHES = {
    0x70002391f0: (0xfc190fe8, _quickstep_prefix('quickstep_stats_begin'),
                   'capture exact owned equipment summary before native frame allocation'),
    0x70002393a4: (0xf940baa8, _quickstep_stats_count,
                   'original bounded count then owned virtual ninth-row count'),
    0x70002393b0: (0x52800508, _quickstep_stats_row,
                   'owned local summary copy or original copy; stale lease uses native cleanup'),
    0x70002393cc: (0xf940bac9, _quickstep_stats_resume,
                   'explicit local-row resume label, retaining original baseline count load'),
    0x7000239420: (0x3945c3e8, _quickstep_prefix('quickstep_stats_compare'),
                   'bonus-aware native comparison flags, retaining native type load'),
    0x70002395d8: (0x910903ff, _quickstep_prefix('quickstep_stats_end'),
                   'release owned summary lease before native frame restoration'),
}
for _site, (_word, _emit, _note) in QUICKSTEP_STATS_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-040', _note)


QUICKSTEP_STATS_UI_PATCHES = {
    0x700023e700: (0xa9be4ff4, _quickstep_prefix('quickstep_stats_ui_release_panel'),
                   'destroy owned extra tail row and restore counts before native panel destructor'),
}
for _site, (_word, _emit, _note) in QUICKSTEP_STATS_UI_PATCHES.items():
    PATCHES[_site] = Patch(_word, _emit, 'LINUX-040', _note)


# [XCDE] LINUX-072: authored opt-in award adapters. Native eligibility, level-ups,
# skill bonuses and balance caps remain authoritative. Each award is scaled once;
# Expert Mode's existing bonus-EXP transfer is deliberately not patched.
def _cheats_reward_award(gen, addr):
    original = _system_call(gen, addr, 0x70000ba860)
    return ('{ extern _Bool xcde_cheats_rewards_call(Cpu *c); '
            f'c->x[30] = 0x{addr + 4:x}ull; '
            'if (!xcde_cheats_rewards_call(c)) { ' + original + '} }')


def _cheats_prefix(helper):
    def emit(gen, addr):
        original = _title_plain(gen, addr)
        return f'{{ extern void {helper}(Cpu *c); {helper}(c); }} ' + original
    return emit


CHEATS_REWARD_CALLS = {
    0x70000b5d90: 0x940012b4,
    0x70000b5dc0: 0x940012a8,
    0x70000b5df0: 0x9400129c,
    0x70000b5e20: 0x94001290,
    0x70000b5e50: 0x94001284,
    0x70000b5e80: 0x94001278,
    0x70000b5eb0: 0x9400126c,
    0x70000b5edc: 0x94001261,
    0x70000bb60c: 0x97fffc95,
    0x70000bbe20: 0x97fffa90,
    0x70000bc09c: 0x97fff9f1,
}
for _site, _word in CHEATS_REWARD_CALLS.items():
    assert _site not in PATCHES, f'Conflicting cheat patch at {_site:#x}'
    PATCHES[_site] = Patch(_word, _cheats_reward_award, 'LINUX-072',
                          'new EXP/AP/SP award; original call when off/1x, owned scaled record otherwise')

PATCHES[0x70000bc830] = Patch(0xf81e0ff3, _cheats_prefix('xcde_cheats_gold'), 'LINUX-072',
                            'positive gold-gain amount only; retain original add/cap behavior and prologue')


def _cheats_after(helper):
    def emit(gen, addr):
        original = _title_plain(gen, addr)
        return original + f' {{ extern void {helper}(Cpu *c); {helper}(c); }}'
    return emit


# Scale positive native event-9 HP loss once, after native source/target lookup.
# Both normal and linked damage dispatch retain their own immunity/presentation.
CHEATS_COMBAT_PATCHES = {
    0x700049eabc: (0xb0003788, 'cheats_combat_hit'),
    0x700049d148: (0xf9400fe8, 'cheats_combat_linked_hit'),
}
for _site, (_word, _helper) in CHEATS_COMBAT_PATCHES.items():
    assert _site not in PATCHES, f'Conflicting cheat patch at {_site:#x}'
    PATCHES[_site] = Patch(_word, _cheats_after(_helper), 'LINUX-072',
                          'optional party damage magnitude; native event dispatch and HP consumer remain')


# This target is an existing native no-damage path in the same function, not a
# new dispatch entry. Bind the saved arguments and false-return epilogue as well
# as the patched instruction, so a mismatched native layout fails generation.
CHEATS_FALL_CONTEXT = {
    0x700044678c: 0x2a0103f6,  # original forced-event argument -> w22
    0x7000446858: 0xaa0003f7,  # native status-kind result -> w23
    0x700044691c: 0x2a1f03f6,  # existing no-damage/false path
    0x7000446924: 0x2a1603e0,  # return original native false result
    0x700044693c: 0xd65f03c0,  # native epilogue returns normally
}


def _cheats_fall(gen, addr):
    for site, expected in CHEATS_FALL_CONTEXT.items():
        if gen.word(site) != expected:
            raise ValueError(f'{site:#x}: LINUX-072 native fall context changed')
    original = _title_plain(gen, addr)
    return (original + ' { extern _Bool cheats_skip_fall_damage(Cpu *c); '
            'if (cheats_skip_fall_damage(c)) goto L_700044691c; }')


PATCHES[0x7000446864] = Patch(0xb9400815, _cheats_fall, 'LINUX-072',
                            'optional ordinary PC fall immunity before nonlethal/lethal split; forced events remain native')
