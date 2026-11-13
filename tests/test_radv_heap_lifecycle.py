"""LINUX-070: execute the real heap integration against controlled backends.

Only authored C functions are extracted; no game, GPU, window or dependency
installation is needed. The helper's actual Vulkan behavior has separate tests.
"""
from pathlib import Path
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
PORT = ROOT / 'Monado_Linux'


def block(source, pattern):
    match = re.search(pattern, source, re.MULTILINE)
    if not match:
        raise AssertionError('missing production block: ' + pattern)
    opening = source.index('{', match.start())
    # Ignore braces in comments and string literals while retaining offsets.
    tokens = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
    masked = tokens.sub(lambda item: ' ' * len(item.group()), source)
    depth = 1
    end = opening + 1
    while depth:
        depth += (masked[end] == '{') - (masked[end] == '}')
        end += 1
    return source[match.start():end] + '\n'


VULKAN_STUB = r'''
#pragma once
#include <stdint.h>
typedef struct VkPhysicalDevice_T *VkPhysicalDevice;
typedef struct VkDevice_T *VkDevice;
typedef struct VkBuffer_T *VkBuffer;
typedef struct VkDeviceMemory_T *VkDeviceMemory;
typedef uint64_t VkDeviceSize;
typedef uint32_t VkBufferUsageFlags;
typedef int VkResult;
typedef void (*PFN_vkUnmapMemory2KHR)(void);
typedef struct VkDescriptorBufferInfo { VkBuffer buffer; VkDeviceSize offset, range; } VkDescriptorBufferInfo;
#define VK_SUCCESS 0
#define VK_ERROR_OUT_OF_HOST_MEMORY (-1)
#define VK_NULL_HANDLE 0
#define VK_BUFFER_USAGE_STORAGE_BUFFER_BIT 32
#define VK_BUFFER_USAGE_TRANSFER_SRC_BIT 1
#define VK_BUFFER_USAGE_TRANSFER_DST_BIT 2
#define VK_BUFFER_USAGE_VERTEX_BUFFER_BIT 128
#define VK_BUFFER_USAGE_INDEX_BUFFER_BIT 64
'''


@unittest.skipUnless(sys.platform == 'linux', 'native Linux lifecycle contract')
class RadvHeapLifecycleTests(unittest.TestCase):
    def test_native_recipe_enables_kernel_hook_without_changing_other_units(self):
        spec = importlib.util.spec_from_file_location('radv_heap_native_recipe', PORT / 'scripts/build_linux.py')
        recipe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(recipe)
        with tempfile.TemporaryDirectory(prefix='monado-heap-recipe-') as directory:
            builder = recipe.Builder.__new__(recipe.Builder)
            builder.output = Path(directory)
            (builder.output / 'obj').mkdir()
            builder.flags = ['-O1']
            builder.cc = builder.cxx = 'authored-compiler-placeholder'
            builder.lock = threading.Lock()
            builder.failed = threading.Event()
            builder.args = types.SimpleNamespace(keep_going=False)
            builder.receipt = {'objects': {}, 'errors': []}
            builder.save = lambda: None
            invocations = []
            def compile_fixture(name, argv):
                invocations.append(argv)
                Path(argv[argv.index('-o') + 1]).write_bytes(b'authored object placeholder')
                return {'exit': 0}, ''
            builder.run = compile_fixture
            for name in ('kernel.c', 'platform/linux.c', 'host/main_boot.c'):
                self.assertIsNotNone(builder.compile(PORT / 'runtime' / name))
            self.assertIn('-DXCDE_LINUX_RADV_HEAP=1', invocations[0])
            self.assertNotIn('-DXCDE_LINUX_RADV_HEAP=1', invocations[1])
            self.assertNotIn('-DXCDE_LINUX_RADV_HEAP=1', invocations[2])
            self.assertIn('-DXCDE_GFX', invocations[2])

    def test_actual_kernel_renderer_heap_lifecycle(self):
        compiler = os.environ.get('MONADO_TEST_CC')
        local = PORT / '.deps/bin/clang-cc'
        compiler = compiler or (str(local) if local.is_file() else shutil.which('clang'))
        if not compiler:
            self.skipTest('Clang is required for the native lifecycle fixture')
        source = (PORT / 'runtime/nvn/vulkan/exec.c').read_text()
        kernel = (PORT / 'runtime/kernel.c').read_text()
        funcs = ''.join(block(source, r'^(?:static )?[^\n;]*\b' + name + r'\([^;]*?\)\s*\{') for name in (
            'backend_guest_heap_prepare', 'gmem_wanted_size', 'gmem_import',
            'gmem_info', 'gmem_prepare_command', 'vk_exec_reset'))
        case = block(kernel, r'^    case 0x01:\s*\{')
        with tempfile.TemporaryDirectory(prefix='monado-radv-lifecycle-') as temporary:
            folder = Path(temporary)
            (folder / 'vulkan').mkdir()
            (folder / 'vulkan/vulkan.h').write_text(VULKAN_STUB)
            (folder / 'heap_integration_source.h').write_text(funcs)
            (folder / 'set_heap_source.h').write_text(
                'static void set_heap(Cpu *c) { uint64_t *x = c->x; switch(1) {\n'
                + case + '\ndefault: abort(); } }\n')
            binary = folder / 'contracts'
            command = [compiler, '-std=gnu11', '-O1', '-UNDEBUG', '-ffp-contract=off',
                       '-fno-strict-aliasing', '-Wall', '-Wextra', '-Werror',
                       '-Wno-unused-function', '-Wno-unused-variable', '-pthread',
                       '-DXCDE_LINUX_RADV_HEAP=1', '-I', str(folder), '-I', str(PORT / 'runtime/nvn/vulkan'),
                       str(PORT / 'tests/native/test_radv_heap_lifecycle.c'), '-o', str(binary)]
            if os.environ.get('MONADO_TEST_UBSAN') == '1':
                command[1:1] = ['-fsanitize=undefined', '-fno-sanitize-recover=all']
            result = subprocess.run(command, capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], cwd=temporary, capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('heap lifecycle contracts: PASS', result.stdout)


if __name__ == '__main__':
    unittest.main()
