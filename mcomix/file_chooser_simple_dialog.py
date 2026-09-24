"""file_chooser_simple_dialog.py - Custom FileChooserDialog implementations."""

from gi.repository import Gtk

from mcomix import file_chooser_base_dialog

from collections.abc import Callable


class SimpleFileChooserDialog(file_chooser_base_dialog._BaseFileChooserDialog):

    """A simple filechooser dialog that hands the paths it collected to a
    callback. The <action> dictates what type of filechooser dialog we want
    (i.e. save or open). If the type is an open-dialog, we use multiple
    selection by default.  It is transient for <parent>, the window it was
    opened from, or for the main window if none is given, and opens in
    <folder> where one is named.
    """

    def __init__(self, action: Gtk.FileChooserAction = Gtk.FileChooserAction.OPEN,
                 parent: "Gtk.Window | None" = None,
                 folder: str | None = None) -> None:
        super().__init__(action, parent, folder)
        if action == Gtk.FileChooserAction.OPEN:
            self.filechooser.set_select_multiple(True)
        self._paths: list[str] | None = None
        self._on_paths: "Callable[[list[str]], None] | None" = None

    def run_async(self, on_paths: Callable[[list[str]], None]) -> None:
        """Show the dialog and call <on_paths> with the chosen paths.

        The list is empty if the user chose nothing.  Destroying the
        dialog afterwards is left to <on_paths>.
        """
        self._on_paths = on_paths
        self.set_visible(True)

    def files_chosen(self, paths: list[str]) -> None:
        self._paths = paths
        if self._on_paths is not None:
            on_paths, self._on_paths = self._on_paths, None
            on_paths(paths)

# vim: expandtab:sw=4:ts=4
