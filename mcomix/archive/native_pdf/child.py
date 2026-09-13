"""Child process code for native PDF multiprocessing."""

import io
import os
import multiprocessing as mp
from PIL import Image, ExifTags
from collections.abc import Iterator

try:
    import pymupdf
except ImportError:
    # PyMuPDF only gained its own name in 1.24.3.  Before that it was
    # importable as "fitz" alone, a name it shares with an unrelated
    # package on PyPI.
    import fitz as pymupdf  # type: ignore[no-redef,import-untyped]

from mcomix.constants import PDF_RENDER_DPI_DEF


# Will delimit the page name from the xref part of a file name
XREF_DELIMITER = '_mcmxref'

#: The Exif orientation that shows a page turned by the PDF's rotation.
EXIF_ORIENTATIONS = {
    90: 6,
    180: 3,
    270: 8,
}

#: The image types a turned page is extracted as with its orientation in
#: it.  Pillow writes no Exif into the other types an embedded image can
#: come as, such as JPEG 2000, so a turned page of one of those is
#: converted to PNG.
EXIF_CARRIERS = ('jpeg', 'png')


def jpeg_with_orientation(jpeg: bytes, orientation: int) -> bytes:
    """<jpeg>, the bytes of a JPEG file, with its Exif orientation set to
    <orientation>.

    Only the Exif segment is written anew, keeping whatever else it held;
    every other segment and the compressed image are copied as they are,
    where saving the picture again would compress it again.  Raises
    ValueError for data that is not a JPEG file, or whose Exif cannot be
    read or does not fit a segment.
    """
    if not jpeg.startswith(b'\xff\xd8'):
        raise ValueError('not a JPEG file')
    exif = Image.Exif()
    segments: list[bytes] = []
    position = 2
    while True:
        if jpeg[position:position + 1] != b'\xff':
            raise ValueError('no JPEG marker at byte %d' % position)
        marker = jpeg[position + 1]
        if marker == 0xFF:
            # A fill byte ahead of the marker.
            position += 1
            continue
        if marker in (0xDA, 0xD9):
            # The compressed image, or the end: copied from here on.
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            # A marker without a length.
            segments.append(jpeg[position:position + 2])
            position += 2
            continue
        size = int.from_bytes(jpeg[position + 2:position + 4], 'big')
        segment = jpeg[position:position + 2 + size]
        if marker == 0xE1 and segment[4:10] == b'Exif\x00\x00':
            try:
                exif.load(segment[4:])
            except Exception as error:
                raise ValueError('unreadable Exif') from error
        else:
            segments.append(segment)
        position += 2 + size
    exif[ExifTags.Base.Orientation] = orientation
    payload = exif.tobytes()
    if not payload.startswith(b'Exif\x00\x00'):
        payload = b'Exif\x00\x00' + payload
    if len(payload) + 2 > 0xFFFF:
        raise ValueError('Exif too large for a JPEG segment')
    exif_segment = b'\xff\xe1' + (len(payload) + 2).to_bytes(2, 'big') + payload
    # A JFIF file has to start with its APP0 segment.
    first = 1 if segments and segments[0][1] == 0xE0 else 0
    return (b'\xff\xd8' + b''.join(segments[:first]) + exif_segment
            + b''.join(segments[first:]) + jpeg[position:])


