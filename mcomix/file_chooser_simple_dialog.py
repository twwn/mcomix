"""file_chooser_simple_dialog.py - Custom FileChooserDialog implementations."""

from gi.repository import Gtk

from mcomix import file_chooser_base_dialog

from collections.abc import Callable

class SimpleFileChooserDialog(file_chooser_base_dialog._BaseFileChooserDialog):

    """A simple filechooser dialog that hands the paths it collected to a
    callback. The <action> dictates what type of filechooser dialog we want
    (i.e. save or open). If the type is an open-dialog, we use multiple
    selection by default.
    """

    def __init__(self, action=Gtk.FileChooserAction.OPEN):
        super(SimpleFileChooserDialog, self).__init__(action)
        if action == Gtk.FileChooserAction.OPEN:
            self.filechooser.set_select_multiple(True)
        self._paths = None
        self._on_paths = None

    def run_async(self, on_paths: Callable[[list], None]) -> None:
        """Show the dialog and call <on_paths> with the chosen paths.

        The list is empty if the user chose nothing.  Destroying the
        dialog afterwards is left to <on_paths>.
        """
        self._on_paths = on_paths
        self.show_all()

    def get_paths(self):
        """Return the paths that were selected, if any."""
        return self._paths

    def files_chosen(self, paths):
        self._paths = paths
        if self._on_paths is not None:
            on_paths, self._on_paths = self._on_paths, None
            on_paths(paths)

# vim: expandtab:sw=4:ts=4
