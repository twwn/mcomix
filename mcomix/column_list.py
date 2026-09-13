"""column_list.py - The rows-and-columns list GTK4 draws with."""

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from mcomix import tools
from mcomix.i18n import _

from collections.abc import Callable, Iterable, Iterator
import re
from typing import Any, cast


#: What an accelerator cell says while it is waiting for one.
_ASK_FOR_ONE_HINT = _('New accelerator...')

#: How wide an accelerator cell asks to be, in characters.  It is the
#: width at which all 98 of the shortcuts MComix binds by default fit
#: in a German locale, which is a wordier one than most, and in an
#: English one; a language whose keypad keys cannot be shortened has
#: some that do not, four of the 98 in French.  A list of shortcuts is
#: several columns wide, so what does not fit is ellipsized, with a
#: tooltip, rather than allowed to take the room the column naming the
#: action needs.
_ACCEL_WIDTH_CHARS = 14


def _text_width(characters: int) -> int:
    """How wide <characters> of text come out, in pixels.

    Whatever a fixed width is set to has to follow the font the desktop
    is drawn in, so it is measured rather than stated.
    """
    return Gtk.Label(width_chars=characters).measure(
        Gtk.Orientation.HORIZONTAL, -1)[1]


def accelerator_label(accelerator: str) -> str:
    """What the keyboard calls <accelerator>, or '' where there is none."""
    if not accelerator:
        return ''
    parsed, keyval, modifiers = Gtk.accelerator_parse(accelerator)
    if not parsed:
        return ''
    return Gtk.accelerator_get_label(keyval, modifiers)


class Row(GObject.Object):

    """One row of a ColumnListView.

    A row is a bag of named values: each column is told which attribute
    it shows, and reads it off the row by name.  What a Gtk.ListStore
    held in numbered columns is a plain Python attribute here, so the
    column numbers that had to be kept in step with the store - and the
    COL_* constants that named them - are gone.

    Nothing watches those attributes, so a row that is changed while it
    is on screen says so with changed().
    """

    __gtype_name__ = 'MComixColumnRow'

    __gsignals__ = {
        'changed': (GObject.SignalFlags.RUN_LAST, None, ()),
    }

    def __init__(self, **values: object) -> None:
        super().__init__()
        for name, value in values.items():
            setattr(self, name, value)

    def __getattr__(self, name: str) -> Any:  # type: ignore[explicit-any]  # a row carries whatever it was built with
        # A row carries whatever it was built with, so there is no set
        # of attributes to declare; this says so, to a reader and to
        # mypy alike, and answers as any object does for one that is
        # not there.
        raise AttributeError(name)

    def __setattr__(self, name: str, value: object) -> None:
        # The write side of __getattr__: a column writes back whatever
        # attribute it was told to show, and none of them are declared.
        super().__setattr__(name, value)

    def changed(self) -> None:
        """Redraw this row: something it shows is not what it was."""
        self.emit('changed')


class _Cell:

    """What every cell of a ColumnListView remembers.

    The row and the handler are kept on the widget rather than in the
    factory's closure because PyGObject is free to drop the Python
    wrapper of a widget only GTK still holds, and to build a new one
    without them when the row comes back.
    """

    def _init_cell(self) -> None:
        self.row: Row | None = None
        #: The row's 'changed' handler while this cell is bound.
        self.handler: int | None = None
        #: The position this cell is showing.
        self.position = 0


class _TextCell(Gtk.Label, _Cell):

    __gtype_name__ = 'MComixColumnTextCell'

    def __init__(self) -> None:
        super().__init__()
        self._init_cell()
        self.set_xalign(0.0)
        self.set_ellipsize(Pango.EllipsizeMode.END)


class _IconCell(Gtk.Image, _Cell):

    __gtype_name__ = 'MComixColumnIconCell'

    def __init__(self) -> None:
        super().__init__()
        self._init_cell()
        self.set_halign(Gtk.Align.CENTER)


class _ToggleCell(Gtk.CheckButton, _Cell):

    __gtype_name__ = 'MComixColumnToggleCell'

    def __init__(self) -> None:
        super().__init__()
        self._init_cell()
        self.set_halign(Gtk.Align.CENTER)


class _ChoiceCell(Gtk.DropDown, _Cell):

    __gtype_name__ = 'MComixColumnChoiceCell'

    def __init__(self) -> None:
        super().__init__()
        self._init_cell()
        self.set_model(Gtk.StringList())


# pygobject-stubs declares install_properties() on GObject.Object and
# on Gtk.Editable with signatures that do not match, so any class
# implementing the interface is reported.
class _EditableCell(Gtk.EditableLabel, _Cell):  # type: ignore[misc]

    """A cell whose text the user can rewrite in place.

    This is what a Gtk.CellRendererText with editable set was.  The
    renderer answered once, with the new text, when the edit was
    finished; a Gtk.EditableLabel says when it stops editing, and the
    text it holds by then is the answer.
    """

    __gtype_name__ = 'MComixColumnEditableCell'

    def __init__(self) -> None:
        super().__init__()
        self._init_cell()
        #: Told the row and the text it was given.
        self.edited: "Callable[[Row, str], None] | None" = None
        self.connect('notify::editing', self._editing)
        self._was_editing = False

    def _editing(self, _widget: Gtk.Widget,
                 _param: GObject.ParamSpec) -> None:
        editing = self.get_property('editing')
        finished = self._was_editing and not editing
        self._was_editing = editing
        if finished and self.edited is not None and self.row is not None:
            self.edited(self.row, self.get_text())