class FitzWorker:

    """A PDF open in this process, which is one MComix did not start in.

    PyMuPDF is a C library with global state, and a page that cannot be
    parsed can take the interpreter down with it, so the whole of it is
    kept out of the process drawing the window: this class is what runs
    on the other side of the manager.
    """

    def __init__(self, filename: str | None, log_level: int | None = None) -> None:
        self._extension: str | None = None
        self._complex_doc = False
        self.log = mp.get_logger()
        if log_level is not None:
            self.log.setLevel(log_level)
        self.doc = pymupdf.open(filename)

    def page_count(self) -> int:
        """How many pages the document has."""
        return int(self.doc.page_count)

    def _image_extension(self, xref: int) -> str:
        """Return the filename extension for extracted page images."""
        if self._extension is None:
            self._extension = self._check_image_type(xref)
        return self._extension

    def _extractable_image(self, page_num: int) -> tuple[int, int] | None:
        """Return the xref of the image to extract for <page_num> and the
        page's rotation, or None if the page has to be rendered to a pixmap
        instead.

        Rendering has to be forced if any of these apply:
            - The page has any text content
            - The page has any drawing content
            - The page contains 0, or more than 1, embedded image
            - The single embedded image does not cover the whole page

        Only the first of those makes the whole document complex: a page
        carrying text or drawings marks the document as one to be rendered
        throughout, whereas a page whose image happens not to be full-page
        says nothing about its neighbours.

        The page is loaded, and its image list taken, exactly once.  For a
        document of scanned pages this runs for every page in it, so the
        repeated loads and lookups this replaces made up the bulk of the
        cost of listing one.
        """
        if self._complex_doc:
            return None
        page = self.doc[page_num]
        images = page.get_images()
        if len(images) != 1 or page.get_text():
            self._complex_doc = True
            self.log.debug("PDF page %d, must render page", page_num + 1)
            return None
        self.log.debug("PDF page %d, rendering not forced", page_num + 1)

        # The image list says what the page carries, not what it shows, so
        # take a closer look at the single image's placement before
        # deciding that extracting it can stand in for rendering the page.
        image_info = page.get_image_info()
        if len(image_info) != 1:
            self.log.debug(
                "PDF page %d, cannot extract. Image count = %d",
                page_num + 1, len(image_info))
            return None
        img_rect = pymupdf.Rect(image_info[0].get('bbox', (0, 0, 0, 0))).irect
        page_rect = pymupdf.Rect(page.mediabox).irect
        page_area = page_rect.get_area()
        if abs(page_area - img_rect.get_area()) >= 0.05 * page_area:
            self.log.debug(
                'PDF page %d, cannot extract image: %s',
                page_num + 1, f"img_rect={img_rect}, page_rect={page_rect}")
            return None
        self.log.debug('PDF page %d: can extract fullpage image', page_num + 1)
        return int(images[0][0]), int(page.rotation)

    def _check_image_type(self, xref: int) -> str:
        """Examine an embedded image for its file type.

        The extension is determined heuristically, by probing the first
        image the document turns out to be able to extract and assuming
        that _all_ extractable images have the same type.  This may be a
        fragile assumption, but it is a huge performance boost.

        Ask extract_image, which is what will do the extracting, rather
        than profiling the raw stream: it reports the type it would hand
        back, and reports "png" of its own accord for the exotic types it
        converts.  If it cannot say, 'png' is used as a fallback, as
        that's the type rendered page pixmaps are saved with.
        """
        try:
            return str(self.doc.extract_image(xref).get('ext', 'png'))
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return 'png'

    def iter_contents(self) -> Iterator[str]:
        """Yield a name per page, saying how that page will be produced.

        A page whose image can be handed over as it is carries the
        image's xref in its name, and keeps that image's file type, unless
        the page is turned and the type cannot carry the orientation: then
        it is named as the PNG it is converted to.  A page that has to be
        rendered is named as a PNG.  The name is what extract_file() reads
        back, so the decision is made once, here, rather than again at
        extraction.
        """
        for pg in range(self.doc.page_count):
            pagenum = f"page{pg + 1:04}"
            found = self._extractable_image(pg)
            if found is None:
                yield f"{pagenum}.png"
                continue
            xref, rotation = found
            extension = self._image_extension(xref)
            if rotation in EXIF_ORIENTATIONS and extension not in EXIF_CARRIERS:
                extension = 'png'
            yield f"{pagenum}{XREF_DELIMITER}{xref:04}.{extension}"

    def extract_xref(self, page: int, xref: int, path: str) -> None:
        """Save the embedded PDF image for a given xref. The page is indexed starting with zero.

        The extract_image method always returns the unrotated version of
        the image, unaffected by any page modifications of rotation, so
        the page's rotation is recorded as the image's Exif orientation,
        which the display applies as it does for any image.
        """
        img = self.doc.extract_image(xref)
        if not img:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img_bytes = img.get("image", b"")

        orientation = EXIF_ORIENTATIONS.get(self.doc[page].rotation)
        if orientation is None:
            with open(path, "wb") as out:
                out.write(img_bytes)
            return

        if img.get("ext") == "jpeg" and path.endswith(".jpeg"):
            # Saved again through Pillow, the picture would be compressed
            # again, at Pillow's default quality.
            try:
                turned = jpeg_with_orientation(img_bytes, orientation)
            except ValueError as error:
                self.log.debug("PDF page %d: %s, saving it again", page + 1, error)
            else:
                with open(path, "wb") as out:
                    out.write(turned)
                return

        try:
            with Image.open(io.BytesIO(img_bytes)) as pil_img:
                exif_data = pil_img.getexif()
                exif_data[ExifTags.Base.Orientation] = orientation
                pil_img.save(path, exif=exif_data)
        except OSError:
            # A type Pillow cannot read, such as JBIG2: the page is
            # rendered instead, turned as the PDF shows it.
            self.log.debug("PDF page %d: cannot read its image, rendering it", page + 1)
            self.render_page(page, path)

    def render_page(self, pg: int, path: str) -> None:
        """Render the page to an image file and save."""
        page = self.doc[pg]
        pixmap = page.get_pixmap(dpi=PDF_RENDER_DPI_DEF)
        pixmap.save(path)
        del pixmap
        del page

    def extract_file(self, filename: str, dest: str) -> None:
        """Produce the page <filename> names, under <dest>.

        Which of the two ways is used is what iter_contents() decided
        when it made the name up.
        """
        outpath = os.path.join(dest, filename)
        # Page and xref numbers are zero padded to four digits, but may well
        # need more than that, so parse them by delimiter instead of by width.
        name = os.path.splitext(filename)[0]
        if XREF_DELIMITER in name:
            pginfo, ref = name.split(XREF_DELIMITER)
            self.extract_xref(int(pginfo[4:]) - 1, int(ref), outpath)
        elif name.startswith('page'):
            self.render_page(int(name[4:]) - 1, outpath)
