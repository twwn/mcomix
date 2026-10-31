"""The fuzz targets in fuzz/, run here without Atheris: each over its
seeds, and over every input a fuzzing run found a failure with, which
fuzz/regressions/ keeps.  A target raises on an input its contract does
not allow, so a failure fixed stays fixed, and a target that no longer
runs is found here rather than by the weekly fuzzing.
"""

import contextlib
import importlib.util
import os
import shutil
import sys
import types
import unittest.mock

from . import MComixTest

FUZZ = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'fuzz')
TARGETS = ('ion', 'kfx', 'epub', 'comicinfo')


def _load(target):
    """fuzz/fuzz_<target>.py, with Atheris stood in for, and without
    _setup, which would move this process's home folder."""
    atheris = types.ModuleType('atheris')
    atheris.instrument_imports = lambda **kwargs: contextlib.nullcontext()
    standing_in = {'atheris': atheris, '_setup': types.ModuleType('_setup')}
    for name, module in standing_in.items():
        sys.modules.setdefault(name, module)
    try:
        spec = importlib.util.spec_from_file_location(
            '_fuzz_' + target, os.path.join(FUZZ, 'fuzz_%s.py' % target))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, stand_in in standing_in.items():
            if sys.modules.get(name) is stand_in:
                del sys.modules[name]
    return module


def _inputs(target):
    for folder in ('corpus', 'regressions'):
        path = os.path.join(FUZZ, folder, target)
        for name in sorted(os.listdir(path)) if os.path.isdir(path) else ():
            with open(os.path.join(path, name), 'rb') as fp:
                yield folder + '/' + name, fp.read()


class FuzzTargetTest(MComixTest):

    def _run(self, target):
        module = _load(target)
        if hasattr(module, 'FOLDER'):
            self.addCleanup(shutil.rmtree, module.FOLDER, True)
        inputs = list(_inputs(target))
        self.assertTrue(inputs)
        for name, data in inputs:
            with self.subTest(name):
                module.TestOneInput(data)
        return inputs

    def test_ion(self):
        self._run('ion')

    def test_kfx(self):
        # JPEG XR is jxrlib's program to decode, not MComix', as the
        # target leaves it out when it fuzzes.
        from mcomix.archive import kfx
        with unittest.mock.patch.object(kfx, '_jxr_decoder', lambda: None):
            inputs = self._run('kfx')
        self.assertTrue(any(name.startswith('regressions/') for name, _ in inputs))

    def test_epub(self):
        self._run('epub')

    def test_comicinfo(self):
        self._run('comicinfo')

    def test_every_target_is_run_here(self):
        found = sorted(name[len('fuzz_'):-len('.py')] for name in os.listdir(FUZZ)
                       if name.startswith('fuzz_') and name.endswith('.py'))
        self.assertEqual(sorted(TARGETS), found)

# vim: expandtab:sw=4:ts=4
