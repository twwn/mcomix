"""The translation template against the strings the source actually marks.

A msgid that never reaches mcomix.pot cannot be translated, in any
language, however complete a catalogue looks; one that lingers after its
string is gone wastes a translator's attention. Both drift in silently,
because nothing about a stale template shows up when the program runs.
"""

import ast
import gettext
import glob
import os
import shutil
import subprocess
import unittest

from . import MComixTest

from mcomix import constants
from mcomix import ui


MESSAGES_PATH = os.path.join(constants.BASE_PATH, 'mcomix', 'messages')
TEMPLATE_PATH = os.path.join(MESSAGES_PATH, 'mcomix.pot')


def read_msgids(path):
    """The set of msgids <path> defines, ignoring obsolete entries and
    the header, whose msgid is empty."""
    msgids, parts, reading = set(), [], False
    with open(path, encoding='utf-8') as catalogue:
        for line in catalogue:
            line = line.rstrip('\n')
            if line.startswith('msgid '):
                reading, parts = True, [line[len('msgid '):]]
            elif reading and line.startswith('"'):
                parts.append(line)
            elif reading:
                msgids.add(''.join(part[1:-1] for part in parts))
                reading = False
    if reading:
        msgids.add(''.join(part[1:-1] for part in parts))
    msgids.discard('')
    return msgids


def read_catalogue(path):
    """What a compiled catalogue translates, without its header."""
    with open(path, 'rb') as catalogue:
        translations = dict(gettext.GNUTranslations(catalogue)._catalog)
    translations.pop('', None)
    return translations


@unittest.skipIf(shutil.which('xgettext') is None, 'xgettext is not installed')
class TemplateTest(MComixTest):

    """mcomix.pot names every string the source marks for translation."""

    def _extract(self):
        """The msgids xgettext finds in the source right now. The file set
        is the one wiki/content/Maintenance.md documents.

        The header is kept, though read_msgids() drops it again: it is
        where xgettext states the encoding it wrote, and asked to omit
        it xgettext writes ASCII instead and drops what will not fit -
        a msgid of "Rotate 90° CW" comes back as "Rotate 90 CW".
        """
        extracted = os.path.join(self.tmp_dir, 'extracted.pot')
        sources = []
        for pattern in ('mcomix/*.py', 'mcomix/archive/*.py',
                        'mcomix/library/*.py'):
            sources.extend(sorted(glob.glob(
                os.path.join(constants.BASE_PATH, pattern))))
        self.assertTrue(sources, 'no sources to extract from')
        subprocess.run(
            ['xgettext', '-LPython', '-o', extracted, '--from-code=utf-8']
            + sources,
            check=True, capture_output=True)
        return read_msgids(extracted)

    def test_the_template_holds_every_marked_string(self):
        missing = self._extract() - read_msgids(TEMPLATE_PATH)
        self.assertEqual(set(), missing,
                         'strings the source marks that mcomix.pot lacks; '
                         'regenerate it as wiki/content/Maintenance.md says')

    def test_the_template_holds_nothing_the_source_dropped(self):
        stale = read_msgids(TEMPLATE_PATH) - self._extract()
        self.assertEqual(set(), stale,
                         'strings in mcomix.pot the source no longer marks; '
                         'regenerate it as wiki/content/Maintenance.md says')

    @unittest.skipIf(shutil.which('msgfmt') is None, 'msgfmt is not installed')
    def test_every_catalogue_is_compiled(self):
        """The .mo beside each .po says what the .po says.

        gettext reads the .mo and nothing reads the .po, so a
        translation that was never compiled is not a translation: it is
        a file saying what the program would have said if anyone had
        run msgfmt. The header is left out of the comparison, being
        stamped with the time it was compiled at."""
        for path in sorted(glob.glob(
                os.path.join(MESSAGES_PATH, '*', 'LC_MESSAGES', 'mcomix.po'))):
            name = os.path.relpath(path, constants.BASE_PATH)
            compiled = path[:-len('.po')] + '.mo'
            self.assertTrue(os.path.isfile(compiled),
                            '%s was never compiled' % name)
            fresh = os.path.join(self.tmp_dir, 'fresh.mo')
            subprocess.run(['msgfmt', path, '-o', fresh],
                           check=True, capture_output=True)
            self.assertEqual(read_catalogue(fresh), read_catalogue(compiled),
                             '%s is out of step with its catalogue; compile '
                             'it as wiki/content/Maintenance.md says' % name)

    def test_every_catalogue_covers_the_template(self):
        template = read_msgids(TEMPLATE_PATH)
        for path in sorted(glob.glob(
                os.path.join(MESSAGES_PATH, '*', 'LC_MESSAGES', 'mcomix.po'))):
            missing = template - read_msgids(path)
            self.assertEqual(set(), missing,
                             '%s is behind the template; msgmerge it'
                             % os.path.relpath(path, constants.BASE_PATH))


