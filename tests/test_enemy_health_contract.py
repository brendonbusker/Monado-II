"""LINUX-129: independent authored production-hook and lifetime contracts.

Only single checked instruction contracts and authored state are used. No game
function body, game input, generated chunk, asset, save or route is embedded.
"""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
sys.path.insert(0, str(PORT / 'tools/lifter'))
from lifter import Lifter  # noqa: E402
from patchfmt import PatchMismatch  # noqa: E402

SPEC = importlib.util.spec_from_file_location('enemy_health_contract', PORT / 'games/xcde/patches.py')
PATCHES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHES)
BASE = 0x7000000000


def fixture():
    words = dict(PATCHES.ENEMY_HEALTH_CONTEXT)
    words.update({address: spec[0] for address, spec in PATCHES.ENEMY_HEALTH_PATCHES.items()})
    lifter = Lifter(BASE, 'c')
    gen = SimpleNamespace(name='main', nso=SimpleNamespace(build_id=PATCHES.ENEMY_HEALTH_BUILD_ID),
                          word=words.__getitem__, lift=lambda address: lifter.lift(words[address], address))
    return gen, words


class EnemyHealthPatchContract(unittest.TestCase):
    def test_required_lifetimes_and_all_delta_paths_are_guarded(self):
        # Independently reviewed obligations: construction, native reinitialization,
        # direct status destruction, inlined deleting owner destruction, update,
        # fresh-stat entry/store, three delta branches and protection-floor math.
        required = {BASE + offset for offset in (
            0x47dbb0, 0x47eb70, 0x4b9a30, 0x4b9920, 0x47fb8c, 0x8e8b0,
            0x8ed38, 0x47d390, 0x47d420, 0x47d4fc, 0x41f518, 0x41f528)}
        self.assertEqual(set(PATCHES.ENEMY_HEALTH_PATCHES), required)
        for address in required:
            self.assertEqual(PATCHES.PATCHES[address].req, 'LINUX-129')
        # Native immunity/phase/survival control flow and script HP query APIs are
        # not replaced to force cheat results. The existing branches still run.
        for offset in (0x47d320, 0x47d4d0, 0x41f3d0, 0x41f4d4,
                       0x524210, 0x524360, 0x47b590):
            self.assertNotIn(BASE + offset, PATCHES.ENEMY_HEALTH_PATCHES)

    def test_wrong_module_build_instruction_or_context_is_rejected(self):
        for address in PATCHES.ENEMY_HEALTH_PATCHES:
            for name, build in [('sdk', PATCHES.ENEMY_HEALTH_BUILD_ID), ('main', '0' * 32)]:
                gen, _ = fixture(); gen.name = name; gen.nso.build_id = build
                with self.subTest(site=hex(address), module=name, build=build):
                    with self.assertRaisesRegex(ValueError, 'checked DE 2.0.0 main'):
                        PATCHES.PATCHES[address].apply(gen, address)
            for changed in [address, *PATCHES.ENEMY_HEALTH_CONTEXT]:
                gen, words = fixture(); words[changed] ^= 1
                with self.subTest(site=hex(address), context=hex(changed)):
                    with self.assertRaises((ValueError, PatchMismatch)):
                        PATCHES.PATCHES[address].apply(gen, address)

    def test_native_operation_remains_once_and_in_the_required_order(self):
        for address in PATCHES.ENEMY_HEALTH_PATCHES:
            gen, _ = fixture(); native = gen.lift(address)
            self.assertEqual(native.kind, 'op')
            text = PATCHES.PATCHES[address].apply(gen, address)
            self.assertEqual(text.count(native.code), 1)
            if address in {BASE + x for x in (0x47d390, 0x47d420, 0x47d4fc, 0x41f518)}:
                self.assertIn('if (!xcde_cheats_enemy_health_', text)
            elif address == BASE + 0x41f528:
                self.assertTrue(text.startswith(native.code))
            else:
                self.assertTrue(text.endswith(native.code))


@unittest.skipUnless(sys.platform == 'linux', 'Linux native hook and guest-memory contract')
class EnemyHealthEmittedNative(unittest.TestCase):
    def test_emitted_adapters_original_identity_lifetimes_and_overflow(self):
        local = PORT / '.deps/bin/clang-cc'
        compiler = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            self.skipTest('Clang required for authored production CPU-header fixture')
        source = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <fenv.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "hle.h"
#include "settings.h"
#include "cheats_options.h"
#include "hle/cheats_enemy_health.h"
#pragma STDC FENV_ACCESS ON
// The fixture explicitly walks reset registrations. Keep that section under
// the portable compiler's dead-section elimination; production bodies are exact.
#undef RT_ON_RESET
#define RT_ON_RESET(fn) \
    static void fn(void); \
    __attribute__((used,retain,section(RESET_SECTION))) static const ResetFn test_reset_##fn = fn; \
    static void fn(void)
