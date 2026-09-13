"""What an action table's callback is handed when its action runs.

Gio hands an activate handler both the action and the parameter it was
activated with, and a handler that takes only one of them raises
TypeError - which GObject prints and swallows, leaving the menu item
doing nothing at all.  The tables go through one place that gets this
right; these are what say so.
"""

from . import MComixTest

from mcomix import ui


class ActionTableTest(MComixTest):

    def setUp(self):
        super().setUp()
        self.actions = ui.Actions()
        self.ran = []

    def test_a_plain_action_is_run_with_the_action_that_ran(self):
        self.actions.add([ui._Entry('probe', None, 'Probe', None,
                                    self.ran.append)])
        self.actions.get_action('probe').activate()
        self.assertEqual(1, len(self.ran))
        self.assertEqual('probe', self.ran[0].get_name())

    def test_an_action_with_data_is_run_with_the_data_as_well(self):
        self.actions.add_with_data(
            [ui._Entry('probe', None, 'Probe', None,
                       lambda action, data: self.ran.append(data))],
            'the data')
        self.actions.get_action('probe').activate()
        self.assertEqual(['the data'], self.ran)

    def test_a_toggle_is_run_with_the_action_in_mcomix_own_shape(self):
        # Not the Gio action: a toggle's callback asks get_active(),
        # which is what the wrapper adds.
        self.actions.add_toggle(
            [ui._Entry('probe', None, 'Probe', None,
                       lambda action: self.ran.append(action.get_active()))])
        self.actions.get_action('probe').set_active(True)
        self.assertEqual([True], self.ran)

    def test_a_radio_group_hands_its_callback_the_value_that_was_picked(self):
        self.actions.add_radio(
            'probe-group',
            [ui._Choice('one', None, 'One', None, 1),
             ui._Choice('two', None, 'Two', None, 2)],
            1, lambda action: self.ran.append(action.get_current_value()))
        self.actions.get_action('two').activate()
        self.assertEqual([2], self.ran)

    def test_a_row_with_nothing_to_do_still_names_its_action(self):
        # A menu that only opens a submenu has no callback at all.
        self.actions.add([ui._Entry('menu_probe', None, 'Probe')])
        self.assertEqual('Probe', self.actions.label('menu_probe'))


# vim: expandtab:sw=4:ts=4
