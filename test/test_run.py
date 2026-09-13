"""What the program does before it has a window to say it in."""

import unittest.mock

import gi

from . import MComixTest

from mcomix import run


class DependencyCheckTest(MComixTest):

    """setup_dependencies() reports a missing dependency rather than
    letting it out as a traceback."""

    def _fail_with(self, error):
        with unittest.mock.patch.object(gi, 'require_version',
                                        side_effect=error):
            with self.assertRaises(SystemExit) as caught:
                run.setup_dependencies()
        return caught.exception

    def test_an_unavailable_namespace_exits_with_a_message(self):
        # This is what gi.require_version() raises, and the only thing it
        # documents raising.
        exit = self._fail_with(
            ValueError('Namespace Gtk not available for version 4.0'))
        self.assertEqual(1, exit.code)

    def test_a_namespace_already_loaded_elsewhere_exits_too(self):
        exit = self._fail_with(
            ValueError('Namespace Gtk is already loaded with version 3.0'))
        self.assertEqual(1, exit.code)


class ArgumentTest(MComixTest):

    """The command line, which is also how MComix asks another MComix to
    open something: a middle click on a bookmark starts one with the
    bookmark's file and its page."""

    def test_a_book_is_opened_at_its_first_page_by_default(self):
        opts, args = run.parse_arguments(['/books/one.cbz'])
        self.assertEqual(args, ['/books/one.cbz'])
        self.assertEqual(opts.page, 0)

    def test_a_page_can_be_named(self):
        opts, args = run.parse_arguments(['--page', '7', '/books/one.cbz'])
        self.assertEqual(args, ['/books/one.cbz'])
        self.assertEqual(opts.page, 7)

    def test_a_page_that_is_not_a_number_is_refused(self):
        with self.assertRaises(SystemExit):
            run.parse_arguments(['--page', 'seven', '/books/one.cbz'])


# vim: expandtab:sw=4:ts=4
