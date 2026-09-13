"""The ComicInfo.xml MComix writes into the archives it saves.

Two fields go in it, PageCount and Pages, because those are the two that
describe the file rather than the comic.  An archive that already
carries one keeps it untouched unless the pages it counts are no longer
the pages being written.
"""

import os
import xml.etree.ElementTree as ElementTree

from . import MComixTest, get_testfile_path

from mcomix import comicinfo


class ForPagesTest(MComixTest):

    """What for_pages() writes, and when it writes nothing."""

    def setUp(self):
        super().setUp()
        self.pages = [get_testfile_path('images', name)
                      for name in ('01-JPG-Indexed.jpg', '02-JPG-RGB.jpg',
                                   '03-PNG-RGB.png')]

    def _written(self, existing=None):
        """The root element for_pages() produces, or None."""
        document = comicinfo.for_pages(self.pages, existing)
        return None if document is None else ElementTree.fromstring(document)

    def test_a_book_with_no_metadata_gets_a_count_and_its_pages(self):
        root = self._written()
        self.assertEqual('3', root.findtext('PageCount'))
        pages = root.find('Pages').findall('Page')
        self.assertEqual(['0', '1', '2'],
                         [page.get('Image') for page in pages])

    def test_every_page_carries_the_size_it_was_written_at(self):
        pages = self._written().find('Pages').findall('Page')
        for page, path in zip(pages, self.pages):
            with self.subTest(page=page.get('Image')):
                self.assertEqual(str(os.path.getsize(path)),
                                 page.get('ImageSize'))
                self.assertTrue(int(page.get('ImageWidth')) > 0)
                self.assertTrue(int(page.get('ImageHeight')) > 0)

    def test_the_first_page_is_marked_as_the_cover(self):
        pages = self._written().find('Pages').findall('Page')
        self.assertEqual('FrontCover', pages[0].get('Type'))
        self.assertIsNone(pages[1].get('Type'))

    def test_the_document_says_it_is_a_utf_8_xml_file(self):
        document = comicinfo.for_pages(self.pages)
        self.assertTrue(document.startswith(b'<?xml '), document[:40])
        self.assertIn(b"encoding='utf-8'", document[:60])

    def test_the_root_declares_the_two_namespaces_of_the_schema(self):
        document = comicinfo.for_pages(self.pages)
        self.assertIn(b'http://www.w3.org/2001/XMLSchema-instance', document)
        self.assertIn(b'http://www.w3.org/2001/XMLSchema', document)

    def test_one_that_already_counts_these_pages_is_left_alone(self):
        """Everything in it beyond the count is worth more than a rewrite
        that could only guess at it."""
        existing = (b'<ComicInfo><Series>S</Series><PageCount>3</PageCount>'
                    b'</ComicInfo>')
        self.assertIsNone(comicinfo.for_pages(self.pages, existing))

    def test_one_that_says_nothing_about_the_pages_is_left_alone(self):
        """Something wrote it meaning to describe the comic and not the
        file, and no page was added or removed to make it wrong."""
        self.assertIsNone(comicinfo.for_pages(
            self.pages, b'<ComicInfo><Writer>W</Writer></ComicInfo>'))

    def test_a_count_a_deletion_has_invalidated_is_written_again(self):
        root = self._written(b'<ComicInfo><PageCount>7</PageCount></ComicInfo>')
        self.assertEqual('3', root.findtext('PageCount'))

    def test_a_page_list_a_deletion_has_invalidated_is_written_again(self):
        """The count and the list can disagree, and a reader may believe
        either of them."""
        root = self._written(
            b'<ComicInfo><PageCount>3</PageCount><Pages>'
            b'<Page Image="0"/><Page Image="1"/></Pages></ComicInfo>')
        self.assertEqual(
            3, len(root.find('Pages').findall('Page')))

    def test_everything_the_rewrite_does_not_describe_is_kept(self):
        root = self._written(
            b'<ComicInfo><Series>Sandman</Series><Number>8</Number>'
            b'<PageCount>7</PageCount></ComicInfo>')
        self.assertEqual('Sandman', root.findtext('Series'))
        self.assertEqual('8', root.findtext('Number'))

    def test_the_count_is_written_in_front_of_the_page_list(self):
        """The schema is a sequence: PageCount comes before Pages in it,
        and a document that carried a list but no count would otherwise
        have the count appended after it."""
        document = comicinfo.for_pages(self.pages, (
            b'<ComicInfo><Pages><Page Image="0"/></Pages></ComicInfo>'))
        self.assertLess(document.index(b'<PageCount>'),
                        document.index(b'<Pages>'))

    def test_a_file_that_is_not_xml_is_replaced(self):
        root = self._written(b'this was never a ComicInfo.xml')
        self.assertEqual('3', root.findtext('PageCount'))

    def test_a_file_that_is_xml_but_not_a_comicinfo_is_replaced(self):
        root = self._written(b'<package><metadata/></package>')
        self.assertEqual('ComicInfo', root.tag)
        self.assertEqual('3', root.findtext('PageCount'))

    def test_a_page_that_cannot_be_measured_is_still_counted(self):
        """A page is written into the archive whether its header can be
        read or not, so leaving it out of the count would make the count
        the wrong one."""
        broken = os.path.join(self.tmp_dir, 'broken.jpg')
        with open(broken, 'wb') as fp:
            fp.write(b'not a picture')
        self.pages.append(broken)
        root = self._written()
        pages = root.find('Pages').findall('Page')
        self.assertEqual('4', root.findtext('PageCount'))
        self.assertEqual(4, len(pages))
        self.assertIsNone(pages[3].get('ImageWidth'))
        self.assertEqual(str(os.path.getsize(broken)),
                         pages[3].get('ImageSize'))


class CarriedTest(MComixTest):

    """Finding the ComicInfo.xml an archive was already carrying."""

    def test_nothing_is_found_where_the_archive_carried_none(self):
        self.assertIsNone(comicinfo.carried({'/tmp/a': 'cover.jpg'}))

    def test_the_name_is_matched_whatever_case_it_was_written_in(self):
        self.assertEqual(('/tmp/a', 'comicinfo.xml'),
                         comicinfo.carried({'/tmp/a': 'comicinfo.xml'}))

    def test_one_in_a_directory_of_its_own_is_found_where_it_sits(self):
        self.assertEqual(('/tmp/a', 'meta/ComicInfo.xml'),
                         comicinfo.carried({'/tmp/a': 'meta/ComicInfo.xml'}))

    def test_the_one_at_the_root_wins_over_one_further_in(self):
        self.assertEqual(
            ('/tmp/a', 'ComicInfo.xml'),
            comicinfo.carried({'/tmp/b': 'meta/ComicInfo.xml',
                               '/tmp/a': 'ComicInfo.xml'}))

# vim: expandtab:sw=4:ts=4
