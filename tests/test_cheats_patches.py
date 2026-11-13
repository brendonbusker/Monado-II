"""LINUX-072: checked award call patches and compiled authored dispatch fixtures."""
from pathlib import Path
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'
sys.path.insert(0, str(PORT / 'tools/lifter'))
from lifter import Lifter  # noqa: E402
from patchfmt import PatchMismatch  # noqa: E402

SPEC = importlib.util.spec_from_file_location('xcde_cheats_patch_fixture', PORT / 'games/xcde/patches.py')
PATCHES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHES)
BASE = 0x7000000000
AWARD = BASE + 0xba860
GOLD = BASE + 0xbc830
EXPERT_TRANSFER = BASE + 0xbad50
GOLD_SET, GOLD_REMOVE = BASE + 0xbc7f0, BASE + 0xbc880


class Instruction:
    """One authored instruction-word contract, lifted by the production lifter."""
    def __init__(self, address, word, context=None):
        self.address, self.value = address, word
        self.context = dict(context or {})
        self.lifter = Lifter(BASE, 'c')

    def word(self, address):
        if address == self.address:
            return self.value
        if address in self.context:
            return self.context[address]
        raise AssertionError('Patch attempted to inspect an undeclared context instruction')

    def lift(self, address):
        return self.lifter.lift(self.word(address), address)


class CheatPatchGuards(unittest.TestCase):
    def test_actual_reward_words_and_wrong_target_fail_closed(self):
        self.assertEqual(len(PATCHES.CHEATS_REWARD_CALLS), 11)
        for address, word in PATCHES.CHEATS_REWARD_CALLS.items():
            with self.subTest(address=hex(address)):
                patch = PATCHES.PATCHES[address]
                self.assertEqual(patch.req, 'LINUX-072')
                fixture = Instruction(address, word)
                instruction = fixture.lift(address)
                self.assertEqual((instruction.kind, instruction.target), ('bl', AWARD))
                emitted = patch.apply(fixture, address)
                self.assertIn('xcde_cheats_rewards_call', emitted)
                self.assertIn(f'c->x[30] = 0x{address + 4:x}ull;', emitted)
                with self.assertRaises(PatchMismatch):
                    patch.apply(Instruction(address, word ^ 1), address)
                # Bypass only the outer word check to test the emitter's own
                # call-kind/target assertion; a valid BL to another target is refused.
                with self.assertRaises(ValueError):
                    patch.emit(Instruction(address, word ^ 1), address)
                with self.assertRaises(ValueError):
                    patch.emit(Instruction(address, 0xd65f03c0), address)

    def test_expert_transfer_and_currency_set_remove_are_not_patched(self):
        for address in [EXPERT_TRANSFER, GOLD_SET, GOLD_REMOVE]:
            self.assertNotIn(address, PATCHES.PATCHES)
        self.assertIn(GOLD, PATCHES.PATCHES)
        self.assertEqual(PATCHES.PATCHES[GOLD].req, 'LINUX-072')

    def test_actual_gold_prologue_preserved_and_nonplain_word_rejected(self):
        patch = PATCHES.PATCHES[GOLD]
        fixture = Instruction(GOLD, patch.expected)
        native = fixture.lift(GOLD)
        self.assertEqual(native.kind, 'op')
        self.assertEqual(patch.apply(fixture, GOLD),
                         '{ extern void xcde_cheats_gold(Cpu *c); xcde_cheats_gold(c); } ' + native.code)
        with self.assertRaises(PatchMismatch):
            patch.apply(Instruction(GOLD, patch.expected ^ 1), GOLD)
        with self.assertRaises(ValueError):
            patch.emit(Instruction(GOLD, 0xd65f03c0), GOLD)