#include "hle/cheats_enemy_health.c"
Settings g_settings;
void rt_fatal_trace(void) { _Exit(86); }
static const uint64_t status = GUEST_LO + 0x1000, stats = GUEST_LO + 0x249c,
                      vtable = GUEST_LO + 0x8000, stack = GUEST_LO + 0xa0000;
static unsigned checks;
static int initial_call;
'''
        for address in PATCHES.ENEMY_HEALTH_PATCHES:
            gen, _ = fixture()
            source += '\nstatic void emitted_' + f'{address:x}' + '(Cpu *c) { '
            source += PATCHES.PATCHES[address].apply(gen, address) + ' }\n'
            source += '\nstatic void original_' + f'{address:x}' + '(Cpu *c) { '
            source += gen.lift(address).code + ' }\n'
        source += r'''
static void options(int percent) {
    memset(&g_settings, 0, sizeof g_settings);
    g_settings.cheat_enemy_health = percent != 100;
    g_settings.cheat_enemy_health_percent = percent;
    xcde_cheats_publish(&g_settings);
}
static Cpu cpu(void) {
    Cpu c; memset(&c, 0x51, sizeof c);
    c.sp = stack; c.fpcr = 0; c.fpsr = 0;
    c.x[0] = status; c.x[3] = status; c.x[19] = status; c.x[20] = status;
    c.v[0] = fb_s(3000000000.f);
    return c;
}
static void actor(void) {
    ST64(status, vtable); ST64(vtable + 8, 0x700047f780ull);
    ST64(vtable + 0xc8, 0x700047f2b0ull);
    ST32(stats + 8, 1000); ST32(stats + 0xe8, 1000);
    Cpu c = cpu(); emitted_700047dbb0(&c); c = cpu(); emitted_700047eb70(&c);
    initial_call = 1;
}
typedef void (*Hook)(Cpu *);
static void identity(Hook patched, Hook native, Cpu c) {
    unsigned char before[0x100000], expected_memory[0x100000];
    memcpy(before, (void *)(uintptr_t)GUEST_LO, sizeof before);
    Cpu expected = c;
    assert(!fesetround(FE_DOWNWARD)); assert(!feclearexcept(FE_ALL_EXCEPT));
    assert(!feraiseexcept(FE_DIVBYZERO));
    int flags = fetestexcept(FE_ALL_EXCEPT);
    native(&expected);
    int expected_flags = fetestexcept(FE_ALL_EXCEPT);
    memcpy(expected_memory, (void *)(uintptr_t)GUEST_LO, sizeof expected_memory);
    memcpy((void *)(uintptr_t)GUEST_LO, before, sizeof before);
    assert(!feclearexcept(FE_ALL_EXCEPT)); assert(!feraiseexcept(flags));
    patched(&c);
    assert(!memcmp(&c, &expected, sizeof c));
    assert(!memcmp(expected_memory, (void *)(uintptr_t)GUEST_LO, sizeof expected_memory));
    assert(fegetround() == FE_DOWNWARD);
    assert(fetestexcept(FE_ALL_EXCEPT) == expected_flags);
    ++checks;
}
static void recalculate(int requested, unsigned fresh, unsigned expected_max, unsigned expected_hp) {
    options(requested); Cpu c = cpu(); c.x[0] = stats;
    c.x[30] = initial_call ? 0x700047ebc0ull : 0x700047fcfcull;
    emitted_700008e8b0(&c);
    // Authored native-stat producer: the real hook receives these audited
    // registers after the game's own base/buff calculation, not an old max.
    c.x[19] = stats; c.x[20] = status; c.x[8] = fresh;
    Cpu expected = c; expected.x[8] = expected_max;
    emitted_700008ed38(&c);
    assert(!memcmp(&c, &expected, sizeof c));
    assert(LD32(stats + 0xe8) == expected_max && LD32(stats + 8) == expected_hp);
    initial_call = 0;
    ++checks;
}
static void unready_refresh(int requested, uint32_t poison_hp, uint32_t poison_max, int during_init) {
    options(requested);
    ST64(status, vtable); ST64(vtable + 8, 0x700047f780ull);
    ST64(vtable + 0xc8, 0x700047f2b0ull);
    Cpu c = cpu(); emitted_700047dbb0(&c);
    if (during_init) { c = cpu(); emitted_700047eb70(&c); }
    // A constructor installs the native vtable before the HP-stat initializer
    // has run. Native loading refreshes can see allocator poison or zero here.
    ST32(stats + 8, poison_hp); ST32(stats + 0xe8, poison_max);
    c = cpu(); c.x[0] = stats; c.x[30] = 0x700047fcfcull;
    emitted_700008e8b0(&c);
    c.x[19] = stats; c.x[20] = status; c.x[8] = 1;
    Cpu expected = c;
    emitted_700008ed38(&c);
    assert(!memcmp(&c, &expected, sizeof c));
    assert(LD32(stats + 8) == poison_hp && LD32(stats + 0xe8) == 1);
    c = cpu(); identity(emitted_700047fb8c, original_700047fb8c, c);
    c.x[8] = 2000000000; c.x[20] = 1000000000;
    identity(emitted_700047d4fc, original_700047d4fc, c);
    // Only the real post-base-initialization call establishes readiness. A
    // nested refresh must not consume that transition or treat poison as HP.
    if (!during_init) { c = cpu(); emitted_700047eb70(&c); }
    ST32(stats + 8, 1000); initial_call = 1;
    recalculate(requested, 1000, requested == 2000 ? 20000 : requested == 200 ? 2000 : 1000,
                requested == 2000 ? 20000 : requested == 200 ? 2000 : 1000);
}
static void all_default_hooks(int enabled_one) {
    options(100); g_settings.cheat_enemy_health = enabled_one; xcde_cheats_publish(&g_settings);
    actor(); Cpu c = cpu();
    identity(emitted_700047dbb0, original_700047dbb0, c);
    identity(emitted_700047eb70, original_700047eb70, c);
    identity(emitted_700047fb8c, original_700047fb8c, c);
    c.x[0] = stats;
    c.x[30] = 0x700047fcfcull;
    identity(emitted_700008e8b0, original_700008e8b0, c);
    c = cpu(); c.x[19] = stats; c.x[8] = 1000; c.sp -= 0xb0;
    identity(emitted_700008ed38, original_700008ed38, c);
    c = cpu(); c.x[8] = 2000000000; c.x[20] = 1000000000;
    identity(emitted_700047d390, original_700047d390, c);
    identity(emitted_700047d420, original_700047d420, c);
    identity(emitted_700047d4fc, original_700047d4fc, c);
    c = cpu(); c.x[8] = 876543; c.x[0] = stats;
    identity(emitted_700041f518, original_700041f518, c);
    c = cpu();
    identity(emitted_700041f528, original_700041f528, c);
    identity(emitted_70004b9a30, original_70004b9a30, c);
    actor(); c = cpu(); c.x[0] = status - 0x60;
    identity(emitted_70004b9920, original_70004b9920, c);
}
int main(int argc, char **argv) {
    assert(mmap((void *)(uintptr_t)GUEST_LO, 0x100000, PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) == (void *)(uintptr_t)GUEST_LO);
    if (argc == 2 && !strcmp(argv[1], "ready-invalid")) {
        options(200); actor(); recalculate(200, 1000, 2000, 2000);
        ST32(stats + 0xe8, 0); ST32(stats + 8, UINT32_MAX);
        recalculate(10, 1000, 100, 1);
        return 91; // A ready live instance must still reject corrupt prior HP.
    }
    for (unsigned during_init = 0; during_init < 2; ++during_init)
        for (unsigned mode = 0; mode < 3; ++mode)
            unready_refresh(mode == 0 ? 100 : mode == 1 ? 200 : 2000,
                            mode == 0 ? 0 : UINT32_MAX, mode == 2 ? 0 : UINT32_MAX, during_init);
    all_default_hooks(0); all_default_hooks(1);
    options(100); actor(); recalculate(100, 1000, 1000, 1000);
    recalculate(200, 1000, 2000, 2000); // Off initialization must still establish readiness.
    options(200); actor(); recalculate(200, 1000, 2000, 2000);
    ST32(stats + 8, 1000); recalculate(200, 1200, 2400, 1000); // Buff refresh must not heal/rebase.
    recalculate(10, 1200, 120, 50); // Live rebase retains the fraction.
    recalculate(2000, 1200, 24000, 10000);
    recalculate(100, 1200, 1200, 500);
    ST32(stats + 8, 0); recalculate(200, 1200, 2400, 0); // Never resurrect.
    // Conservative minimum prevents a fixed1HP native survival floor from
    // becoming coarser than1%, or coarser than a tiny original health bar.
    actor(); ST32(stats + 8, 200); recalculate(10, 200, 100, 100);
    ST32(stats + 8, 1); assert((100 * LD32(stats + 8) + LD32(stats + 0xe8) - 1) / LD32(stats + 0xe8) == 1);
    actor(); ST32(stats + 8, 50); recalculate(10, 50, 50, 50);
    ST32(stats + 8, 1); assert((100 * LD32(stats + 8) + LD32(stats + 0xe8) - 1) / LD32(stats + 0xe8) == 2);
    // Both concrete destruction routes invalidate scaled ownership. With the
    // preference still enabled, a stale instance must use the original ADD.
    for (unsigned deleting = 0; deleting != 2; ++deleting) {
        actor(); recalculate(200, 1000, 2000, 2000);
        Cpu c = cpu(); if (deleting) { c.x[0] -= 0x60; emitted_70004b9920(&c); }
        else emitted_70004b9a30(&c);
        c = cpu(); c.x[8] = 2000000000; c.x[20] = 1000000000;
        identity(emitted_700047d4fc, original_700047d4fc, c);
        actor(); recalculate(200, 1000, 2000, 2000); // Reused address starts fresh.
    }
    for (unsigned path = 0; path < 3; ++path) {
        Cpu c = cpu(), expected = c; c.x[8] = 2000000000; c.x[20] = 1000000000;
        expected = c; expected.x[20] = INT32_MAX;
        if (path == 0) emitted_700047d390(&c);
        else if (path == 1) emitted_700047d420(&c);
        else emitted_700047d4fc(&c);
        assert(!memcmp(&c, &expected, sizeof c)); ++checks;
    }
    // The conversion consumes the full HP×parameter, while native W8 product
    // and unrelated CPU fields remain as produced by the original MUL.
    ST32(stats + 0xe8, 1000000000);
    Cpu c = cpu(); c.x[0] = stats; c.x[8] = (uint32_t)(UINT64_C(1000000000) * 100); c.x[9] = 100;
    Cpu expected = c; expected.v[0] = fb_s(100000000000.f);
    assert(!fesetround(FE_TONEAREST)); emitted_700041f518(&c);
    assert(!memcmp(&c, &expected, sizeof c)); ++checks;
    // Independent host conversion oracle for all guest rounding directions.
    // The production runtime keeps the guest mode in Cpu and restores the host
    // rounding mode after the slow conversion. Other CPU state must stay exact.
    const int modes[] = {FE_TONEAREST, FE_UPWARD, FE_DOWNWARD, FE_TOWARDZERO};
    for (unsigned mode = 0; mode < 4; ++mode) {
        c = cpu(); c.x[0] = stats; c.x[8] = (uint32_t)(UINT64_C(1000000000) * 100); c.x[9] = 100;
        c.fpcr = (uint64_t)mode << 22; c.fpsr = 0x08000001;
        expected = c;
        assert(!fesetround(modes[mode]));
        volatile uint64_t product = UINT64_C(1000000000) * 100;
        volatile float converted = (float)product;
        expected.v[0] = fb_s(converted);
        assert(!fesetround(FE_TONEAREST));
        emitted_700041f518(&c);
        assert(!memcmp(&c, &expected, sizeof c) && fegetround() == FE_TONEAREST); ++checks;
    }
    c = cpu(); expected = c; original_700041f528(&expected); expected.x[22] = 1000000000;
    emitted_700041f528(&c); assert(!memcmp(&c, &expected, sizeof c)); ++checks;
    // Enemy-only guard: a party kind at an otherwise identical address keeps
    // native arithmetic, even with an old scaled record and preference enabled.
    ST64(vtable + 8, 0x700047f750ull); c = cpu(); c.x[8] = 2000000000; c.x[20] = 1000000000;
    identity(emitted_700047d4fc, original_700047d4fc, c);
    // Explicitly invoke the registered reset only at a quiescent fixture
    // boundary. No guest worker exists or can retain a node here.
    extern const ResetFn __start_resets[], __stop_resets[];
    for (const ResetFn *reset = __start_resets; reset != __stop_resets; ++reset) (*reset)();
    actor(); recalculate(200, 1000, 2000, 2000);
    assert(!munmap((void *)(uintptr_t)GUEST_LO, 0x100000));
    printf("PASS independent enemy-health emitted contracts: %u checks\n", checks);
}
'''
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('LD_', 'XCDE_', 'LARECOMP_', 'LASRECOMP_'))}
        env.pop('GLIBC_TUNABLES', None)
        with tempfile.TemporaryDirectory(prefix='monado-enemy-health-contract-') as directory:
            root = Path(directory); cfile = root / 'fixture.c'; binary = root / 'contract'
            cfile.write_text(source)
            command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       '-fno-fast-math', '-ffp-contract=off', '-fno-strict-aliasing',
                       '-I', str(PORT / 'runtime'), str(cfile),
                       str(PORT / 'runtime/hle/cheats_options.c'), '-pthread', '-lm', '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
                env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS independent enemy-health emitted contracts:', result.stdout)
            result = subprocess.run([str(binary), 'ready-invalid'], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 86, result.stdout + result.stderr)
            self.assertIn('enemy health prior HP outside signed range', result.stderr)


if __name__ == '__main__':
    unittest.main()
