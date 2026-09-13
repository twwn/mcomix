# -*- coding: utf-8 -*-

"""The dropdown the preferences dialog picks its options from.

It was a Gtk.ComboBox over a two-column Gtk.ListStore: the label in one
column and the value in the other, walked back out with a Gtk.TreeIter
by every one of the twelve callbacks that read it. What those callbacks
need is the value, so that is what it answers with.
"""

from . import MComixTest

from mcomix import widgets


class ChooserTest(MComixTest):

    OPTIONS = (('Never', 0), ('Sometimes', 1), ('Always', 2))

    def setUp(self):
        super(ChooserTest, self).setUp()
        self.chooser = widgets.Chooser(self.OPTIONS, 1)

    def test_the_labels_are_the_ones_that_were_offered(self):
        model = self.chooser.get_model()
        self.assertEqual([model.get_string(position)
                          for position in range(model.get_n_items())],
                         ['Never', 'Sometimes', 'Always'])

    def test_it_starts_on_the_value_it_was_given(self):
        self.assertEqual(self.chooser.get_value(), 1)

    def test_a_value_that_was_not_offered_leaves_the_first_one_showing(self):
        """A Gtk.DropDown cannot show nothing, where a Gtk.ComboBox
        could: with a preference holding a value that is no longer
        offered, the box went blank and now shows the first option."""
        chooser = widgets.Chooser(self.OPTIONS, 99)
        self.assertEqual(chooser.get_selected(), 0)

    def test_a_chooser_with_nothing_to_offer_is_refused(self):
        # A dropdown showing none of its options is a blank box the user
        # cannot do anything with, and every chooser in MComix is built
        # from a fixed list.  Refusing the empty one is what lets
        # get_value() always have an answer.
        self.assertRaises(ValueError, widgets.Chooser, ())

    def test_picking_a_position_answers_with_its_value(self):
        self.chooser.set_selected(2)
        self.assertEqual(self.chooser.get_value(), 2)

    def test_setting_a_value_picks_the_position_it_is_at(self):
        self.chooser.set_value(0)
        self.assertEqual(self.chooser.get_selected(), 0)

    def test_a_change_reaches_whoever_is_listening(self):
        seen = []
        self.chooser.connect_changed(lambda widget: seen.append(
            widget.get_value()))
        self.chooser.set_value(2)
        self.assertEqual(seen, [2])

    def test_a_value_that_is_not_a_number_works_the_same_way(self):
        """The language chooser's values are strings, and the store had
        to be told the type of its second column from the first item."""
        chooser = widgets.Chooser((('English', 'en'), ('Suomi', 'fi')), 'fi')
        self.assertEqual(chooser.get_value(), 'fi')

# vim: expandtab:sw=4:ts=4
