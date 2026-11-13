"""Headless SDL virtual-pad integration for the actual production input route."""
from pathlib import Path
import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


def dependency_port():
    override = os.environ.get('MONADO_TEST_SDL_PORT')
    candidates = [Path(override)] if override else [PORT]
    for port in candidates:
        marker = port / '.deps/graphics/active-sysroot.txt'
        wrapper = port / '.deps/bin/pkg-config-graphics'
        if marker.is_file() and wrapper.is_file():
            return port.resolve()
    return None


@unittest.skipUnless(sys.platform == 'linux', 'native Linux SDL virtual gamepads')
class InputCamera(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = dependency_port()
        if port is None:
            raise unittest.SkipTest('Pinned SDL3 development dependencies unavailable; set MONADO_TEST_SDL_PORT')
        compiler = os.environ.get('MONADO_TEST_CC')
        if not compiler:
            local = port / '.deps/bin/clang-cc'
            compiler = str(local) if local.is_file() else shutil.which('clang')
        if not compiler:
            raise unittest.SkipTest('Clang is required for the actual input.c fixture')
        spec = importlib.util.spec_from_file_location('camera_runtime_check', port / 'scripts/linux_runtime_check.py')
        runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
        sysroot = Path((port / '.deps/graphics/active-sysroot.txt').read_text().strip())
        policy, _ = runtime.load_policy(port, sysroot)
        cls.environment = runtime.clean_environment(runtime.library_path(sysroot, policy))
        cls.environment.update(SDL_VIDEODRIVER='dummy', SDL_AUDIODRIVER='dummy')
        for key in tuple(cls.environment):
            if key.startswith(('LARECOMP_', 'XCDE_', 'LASRECOMP_')):
                cls.environment.pop(key)
        result = subprocess.run([str(port / '.deps/bin/pkg-config-graphics'), '--cflags', '--libs', 'sdl3'],
                                env=runtime.clean_environment(), capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.temporary = tempfile.TemporaryDirectory(prefix='monado-native-camera-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.binary = Path(cls.temporary.name) / 'input-camera'
        command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-ffp-contract=off',
                   '-fno-strict-aliasing', '-ffunction-sections', '-fdata-sections',
                   '-pthread', '-I', str(PORT / 'runtime'),
                   str(ROOT / 'tests/native/test_input_camera.c'), str(PORT / 'runtime/hle/bindings.c'),
                   *shlex.split(result.stdout), '-Wl,--gc-sections', '-lm',
                   '-Xlinker', '-rpath', '-Xlinker', cls.environment['LD_LIBRARY_PATH'],
                   '-o', str(cls.binary)]
        if os.environ.get('MONADO_TEST_UBSAN') == '1':
            command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            cls.environment['UBSAN_OPTIONS'] = 'halt_on_error=1:print_stacktrace=1'
        compiled = subprocess.run(command, env=runtime.clean_environment(), capture_output=True,
                                  text=True, timeout=120)
        if compiled.returncode:
            raise AssertionError(compiled.stdout + compiled.stderr)
        runtime.check_artifacts([cls.binary], sysroot, policy)

    def scenario(self, name):
        result = subprocess.run([str(self.binary), name], cwd=self.temporary.name,
                                env=self.environment, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('native SDL camera input: PASS ' + name, result.stdout)
        self.assertEqual({p.name for p in Path(self.temporary.name).iterdir()}, {self.binary.name},
                         'Input fixture must never write profiles or other runtime state')

    def test_vanilla_trigger_and_camera(self): self.scenario('vanilla')
    def test_immediate_neutral_trigger_hold_reaches_native_hud(self): self.scenario('immediate-hold')
    def test_option_preserves_native_trigger_and_camera_stick(self): self.scenario('camera-stick')
    def test_camera_motion_before_trigger(self): self.scenario('preexisting-motion')
    def test_camera_dpad_has_priority_over_optional_dpad_walk(self): self.scenario('camera-dpad')
    def test_drift_deadzone_preserves_axes_and_native_held_trigger(self): self.scenario('drift-deadzone')
    def test_option_and_binding_transition_cancel_current_hold(self): self.scenario('transition-held')
    def test_lone_trigger_tap_preserved(self): self.scenario('tap')
    def test_left_shoulder_chord(self): self.scenario('chord-left')
    def test_right_shoulder_chord(self): self.scenario('chord-right')
    def test_chord_trigger_released_before_shoulder(self): self.scenario('chord-trigger-release')
    def test_sampled_shoulder_does_not_leak_before_queued_button_event(self): self.scenario('queued-chord')
    def test_custom_bindings_do_not_inject_zl(self): self.scenario('remapped')
    def test_trigger_remapped_as_direction_has_native_press_release(self): self.scenario('remapped-direction')
    def test_keyboard_zl_independent_of_controller_modifier(self): self.scenario('keyboard')
    def test_keyboard_camera_axes_coexist_with_held_controller_trigger(self): self.scenario('keyboard-camera')
    def test_scripted_host_and_keyboard_input_without_controller(self): self.scenario('scripted-without-pad')
    def test_overlay_reset_cancels_pending_controller_gesture(self): self.scenario('menu-reset')
    def test_focus_loss_cancels_pending_controller_gesture(self): self.scenario('focus-reset')
    def test_other_controller_cannot_switch_selected_party(self): self.scenario('wrong-device')
    def test_disconnect_cancels_gesture_and_new_controller_recovers(self): self.scenario('disconnect')
    def test_concurrent_overlay_cancellation_cannot_republish_held_camera(self): self.scenario('concurrent-cancellation')


if __name__ == '__main__':
    unittest.main()
