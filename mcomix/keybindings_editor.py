# -*- coding: utf-8 -*-

""" Configuration list for the preferences dialog to edit keybindings. """

from gi.repository import Gtk

from mcomix import column_list
from mcomix import keybindings
from mcomix.i18n import _
from mcomix import widgets


class KeybindingEditorWindow(Gtk.ScrolledWindow):

    #: How much of the name of an action is always shown, in characters.
    _NAME_WIDTH = 16

    def __init__(self, keymanager):
        """ @param keymanager: KeybindingManager instance. """
        super(KeybindingEditorWindow, self).__init__()
        widgets.set_border(self, 5)
        self.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.ALWAYS)

        self.keymanager = keymanager

        accel_column_num = max([
            len(self.keymanager.get_bindings_for_action(action))
            for action in list(keybindings.BINDING_INFO.keys())
        ])
        accel_column_num = self.accel_column_num = max([3, accel_column_num])

        # The actions of a group sit under a row naming it, which is
        # what a Gtk.TreeStore held and a Gtk.TreeListModel holds now.
        self._list = column_list.ColumnListView(tree=True)
        # A line between the columns: five of them side by side, four
        # holding shortcuts that look much alike, are hard to read down
        # without one.
        self._list.add_css_class('column-separators')
        # The names are what the list is read by, so the column keeps
        # room for them: everything past what the shortcuts take is
        # theirs, and where there is not enough the list scrolls
        # sideways rather than cutting them down to nothing.
        self._name_col = self._list.add_text_column(
            _("Name"), 'title', expand=True, width_chars=self._NAME_WIDTH)
        for index in range(0, self.accel_column_num):
            self._list.add_accel_column(
                _("Key %d") % (index + 1), self._key_of(index),
                self._rebound(index), bindable=self._takes_a_shortcut)

        self.refresh_model()

        self.set_child(self._list)

    @staticmethod
    def _takes_a_shortcut(row: column_list.Row) -> bool:
        """Whether <row> stands for an action rather than a group."""
        return row.action is not None

    @staticmethod
    def _key_of(index):
        """The attribute a row keeps its <index>th shortcut under."""
        return 'key%d' % index

    def refresh_model(self) -> None:
        """ Initializes the model from data provided by the keybinding
        manager. """
        section_order = list(set(d['group']
             for d in list(keybindings.BINDING_INFO.values())))
        section_order.sort()
        sections = {}
        rows = []
        for section_name in section_order:
            # A group heading is a row with no action behind it, which
            # is what its empty accelerators and its name say.
            section = column_list.Row(title=section_name, action=None,
                                      children=[])
            sections[section_name] = section
            rows.append(section)

        action_rows = self.action_rows = {}
        # Sort actions by action name
        actions = sorted(list(keybindings.BINDING_INFO.items()),
                key=lambda item: item[1]['title'])
        for action_name, action_data in actions:
            old_bindings = self.keymanager.get_bindings_for_action(action_name)
            row = column_list.Row(title=action_data['title'],
                                  action=action_name)
            for index in range(0, self.accel_column_num):
                setattr(row, self._key_of(index),
                        Gtk.accelerator_name(*old_bindings[index])
                        if len(old_bindings) > index else '')
            sections[action_data['group']].children.append(row)
            action_rows[action_name] = row

        self._list.set_rows(rows)

    def _rebound(self, column):
        """Answer a rebinding of the <column>th shortcut of a row."""
        def rebound(row, accelerator):
            if row.action is None:
                # A group heading has no shortcut to rebind.
                return
            if accelerator is None:
                self._clear_accel(row, column)
            else:
                self._edit_accel(row, column, accelerator)
            row.changed()
        return rebound

    def _edit_accel(self, row, column, new_accel) -> None:
        """Bind <new_accel> as the <column>th shortcut of <row>."""
        key = self._key_of(column)
        old_accel = getattr(row, key)
        setattr(row, key, new_accel)
        affected_action = self.keymanager.edit_accel(row.action, new_accel,
                                                     old_accel)

        # A shortcut answers to one action only, so wherever it was
        # before, it is not there any more.
        if affected_action == row.action:
            self._take_accel_from(row, new_accel, except_column=column)
        elif affected_action is not None:
            affected = self.action_rows[affected_action]
            self._take_accel_from(affected, new_accel)
            affected.changed()

        # updating the accelerator shown against the action in the menu
        bindings = self.keymanager.get_bindings_for_action(row.action)
        if bindings and Gtk.accelerator_name(*bindings[0]) == new_accel:
            self.keymanager.announce_accelerator(row.action, new_accel)

    def _clear_accel(self, row, column) -> None:
        """Unbind the <column>th shortcut of <row>."""
        key = self._key_of(column)
        accel = getattr(row, key)
        setattr(row, key, '')
        if not accel:
            return

        self.keymanager.clear_accel(row.action, accel)

        # updating the accelerator shown against the action in the menu
        bindings = self.keymanager.get_bindings_for_action(row.action)
        self.keymanager.announce_accelerator(
            row.action, Gtk.accelerator_name(*bindings[0]) if bindings else '')

    def _take_accel_from(self, row, accelerator, except_column=None) -> None:
        """Clear <accelerator> off <row>, wherever it is shown on it."""
        for index in range(0, self.accel_column_num):
            if index == except_column:
                continue
            key = self._key_of(index)
            if getattr(row, key) == accelerator:
                setattr(row, key, '')

# vim: expandtab:sw=4:ts=4
