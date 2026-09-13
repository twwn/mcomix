# -*- coding: utf-8 -*-

"""Opening the dialogs that only show something and close again.

dialog_handler keeps one of each at a time, so a second request brings
the open one forward rather than stacking a copy behind it.
"""

from gi.repository import Gtk

from . import MComixTest, pump

from mcomix import dialog_handler


class OneAtATimeTest(MComixTest):

    NAME = 'about-dialog'

    def setUp(self):
        super(OneAtATimeTest, self).setUp()
        self.window = Gtk.Window()

    def tearDown(self):
        # Anything left open is answered by whatever looks for a window
        # next, so close through the handler and then make sure.
        dialog_handler._close_dialog(None, self.NAME)
        for name in list(dialog_handler._open_dialogs):
            dialog_handler._close_dialog(None, name)
        self.window.destroy()
        pump()
        super(OneAtATimeTest, self).tearDown()

    def _open(self):
        dialog_handler.open_dialog(None, (self.window, self.NAME))
        return dialog_handler._open_dialogs.get(self.NAME)

    def test_opening_one_registers_it(self):
        dialog = self._open()
        self.assertIsNotNone(dialog, 'the dialog was not opened')
        self.assertIsInstance(dialog, Gtk.AboutDialog)

    def test_opening_it_twice_keeps_the_first(self):
        first = self._open()
        second = self._open()
        self.assertIs(first, second, 'a second copy was stacked on the first')
        self.assertEqual(1, len(dialog_handler._open_dialogs))

    def test_closing_it_lets_the_next_open_build_a_new_one(self):
        first = self._open()
        dialog_handler._close_dialog(first, self.NAME)
        self.assertNotIn(self.NAME, dialog_handler._open_dialogs,
                         'a closed dialog was left in the register')
        second = self._open()
        self.assertIsNot(first, second, 'the destroyed dialog was reopened')

    def test_closing_a_name_that_is_not_open_does_nothing(self):
        dialog_handler._close_dialog(None, self.NAME)
        self.assertEqual({}, dialog_handler._open_dialogs)


# vim: expandtab:sw=4:ts=4
