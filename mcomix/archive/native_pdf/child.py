"""Child process code for native PDF multiprocessing."""

import io
import os
import multiprocessing as mp
from PIL import Image, ExifTags
from collections.abc import Generator

try:
    import pymupdf
except ImportError:
    # PyMuPDF only gained its own name in 1.24.3.  Before that it was
    # importable as "fitz" alone, a name it shares with an unrelated
    # package on PyPI.
    import fitz as pymupdf  # type: ignore[no-redef]

from mcomix.constants import PDF_RENDER_DPI_DEF


# Will delimit the page name from the xref part of a file name
XREF_DELIMITER = '_mcmxref'


class FitzWorker:
    def __init__(self, filename: str | None, log_level: int | None = None) -> None:
        self._extension: str | None = None
        self._complex_doc = False
        self.log = mp.get_logger()
        if log_level is not None:
            self.log.setLevel(log_level)
        self.doc = pymupdf.open(filename)

    def page_count(self) -> int:
        return self.doc.page_count

    def _image_extension(self, xref: int) -> str:
        """Return the filename extension for extracted page images."""
        if self._extension is None:
            self._extension = self._check_image_type(xref)
        return self._extension

    def _extractable_image_xref(self, page_num: int) -> int | None:
        """Return the xref of the image to extract for <page_num>, or None
        if the page has to be rendered to a pixmap instead.

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
        if len(images) != 1 or len(page.get_text()) > 0:
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
        return int(images[0][0])

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

    def iter_contents(self) -> Generator[str, None, None]:
        for pg in range(self.doc.page_count):
            pagenum = f"page{pg + 1:04}"
            xref = self._extractable_image_xref(pg)
            if xref is None:
                yield f"{pagenum}.png"
            else:
                yield f"{pagenum}{XREF_DELIMITER}{xref:04}.{self._image_extension(xref)}"

    def extract_xref(self, page: int, xref: int, path: str) -> None:
        """Save the embedded PDF image for a given xref. The page is indexed starting with zero."""
        img = self.doc.extract_image(xref)
        if not img:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img_bytes = img.get("image", b"")

        # The extract_image method always returns the unrotated version of the image,
        # unaffected by any page modifications of rotation.
        EXIF_ROTS = {
            90: 6,
            180: 3,
            270: 8,
        }
        rotation = self.doc[page].rotation
        if rotation in EXIF_ROTS.keys():
            # Embed rotation in image as EXIF data
            buffer = io.BytesIO(img_bytes)
            with Image.open(buffer) as pil_img:
                exif_data = pil_img.getexif()
                exif_data[ExifTags.Base.Orientation] = EXIF_ROTS[rotation]
                pil_img.save(path, exif=exif_data)
            del buffer

        else:
            with open(path, "wb") as out:
                out.write(img_bytes)
        del img_bytes

    def render_page(self, pg: int, path: str) -> None:
        """Render the page to an image file and save."""
        page = self.doc[pg]
        pixmap = page.get_pixmap(dpi=PDF_RENDER_DPI_DEF)
        pixmap.save(path)
        del pixmap
        del page

    def extract_file(self, filename: str, dest: str) -> None:
        outpath = os.path.join(dest, filename)
        # Page and xref numbers are zero padded to four digits, but may well
        # need more than that, so parse them by delimiter instead of by width.
        name = os.path.splitext(filename)[0]
        if XREF_DELIMITER in name:
            pginfo, ref = name.split(XREF_DELIMITER)
            self.extract_xref(int(pginfo[4:]) - 1, int(ref), outpath)
        elif name.startswith('page'):
            self.render_page(int(name[4:]) - 1, outpath)