#: The sign a keyboard prints on a key, which the key is drawn as
#: rather than by name - the name is the longest thing in a column of
#: shortcuts.  A Gtk.ShortcutLabel draws the arrows, space and return
#: this way for itself, and spells the rest out; they are listed all the
#: same, because this is also where the keys of the numeric keypad find
#: the sign of the key they stand beside.
#:
#: Only keys that can be bound are listed: the locks - caps, num and
#: scroll - are printed with a sign of their own, but no accelerator
#: can be made of them, so an entry for one would never be read.
_KEY_SYMBOLS = {
    'Page_Up': '\u21de', 'Page_Down': '\u21df',
    'BackSpace': '\u232b', 'Delete': '\u2326', 'Insert': '\u2380',
    'Tab': '\u21e5', 'ISO_Left_Tab': '\u21e4', 'Escape': '\u238b',
    'Home': '\u21f1', 'End': '\u21f2',
    'Menu': '\u2630', 'Print': '\u2399',
    'Pause': '\u2389', 'Break': '\u238a',
    # The ones the label draws for itself, listed for the keypad's sake.
    'Left': '\u2190', 'Right': '\u2192', 'Up': '\u2191', 'Down': '\u2193',
    'space': '\u2423', 'Return': '\u23ce',
}

#: What the name of one of the numeric keypad's keys begins with, and
#: the mark a Gtk.ShortcutLabel ends it with to tell it from the key of
#: the same name: German draws KP_Page_Up as "Bild auf (Nmblck)".
_KEYPAD_PREFIX = 'KP_'
_KEYPAD_MARK = re.compile(r'\s*\([^()]*\)$')


def _keypad_symbol(name: str, spelled: str) -> "str | None":
    """The sign for the keypad key <name>, or None to leave it be.

    <spelled> is what the label spelled the key out as.  A keypad key is
    told from the key of the same name by the mark the label puts after
    it, not by the name itself, so the sign of the key it stands beside
    is drawn with that mark kept.

    Which is only possible where the mark can be told from the name.
    Half the desktop's languages bracket it, as German and English and
    French do; Spanish writes "TN Re Pag" and Polish spells the whole
    keypad out after the name, and there the key is left as it stands.
    Enter is left as it stands everywhere: the keypad's is KP_Enter, and
    there is no plain Enter for it to stand beside.

    The key it stands beside is looked up by keyval rather than by name,
    because GDK answers with a different one of a key's names on either
    side of the keypad: 0xff9b is KP_Next, whose plain twin 0xff56 is
    Page_Down.
    """
    plain = Gdk.keyval_from_name(name[len(_KEYPAD_PREFIX):])
    if not plain:
        return None
    symbol = _KEY_SYMBOLS.get(Gdk.keyval_name(plain) or '')
    if symbol is None:
        return None
    mark = _KEYPAD_MARK.search(spelled)
    return None if mark is None else symbol + mark.group(0)

#: The sign printed on the shift key.  The other modifiers are printed
#: as words - Ctrl, Alt - and are left as the label spells them out;
#: this one has a sign, and is the one worth drawing as one, being the
#: widest cap of the three in several languages.  German's "Umschalt"
#: comes to as much as the two caps it is usually held down with put
#: together.
_SHIFT_SYMBOL = '\u21e7'


def _draw_caps(label: Gtk.ShortcutLabel, accelerator: str) -> None:
    """Redraw what <label> made of <accelerator>.

    The key is drawn as the sign printed on it where it has one - one of
    the keypad's keeping the mark that tells it from the key of the same
    name - and so is shift; the plusses the label puts between the caps are dropped,
    because keys drawn as keys are read as keys held together and the
    plusses are a third of the width of a short shortcut; and the caps
    are left free to be drawn at the width they need rather than the
    one GTK asks for.

    The key is the last cap the label drew; the caps before it are the
    modifiers, shift always first.  Which cap is which is worked out
    from the order they are drawn in rather than from what they say,
    because what they say is in the desktop's language.
    """
    caps, joiners = [], []
    child = label.get_first_child()
    while child is not None:
        if isinstance(child, Gtk.Label):
            if 'keycap' in child.get_css_classes():
                caps.append(child)
            elif 'dim-label' in child.get_css_classes():
                joiners.append(child)
        child = child.get_next_sibling()
    if not caps:
        # Nothing is bound, and what stands there is the disabled text.
        return
    for joiner in joiners:
        joiner.set_visible(False)
    for cap in caps:
        # A cap that will not fit is ellipsized rather than cut off
        # halfway through a letter, which is what clipping alone did.
        cap.set_ellipsize(Pango.EllipsizeMode.END)
    for modifier_cap in caps[:-1]:
        # GTK asks for fifty pixels for every modifier cap, whatever
        # it says, to line the modifiers of one shortcut up under those
        # of the next.  Here they stand one to a row, with nothing to
        # line up with, and the room is worth more to the key beside
        # them: it is fourteen pixels of white space around a "Ctrl".
        modifier_cap.set_size_request(-1, -1)
    parsed, keyval, modifiers = Gtk.accelerator_parse(accelerator)
    if not parsed:
        return
    name = Gdk.keyval_name(keyval) or ''
    symbol = _KEY_SYMBOLS.get(name)
    if symbol is None and name.startswith(_KEYPAD_PREFIX):
        symbol = _keypad_symbol(name, caps[-1].get_text())
    if symbol is not None:
        caps[-1].set_text(symbol)
    if modifiers & Gdk.ModifierType.SHIFT_MASK and len(caps) > 1:
        caps[0].set_text(_SHIFT_SYMBOL)