class CheatCombatPatchGuards(unittest.TestCase):
    def test_original_instruction_precedes_each_combat_helper(self):
        self.assertEqual(len(PATCHES.CHEATS_COMBAT_PATCHES), 2)
        for address, (word, helper) in PATCHES.CHEATS_COMBAT_PATCHES.items():
            with self.subTest(address=hex(address)):
                patch = PATCHES.PATCHES[address]; fixture = Instruction(address, word)
                self.assertEqual(patch.req, 'LINUX-072')
                instruction = fixture.lift(address)
                self.assertEqual(instruction.kind, 'op')
                emitted = patch.apply(fixture, address)
                self.assertEqual(emitted, instruction.code + f' {{ extern void {helper}(Cpu *c); {helper}(c); }}')
                with self.assertRaises(PatchMismatch):
                    patch.apply(Instruction(address, word ^ 1), address)
                with self.assertRaises(ValueError):
                    patch.emit(Instruction(address, 0xd65f03c0), address)
        # Native event10 healing/effect dispatch and the common HP consumers stay native.
        for address in [BASE + 0x49e95c, BASE + 0x42238c, BASE + 0x422398, BASE + 0x41f448]:
            self.assertNotIn(address, PATCHES.PATCHES)

    def test_fall_original_context_and_existing_return_target(self):
        address = BASE + 0x446864; patch = PATCHES.PATCHES[address]
        fixture = Instruction(address, patch.expected, PATCHES.CHEATS_FALL_CONTEXT)
        native = fixture.lift(address)
        self.assertEqual(native.kind, 'op')
        emitted = patch.apply(fixture, address)
        self.assertEqual(emitted, native.code + ' { extern _Bool cheats_skip_fall_damage(Cpu *c); if (cheats_skip_fall_damage(c)) goto L_700044691c; }')
        self.assertNotIn(BASE + 0x44691c, PATCHES.PATCHES)
        with self.assertRaises(PatchMismatch):
            patch.apply(Instruction(address, patch.expected ^ 1, PATCHES.CHEATS_FALL_CONTEXT), address)
        for context_address in PATCHES.CHEATS_FALL_CONTEXT:
            context = dict(PATCHES.CHEATS_FALL_CONTEXT); context[context_address] ^= 1
            with self.subTest(context_address=hex(context_address)), self.assertRaisesRegex(ValueError, 'native fall context changed'):
                patch.apply(Instruction(address, patch.expected, context), address)
        with self.assertRaises(ValueError):
            patch.emit(Instruction(address, 0xd65f03c0, PATCHES.CHEATS_FALL_CONTEXT), address)


@unittest.skipUnless(sys.platform == 'linux', 'native Linux award call integration')
class CheatPatchNative(unittest.TestCase):
    def test_compiled_emitted_calls_route_once_and_set_native_link_register(self):
        local = PORT / '.deps/bin/clang-cc'
        cc = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not cc:
            self.skipTest('Clang required for production CPU-header native fixture')
        # Only emitted authored adapter/prologue code is produced into the private
        # temporary fixture. No game function implementation, input or asset is used.
        functions = []
        for index, (address, word) in enumerate(PATCHES.CHEATS_REWARD_CALLS.items()):
            body = PATCHES.PATCHES[address].apply(Instruction(address, word), address)
            body = body.replace(f'f_{AWARD:x}', 'authored_award')
            functions.append(f'static void checked_call_{index}(Cpu *c) {{ {body} }}')
        gold = PATCHES.PATCHES[GOLD]
        gold_body = gold.apply(Instruction(GOLD, gold.expected), GOLD)
        fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "cpu.h"
static unsigned awards, hooks, gold_hooks;
static _Bool intercept;
static uint64_t expected_lr;
void authored_award(Cpu *c) {
    ++awards; assert(c->x[30] == expected_lr); assert(c->x[2] == 17);
    c->x[0] = 0x123; c->x[3] = 0x456;
}
_Bool xcde_cheats_rewards_call(Cpu *c) {
    ++hooks; assert(c->x[30] == expected_lr);
    if (!intercept) return 0;
    authored_award(c); return 1;
}
void xcde_cheats_gold(Cpu *c) { ++gold_hooks; if (intercept) c->x[1] *= 2; }
'''
        fixture += '\n'.join(functions)
        fixture += '\nstatic void checked_gold(Cpu *c) {' + gold_body + '}\n'
        fixture += 'typedef void (*Call)(Cpu *);\nstatic const Call calls[] = {'
        fixture += ','.join(f'checked_call_{i}' for i in range(len(functions))) + '};\n'
        fixture += 'static const uint64_t links[] = {'
        fixture += ','.join(hex(address + 4) + 'ull' for address in PATCHES.CHEATS_REWARD_CALLS) + '};\n'
        fixture += r'''