class MnemonicTest(MComixTest):

    """No two items of one menu answer to the same Alt key.

    Two that do are both out of reach of it: GTK moves the highlight
    from one to the other instead of activating either, so the key that
    should run a command runs nothing.  A translated menu is where this
    goes wrong, because the letters a translation offers are not the
    ones the English label did, and it has gone wrong here twice - once
    for 261 items across ten languages, and again for 30 more that crept
    back in as items were added to the menus afterwards.

    The menus are read from ui.py rather than from a window that has
    been built: a built window's labels are already translated into one
    language, and checking all 24 would mean building 24 windows.  The
    layouts are module constants, and the label each action carries is
    taken out of the _Entry() calls with ast, so the menus this checks
    are the menus the program builds.
    """

    @staticmethod
    def _label_msgids():
        """The msgid of every action's label, by action name."""
        source = os.path.join(constants.BASE_PATH, 'mcomix', 'ui.py')
        msgids = {}
        for node in ast.walk(ast.parse(
                open(source, encoding='utf-8').read())):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == '_Entry'
                    and isinstance(node.args[0], ast.Constant)):
                continue
            if len(node.args) < 3:
                continue
            label = node.args[2]
            if (isinstance(label, ast.Call)
                    and isinstance(label.func, ast.Name)
                    and label.func.id == '_'
                    and isinstance(label.args[0], ast.Constant)):
                msgids[node.args[0].value] = label.args[0].value
        return msgids

    @classmethod
    def _menus(cls, layout, msgids, title):
        """Yield (name, [msgid, ...]) for <layout> and its submenus.

        A section is a run of items with a separator drawn round it, not
        a scope of its own - everything on one level of a menu answers
        to the same key press - so the sections are flattened.
        """
        here = []
        for item in layout:
            if item is None:
                continue
            if isinstance(item, tuple):
                name, contents = item
                here.append(name)
                yield from cls._menus(contents, msgids, name)
            else:
                here.append(item)
        yield title, [msgids[name] for name in here if name in msgids]

    #: The modules that build a menu of their own rather than through
    #: ui.py.  Each builds exactly one, and every translatable string in
    #: it that carries a mnemonic is a label of that menu, so the module
    #: is the scope - which is why a module holding dialog buttons as
    #: well, where Gtk.ButtonsType shows one set and not another, is not
    #: on this list.
    MENU_MODULES = (
        'mcomix/bookmark_menu.py',
        'mcomix/edit_image_area.py',
        'mcomix/edit_comment_area.py',
        'mcomix/library/book_area.py',
        'mcomix/library/collection_area.py',
        'mcomix/openwith_menu.py',
    )

    @classmethod
    def _module_menus(cls):
        """The menus built outside ui.py, by the module that builds one.

        ui.py names its labels in a table this can read; these modules
        write theirs where they use them, so what is collected is every
        string the module marks for translation, and the ones carrying a
        mnemonic are the menu.
        """
        found = {}
        for relative in cls.MENU_MODULES:
            path = os.path.join(constants.BASE_PATH, relative)
            labels = []
            for node in ast.walk(ast.parse(
                    open(path, encoding='utf-8').read())):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == '_' and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)):
                    continue
                label = node.args[0].value
                if cls._mnemonic(label) is not None and label not in labels:
                    labels.append(label)
            found[relative] = labels
        return found

    @classmethod
    def _all_menus(cls):
        """Every menu in the program, as the msgids of its labels."""
        msgids = cls._label_msgids()
        found = {}
        for layout, title in ((ui._MENUBAR, 'menu bar'),
                              (ui._POPUP, 'right-click')):
            for name, in_menu in cls._menus(layout, msgids, title):
                # The menu bar and the right-click menu share submenus.
                found.setdefault(name, [])
                for msgid in in_menu:
                    if msgid not in found[name]:
                        found[name].append(msgid)
        found.update(cls._module_menus())
        return found

    @staticmethod
    def _mnemonic(label):
        """The letter <label> answers to, or None if it names none.

        A CJK catalogue writes the mnemonic as a trailing "(_A)", which
        needs no special case: it is the character after the underscore
        either way.
        """
        underscore = label.find('_')
        if underscore < 0 or underscore == len(label) - 1:
            return None
        return label[underscore + 1].upper()

    def test_the_menus_are_read_from_the_source(self):
        """The reading above finds menus at all, so that a change to how
        ui.py is written cannot quietly turn the test below into one
        that checks nothing."""
        menus = self._all_menus()
        self.assertIn('menu_edit', menus)
        self.assertIn('_Undo', menus['menu_edit'])
        self.assertGreater(len(menus), 8)
        self.assertTrue(all(menus.values()))
        # And the menus the modules build themselves.
        self.assertIn('_Undo', menus['mcomix/edit_image_area.py'])
        self.assertIn('_Open', menus['mcomix/library/book_area.py'])
        self.assertEqual(sorted(self.MENU_MODULES),
                         sorted(self._module_menus()))

    def test_no_translation_drops_the_mnemonic_its_label_carries(self):
        """A label with an Alt key in English has one in every language.

        The underscore is not part of the wording, so a translator who
        writes the sentence without it leaves that button or menu item
        with no key at all - reachable only with the mouse, in that
        language and nowhere else.  It is invisible from the outside:
        nothing about the program looks wrong, the key simply does
        nothing.  41 labels across 13 languages had lost theirs.
        """
        template = [msgid for msgid in read_msgids(TEMPLATE_PATH)
                    if self._mnemonic(msgid) is not None]
        self.assertTrue(template, 'no labels carry a mnemonic')
        for path in sorted(glob.glob(os.path.join(
                MESSAGES_PATH, '*', 'LC_MESSAGES', 'mcomix.mo'))):
            language = os.path.basename(os.path.dirname(os.path.dirname(path)))
            catalogue = gettext.translation(
                'mcomix', MESSAGES_PATH, languages=[language])
            with self.subTest(language=language):
                for msgid in template:
                    label = catalogue.gettext(msgid)
                    if label == msgid:
                        # Untranslated, so it still carries the English
                        # one; test_every_catalogue_covers_the_template
                        # is what watches for those.
                        continue
                    self.assertIsNotNone(
                        self._mnemonic(label),
                        '%r is translated as %r, which has no mnemonic'
                        % (msgid, label))

    def test_no_menu_has_two_items_on_one_key(self):
        menus = self._all_menus()
        languages = sorted(
            os.path.basename(os.path.dirname(os.path.dirname(path)))
            for path in glob.glob(os.path.join(
                MESSAGES_PATH, '*', 'LC_MESSAGES', 'mcomix.mo')))
        self.assertTrue(languages, 'no catalogues to check')
        for language in languages:
            catalogue = gettext.translation(
                'mcomix', MESSAGES_PATH, languages=[language])
            for menu, msgids in menus.items():
                with self.subTest(language=language, menu=menu):
                    taken = {}
                    for msgid in msgids:
                        label = catalogue.gettext(msgid)
                        key = self._mnemonic(label)
                        if key is None:
                            continue
                        self.assertNotIn(
                            key, taken,
                            '%r and %r both answer to Alt+%s'
                            % (taken.get(key), label, key))
                        taken[key] = label


# vim: expandtab:sw=4:ts=4
