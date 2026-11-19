"""The library window and what it is built from."""

import weakref

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcomix.library import main_dialog


class LibraryPart:

    """An area of the library window, which holds the window weakly."""

    _library_ref: 'weakref.ref[main_dialog._LibraryDialog]'

    @property
    def _library(self) -> 'main_dialog._LibraryDialog':
        """The library window this area is part of.

        Held weakly: GTK holds the area for as long as the window's
        widgets stand, which is for good once the window is closed,
        and a plain reference would keep the window alive with it.
        """
        library = self._library_ref()
        assert library is not None, 'the library window is gone'
        return library


# vim: expandtab:sw=4:ts=4
