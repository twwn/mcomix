""" Gtk.IconView subclass for dynamically generated thumbnails. """

from gi.repository import Gtk, GLib

from mcomix.preferences import prefs
from mcomix.worker_thread import WorkerThread


#: How long to wait before asking a view that has not been laid out
#: what is on screen, and how many times to ask.
_RETRY_DELAY = 50
_RETRIES = 40


class ThumbnailViewBase(object):
    """ This class provides shared functionality for Gtk.TreeView and
    Gtk.IconView. Instantiating this class directly is *impossible*,
    as it depends on methods provided by the view classes. """

    def __init__(self, uid_column, pixbuf_column, status_column):
        """ Constructs a new ThumbnailView.
        @param uid_column: index of unique identifer column.
        @param pixbuf_column: index of pixbuf column.
        @param status_column: index of status boolean column
                              (True if pixbuf is not temporary filler)
        """

        #: Keep track of already generated thumbnails.
        self._uid_column = uid_column
        self._pixbuf_column = pixbuf_column
        self._status_column = status_column

        #: Ignore updates when this flag is True.
        self._updates_stopped = True
        #: The adjustment updates are currently being followed on.
        self._adjustment = None
        #: A pending "ask again", and how many are left to make.
        self._retry = None
        self._retries_left = _RETRIES
        #: Worker thread
        self._thread = WorkerThread(self._pixbuf_worker,
                                    name='thumbview',
                                    unique_orders=True,
                                    max_threads=prefs["max threads"])

    def generate_thumbnail(self, uid):
        """ This function must return the thumbnail for C{uid}. """
        raise NotImplementedError()

    def get_visible_range(self) -> "tuple[Gtk.TreePath, Gtk.TreePath] | None":
        """ See L{Gtk.IconView.get_visible_range}.

        The view classes provide this; the pair is the first and the last
        row on screen, and it is None while nothing has been laid out.
        PyGObject drops the success flag the C function returns, so what
        arrives here is the two paths alone rather than a triple. """
        raise NotImplementedError()

    def stop_update(self) -> None:
        """ Stops generation of pixbufs. """
        self._updates_stopped = True
        self._thread.stop()

    def _follow_visible_range(self) -> None:
        """Ask for the thumbnails on screen whenever they may have changed.

        Gtk.Widget::draw was what said so up to GTK3, and GTK4 has no
        such signal - a widget is asked for a render node instead, which
        is no place to start worker threads from.  Scrolling and
        resizing both reach the vertical adjustment, which is where the
        visible range is read from in the first place.
        """
        self.connect('map', self.draw_thumbnails_on_screen)
        self.connect('notify::vadjustment', self._vadjustment_set)
        self._vadjustment_set()

    def _retry_visible_range(self) -> None:
        """Ask again once the view has had a chance to lay itself out."""
        if self._retry is not None or not self._retries_left:
            return
        self._retries_left -= 1
        self._retry = GLib.timeout_add(_RETRY_DELAY, self._retry_now)

    def _retry_now(self) -> bool:
        self._retry = None
        self.draw_thumbnails_on_screen()
        return GLib.SOURCE_REMOVE

    def _vadjustment_set(self, *args) -> None:
        adjustment = self.get_vadjustment()
        if adjustment is None or adjustment is self._adjustment:
            return
        self._adjustment = adjustment
        # 'changed' covers the view being resized, 'value-changed'
        # covers it being scrolled.
        adjustment.connect('changed', self.draw_thumbnails_on_screen)
        adjustment.connect('value-changed', self.draw_thumbnails_on_screen)

    def draw_thumbnails_on_screen(self, *args):
        """ Prepares valid thumbnails for currently displayed icons. """

        visible = self.get_visible_range()
        if not visible:
            # Nothing has been laid out yet, so there is nothing to ask
            # about.  Neither being mapped nor the adjustment settling
            # is late enough for an icon view - it answers None to both -
            # and if nobody asks again the thumbnails are never made at
            # all, leaving a page of empty cells.  Ask again shortly.
            self._retry_visible_range()
            return

        pixbufs_needed = []
        start = visible[0][0]
        end = visible[1][0]
        # Read ahead/back and start caching a few more icons. Currently invisible
        # icons are always cached only after the visible icons have been completed.
        additional = (end - start) // 2
        required = list(range(start, end + additional + 1)) + \
                   list(range(max(0, start - additional), start))
        model = self.get_model()
        # Filter invalid paths.
        required = [path for path in required if 0 <= path < len(model)]
        self._retries_left = _RETRIES
        with self._thread:
            # Flush current pixmap generation orders.
            self._thread.clear_orders()
            for path in required:
                iter = model.get_iter(path)
                uid, generated = model.get(iter,
                                           self._uid_column,
                                           self._status_column)
                # Do not queue again if thumbnail was already created.
                if not generated:
                    pixbufs_needed.append((uid, iter))
            if len(pixbufs_needed) > 0:
                self._updates_stopped = False
                self._thread.extend_orders(pixbufs_needed)

    def _pixbuf_worker(self, order):
        """ Run by a worker thread to generate the thumbnail for a path."""
        uid, iter = order
        pixbuf = self.generate_thumbnail(uid)
        if pixbuf is not None:
            GLib.idle_add(self._pixbuf_finished, iter, pixbuf)

    def _pixbuf_finished(self, iter, pixbuf):
        """ Executed when a pixbuf was created, to actually insert the pixbuf
        into the view store. C{pixbuf_info} is a tuple containing
        (index, pixbuf). """

        if self._updates_stopped:
            return 0

        model = self.get_model()
        model.set(iter, self._status_column, True, self._pixbuf_column, pixbuf)

        # Remove this idle handler.
        return 0

class ThumbnailIconView(Gtk.IconView, ThumbnailViewBase):
    def __init__(self, model, uid_column, pixbuf_column, status_column):
        assert 0 != (model.get_flags() & Gtk.TreeModelFlags.ITERS_PERSIST)
        super(ThumbnailIconView, self).__init__(model=model)
        ThumbnailViewBase.__init__(self, uid_column, pixbuf_column, status_column)
        self.set_pixbuf_column(pixbuf_column)

        self._follow_visible_range()

class ThumbnailTreeView(Gtk.TreeView, ThumbnailViewBase):
    def __init__(self, model, uid_column, pixbuf_column, status_column):
        assert 0 != (model.get_flags() & Gtk.TreeModelFlags.ITERS_PERSIST)
        super(ThumbnailTreeView, self).__init__(model=model)
        ThumbnailViewBase.__init__(self, uid_column, pixbuf_column, status_column)

        self._follow_visible_range()

# vim: expandtab:sw=4:ts=4