class _ClampLayout(Gtk.LayoutManager):

    """Lays out one child at a width of its own, in a fixed width.

    A Gtk.ColumnView asks the cells that are on screen how wide their
    column should be, where the Gtk.TreeView it replaced asked the whole
    model, so a cell that answers with what it holds makes the column a
    different width every time the list is scrolled.  This answers with
    the same width whatever it holds, and lets the child overflow it -
    the widget clips what does not fit.
    """

    __gtype_name__ = 'MComixClampLayout'

    def __init__(self, width: int) -> None:
        super().__init__()
        self._width = width

    def do_measure(self, widget: Gtk.Widget, orientation: Gtk.Orientation,
                   for_size: int) -> tuple[int, int, int, int]:
        child = widget.get_first_child()
        if child is None:
            return 0, 0, -1, -1
        if orientation == Gtk.Orientation.HORIZONTAL:
            return self._width, self._width, -1, -1
        return child.measure(orientation, for_size)

    def do_allocate(self, widget: Gtk.Widget, _width: int, height: int,
                    baseline: int) -> None:
        child = widget.get_first_child()
        if child is None:
            return
        # Its own width where that is less than the room it was given -
        # it is drawn at its own size, not stretched to fill - and the
        # room itself where it is more, so that a child that can be
        # drawn narrower does the cutting itself, in whole letters.
        # What still overflows is what the clipping answers for.
        wanted = child.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        child.allocate(min(wanted, self._width), height, baseline, None)


class _AccelCell(Gtk.Button, _Cell):

    """A cell showing a keyboard shortcut, which a click rebinds.

    This is what a Gtk.CellRendererAccel was: click it and the next
    combination pressed becomes the shortcut, backspace clears it and
    escape leaves it alone.  The shortcut is drawn as the key caps a
    Gtk.ShortcutLabel makes of it, which is as wide as they come to and
    cannot be drawn any narrower, so the label is held in a fixed width
    and what does not fit is cut off - with the shortcut spelled out in
    a tooltip where that happens.
    """

    __gtype_name__ = 'MComixColumnAccelCell'

    def __init__(self) -> None:
        super().__init__()
        self._init_cell()
        self.set_has_frame(False)
        # A shortcut label draws its disabled text where it has no
        # accelerator, which is what an action nothing is bound to
        # shows: nothing.  The hint goes there only while the cell is
        # waiting for a combination to be pressed.
        self.label = Gtk.ShortcutLabel(disabled_text='')
        self._room = _text_width(_ACCEL_WIDTH_CHARS)
        clamp = Gtk.Box()
        clamp.set_layout_manager(_ClampLayout(self._room))
        clamp.set_overflow(Gtk.Overflow.HIDDEN)
        clamp.append(self.label)
        self.set_child(clamp)
        #: Whether the next key pressed is the new shortcut.
        self.capturing = False
        self.connect('clicked', self._clicked)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._pressed)
        self.add_controller(keys)
        #: Told the row and the new accelerator, or None to clear it.
        self.rebind: "Callable[[Row, str | None], None] | None" = None

    def _clicked(self, _button: Gtk.Button) -> None:
        self.capturing = True
        # The property, not set_accelerator(): the two accessors are
        # deprecated where the property they stand for is not.
        self.label.props.disabled_text = _ASK_FOR_ONE_HINT
        self.label.props.accelerator = ''
        self.set_tooltip_text(None)

    def _pressed(self, controller: Gtk.EventControllerKey, keyval: int,
                 keycode: int, state: Gdk.ModifierType) -> bool:
        if not self.capturing:
            return False
        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.capturing = False
            self._show()
            return True
        if keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete):
            self.capturing = False
            if self.rebind is not None and self.row is not None:
                self.rebind(self.row, None)
            return True
        modifiers = state & Gtk.accelerator_get_default_mod_mask()
        if not Gtk.accelerator_valid(keyval, modifiers):
            return True
        self.capturing = False
        if self.rebind is not None and self.row is not None:
            self.rebind(self.row, Gtk.accelerator_name(keyval, modifiers))
        return True

    def _show(self) -> None:
        """Draw the shortcut the row carries."""
        self.label.props.disabled_text = ''
        self.label.props.accelerator = self.accelerator
        _draw_caps(self.label, self.accelerator)
        # Only where the caps do not fit: a tooltip on every shortcut in
        # a list of them would be in the way rather than of any help.
        wanted = self.label.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        self.set_tooltip_text(accelerator_label(self.accelerator)
                              if wanted > self._room else None)

    #: What the row says the shortcut is; filled in when it is bound.
    accelerator = ''


