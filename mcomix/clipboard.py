"""clipboard.py - Clipboard handler"""

from gi.repository import Gdk, GdkPixbuf

from mcomix import widgets
from mcomix import constants
from mcomix import image_tools
from mcomix.transform import Matrix, Transform

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix import box
    from mcomix import main


class Clipboard:

    """Copying the open page to the system clipboard.

    Nothing here reads the clipboard: MComix copies a page out of
    itself and never pastes one in.
    """

    def __init__(self, window: "main.MainWindow") -> None:
        # A clipboard belongs to the display.
        self._clipboard = widgets.display().get_clipboard()
        self._window = window

    def copy(self, text: str, pixbuf: GdkPixbuf.Pixbuf) -> None:
        """Put <text> and <pixbuf> on the clipboard."""
        # A GTK4 clipboard holds one content provider rather than a set
        # of targets set one at a time, so offer both and leave whoever
        # pastes to take the one it understands.
        self._clipboard.set_content(Gdk.ContentProvider.new_union([
            Gdk.ContentProvider.new_for_value(text),
            Gdk.ContentProvider.new_for_value(
                image_tools.pixbuf_to_texture(pixbuf)),
        ]))

    def copy_page(self, *args: object) -> None:
        """Put the open page on the clipboard, as an image and as a path.

        The image is the page the way the view puts it on screen: turned
        the way the view turns it, flipped the way it flips it, and two
        pages side by side joined into the one image they read as, in the
        order and along the axis they are shown in.  What it does not
        take from the view is the size - the page goes on the clipboard
        at the resolution it was stored at rather than the one it happens
        to be scaled to in a window - or the brightness and contrast
        adjustments, which are a way of reading a page rather than part
        of it.

        The path is the current page's either way.
        """

        if not self._window.filehandler.file_loaded:
            return

        pixbufs = [
            self._as_shown(pixbuf, transform) for pixbuf, transform in
            zip(self._window.imagehandler.get_pixbufs(
                    self._window.displayed_page_count()),
                self._window.transforms + [Transform.ID] * 2)
        ]

        if len(pixbufs) == 1:
            pixbuf = pixbufs[0]
        else:
            first, second, axis = self._spread_order(pixbufs)
            pixbuf = image_tools.combine_pixbufs(first, second, axis)

        path = self._window.imagehandler.get_path_to_page()
        # A page that is loaded has a file behind it; there is
        # nothing to name in the unlikely case that it has not.
        self.copy(path or '', pixbuf)

    @staticmethod
    def _as_shown(pixbuf: GdkPixbuf.Pixbuf,
                  transform: Matrix) -> GdkPixbuf.Pixbuf:
        """Return <pixbuf> turned and flipped the way <transform> draws it.

        The scale the transform also carries is dropped: it is the one
        the page was fitted to the window with, and a copy is wanted at
        the page's own resolution.  An animation is drawn with the
        identity transform, so it comes back untouched, which is what
        there is to do with one anyway - only its first frame is here.
        """
        _scale, rotation, flips = transform.to_image_transforms()
        pixbuf = image_tools.rotate_pixbuf(pixbuf, rotation)
        for axis in constants.PageAxis:
            if flips[axis]:
                pixbuf = image_tools.flip_pixbuf(pixbuf, axis)
        return pixbuf

    def _spread_order(self, pixbufs: Sequence[GdkPixbuf.Pixbuf]
                      ) -> tuple[GdkPixbuf.Pixbuf, GdkPixbuf.Pixbuf, int]:
        """Return the two pages in the order they are shown, and their axis.

        The layout has already placed them, so where they sit relative to
        one another answers both questions at once: a manga's first page
        is to the right of its second, and a view turned by a quarter
        turn stacks the two rather than setting them side by side.  Read
        off the boxes rather than worked out again from the preferences,
        which is how the lens reads the same layout.

        Before the first page is drawn there is no layout to read - the
        window starts on a dummy one - and the pages then go side by side
        in reading order, which is what an untransformed view shows.
        """
        boxes = self._window.layout.get_content_boxes()
        if len(boxes) != len(pixbufs):
            return (*self._reading_order(pixbufs),
                    constants.DISTRIBUTION_AXIS)
        axis = self._distribution_axis(boxes)
        if boxes[0].get_position()[axis] > boxes[1].get_position()[axis]:
            return pixbufs[1], pixbufs[0], axis
        return pixbufs[0], pixbufs[1], axis

    def _reading_order(self, pixbufs: Sequence[GdkPixbuf.Pixbuf]
                       ) -> tuple[GdkPixbuf.Pixbuf, GdkPixbuf.Pixbuf]:
        """The two pages left to right, which a manga reads backwards."""
        if self._window.is_manga_mode:
            return pixbufs[1], pixbufs[0]
        return pixbufs[0], pixbufs[1]

    @staticmethod
    def _distribution_axis(boxes: Sequence["box.Box"]) -> int:
        """The constants.PageAxis the two <boxes> are laid out along.

        The one they differ on.  Two pages drawn at the same position on
        both axes are what an empty page or a zero-sized window gives;
        the width is then as good an answer as the height.
        """
        positions = [box.get_position() for box in boxes]
        if positions[0][constants.PageAxis.HEIGHT] != \
                positions[1][constants.PageAxis.HEIGHT]:
            return constants.PageAxis.HEIGHT
        return constants.PageAxis.WIDTH

# vim: expandtab:sw=4:ts=4
