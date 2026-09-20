"""rename_dialog.py - Asking the reader what to call a file in the book.

A page of the book being read and a comment file the archive editor
lists are the same thing to whoever is renaming one: a file inside one
archive, called what the reader calls it once the archive is written
again, and answerable for a name that something else in the archive
holds already.  The dialog they both ask through is here rather than
beside either of them, so that the two ask in the same words and warn
about a taken name in the same way.
"""

import os

from gi.repository import GLib, Gtk

from mcomix import message_dialog
from mcomix import widgets
from mcomix.dialog import Response
from mcomix.i18n import _

from collections.abc import Callable
from typing import NamedTuple

#: What the dialog answers with where the name typed is one that
#: something else holds: swap the two names, or write the other file
#: over.  Response has no member for either, and no other button of this
#: dialog answers with these numbers.
SWAP = Response.APPLY
REPLACE = Response.ACCEPT


class Clash(NamedTuple):

    """What holds the name that has been typed, and what can be done."""

    #: The line the dialog warns on, naming what holds the name.
    told: str
    #: Whether the two answers a clash leaves - swapping the two names,
    #: or writing the other file over - can be offered at all.  A
    #: comment file whose name a page holds cannot offer either: the
    #: page is not the editor's list's to rename or to remove.
    answers: bool


def ask(parent: Gtk.Window, *, title: str, prompt: str, name: str,
        clash: Callable[[str], "Clash | None"],
        answered: Callable[[int, str], None]) -> None:
    """Ask what to call the file called <name>, under <parent>.

    <title> and <prompt> are what the dialog says above the entry, which
    opens with <name> in it and everything but the extension picked out,
    as a file manager picks a name out.

    <clash> is asked what has been typed, as it is typed, and answers
    with a Clash where something else in the archive is called that, or
    None where the name is free.  A clash brings up the warning line and
    replaces the plain rename with the answers the clash leaves.

    <answered> is handed the answer and the text that was typed, once
    the dialog has been taken down; it is not called at all for an
    answer of Cancel.  The text rather than a name, because what a name
    typed here means is the caller's to say.
    """
    dialog = message_dialog.MessageDialog(
        parent, buttons=Gtk.ButtonsType.OK_CANCEL)
    dialog.set_text(title, prompt)
    dialog.set_default_response(Response.OK)

    entry = Gtk.Entry()
    entry.set_text(name)
    entry.set_activates_default(True)
    widgets.pack(dialog.get_content_area(), entry, True, True, 6)

    warning = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    # The style class the desktop paints its warnings in, on the line
    # and on the icon beside it: a name that is taken is not a refusal -
    # the dialog goes on offering what can be done about it - but it is
    # not to be missed either.
    warning.add_css_class('warning')
    told = Gtk.Label()
    told.set_xalign(0)
    told.set_wrap(True)
    warning.append(Gtk.Image.new_from_icon_name('dialog-warning-symbolic'))
    warning.append(told)
    warning.set_visible(False)
    widgets.pack(dialog.get_content_area(), warning, False, False, 0)

    swap = dialog.add_button(_('S_wap the names'), SWAP)
    replace = dialog.add_button(_('_Replace'), REPLACE)
    replace.add_css_class('destructive-action')
    swap.set_visible(False)
    replace.set_visible(False)

    def name_typed(*args: object) -> None:
        """Say whether what has been typed is a name something else
        holds, and offer what can be done about it.

        Enter renames while the name is free, and cancels once it is
        not: the answers a taken name leaves - one file's name for
        another's, or a file written over - are neither of them the
        harmless one that a confirmation defaults to.
        """
        taken = clash(entry.get_text())
        if taken is not None:
            told.set_text(taken.told)
        warning.set_visible(taken is not None)
        swap.set_visible(taken is not None and taken.answers)
        replace.set_visible(taken is not None and taken.answers)
        renames = dialog.get_widget_for_response(Response.OK)
        if renames is not None:
            renames.set_visible(taken is None)
        dialog.set_default_response(
            Response.OK if taken is None else Response.CANCEL)

    entry.connect('changed', name_typed)
    name_typed()

    # The entry outlives the dialog: what was typed is read out of it
    # once the answer has come back.
    dialog.run_async(lambda response: answered(response, entry.get_text()))

    def pick_out_the_name() -> bool:
        """Select the part a rename replaces: the name without its
        extension, as a file manager picks it out.

        Once the dialog has been shown, rather than before: the entry
        takes the focus as that happens, and a focused entry has the
        whole of its text selected.
        """
        entry.select_region(0, len(os.path.splitext(name)[0]))
        return GLib.SOURCE_REMOVE

    GLib.idle_add(pick_out_the_name)

# vim: expandtab:sw=4:ts=4
