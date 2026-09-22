"""The version the Windows builds stamp on what they build.

MComix is numbered by year and month, as 26.10, and both WiX and the
version resource of the executable want three numbers.  The scripts
under win32/ only ever run on Windows, at release time, so a version
they cannot read would first be found there; these tests run the part
that reads it here.
"""

import os
import shutil
import sys
import unittest.mock

from . import MComixTest

WIN32 = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))), 'win32')
sys.path.insert(0, WIN32)
try:
    import build_msi
    import build_pyinstaller
finally:
    sys.path.remove(WIN32)


class VersionTripletTest(MComixTest):

    def test_a_year_and_a_month_get_a_third_number(self):
        self.assertEqual((26, 10, 0), build_msi.version_triplet('26.10'))

    def test_three_numbers_are_kept(self):
        self.assertEqual((26, 10, 1), build_msi.version_triplet('26.10.1'))
        self.assertEqual((4, 0, 1), build_msi.version_triplet('4.0.1'))

    def test_a_suffix_is_left_out(self):
        self.assertEqual((26, 10, 0),
                         build_msi.version_triplet('26.10-dev0'))

    def test_no_number_at_all_is_an_error(self):
        with self.assertRaises(ValueError):
            build_msi.version_triplet('unknown')

    def test_wix_is_given_three_numbers(self):
        with unittest.mock.patch.object(build_msi, 'VERSION', '26.10'):
            self.assertEqual('26.10.0', build_msi.normalize_mcomix_version())


class VersionFileTest(MComixTest):

    """The version resource PyInstaller embeds in MComix.exe."""

    def test_a_year_and_a_month_are_written_as_four_numbers(self):
        os.mkdir(os.path.join(self.tmp_dir, 'win32'))
        shutil.copy(os.path.join(WIN32, 'version_file.template'),
                    os.path.join(self.tmp_dir, 'win32'))
        cwd = os.getcwd()
        os.chdir(self.tmp_dir)
        self.addCleanup(os.chdir, cwd)

        with unittest.mock.patch.object(build_pyinstaller.constants,
                                        'VERSION', '26.10'), \
                unittest.mock.patch('builtins.print'):
            build_pyinstaller.prepare_version_file()

        with open(os.path.join('win32', 'version_file.txt')) as fp:
            written = fp.read()
        self.assertIn('filevers=(26, 10, 0, 0)', written)
        self.assertIn('prodvers=(26, 10, 0, 0)', written)


# vim: expandtab:sw=4:ts=4
