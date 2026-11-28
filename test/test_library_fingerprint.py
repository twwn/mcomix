"""What the library reads of a book to find its copies
(mcomix.library.fingerprint)."""

import io
import os
import shutil
import tarfile
import threading
import zipfile
from unittest import mock

from PIL import Image, ImageOps

from . import (MComixTest, damage_member, drawn_page, encoded,
               get_testfile_path, refuse_passwords)
from mcomix.library import fingerprint


def _picture(data):
    """What picture_of() keeps of the page whose file holds <data>."""
    return fingerprint.picture_of(io.BytesIO(data))[0]


class PictureTest(MComixTest):

    """The small picture kept of a page stays close for a copy of the
    page and lies far from another page."""

    def setUp(self):
        super().setUp()
        self.page = drawn_page(1)

    def _copies(self):
        """The page as a copy holds it, each by how it was changed."""
        width, height = self.page.size
        framed = Image.new('RGB', (width * 6 // 5, height * 6 // 5), 'white')
        framed.paste(self.page, (width // 10, height // 10))
        return {
            'half the size': encoded(
                self.page.resize((width // 2, height // 2)), 'PNG'),
            'compressed again': encoded(self.page, 'JPEG', quality=40),
            'in grey': encoded(self.page.convert('L'), 'PNG'),
            'in a white frame': encoded(framed, 'PNG'),
            'as a WebP': encoded(self.page, 'WEBP', quality=60),
        }

    def _other_pages(self):
        """Pages that are not this one."""
        others = {'page %d' % seed: encoded(drawn_page(seed), 'PNG')
                  for seed in (2, 3, 4)}
        others['the page mirrored'] = encoded(
            ImageOps.mirror(self.page), 'PNG')
        return others

    def test_a_copy_lies_much_closer_than_another_page(self):
        kept = _picture(encoded(self.page, 'PNG'))
        self.assertEqual(fingerprint.PICTURE_SIDE ** 2, len(kept))
        near = {name: fingerprint.difference(kept, _picture(data))
                for name, data in self._copies().items()}
        far = {name: fingerprint.difference(kept, _picture(data))
               for name, data in self._other_pages().items()}
        self.assertLess(max(near.values()) * 2, min(far.values()),
                        msg='copies %s, other pages %s' % (near, far))

    def test_a_transparent_page_is_seen_on_white(self):
        """As MComix shows it, so that its copy flattened on white is
        the same picture."""
        clear = self.page.convert('RGBA')
        clear.putalpha(Image.new('L', clear.size, 0))
        white = Image.new('RGB', clear.size, 'white')
        self.assertEqual(_picture(encoded(white, 'PNG')),
                         _picture(encoded(clear, 'PNG')))
        # Black under the clear parts, in the other transparent modes.
        grey = Image.new('LA', clear.size, (0, 0))
        indexed = Image.new('P', clear.size, 0)
        for name, page, options in (('grey with alpha', grey, {}),
                                    ('a palette with a clear colour',
                                     indexed, {'transparency': 0})):
            with self.subTest(name):
                self.assertEqual(_picture(encoded(white, 'PNG')),
                                 _picture(encoded(page, 'PNG', **options)))

    def test_a_plain_page_keeps_its_picture(self):
        """Nothing to cut, and nothing to stretch."""
        plain = _picture(encoded(Image.new('L', (40, 60), 200), 'PNG'))
        self.assertEqual(fingerprint.PICTURE_SIDE ** 2, len(plain))

    def test_missing_pictures_lie_as_far_apart_as_can_be(self):
        kept = _picture(encoded(self.page, 'PNG'))
        self.assertEqual(255, fingerprint.difference(b'', kept))
        self.assertEqual(255, fingerprint.difference(kept, b''))
        self.assertEqual(0, fingerprint.difference(kept, kept))


class MakeTest(MComixTest):

    """make() reads the fingerprint of a book's file."""

    def _pages(self, count):
        """<count> pages, by their names in the book, of three drawn
        pages in turn, a JPEG, a PNG and a JPEG."""
        drawn = [encoded(drawn_page(1), 'JPEG'),
                 encoded(drawn_page(2), 'PNG'),
                 encoded(drawn_page(3), 'JPEG')]
        return {'%02d.%s' % (number + 1, ('jpg', 'png')[number % 3 == 1]):
                drawn[number % 3] for number in range(count)}

    def _zip(self, pages, name='book.cbz'):
        path = os.path.join(self.tmp_dir, name)
        with zipfile.ZipFile(path, 'w') as book:
            # Not in order, which the samples are taken in all the same.
            for member in sorted(pages, reverse=True):
                book.writestr(member, pages[member])
        return path

    def _tar(self, pages, name='book.cbt'):
        path = os.path.join(self.tmp_dir, name)
        with tarfile.open(path, 'w') as book:
            for member, data in pages.items():
                info = tarfile.TarInfo(member)
                info.size = len(data)
                book.addfile(info, io.BytesIO(data))
        return path

    def test_the_first_pages_are_sampled_in_order(self):
        pages = self._pages(6)
        made = fingerprint.make(self._zip(pages))
        self.assertEqual(6, made.pages)
        self.assertEqual(fingerprint.SAMPLED, len(made.samples))
        self.assertEqual((600, 900), (made.samples[0].width,
                                      made.samples[0].height))
        first = sorted(pages)[:fingerprint.SAMPLED]
        self.assertEqual([_picture(pages[name]) for name in first],
                         [sample.picture for sample in made.samples])
        # The second sample is another picture than the first, the
        # fourth the same file as the first.
        self.assertNotEqual(made.samples[0].file_hash,
                            made.samples[1].file_hash)
        self.assertEqual(made.samples[0].file_hash,
                         made.samples[3].file_hash)

    def test_a_book_packed_again_keeps_its_samples(self):
        """A CBZ made a CBT: the pages' files are the same."""
        pages = self._pages(3)
        zipped = fingerprint.make(self._zip(pages))
        tarred = fingerprint.make(self._tar(pages))
        self.assertEqual(zipped.samples, tarred.samples)
        self.assertEqual(zipped.pages, tarred.pages)
        self.assertNotEqual(zipped.size, tarred.size)

    def test_only_pages_are_counted_and_sampled(self):
        """Not a text, nor the file macOS keeps beside each page, though
        both sort before the pages."""
        pages = self._pages(3)
        made = fingerprint.make(self._zip(pages))
        with_others = fingerprint.make(self._zip(
            pages | {'._01.jpg': b'resource fork', '00 notes.txt': b'notes'},
            'others.cbz'))
        self.assertEqual(made.pages, with_others.pages)
        self.assertEqual(made.samples, with_others.samples)

    def test_a_damaged_page_leaves_the_next_ones_sampled(self):
        pages = self._pages(3)
        path = self._zip(pages)
        damage_member(path, '01.jpg')
        made = fingerprint.make(path)
        self.assertEqual(3, made.pages)
        self.assertEqual([_picture(pages['02.png']), _picture(pages['03.jpg'])],
                         [sample.picture for sample in made.samples])

    def test_a_page_pillow_cannot_read_has_no_picture(self):
        made = fingerprint.make(self._zip({'01.png': b'not a picture'}))
        self.assertEqual(1, made.pages)
        sample, = made.samples
        self.assertEqual(b'', sample.picture)
        self.assertEqual(8, len(sample.file_hash))

    def test_what_is_no_book_has_none(self):
        text = os.path.join(self.tmp_dir, 'notes.txt')
        with open(text, 'w') as file:
            file.write('no pages')
        self.assertIsNone(fingerprint.make(text))

    def test_an_encrypted_book_asks_no_password(self):
        asked = refuse_passwords(self)
        made = fingerprint.make(get_testfile_path('archives', 'Encrypted.zip'))
        self.assertEqual([], asked)
        self.assertTrue(made is None or all(
            sample.picture == b'' for sample in made.samples), msg=made)

    def test_the_samples_are_stored_and_read_back(self):
        made = fingerprint.make(self._zip(self._pages(2)))
        self.assertEqual(made.samples, fingerprint.Fingerprint.unpacked_samples(
            made.packed_samples()))
        self.assertIsNone(fingerprint.Fingerprint.unpacked_samples(
            b'\x00' + made.packed_samples()[1:]))

    def test_a_fingerprint_is_of_the_file_as_it_was(self):
        path = self._zip(self._pages(1))
        made = fingerprint.make(path)
        self.assertTrue(fingerprint.is_current(made, path))
        os.utime(path, ns=(made.mtime + 10 ** 9, made.mtime + 10 ** 9))
        self.assertFalse(fingerprint.is_current(made, path))
        os.remove(path)
        self.assertFalse(fingerprint.is_current(made, path))

    def test_the_digest_is_of_every_byte(self):
        path = self._zip(self._pages(2))
        copy = os.path.join(self.tmp_dir, 'copy.cbz')
        shutil.copyfile(path, copy)
        other = self._zip(self._pages(3), 'other.cbz')
        self.assertEqual(fingerprint.digest(path), fingerprint.digest(copy))
        self.assertNotEqual(fingerprint.digest(path),
                            fingerprint.digest(other))
        stop = threading.Event()
        stop.set()
        self.assertIsNone(fingerprint.digest(path, stop))


class UpdateTest(MakeTest):

    """update() reads only the fingerprints that are not current."""

    def setUp(self):
        super().setUp()
        self.books = {number: self._zip(self._pages(number),
                                        'book-%d.cbz' % number)
                      for number in (1, 2, 3)}
        self.kept = {}
        self.read = self.enterContext(mock.patch.object(
            fingerprint, 'make', wraps=fingerprint.make))

    def _keep(self, book, made):
        self.kept[book] = made

    def test_the_books_without_one_are_read_and_kept(self):
        done = []
        found = fingerprint.update(self.books, {}, self._keep,
                                   threading.Event(),
                                   lambda *step: done.append(step))
        self.assertEqual({1, 2, 3}, set(found))
        self.assertEqual(found, self.kept)
        self.assertEqual([(1, 3), (2, 3), (3, 3)], done)
        self.assertEqual(2, found[2].pages)

    def test_a_current_one_is_not_read_again(self):
        stored = fingerprint.update(self.books, {}, self._keep,
                                    threading.Event())
        self.kept.clear()
        self.read.reset_mock()
        # The second book's file changes.
        with open(self.books[2], 'ab') as file:
            file.write(b'\0')
        found = fingerprint.update(self.books, stored, self._keep,
                                   threading.Event())
        self.read.assert_called_once_with(self.books[2])
        self.assertEqual([2], list(self.kept))
        self.assertEqual(stored[1], found[1])
        self.assertNotEqual(stored[2].size, found[2].size)

    def test_once_stopped_no_book_is_begun(self):
        stop = threading.Event()
        stop.set()
        found = fingerprint.update(self.books, {}, self._keep, stop)
        self.assertEqual({}, found)
        self.assertEqual({}, self.kept)
        self.read.assert_not_called()

    def test_a_book_that_fails_leaves_the_others(self):
        broken = os.path.join(self.tmp_dir, 'broken.cbz')
        with open(broken, 'wb') as file:
            file.write(b'PK\x03\x04 damaged')
        books = {**self.books, 4: broken}
        found = fingerprint.update(books, {}, self._keep, threading.Event())
        self.assertEqual({1, 2, 3}, set(found))