int main(void) {
    for (unsigned mode = 0; mode < 2; ++mode) {
        intercept = mode != 0;
        for (unsigned i = 0; i < sizeof calls / sizeof *calls; ++i) {
            Cpu c = {0}; c.x[30] = 0xdead; c.x[1] = 0; c.x[2] = 17;
            c.sp = 0x1000; c.pc = 0x2000; c.tpidr = 0x3000; c.tpidrro = 0x4000;
            expected_lr = links[i]; unsigned prior_awards = awards, prior_hooks = hooks;
            calls[i](&c);
            assert(awards == prior_awards + 1 && hooks == prior_hooks + 1);
            assert(c.x[30] == expected_lr && c.x[0] == 0x123 && c.x[3] == 0x456);
            assert(c.sp == 0x1000 && c.pc == 0x2000 && c.tpidr == 0x3000 && c.tpidrro == 0x4000);
        }
        _Alignas(16) uint8_t stack[128]; memset(stack, 0xa5, sizeof stack);
        Cpu c = {0}; c.sp = (uintptr_t)(stack + 96); c.x[19] = 0x1122334455667788ull; c.x[1] = 7;
        uint64_t old_sp = c.sp; unsigned prior = gold_hooks;
        checked_gold(&c);
        assert(gold_hooks == prior + 1 && c.sp == old_sp - 32);
        assert(LD64(c.sp) == c.x[19] && c.x[1] == (mode ? 14 : 7));
    }
    puts("checked cheat patches: 11 native calls x 2 modes, prologue and ABI PASS");
}
'''
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(('LD_', 'XCDE_', 'LARECOMP_', 'LASRECOMP_'))}
        environment.pop('GLIBC_TUNABLES', None)
        with tempfile.TemporaryDirectory(prefix='monado-cheat-patches-') as directory:
            root = Path(directory); source = root / 'authored.c'; source.write_text(fixture)
            target = root / 'patches'
            command = [cc, '-std=c11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       '-fno-strict-aliasing', '-ffp-contract=off', '-I', str(PORT / 'runtime'),
                       str(source), '-o', str(target)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
                environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            built = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            result = subprocess.run([str(target)], cwd=root, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('prologue and ABI PASS', result.stdout)
            self.assertEqual({p.name for p in root.iterdir()}, {'authored.c', 'patches'})

    def test_launcher_runtime_configuration_interoperability(self):
        cc = os.environ.get('MONADO_TEST_CC')
        local = PORT / '.deps/bin/clang-cc'
        cc = cc or (str(local) if local.is_file() else shutil.which('clang'))
        cxx = os.environ.get('MONADO_TEST_CXX')
        local_cxx = PORT / '.deps/bin/clang-cxx'
        cxx = cxx or (str(local_cxx) if local_cxx.is_file() else shutil.which('clang++'))
        if not cxx and cc and Path(cc).with_name('clang-cxx').is_file():
            cxx = str(Path(cc).with_name('clang-cxx'))
        if not cc or not cxx:
            self.skipTest('Clang C/C++ required for launcher/runtime configuration interop')
        source = (PORT / 'tools/launcher/launcher.cpp').read_text()
        fields = '    bool cheat_enabled[6]' + source.split('    bool cheat_enabled[6]', 1)[1].split('    bool show_fps', 1)[0]
        helpers = source.split('// [XCDE] LINUX-072: launcher cheat configuration,', 1)[1]
        helpers = helpers[helpers.index('static const char *const k_cheat_ini'):]
        helpers = helpers.split('// [XCDE] LINUX-072: end launcher cheat configuration.', 1)[0]
        fixture = r'''
