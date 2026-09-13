"""Child process code for native PDF multiprocessing."""

import io
import os
import multiprocessing as mp
from PIL import Image, ExifTags
from typing import Generator, Optional

try:
    import fitz
except ImportError:
    import fitz_old as fitz

from mcomix.constants import PDF_RENDER_DPI_DEF


# Will delimit the page name from the xref part of a file name
XREF_DELIMITER = '_mcmxref'


class FitzWorker:
    def __init__(self, filename: Optional[str], log_level: Optional[int] = None) -> None:
        self._extension: Optional[str] = None
        self._complex_doc = False
        self.log = mp.get_logger()
        if log_level is not None:
            self.log.setLevel(log_level)
        self.doc = fitz.open(filename)

    def page_count(self) -> int:
        return self.doc.page_count

    def _image_extension(self, page_num: int) -> str:
        """Return the filename extension for the page image."""
        if self._extension is None:
            self._extension = self._check_image_type(page_num)
        return self._extension

    def _extract_as_image(self, page_num: int) -> bool:
        """Check whether the page can be extracted via image export."""
        if self._complex_doc:
            return False
        if not self._must_render_page(page_num) and self._can_extract_image(page_num):
            return True
        return False

    def _must_render_page(self, page_num: int) -> bool:
        """Determine if a page has any forced-render markers.

        Rendering to pixmap must be forced if any of these apply:
            - The page has any text content
            - The page has any drawing content
            - The page contains 0, or more than 1, embedded image
        """
        page = self.doc[page_num]
        if len(page.get_images()) != 1 or len(page.get_text()) > 0:
            self._complex_doc = True
            result = True
            self.log.debug("PDF page %d, must render page", page_num + 1)
        else:
            result = False
            self.log.debug("PDF page %d, rendering not forced", page_num + 1)
        del page
        return result

    def _can_extract_image(self, page_num: int) -> bool:
        """Determine if a page has an extractable image.

        Makes a closer examination than _must_render_page(),
        by checking whether the page contains a single, full-page
        image, then actually extracting the first such image
        encountered to determine the filetype (extension).

        (Subsequent embedded images are assumed to have the same
        type as the first full-page image encountered. This may
        be somewhat fragile, but it's a huge performance boost.)
        """
        page = self.doc[page_num]
        image_info = page.get_image_info()
        if len(image_info) != 1:
            self.log.debug(
                "PDF page %d, cannot extract. Image count = %d",
                page_num + 1, len(image_info))
            return False
        info = image_info[0]
        img_rect = fitz.Rect(info.get('bbox', (0, 0, 0, 0))).irect
        page_rect = fitz.Rect(page.mediabox).irect
        page_area = page_rect.get_area()
        area_diff = abs(page_area - img_rect.get_area())
        is_full_page: bool = area_diff < 0.05 * page_area
        if is_full_page:
            self.log.debug('PDF page %d: can extract fullpage image', page_num + 1)
        else:
            self.log.debug(
                'PDF page %d, cannot extract image: %s',
                page_num + 1, f"img_rect={img_rect}, page_rect={page_rect}")
        del page
        del image_info
        return is_full_page

    def _check_image_type(self, page_num: int) -> str:
        """Examine the page's embedded image for its file type.

        The extension is determined heuristically by probing only the
        first page of the document for an embedded image, then using
        its type.

        If the first page does have a single embedded image, it's
        assumed that _all_ pages contain an image of the same type.
        This may be a fragile assumption.

        If the probe fails, 'png' is used as a fallback, as that's the
        type rendered page pixmaps will be saved with.
        """
        extension = 'png'
        try:
            xref = self._get_image_xref(page_num)
            img = fitz.image_profile(
                self.doc.xref_stream_raw(xref))
            # If image_profile returns an empty dict, the image type is
            # "exotic" and not supported for direct extraction.
            # That doesn't mean that the images can't be extracted.
            # Document.extract_image will automatically convert to PNG,
            # when we call it to extract the xref. It'll be slower than
            # extraction without converting, but still very fast.
            if img:
                extension = img.get('ext', 'png')
                del img
        except (AttributeError, TypeError):
            pass
        return extension

    def _get_image_xref(self, page_num: int) -> int:
        try:
            image_info = self.doc.get_page_images(page_num)
            return int(image_info[0][0])
        except (TypeError, IndexError):
            return -1

    def iter_contents(self) -> Generator[str, None, None]:
        for pg in range(self.doc.page_count):
            pagenum = f"page{pg + 1:04}"
            if self._extract_as_image(pg):
                xref = self._get_image_xref(pg)
                ext = self._image_extension(pg)
                filename = f"{pagenum}{XREF_DELIMITER}{xref:04}.{ext}"
            else:
                filename = f"{pagenum}.png"
            yield filename

    def extract_xref(self, page: int, xref: int, path: str) -> None:
        """Save the embedded PDF image for a given xref. The page is indexed starting with zero."""
        img = self.doc.extract_image(xref)
        if not img:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img_bytes = img.get("image", b"")
        del img

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