class ColumnListView(Gtk.ColumnView):

    """A list of rows under titled columns.

    This is what a Gtk.TreeView over a Gtk.ListStore was, both of which
    GTK deprecated in 4.10, along with every cell renderer that filled
    one in.  A column is a factory building the widget its cells are
    made of, so a cell is an ordinary widget: what a
    Gtk.CellRendererToggle drew is a real Gtk.CheckButton here, and what
    a Gtk.CellRendererCombo drew is a Gtk.DropDown.
    """

    __gtype_name__ = 'MComixColumnListView'

    def __init__(self, multiple: bool = False, tree: bool = False) -> None:
        #: Whether a row can have rows under it.  A Gtk.TreeStore was a
        #: Gtk.ListStore that did; here the rows carry their own
        #: children and a Gtk.TreeListModel walks them.
        self._tree = tree
        #: The rows, in the order they were added.  With a tree, the
        #: ones at the top level; a row's children are its own.
        self.store = Gio.ListStore(item_type=Row)
        # Always a sort model, with no sorter until a heading is
        # clicked: it costs nothing while it passes the store straight
        # through, and it is what makes the headings work at all, since
        # the sorter a Gtk.ColumnView keeps has to be given to a model
        # by whoever built it.
        self._sorted = Gtk.SortListModel(
            model=Gtk.TreeListModel.new(self.store, False, False,
                                        self._children_of)
            if tree else self.store)
        #: What the view shows: the rows in the order the headings put
        #: them in, which is the order they were added until one is
        #: clicked.  A tree hands out Gtk.TreeListRows wrapping the rows
        #: rather than the rows themselves, which is what _row_of()
        #: unwraps and what the walks below look for.
        self.model: "Gio.ListModel[Row] | Gio.ListModel[Gtk.TreeListRow]" = \
            self._sorted
        self.selection: "Gtk.MultiSelection | Gtk.SingleSelection"
        if multiple:
            self.selection = Gtk.MultiSelection(model=self.model)
        else:
            self.selection = Gtk.SingleSelection(model=self.model)
            # A Gtk.SingleSelection selects the first row as soon as
            # there is one, where a Gtk.TreeView left the selection
            # empty until something was clicked.
            self.selection.set_autoselect(False)
            self.selection.set_can_unselect(True)
        super().__init__(model=self.selection)
        self._sorted.set_sorter(self.get_sorter())
        self._reorderable = False
        #: Every column, by the attribute it shows, in the order added.
        self._columns: list[tuple[str, Gtk.ColumnViewColumn]] = []
        #: The chooser's actions, once a caller has asked for one.
        self._chooser_actions: Gio.SimpleActionGroup | None = None
        #: Who to tell when the chosen columns change.
        self._columns_changed: "Callable[[list[str]], None] | None" = None
        self._search_attribute: str | None = None
        self._search_controller: Gtk.EventControllerKey | None = None
        self._search_typed_so_far = ''
        self._search_at = 0

    @staticmethod
    def _children_of(row: Row) -> "Gio.ListStore[Row] | None":
        """The rows under <row>, if it has any."""
        children = getattr(row, 'children', None)
        if not children:
            return None
        store = Gio.ListStore(item_type=Row)
        for child in children:
            store.append(child)
        return store

    def expand_all(self) -> None:
        """Show the rows under every row that has any."""
        if not self._tree:
            return
        # Walking it grows it: expanding a row puts its children in the
        # model, which the walk then reaches in turn.
        position = 0
        while position < self.model.get_n_items():
            item = self.model.get_item(position)
            if isinstance(item, Gtk.TreeListRow):
                item.set_expanded(True)
            position += 1

    # -- The columns ------------------------------------------------------

    def add_text_column(self, title: str, attr: str,
                        expand: bool = False,
                        text: "Callable[[Row], str] | None" = None,
                        sort_key: "Callable[[Row], tools.SupportsLessThan] | None" = None,
                        markup: bool = False,
                        width_chars: int = -1,
                        max_width_chars: int = -1) -> Gtk.ColumnViewColumn:
        """Show <attr> of each row as text under the heading <title>.

        <text> reads the text off the row itself where it is not the
        attribute as it stands - a collection's name for the id the row
        carries, say.  <sort_key> makes the heading one that sorts, and
        <markup> says the text is Pango markup rather than plain.
        <width_chars> is how narrow the column may be squeezed before
        the list scrolls sideways instead, which a column of names worth
        reading wants and one that only has to fit its heading does not.
        <max_width_chars> is how wide it asks to be drawn at most, which
        bounds what one long entry can take from the columns beside it.
        """
        if text is None:
            def text(row: Row, attr: str = attr) -> str:
                return str(getattr(row, attr, ''))

        def bind(cell: _TextCell, row: Row) -> None:
            cell.set_width_chars(width_chars)
            cell.set_max_width_chars(max_width_chars)
            if markup:
                cell.set_markup(text(row))
            else:
                cell.set_text(text(row))

        return self._add_column(title, _TextCell, bind, expand, attr, sort_key)

    def add_editable_column(self, title: str, attr: str,
                            edited: "Callable[[Row, str], None]",
                            editable: "Callable[[Row], bool] | None" = None,
                            expand: bool = False) -> Gtk.ColumnViewColumn:
        """Show <attr> of each row as text the user can rewrite.

        <editable> says which rows may be rewritten at all, which is
        what a Gtk.CellRendererText read out of a column of the store.
        """
        def bind(cell: _EditableCell, row: Row) -> None:
            cell.edited = None
            cell.set_text(str(getattr(row, attr, '')))
            cell.set_editable(editable(row) if editable is not None else True)
            cell.edited = edited

        return self._add_column(title, _EditableCell, bind, expand, attr, None)

    def add_icon_column(self, title: str, attr: str,
                        expand: bool = False,
                        sort_key: "Callable[[Row], tools.SupportsLessThan] | None" = None) \
            -> Gtk.ColumnViewColumn:
        """Show <attr> of each row, an icon name, as that icon.

        The name rather than a picture: a Gtk.CellRendererPixbuf had to
        be handed a GdkPixbuf.Pixbuf, so whoever filled the row in
        loaded the icon out of the theme itself, at a size it had to
        guess.  A Gtk.Image looks it up for itself, at the size the
        theme says an icon in a list is.
        """
        def bind(cell: _IconCell, row: Row) -> None:
            cell.set_from_icon_name(getattr(row, attr, None))

        return self._add_column(title, _IconCell, bind, expand, attr,
                                sort_key)

    def add_toggle_column(self, title: str, attr: str,
                          toggled: "Callable[[Row, bool], None] | None" = None,
                          activatable: "Callable[[Row], bool] | None" = None,
                          expand: bool = False) -> Gtk.ColumnViewColumn:
        """Show <attr> of each row as a checkbox.

        <toggled> is told the row and the new state when the user clicks
        one; setting the attribute is its business, as it was the
        business of whoever answered a Gtk.CellRendererToggle.
        """
        def bind(cell: _ToggleCell, row: Row) -> None:
            # Setting 'active' emits 'toggled' as a click does, so the
            # handler is put back only once the value is in place.
            if cell.handler is not None:
                cell.disconnect(cell.handler)
                cell.handler = None
            cell.set_active(bool(getattr(row, attr, False)))
            cell.set_sensitive(activatable(row)
                               if activatable is not None else True)
            if toggled is not None:
                cell.handler = cell.connect(
                    'toggled',
                    lambda button: toggled(row, button.get_active()))

        def unbind(cell: _ToggleCell) -> None:
            if cell.handler is not None:
                cell.disconnect(cell.handler)
                cell.handler = None

        return self._add_column(title, _ToggleCell, bind, expand, attr, None,
                                unbind=unbind)

    def add_accel_column(self, title: str, attr: str,
                         rebind: "Callable[[Row, str | None], None]",
                         bindable: "Callable[[Row], bool] | None" = None,
                         expand: bool = False) -> Gtk.ColumnViewColumn:
        """Show <attr> of each row as a keyboard shortcut to rebind.

        <rebind> is told the row and the accelerator that was pressed,
        or None where it was cleared; writing it to the row is its
        business, as it was the business of whoever answered a
        Gtk.CellRendererAccel.  <bindable> says which rows have a
        shortcut at all - a heading standing over other rows does not.
        """
        def bind(cell: _AccelCell, row: Row) -> None:
            cell.capturing = False
            cell.rebind = rebind
            # A heading has no shortcut, so its cell stands empty and
            # cannot be pressed.  It is not hidden: a hidden cell asks
            # for no width, and the column would then be a different
            # width whenever headings were all that was on screen.
            takes_one = bindable(row) if bindable is not None else True
            cell.accelerator = str(getattr(row, attr, '') or '') \
                if takes_one else ''
            cell._show()
            cell.set_sensitive(takes_one)

        return self._add_column(title, _AccelCell, bind, expand, attr, None)

    def add_choice_column(self, title: str, attr: str,
                          choices: "Callable[[], list[str]]",
                          chosen: "Callable[[Row, str], None]",
                          shown: "Callable[[Row], str] | None" = None,
                          expand: bool = False) -> Gtk.ColumnViewColumn:
        """Show <attr> of each row as one of <choices> to pick from.

        <choices> is asked for the list every time a cell is filled in,
        because it is not fixed: the collections a watched directory can
        be put in change while the dialog stands.
        """
        def bind(cell: _ChoiceCell, row: Row) -> None:
            if cell.handler is not None:
                cell.disconnect(cell.handler)
                cell.handler = None
            options = choices()
            model = Gtk.StringList()
            for option in options:
                model.append(option)
            cell.set_model(model)
            current = shown(row) if shown is not None \
                else str(getattr(row, attr, ''))
            if current in options:
                cell.set_selected(options.index(current))
            else:
                cell.set_selected(Gtk.INVALID_LIST_POSITION)
            cell.handler = cell.connect(
                'notify::selected',
                lambda widget, _param: self._chose(widget, row, chosen))

        def unbind(cell: _ChoiceCell) -> None:
            if cell.handler is not None:
                cell.disconnect(cell.handler)
                cell.handler = None

        return self._add_column(title, _ChoiceCell, bind, expand, attr, None,
                                unbind=unbind)

    @staticmethod
    def _chose(cell: _ChoiceCell, row: Row,
               chosen: "Callable[[Row, str], None]") -> None:
        item = cell.get_selected_item()
        if item is not None:
            chosen(row, cast(Gtk.StringObject, item).get_string())

    def _add_column(self, title: str, cell_type: type,  # type: ignore[explicit-any]  # each column binds a cell class of its own
                    bind: "Callable[..., None]",
                    expand: bool, attr: str,
                    sort_key: "Callable[[Row], tools.SupportsLessThan] | None",
                    unbind: "Callable[[Any], None] | None" = None) \
            -> Gtk.ColumnViewColumn:
        factory = Gtk.SignalListItemFactory()

        #: The expander goes in the first column, which is the one the
        #: rows under a row are indented from.
        expanding = self._tree and not self.get_columns().get_n_items()

        def on_setup(_factory: Gtk.SignalListItemFactory,
                     item: Gtk.ListItem) -> None:
            cell = cell_type()
            self._decorate_cell(cell)
            if expanding:
                expander = Gtk.TreeExpander()
                expander.set_child(cell)
                item.set_child(expander)
            else:
                item.set_child(cell)

        def on_bind(_factory: Gtk.SignalListItemFactory,
                    item: Gtk.ListItem) -> None:
            child = item.get_child()
            if isinstance(child, Gtk.TreeExpander):
                child.set_list_row(cast(Gtk.TreeListRow, item.get_item()))
                child = child.get_child()
            cell = cast(_Cell, child)
            row = self._row_of(item.get_item())
            # Everything in the model is a Row, whatever the Gio.ListModel
            # the tree wraps it in is willing to say it might be.
            assert row is not None
            cell.row = row
            cell.position = item.get_position()
            bind(cell, row)
            if isinstance(cell, (_TextCell, _IconCell, _AccelCell,
                                 _EditableCell)):
                cell.handler = row.connect(
                    'changed', lambda _row, cell=cell: bind(cell, _row))

        def on_unbind(_factory: Gtk.SignalListItemFactory,
                      item: Gtk.ListItem) -> None:
            child = item.get_child()
            if isinstance(child, Gtk.TreeExpander):
                child.set_list_row(None)
                child = child.get_child()
            cell = cast(_Cell, child)
            if isinstance(cell, (_TextCell, _IconCell, _AccelCell,
                                 _EditableCell)):
                if cell.handler is not None and cell.row is not None:
                    cell.row.disconnect(cell.handler)
                cell.handler = None
            elif unbind is not None:
                unbind(cell)
            cell.row = None

        factory.connect('setup', on_setup)
        factory.connect('bind', on_bind)
        factory.connect('unbind', on_unbind)

        column = Gtk.ColumnViewColumn(title=title, factory=factory)
        column.set_expand(expand)
        if sort_key is not None:
            column.set_sorter(Gtk.CustomSorter.new(
                lambda left, right, _data:
                _compare(sort_key(left), sort_key(right))))
        self.append_column(column)
        self._columns.append((attr, column))
        return column

    # -- Choosing which columns are drawn ----------------------------------

    #: The prefix the chooser's actions answer under.
    _CHOOSER_PREFIX = 'columns'

    def offer_column_chooser(
            self, hidden: Iterable[str] = (),
            changed: "Callable[[list[str]], None] | None" = None) -> None:
        """Let every heading offer a menu turning the columns on and off.

        A Gtk.TreeView had no such menu either, which is why the columns
        MComix did not have the room for were built and then hidden with
        no way to ask for them.

        <hidden> names the columns that start out hidden, by the
        attribute each of them shows; <changed> is handed the names of
        the hidden ones whenever that changes, so that a caller can
        remember them.  Call this once, after the last column is added.
        """
        self._columns_changed = changed
        actions = Gio.SimpleActionGroup()
        menu = Gio.Menu()

        for attr, column in self._columns:
            visible = attr not in hidden
            column.set_visible(visible)
            action = Gio.SimpleAction.new_stateful(
                attr, None, GLib.Variant.new_boolean(visible))
            action.connect('change-state', self._column_chosen, column)
            actions.add_action(action)
            menu.append(column.get_title() or attr,
                        '%s.%s' % (self._CHOOSER_PREFIX, attr))

        self._chooser_actions = actions
        self.insert_action_group(self._CHOOSER_PREFIX, actions)
        for _attr, column in self._columns:
            column.set_header_menu(menu)
        self._update_chooser()

    def _column_chosen(self, action: Gio.SimpleAction, state: GLib.Variant,
                       column: Gtk.ColumnViewColumn) -> None:
        column.set_visible(state.get_boolean())
        action.set_state(state)
        self._update_chooser()
        if self._columns_changed is not None:
            self._columns_changed(self.hidden_columns())

    def _update_chooser(self) -> None:
        """Keep the last column that is left from being hidden too.

        The menu hangs off the headings, and a list with no columns has
        none: hiding the last one would take away the way back.
        """
        if self._chooser_actions is None:
            return
        showing = [attr for attr, column in self._columns
                   if column.get_visible()]
        for attr, _column in self._columns:
            action = self._chooser_actions.lookup_action(attr)
            if action is not None:
                cast(Gio.SimpleAction, action).set_enabled(
                    showing != [attr])

    def hidden_columns(self) -> list[str]:
        """The columns that are not drawn, by the attribute each shows."""
        return [attr for attr, column in self._columns
                if not column.get_visible()]

    # -- Reordering by dragging -------------------------------------------

    #: What a reordering drag carries: the position it started from.
    _REORDER_TYPE = 'application/x-mcomix-row-position'

    def set_reorderable(self, reorderable: bool) -> None:
        """Let the rows be dragged into a different order."""
        self._reorderable = reorderable

    def _decorate_cell(self, cell: _Cell) -> None:
        """Make <cell> one a reordering drag can start from and land on.

        Gtk.TreeView.set_reorderable() did this for itself.  A
        Gtk.ColumnView has no notion of it, so every cell carries a drag
        source and a drop target - any cell of a row, so that the row
        can be picked up wherever the pointer is on it.
        """
        if not self._reorderable:
            return
        source = Gtk.DragSource()
        source.set_actions(Gdk.DragAction.MOVE)
        source.connect('prepare', self._reorder_prepare, cell)
        cast(Gtk.Widget, cell).add_controller(source)
        target = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)
        target.connect('drop', self._reorder_drop, cell)
        cast(Gtk.Widget, cell).add_controller(target)

    def _rows_are_the_store(self) -> bool:
        """Whether what is drawn is the store, row for row.

        The position a cell carries is the one the view draws it at,
        and a drag is a move in the store: the two are the same number
        only while nothing stands between them.  A heading that is
        sorting puts the rows in an order of its own, and a tree draws
        the rows under a row alongside the ones the store holds, so
        under either a drop would move whichever row happened to sit at
        that number.  A Gtk.TreeView answered this by refusing to
        reorder a sorted model at all, which is what refusing the drag
        does here.
        """
        if self._tree:
            return False
        sorter = self.get_sorter()
        return not isinstance(sorter, Gtk.ColumnViewSorter) \
            or sorter.get_primary_sort_column() is None

    def _reorder_prepare(self, source: "Gtk.DragSource | None", x: float,
                         y: float, cell: _Cell) -> "Gdk.ContentProvider | None":
        # Nothing to carry is how a Gtk.DragSource is told not to start.
        if not self._rows_are_the_store():
            return None
        return Gdk.ContentProvider.new_for_value(
            '%s:%d' % (self._REORDER_TYPE, cell.position))

    def _reorder_drop(self, target: "Gtk.DropTarget | None", value: str,
                      x: float, y: float, cell: _Cell) -> bool:
        prefix = self._REORDER_TYPE + ':'
        if not isinstance(value, str) or not value.startswith(prefix):
            return False
        if not self._rows_are_the_store():
            return False
        try:
            source_position = int(value[len(prefix):])
        except ValueError:
            return False
        return self.move_row(source_position, cell.position)

    def move_row(self, source: int, destination: int) -> bool:
        """Move the row at <source> so that it sits at <destination>.

        Both are positions in the store, which are the positions the
        rows are drawn at only while nothing is sorting them.
        """
        count = self.store.get_n_items()
        if source == destination or not 0 <= source < count \
                or not 0 <= destination < count:
            return False
        row = cast(Row, self.store.get_item(source))
        self.store.remove(source)
        self.store.insert(destination, row)
        return True

    def _each_cell(self) -> Iterator[_Cell]:
        """Every cell that is on screen right now, whatever column."""
        def walk(widget: Gtk.Widget) -> Iterator[_Cell]:
            child = widget.get_first_child()
            while child is not None:
                if isinstance(child, _Cell):
                    yield child
                else:
                    yield from walk(child)
                child = child.get_next_sibling()
        yield from walk(self)

    def row_paintable(self, row: Row) -> "Gdk.Paintable | None":
        """A picture of <row> as it is drawn, for a drag icon."""
        for cell in self._each_cell():
            if cell.row is row:
                widget = cast(Gtk.Widget, cell)
                parent = widget.get_parent()
                return Gtk.WidgetPaintable.new(parent
                                               if parent is not None
                                               else widget)
        return None

    #: Where a drop on the row under the pointer would land: above it,
    #: on it, or below it.  This is what Gtk.TreeViewDropPosition said,
    #: and it is read the same way - from how far down the row the
    #: pointer is.
    DROP_BEFORE, DROP_INTO, DROP_AFTER = 0, 1, 2

    def drop_at(self, x: float, y: float) -> "tuple[Row, int] | None":
        """The row under (<x>, <y>) and where a drop on it would land."""
        for cell in self._each_cell():
            widget = cast(Gtk.Widget, cell)
            found, bounds = widget.compute_bounds(self)
            if not found or cell.row is None:
                continue
            if not (bounds.origin.y <= y < bounds.origin.y + bounds.size.height):
                continue
            offset = (y - bounds.origin.y) / max(1.0, bounds.size.height)
            if offset < 0.25:
                return cell.row, self.DROP_BEFORE
            if offset > 0.75:
                return cell.row, self.DROP_AFTER
            return cell.row, self.DROP_INTO
        return None

    # -- Rows under rows --------------------------------------------------

    def path_to(self, row: Row) -> "list[Row] | None":
        """Every row above <row> in the tree, the topmost first."""
        def walk(rows: Iterable[Row],
                 above: list[Row]) -> "list[Row] | None":
            for candidate in rows:
                if candidate is row:
                    return above
                children = getattr(candidate, 'children', None)
                if children:
                    found = walk(children, above + [candidate])
                    if found is not None:
                        return found
            return None
        return walk(list(self.store), [])

    def is_above(self, row: Row, other: Row) -> bool:
        """Whether <row> is somewhere above <other> in the tree."""
        path = self.path_to(other)
        return path is not None and row in path

    def expand_to(self, row: Row) -> bool:
        """Expand whatever it takes for <row> to be shown."""
        path = self.path_to(row)
        if path is None:
            return False
        # Top down: a row is only in the model once its parent is
        # expanded, so each step brings the next one into reach.
        for above in path:
            tree_row = self._tree_row_of(above)
            if tree_row is None:
                return False
            tree_row.set_expanded(True)
        return True

    def expanded_rows(self) -> list[Row]:
        """Every row that is expanded right now."""
        expanded: list[Row] = []
        for position in range(self.model.get_n_items()):
            item = self.model.get_item(position)
            if isinstance(item, Gtk.TreeListRow) and item.get_expanded():
                expanded.append(cast(Row, item.get_item()))
        return expanded

    def _tree_row_of(self, row: Row) -> "Gtk.TreeListRow | None":
        """The Gtk.TreeListRow standing for <row>, if it is shown."""
        for position in range(self.model.get_n_items()):
            item = self.model.get_item(position)
            if isinstance(item, Gtk.TreeListRow) and item.get_item() is row:
                return item
        return None

    def toggle_expanded(self, row: Row) -> None:
        """Expand <row> if it is collapsed, and collapse it if not."""
        tree_row = self._tree_row_of(row)
        if tree_row is not None:
            tree_row.set_expanded(not tree_row.get_expanded())

    # -- Finding a row by typing its name ---------------------------------

    #: How long the letters typed so far stand, in milliseconds.  What
    #: Gtk.TreeView's own typeahead used.
    _SEARCH_TIMEOUT = 1000

    def set_search_attribute(self, attr: "str | None") -> None:
        """Select rows by typing the first letters of their <attr>.

        This is Gtk.TreeView.set_search_column(), which a
        Gtk.ColumnView has nothing of: the letters are collected here
        and the first row whose value starts with them is selected.
        """
        self._search_attribute = attr
        if attr is None or self._search_controller is not None:
            return
        self._search_controller = Gtk.EventControllerKey()
        self._search_controller.connect('key-pressed', self._search_typed)
        self.add_controller(self._search_controller)

    def _search_typed(self, controller: Gtk.EventControllerKey, keyval: int,
                      keycode: int, state: Gdk.ModifierType) -> bool:
        if self._search_attribute is None:
            return False
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        character = chr(Gdk.keyval_to_unicode(keyval) or 0)
        if not character.isprintable() or character.isspace():
            return False
        now = GLib.get_monotonic_time() // 1000
        if now - self._search_at > self._SEARCH_TIMEOUT:
            self._search_typed_so_far = ''
        self._search_at = now
        self._search_typed_so_far += character.lower()
        for position, row in enumerate(self.each_row()):
            value = str(getattr(row, self._search_attribute, '')).lower()
            if value.startswith(self._search_typed_so_far):
                self.select_only(position)
                self.scroll_to(position, None, Gtk.ListScrollFlags.NONE, None)
                return True
        return False

    def set_headers_visible(self, visible: bool) -> None:
        """Show or hide the row of column headings.

        Gtk.TreeView had this as a property.  A Gtk.ColumnView has no
        such thing - its heading row is the first child it builds for
        itself - so the child is hidden instead.
        """
        header = self.get_first_child()
        if header is not None and header.get_css_name() == 'header':
            header.set_visible(visible)

    def sort_by(self, column: "Gtk.ColumnViewColumn | None",
                descending: bool = False) -> None:
        """Show the rows in <column>'s order from now on.

        <column> of None puts them back in the order they were added,
        which is what clicking past the last heading does.
        """
        self.sort_by_column(
            column,
            Gtk.SortType.DESCENDING if descending else Gtk.SortType.ASCENDING)

    # -- What is in it ----------------------------------------------------

    def set_rows(self, rows: Iterable[Row]) -> None:
        """Show <rows>, and nothing that was there before."""
        rows = list(rows)
        self.store.splice(0, self.store.get_n_items(), rows)

    def append_row(self, row: Row) -> None:
        """Add <row> to the end."""
        self.store.append(row)

    def insert_row(self, position: int, row: Row) -> None:
        """Put <row> in at <position>."""
        self.store.insert(position, row)

    def remove_row(self, row: Row) -> bool:
        """Take <row> out; False if it was not in there."""
        found, position = self.store.find(row)
        if not found:
            return False
        self.store.remove(position)
        return True

    def clear(self) -> None:
        """Take every row out."""
        self.store.remove_all()

    @staticmethod
    def _row_of(item: "GObject.Object | None") -> "Row | None":
        """The row <item> stands for.

        A Gtk.TreeListModel hands out a Gtk.TreeListRow around each of
        them, which is what carries whether it is expanded and how deep
        it sits; a flat list hands out the row itself.
        """
        if isinstance(item, Gtk.TreeListRow):
            item = item.get_item()
        return item if isinstance(item, Row) else None

    def each_row(self) -> Iterator[Row]:
        """Every row that is shown, in the order they are shown.

        With a tree, the rows under a row that is not expanded are not
        shown and so are not among them.
        """
        for position in range(self.model.get_n_items()):
            yield cast(Row, self._row_of(self.model.get_item(position)))

    def get_row(self, position: int) -> "Row | None":
        """The row shown at <position>."""
        return self._row_of(self.model.get_item(position))

    # -- Selection --------------------------------------------------------

    def get_selected_row(self) -> "Row | None":
        """The selected row, or the first of them, or None."""
        rows = self.get_selected_rows()
        return rows[0] if rows else None

    def get_selected_rows(self) -> list[Row]:
        """Every selected row, in the order they are shown."""
        return [cast(Row, self._row_of(self.model.get_item(position)))
                for position in self.get_selected_positions()]

    def get_selected_positions(self) -> list[int]:
        """Where the selected rows are shown, in order."""
        selected = self.selection.get_selection()
        positions = []
        for index in range(selected.get_size()):
            positions.append(selected.get_nth(index))
        return positions

    def select_only(self, position: int) -> None:
        """Select the row at <position> and nothing else."""
        self.selection.select_item(position, True)

    def select_row(self, row: Row) -> bool:
        """Select <row>; False if it is not shown."""
        for position, shown in enumerate(self.each_row()):
            if shown is row:
                self.select_only(position)
                return True
        return False

    def unselect_all(self) -> None:
        """Leave nothing selected."""
        self.selection.unselect_all()

    def row_at(self, x: float, y: float) -> "Row | None":
        """The row under (<x>, <y>), or None if no row is."""
        picked = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while picked is not None and not isinstance(picked, _Cell):
            picked = picked.get_parent()
        return picked.row if picked is not None else None


def _compare(left: "tools.SupportsLessThan",
             right: "tools.SupportsLessThan") -> int:
    """The -1, 0, 1 a Gtk.CustomSorter answers with.

    Only < is asked of the two, which is all a sort key has to offer:
    Python answers a > b with b.__lt__(a) anyway.
    """
    return int(right < left) - int(left < right)

# vim: expandtab:sw=4:ts=4