#define _POSIX_C_SOURCE 200809L
#include <algorithm>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <string>
extern "C" {
#include "settings.h"
bool bind_settings_load(const char*, const char*) { return false; }
void bind_settings_save(FILE *f) { fputs("bind_key_a = Return\n", f); }
extern bool g_party_switch;
}
struct Cfg {
''' + fields + '};\nstatic Cfg g;\n' + helpers
        fixture += r'''
int main(int argc, char **argv) {
    assert(argc == 2 && !setenv("XCDE_INI", argv[1], 1));
    bool *enabled[] = {&g_settings.cheat_damage_dealt, &g_settings.cheat_damage_received,
        &g_settings.cheat_exp, &g_settings.cheat_ap, &g_settings.cheat_sp, &g_settings.cheat_gold};
    int *percent[] = {&g_settings.cheat_damage_dealt_percent, &g_settings.cheat_damage_received_percent,
        &g_settings.cheat_exp_percent, &g_settings.cheat_ap_percent, &g_settings.cheat_sp_percent, &g_settings.cheat_gold_percent};
    const int values[] = {0, 1, 100, 199, 2000, 567};
    cheats_reset();
    for (int i = 0; i < 6; ++i) { g.cheat_enabled[i] = (i % 2) != 0; g.cheat_percent[i] = values[i]; }
    g.cheat_no_fall_damage = true;
    FILE *file = fopen(argv[1], "w"); assert(file); cheats_save(file);
    fputs("party_switch = 1\nquickstep_slot = 1\n", file); assert(!fclose(file));
    settings_load();
    for (int i = 0; i < 6; ++i) { assert(*enabled[i] == g.cheat_enabled[i]); assert(*percent[i] == values[i]); }
    assert(g_settings.cheat_no_fall_damage && g_party_switch && g_settings.quickstep_slot);
    for (int i = 0; i < 6; ++i) { *enabled[i] = !(i % 2); *percent[i] = 2000 - values[i]; }
    g_settings.cheat_no_fall_damage = false;
    settings_save(); cheats_reset(); file = fopen(argv[1], "r"); assert(file);
    char line[512], key[96], value[128]; int recognized = 0;
    while (fgets(line, sizeof line, file)) if (sscanf(line, "%95s = %127s", key, value) == 2) {
        if (cheats_load(key, value)) { assert(is_cheat_key(key)); ++recognized; }
    }
    assert(!ferror(file) && !fclose(file)); assert(recognized == 13);
    for (int i = 0; i < 6; ++i) { assert(g.cheat_enabled[i] == *enabled[i]); assert(g.cheat_percent[i] == *percent[i]); }
    assert(!g.cheat_no_fall_damage && g_party_switch && g_settings.quickstep_slot);
    puts("launcher/runtime settings interop PASS");
}
'''
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('LD_', 'XCDE_', 'LARECOMP_', 'LASRECOMP_'))}
        env.pop('GLIBC_TUNABLES', None)
        flags = ['-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror']
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            flags += ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        with tempfile.TemporaryDirectory(prefix='monado-cheat-interop-') as directory:
            root = Path(directory); cpp = root / 'interop.cpp'; cpp.write_text(fixture)
            obj = root / 'runtime-settings.o'; target = root / 'interop'
            commands = [[cc, '-std=c11', *flags, '-c', str(PORT / 'runtime/host/settings_ini.c'), '-o', str(obj)],
                        [cxx, '-std=c++17', *flags, '-I', str(PORT / 'runtime'), str(cpp), str(obj), '-o', str(target)]]
            for command in commands:
                result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(target), str(root / 'xcde.ini')], cwd=root, env=env,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('launcher/runtime settings interop PASS', result.stdout)

    def test_emitted_combat_original_effect_and_actual_adapter_cpu_state(self):
        local = PORT / '.deps/bin/clang-cc'
        cc = os.environ.get('MONADO_TEST_CC') or (str(local) if local.is_file() else shutil.which('clang'))
        if not cc:
            self.skipTest('Clang required for actual combat integration fixture')
        bodies = []
        for index, (address, (word, helper)) in enumerate(PATCHES.CHEATS_COMBAT_PATCHES.items()):
            bodies.append(f'static void checked_dispatch_{index}(Cpu *c) {{ ' +
                          PATCHES.PATCHES[address].apply(Instruction(address, word), address) + ' }')
        address = BASE + 0x49eabc; word = PATCHES.CHEATS_COMBAT_PATCHES[address][0]
        displacement = (((word >> 5) & 0x7ffff) << 2) | ((word >> 29) & 3)
        if displacement & (1 << 20):
            displacement -= 1 << 21
        expected_adrp = (address & ~0xfff) + (displacement << 12)
        fixture = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include "cpu.h"
#include "settings.h"
// Generated chunks themselves do not include stdbool. Keep their adapter ABI honest.
#undef bool
#undef true
#undef false
Settings g_settings;
void rt_fatal_trace(void) { _Exit(86); }
''' + '\n'.join(bodies)
        fall_address = BASE + 0x446864; fall = PATCHES.PATCHES[fall_address]
        fall_body = fall.apply(Instruction(fall_address, fall.expected, PATCHES.CHEATS_FALL_CONTEXT), fall_address)
        fixture += '\nstatic int checked_fall(Cpu *c) { ' + fall_body
        fixture += '\nreturn 2; L_700044691c:; c->x[22] = 0; c->x[0] = c->x[22]; return 0; }\n'
        fixture += '\nstatic const uint64_t expected_adrp = ' + hex(expected_adrp) + 'ull;\n'
        fixture += r'''
int main(void) {
    const uint64_t base = 0x7002000000ull;
    assert(mmap((void *)(uintptr_t)base, 0x10000, PROT_READ | PROT_WRITE,
                MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0) == (void *)(uintptr_t)base);
    for (unsigned linked = 0; linked < 2; ++linked) for (unsigned mode = 0; mode < 4; ++mode) {
        memset((void *)(uintptr_t)base, 0xa5, 0x10000);
        Cpu c; memset(&c, 0x6b, sizeof c); c.sp = base + 0x1000;
        c.x[29] = c.sp + (linked ? 0x3c00 : 0x170); c.x[20] = 0;
        uint64_t event = linked ? c.x[29] - 0xb0 : base + 0x8000;
        c.x[linked ? 22 : 21] = event;
        uint64_t source = c.x[29] - (linked ? 0xd0 : 0x50);
        uint64_t target = c.x[29] - (linked ? 0xc0 : 0x60);
        ST64(source, base + 0xe000); ST32(source + 8, 2);
        ST64(target, base + 0xf000); ST32(target + 8, 4);
        if (linked) ST32(c.sp + 0x24, 0);
        const int32_t amount = mode == 3 ? -77 : 123;
        ST32(event + 0x20, (uint32_t)amount); ST64(c.sp + 0x18, 0x1122334455667788ull);
        memset(&g_settings, 0, sizeof g_settings);
        g_settings.cheat_damage_dealt = mode != 0;
        g_settings.cheat_damage_dealt_percent = mode == 1 ? 100 : 200;
        Cpu expected = c; expected.x[8] = linked ? LD64(c.sp + 0x18) : expected_adrp;
        uint8_t memory[0x10000]; memcpy(memory, (const void *)(uintptr_t)base, sizeof memory);
        if (mode == 2) {
            uint32_t scaled = 246;
            memcpy(memory + (size_t)(event - base) + 0x20, &scaled, sizeof scaled);
        }
        if (linked) checked_dispatch_1(&c); else checked_dispatch_0(&c);
        assert(!memcmp(&c, &expected, sizeof c));
        assert(!memcmp(memory, (const void *)(uintptr_t)base, sizeof memory));
    }
    // Authored native-continuation/false-return model exercises the emitted goto;
    // the actual no-damage target remains untouched and guarded in production.
    uint32_t fields[4] = {0, 0, 0x89abcdefu, 0};
    for (unsigned on = 0; on < 2; ++on) for (unsigned kind = 0; kind <= 6; ++kind)
        for (unsigned forced = 0; forced < 8; ++forced) {
            Cpu c; memset(&c, 0x5c, sizeof c);
            c.x[0] = (uintptr_t)fields; c.x[22] = forced; c.x[23] = kind;
            g_settings.cheat_no_fall_damage = on != 0;
            Cpu expected = c; expected.x[21] = 0x89abcdefu;
            int skip = on && kind == 2 && !(forced & 1);
            if (skip) { expected.x[22] = 0; expected.x[0] = 0; }
            assert(checked_fall(&c) == (skip ? 0 : 2));
            assert(!memcmp(&c, &expected, sizeof c));
        }
    assert(!munmap((void *)(uintptr_t)base, 0x10000));
    puts("combat emitted integration: native original ordering, full CPU/FPSR identity and single scaling PASS");
}
'''
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(('LD_', 'XCDE_', 'LARECOMP_', 'LASRECOMP_'))}
        env.pop('GLIBC_TUNABLES', None)
        with tempfile.TemporaryDirectory(prefix='monado-combat-patch-') as directory:
            root = Path(directory); source = root / 'authored.c'; source.write_text(fixture)
            target = root / 'combat'
            command = [cc, '-std=gnu11', '-O1', '-UNDEBUG', '-Wall', '-Wextra', '-Werror',
                       '-fno-strict-aliasing', '-ffp-contract=off', '-I', str(PORT / 'runtime'),
                       str(source), str(PORT / 'runtime/hle/cheats_combat.c'), '-o', str(target)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
                env['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(target)], cwd=root, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('full CPU/FPSR identity and single scaling PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
