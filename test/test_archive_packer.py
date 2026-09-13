# -*- coding: utf-8 -*-

"""Packing the pages of an edited archive into a new one.

The pages are renamed so that their names sort the way the editor put
them, and the files that came with them keep the names they had unless
one of the pages has taken it.
"""

import os
import zipfile

from . import MComixTest, get_testfile_path

from mcomix import archive_packer


class PackerTest(MComixTest):

    def setUp(self):
        super(PackerTest, self).setUp()
        self.pages = [get_testfile_path('images', name)
                      for name in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg',
                                   '03-PNG-RGB.png')]
        self.comment = os.path.join(self.tmp_dir, 'comment.txt')
        with open(self.comment, 'w') as comment:
            comment.write('a comment')
        self.archive = os.path.join(self.tmp_dir, 'packed.zip')

    def _pack(self, base_name, other_files=()):
        packer = archive_packer.Packer(self.pages, list(other_files),
                                       self.archive, base_name)
        packer.pack()
        return packer.wait()

    def _names(self):
        with zipfile.ZipFile(self.archive) as packed:
            return packed.namelist()

    def test_the_pages_are_numbered_in_the_order_they_were_given(self):
        self.assertTrue(self._pack('Comic'))
        self.assertEqual(['1 - Comic.jpg', '2 - Comic.jpg', '3 - Comic.png'],
                         self._names())

    def test_a_name_with_a_per_cent_sign_in_it_is_a_name_like_any_other(self):
        # The number and the extension used to be spliced into a format
        # string that the name itself had already been spliced into, so
        # a per cent sign in the name was read as a format of its own:
        # "My%20Comic", which is what a download names a file, raised
        # ValueError out of the packer thread and left the archive open.
        self.assertTrue(self._pack('My%20Comic'))
        self.assertEqual(['1 - My%20Comic.jpg', '2 - My%20Comic.jpg',
                          '3 - My%20Comic.png'], self._names())

    def test_the_numbers_are_padded_to_sort_lexically(self):
        packer = archive_packer.Packer(self.pages * 4, [], self.archive, 'C')
        packer.pack()
        self.assertTrue(packer.wait())
        self.assertTrue(self._names()[0].startswith('01 - '))

    def test_the_other_files_keep_their_names(self):
        self.assertTrue(self._pack('Comic', [self.comment]))
        self.assertIn('comment.txt', self._names())

    def test_a_file_whose_name_a_page_has_taken_is_moved_aside(self):
        taken = os.path.join(self.tmp_dir, '1 - Comic.jpg')
        with open(taken, 'w') as clash:
            clash.write('not a page')
        self.assertTrue(self._pack('Comic', [taken]))
        self.assertIn('_1 - Comic.jpg', self._names())

    def test_a_page_that_is_not_there_leaves_no_half_written_archive(self):
        packer = archive_packer.Packer(self.pages + ['/no/such/page.jpg'], [],
                                       self.archive, 'Comic')
        packer.pack()
        self.assertFalse(packer.wait())
        self.assertFalse(os.path.exists(self.archive),
                         'the half-written archive was left behind')


# vim: expandtab:sw=4:ts=4
