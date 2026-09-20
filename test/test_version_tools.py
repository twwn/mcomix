import unittest

from mcomix.version_tools import Version


class TestVersion(unittest.TestCase):

    def assertOrdered(self, versions) -> None:
        """Check that <versions> is in strictly ascending order."""
        for lower, higher in zip(versions, versions[1:]):
            self.assertLess(Version(lower), Version(higher),
                            '%s should sort before %s' % (lower, higher))
            self.assertGreater(Version(higher), Version(lower))
            self.assertNotEqual(Version(lower), Version(higher))

    def test_numeric_components_are_ordered_as_numbers(self) -> None:
        self.assertOrdered(['0.9', '1.6', '1.7', '1.8', '1.9', '1.10', '2.0'])

    def test_more_specific_version_sorts_after(self) -> None:
        self.assertOrdered(['1.8', '1.8.1', '1.8.2', '1.9'])

    def test_pre_releases_sort_before_their_release(self) -> None:
        self.assertOrdered(['1.8dev1', '1.8a1', '1.8b1', '1.8rc1', '1.8'])
        self.assertOrdered(['1.24.9-rc1', '1.24.9'])

    def test_trailing_zeroes_are_insignificant(self) -> None:
        self.assertEqual(Version('1.8'), Version('1.8.0'))
        self.assertEqual(Version('1'), Version('1.0.0'))
        self.assertEqual(hash(Version('1.8')), hash(Version('1.8.0')))

    def test_minimum_version_checks(self) -> None:
        # The comparisons MComix actually makes.
        self.assertTrue(Version('1.24.10') >= Version('1.19.2'))
        self.assertTrue(Version('1.24.9') >= Version('1.8'))
        self.assertTrue(Version('1.7') >= Version('1.7'))
        self.assertFalse(Version('1.6') >= Version('1.8'))

    def test_unparseable_version_does_not_raise(self) -> None:
        self.assertNotEqual(Version('unknown'), Version('1.8'))
        self.assertEqual(Version('unknown'), Version('unknown'))
        self.assertIsInstance(Version('') < Version('1.8'), bool)

    def test_a_digit_int_cannot_parse_does_not_raise(self) -> None:
        # str.isdigit() is true of "\u00b2", and int() refuses it.
        self.assertIsInstance(Version('1.\u00b2') < Version('1.8'), bool)

    def test_str_returns_the_original_string(self) -> None:
        self.assertEqual(str(Version('1.24.9-rc1')), '1.24.9-rc1')

    def test_comparison_with_other_types_is_not_supported(self) -> None:
        self.assertNotEqual(Version('1.8'), '1.8')
        self.assertRaises(TypeError, lambda: Version('1.8') < '1.8')

# vim: expandtab:sw=4:ts=4
