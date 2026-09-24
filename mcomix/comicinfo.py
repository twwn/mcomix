"""comicinfo.py - The ComicInfo.xml a comic archive carries.

ComicInfo.xml is the metadata file at the root of a comic archive, and
the one thing every reader of them agrees on.  MComix does not take the
pages or their order from it - those are the archive's own business -
but it reads a few of its fields to tell the reader which comic a book
is, and it writes one into the archives it saves, because an archive
saved without one has lost whatever the archive it was made from had to
say about itself, and because the page sizes in it are what lets another
reader lay a book out before it has decoded anything.

Two fields are written here, PageCount and Pages, and they are the two
that describe the file rather than the work.  The rest of the format -
the series, the writer, the year the issue came out - is about the comic,
which is not something MComix knows and not something it should guess at.
An archive that came with those fields keeps every one of them: the file
is carried through as it is, and rewritten only where a page added or
removed has made its count untrue.
"""

import os
import xml.etree.ElementTree as ElementTree

from mcomix import image_tools

from collections.abc import Mapping, Sequence

#: What the file is called, and where a reader looks for it.
NAME = 'ComicInfo.xml'

#: The fields describe() reads, in the order a reader looks for them:
#: which series, which issue of it, what this one is called, and who
#: wrote it.
DESCRIBED = ('Series', 'Number', 'Title', 'Writer')

#: The most describe() reads, in bytes.  A ComicInfo.xml runs to a few
#: kilobytes even with the page list of a long book; a file far larger
#: than that is not metadata, and parsing it on the main thread would
#: hold the window up.
LARGEST = 1024 * 1024

#: The Type a reader expects to find on the first page of a book, which
#: is what it shows as the cover.
_FRONT_COVER = 'FrontCover'

#: The two namespaces the schema declares.  Every writer of these files
#: puts them on the root element whether or not anything uses them, and
#: some readers are unhappy without them.
_NAMESPACES = {
    'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    'xmlns:xsd': 'http://www.w3.org/2001/XMLSchema',
}


def carried(carried_files: Mapping[str, str]) -> "tuple[str, str] | None":
    """The (path, archive name) of a ComicInfo.xml among <carried_files>.

    None where the archive carried none.  Matched on the file name,
    without regard to case, wherever in the archive it sat: a file that
    is being carried is carried where it was, and putting one at the
    root because the specification says that is where it belongs would
    leave a second copy rather than move the first.
    """
    for path, name in sorted(carried_files.items(), key=lambda entry: entry[1]):
        if os.path.basename(name).lower() == NAME.lower():
            return path, name
    return None


def _page_element(number: int, path: str) -> ElementTree.Element:
    """The <Page> entry for the <number>th page, which is at <path>.

    Pages are counted from zero here, which is how the format counts
    them and not how MComix does.  A size that cannot be read is left
    out rather than written as zero: an attribute that is not there says
    "unknown", which is true, where a zero says the page is empty.
    """
    page = ElementTree.Element('Page')
    page.set('Image', str(number))
    try:
        page.set('ImageSize', str(os.path.getsize(path)))
    except OSError:
        pass
    width, height = image_tools.get_image_size(path)
    if width and height:
        page.set('ImageWidth', str(width))
        page.set('ImageHeight', str(height))
    if number == 0:
        page.set('Type', _FRONT_COVER)
    return page


def _describes(root: ElementTree.Element, page_count: int) -> bool:
    """Whether <root> already counts <page_count> pages.

    Both places it can say so have to agree with the book being written,
    since a reader may believe either.  A file that names no count at
    all describes any number of pages and is left alone: something wrote
    it meaning to say nothing about the pages.
    """
    counted = root.findtext('PageCount')
    if counted is not None:
        try:
            if int(counted.strip()) != page_count:
                return False
        except ValueError:
            return False
    listed = root.find('Pages')
    return listed is None or len(listed.findall('Page')) == page_count


def _parse(existing: bytes) -> "ElementTree.Element | None":
    """The root of <existing>, or None if it is not a ComicInfo.xml.

    Anything that does not parse, or that parses into some other
    document, is not something to edit in place: it is replaced, since
    whatever it was, it was not saying how many pages the book has.
    """
    try:
        root = ElementTree.fromstring(existing)
    except (ElementTree.ParseError, LookupError):
        # LookupError: the document declares an encoding Python's codecs
        # have no name for, which expat hands on rather than refusing.
        return None
    return root if root.tag == 'ComicInfo' else None


def describe(path: str) -> list[tuple[str, str]]:
    """What the ComicInfo.xml at <path> says about the comic.

    (field, text) pairs for those of the DESCRIBED fields it fills in, in
    that order.  A field that is missing or blank is left out, and a file
    that cannot be read, is larger than LARGEST or is not a ComicInfo
    describes nothing.  The file comes out of an archive and is not to be
    trusted: ElementTree fetches no external entities, and expat 2.4.1
    and later refuse the entity expansions that would blow a small file
    up in memory.
    """
    try:
        with open(path, 'rb') as handle:
            document = handle.read(LARGEST + 1)
    except OSError:
        return []
    if len(document) > LARGEST:
        return []
    root = _parse(document)
    if root is None:
        return []
    described = []
    for field in DESCRIBED:
        text = (root.findtext(field) or '').strip()
        if text:
            described.append((field, text))
    return described


def for_pages(image_files: Sequence[str],
              existing: "bytes | None" = None) -> "bytes | None":
    """The ComicInfo.xml an archive of <image_files> should hold.

    <existing> is what the archive being replaced carried under that
    name, or None where it carried nothing.  The answer is None where
    there is nothing to write: an existing file that already counts
    these pages is left exactly as it is, because everything it holds
    beyond the count - which page is the cover, which carries a
    bookmark, who drew it - is worth more than a rewrite that could only
    guess at it.

    Where the count no longer holds, PageCount and Pages are written
    again from the pages actually being saved and every other element is
    kept where it was.  The per-page entries cannot be kept: they are
    addressed by position, and nothing here can say which of the pages
    that are left is the one an entry was written for.
    """
    root = None if existing is None else _parse(existing)
    if root is not None and _describes(root, len(image_files)):
        return None
    if root is None:
        root = ElementTree.Element('ComicInfo')
    for name, value in _NAMESPACES.items():
        root.set(name, value)

    pages = root.find('Pages')
    count = root.find('PageCount')
    if count is None:
        count = ElementTree.Element('PageCount')
        # The schema is a sequence, and PageCount comes before Pages in
        # it, so appending both to a document that had neither puts them
        # in the right order and one that already has a Pages needs the
        # count put in front of it.
        if pages is None:
            root.append(count)
        else:
            root.insert(list(root).index(pages), count)
    count.text = str(len(image_files))

    if pages is None:
        # Pages is the last element of the sequence, so the end of the
        # document is where it belongs.
        pages = ElementTree.SubElement(root, 'Pages')
    else:
        pages.clear()
    pages.extend(_page_element(number, path)
                 for number, path in enumerate(image_files))

    ElementTree.indent(root)
    # tostring() is overloaded on the encoding and typed as returning
    # Any for the one that gives bytes back, which naming the type here
    # pins down without a cast.
    document: bytes = ElementTree.tostring(root, encoding='utf-8',
                                           xml_declaration=True)
    return document

# vim: expandtab:sw=4:ts=4
