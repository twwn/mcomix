"""The ComicInfo.xml MComix writes into the archives it saves.

Two fields go in it, PageCount and Pages, because those are the two that
describe the file rather than the comic.  An archive that already
carries one keeps it untouched unless the pages it counts are no longer
the pages being written.
"""

import os
import tempfile
import xml.etree.ElementTree as ElementTree
import zipfile

from . import MComixTest, get_testfile_path

from mcomix import archive_tools
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

    def test_a_file_in_an_encoding_python_does_not_know_is_replaced(self):
        """The LookupError came out of saving the archive as well."""
        root = ElementTree.fromstring(comicinfo.for_pages(
            self.pages,
            b'<?xml version="1.0" encoding="x-unknown"?><ComicInfo/>'))
        self.assertEqual(str(len(self.pages)), root.findtext('PageCount'))

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



class DescribeTest(MComixTest):

    """What describe() reads out of a ComicInfo.xml for the reader."""

    def _describe(self, document):
        path = os.path.join(self.tmp_dir, 'ComicInfo.xml')
        with open(path, 'wb') as handle:
            handle.write(document if isinstance(document, bytes)
                         else document.encode('utf-8'))
        return comicinfo.describe(path)

    def test_the_fields_come_in_the_order_a_reader_looks_for_them(self):
        self.assertEqual(
            [('Series', 'Night Watch'), ('Number', '3'),
             ('Title', 'The Long Night'), ('Writer', 'A. Writer')],
            self._describe('<ComicInfo><Writer>A. Writer</Writer>'
                           '<Title>The Long Night</Title><Number>3</Number>'
                           '<Series>Night Watch</Series></ComicInfo>'))

    def test_a_field_that_is_missing_or_blank_is_left_out(self):
        self.assertEqual(
            [('Series', 'Night Watch')],
            self._describe('<ComicInfo><Series> Night Watch </Series>'
                           '<Title>   </Title></ComicInfo>'))

    def test_the_page_list_is_not_something_to_describe(self):
        self.assertEqual([], self._describe(comicinfo.for_pages(
            [get_testfile_path('images', '01-JPG-Indexed.jpg')])))

    def test_a_file_that_is_not_xml_describes_nothing(self):
        self.assertEqual([], self._describe('<ComicInfo><Series>Broken'))

    def test_a_file_in_an_encoding_python_does_not_know_describes_nothing(self):
        """expat hands the declared encoding to Python's codecs, and a
        name they do not know raised LookupError, past the ParseError
        the parsing was guarded for: the properties dialog failed on
        such a book."""
        self.assertEqual([], self._describe(
            b'<?xml version="1.0" encoding="x-unknown"?>'
            b'<ComicInfo><Series>S</Series></ComicInfo>'))

    def test_a_document_that_is_not_a_comicinfo_describes_nothing(self):
        self.assertEqual([], self._describe('<Book><Series>Other</Series></Book>'))

    def test_a_file_that_cannot_be_read_describes_nothing(self):
        self.assertEqual([], comicinfo.describe(
            os.path.join(self.tmp_dir, 'missing.xml')))

    def test_a_file_too_large_to_be_metadata_is_not_read(self):
        padding = b'<!--' + b'x' * comicinfo.LARGEST + b'-->'
        self.assertEqual([], self._describe(
            b'<ComicInfo><Series>Night Watch</Series>' + padding
            + b'</ComicInfo>'))


class SampleComicTest(MComixTest):

    """test/files/pepper-and-carrot, the one book with real pages.

    It is Pepper&Carrot, licensed CC BY 4.0, so it may only be kept with
    its attribution: the README beside it and the ComicInfo.xml inside it
    both have to go on naming the author and the licence.
    """

    DIRECTORY = get_testfile_path('pepper-and-carrot')
    BOOK = os.path.join(DIRECTORY, 'Pepper-and-Carrot_E01_The-Potion-of-Flight.cbz')

    def test_the_book_has_its_four_pages(self):
        _mime, pages, _size = archive_tools.get_archive_info(self.BOOK)
        self.assertEqual(4, pages)

    def test_its_comicinfo_describes_the_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            with zipfile.ZipFile(self.BOOK) as archive:
                path = archive.extract(comicinfo.NAME, directory)
            self.assertEqual([('Series', 'Pepper&Carrot'), ('Number', '1'),
                              ('Title', 'The Potion of Flight'),
                              ('Writer', 'David Revoy')],
                             comicinfo.describe(path))
            with open(path, encoding='utf-8') as fp:
                document = fp.read()
        self.assertIn('Creative Commons Attribution 4.0', document)

    def test_the_readme_attributes_it(self):
        with open(os.path.join(self.DIRECTORY, 'README.md'),
                  encoding='utf-8') as fp:
            readme = fp.read()
        for required in ('David Revoy', 'CC BY 4.0',
                         'https://creativecommons.org/licenses/by/4.0/',
                         'https://www.peppercarrot.com',
                         'Changes made for MComix'):
            with self.subTest(required=required):
                self.assertIn(required, readme)

# vim: expandtab:sw=4:ts=4
