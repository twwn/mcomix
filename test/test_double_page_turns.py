"""Which pages double page mode shows together, turning either way.

Turning forward, a narrow page just before a wide one is shown on its
own, and whether it is depends on how the run of narrow pages before it
was paired.  Turning back used to pair the two pages before the current
one wherever it could, so a book showed other spreads going back than
it had going forward: a folder of three narrow pages and then two wide
ones read 1+2, 3, 4, 5 forward and 5, 4, 2+3, 1+2 back.
"""

import os
import shutil
import unittest.mock
import zipfile

from . import MComixTest, get_testfile_path, pump, wait_for

from mcomix import constants, icons, main
from mcomix.preferences import prefs

_PAGES = {'N': get_testfile_path('images', 'portrait-no-exif.png'),
          'W': get_testfile_path('images', 'landscape-no-exif.png')}


class DoublePageTurnsTest(MComixTest):

    def setUp(self):
        super().setUp()
        for directory in (constants.CONFIG_DIR, constants.DATA_DIR,
                          constants.THUMBNAIL_PATH):
            os.makedirs(directory, exist_ok=True)
        icons.load_icons()
        prefs['default double page'] = True
        self.window = None

    def tearDown(self):
        if self.window is not None:
            self.window.terminate_program()
            self.window.destroy()
            main.set_main_window(None)
            pump()
        super().tearDown()

    def _open(self, layout, archive=False):
        """Open a book of narrow (N) and wide (W) pages, all extracted."""
        if archive:
            path = os.path.join(self.tmp_dir, layout + '.cbz')
            with zipfile.ZipFile(path, 'w') as book:
                for number, kind in enumerate(layout, 1):
                    book.write(_PAGES[kind], '%02d.png' % number)
        else:
            folder = os.path.join(self.tmp_dir, layout)
            os.mkdir(folder)
            for number, kind in enumerate(layout, 1):
                shutil.copy(_PAGES[kind],
                            os.path.join(folder, '%02d.png' % number))
            path = os.path.join(folder, '01.png')
        self.window = main.MainWindow(open_path=path)
        main.set_main_window(self.window)
        handler = self.window.imagehandler
        wait_for(lambda: handler.get_number_of_pages() == len(layout),
                 seconds=20)
        wait_for(lambda: all(handler.page_is_available(page)
                             for page in range(1, len(layout) + 1)),
                 seconds=20)
        pump()

    def _shown(self):
        page = self.window.imagehandler.get_current_page()
        if self.window.displayed_double():
            return '%d+%d' % (page, page + 1)
        return str(page)

    def _turn(self, step, single_step=False):
        self.window.flip_page(step, single_step=single_step)
        pump()
        return self._shown()

    def _both_ways(self):
        """The spreads shown turning to the end, and back to the start."""
        last = self.window.imagehandler.get_number_of_pages()
        forward = [self._shown()]
        while self.window.imagehandler.get_current_page() + \
                self.window.displayed_double() < last:
            forward.append(self._turn(+1))
        back = []
        while self.window.imagehandler.get_current_page() > 1:
            back.append(self._turn(-1))
        return forward, back

    def _assert_the_same_spreads(self, layout, archive=False):
        self._open(layout, archive)
        forward, back = self._both_ways()
        self.assertEqual(back, forward[-2::-1],
                         'forward %s, back %s' % (forward, back))

    def test_back_shows_the_spreads_seen_forward_in_a_folder(self):
        self._assert_the_same_spreads('NNNWWN')

    def test_back_shows_the_spreads_seen_forward_in_an_archive(self):
        # The title page stands on its own in an archive, which moves
        # the pairing of every run after it by one.
        self._assert_the_same_spreads('NNNNWWN', archive=True)

    def test_back_shows_the_spreads_seen_forward_past_two_wide_pages(self):
        self._assert_the_same_spreads('NNNWNNNWN')

    def test_back_after_a_single_step_shows_nothing_on_screen_again(self):
        """A single step moves the pairing by one page.  The pairing
        forward from the start of the book would then put the page
        before the one on screen with the page on screen; the turn
        back pairs the two before it instead."""
        self._open('NNNNNN')
        self.assertEqual(self._turn(+1), '3+4')
        self.assertEqual(self._turn(+1, single_step=True), '4+5')
        self.assertEqual(self._turn(-1), '2+3')

    def test_back_before_the_pages_are_extracted_pairs_the_two_before(self):
        """The pairing forward needs the size of every page back to the
        last wide one; with one of them not out of the archive yet, the
        two pages before the current one are paired where they can be,
        as they always were."""
        self._open('NNNWWN')
        handler = self.window.imagehandler
        self.window.set_page(4)
        pump()
        available = handler.page_is_available

        def not_page_one(page=None):
            return page != 1 and available(page)

        with unittest.mock.patch.object(handler, 'page_is_available',
                                        not_page_one):
            self.assertEqual(self.window._previous_spread(4), 2)

    def test_back_past_a_wide_page_after_a_single_step_stops_after_it(self):
        """After a single step the spread before the pages on screen
        would reach into them, and the page before that is wide: the
        turn back lands on the page after the wide one rather than
        skipping it."""
        self._open('NWNNN')
        self.assertEqual(self._turn(+1), '2')
        self.assertEqual(self._turn(+1), '3+4')
        self.assertEqual(self._turn(+1, single_step=True), '4+5')
        self.assertEqual(self.window._previous_spread(4), 3)

# vim: expandtab:sw=4:ts=4
