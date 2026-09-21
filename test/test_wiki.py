"""Whether the pages under docs/ describe the program as it is.

The manual is the only documentation a reader has, and nothing checked it
against the code: Keybindings.md turned out to name the German key "Pos1"
for Home and to describe a keybinding editor that had not existed for two
GTK versions, and Preferences.md documented an option that had been
removed while missing six that had been added.  These tests read both
sides, so an option or a tab added to the program has to be written down.
"""

import ast
import glob as glob_module
import os
import re
import tomllib
import unittest

from mcomix import comicinfo
from mcomix import edit_comment_area
from mcomix import edit_dialog
from mcomix import edit_image_area
from mcomix import enhance_dialog
from mcomix import preferences
from mcomix import preferences_dialog
from mcomix import ui

#: The checkout, and the documentation inside it.
ROOT = os.path.dirname(os.path.dirname(
    os.path.abspath(preferences_dialog.__file__)))
DOCS = os.path.join(ROOT, 'docs')

#: The images the pages show, kept beside them.
IMAGES = os.path.join(DOCS, 'images')

#: How a page shows one of them: GitHub Markdown, relative to the page.
IMAGE_LINK = re.compile(r'!\[[^]]*\]\(images/([^)]+)\)')


def read_page(name):
    with open(os.path.join(DOCS, name), encoding='utf-8') as fp:
        return fp.read()


def parse_module(module):
    with open(module.__file__) as fp:
        return ast.parse(fp.read())


def translated(node):
    """The string inside a _('...') call, or None for anything else."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == '_' and node.args
            and isinstance(node.args[0], ast.Constant)):
        return node.args[0].value
    return None


class PreferencesPageTest(unittest.TestCase):

    """Preferences.md against the dialog it documents."""

    PAGE = 'Preferences.md'

    def setUp(self):
        self.page = read_page(self.PAGE)
        self.tree = parse_module(preferences_dialog)

    def _tab_builders(self):
        """Every _init_*_tab function in the dialog."""
        return [node for node in ast.walk(self.tree)
                if isinstance(node, ast.FunctionDef)
                and node.name.startswith('_init_')
                and node.name.endswith('_tab')]

    def _option_labels(self):
        """The text of every option the dialog shows in a tab.

        A check button's label is its first argument and a row's label is
        the Gtk.Label beside it; the third argument of a check button is
        its tooltip, which the page is not asked to quote.
        """
        labels = set()
        for builder in self._tab_builders():
            for node in ast.walk(builder):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, 'id', None))
                if name == '_create_pref_check_button' and node.args:
                    text = translated(node.args[0])
                    if text is not None:
                        labels.add(text)
                elif name == 'Label':
                    for keyword in node.keywords:
                        if keyword.arg == 'label':
                            text = translated(keyword.value)
                            if text is not None:
                                labels.add(text)
        return labels

    def _tab_titles(self):
        """The title of every tab, in the order the dialog builds them."""
        titles = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Tuple) or len(node.elts) != 2:
                continue
            title = translated(node.elts[0])
            if (title is not None and isinstance(node.elts[1], ast.Attribute)
                    and node.elts[1].attr.startswith('_init_')):
                titles.append(title)
        return titles

    def test_the_page_names_every_option_the_dialog_shows(self):
        """A trailing colon is the dialog's, not the page's, so it is not
        required of the page."""
        missing = sorted(label for label in self._option_labels()
                         if label.rstrip(':') not in self.page)
        self.assertEqual([], missing)

    def test_the_page_names_every_tab(self):
        missing = [title for title in self._tab_titles()
                   if title not in self.page]
        self.assertEqual([], missing)
        # The keybinding editor is added on its own, after the four built
        # from the list above.
        self.assertIn('Shortcuts', self.page)

    def test_the_dialog_really_has_the_tabs_the_test_looked_for(self):
        """So that renaming _init_*_tab silently empties the comparison
        rather than being checked against nothing."""
        self.assertEqual(4, len(self._tab_titles()))
        self.assertEqual(5, len(self._tab_builders()))

    #: A string this short could be a word the page uses for something
    #: else, so only the longer obsolete messages are looked for.
    SHORTEST_OBSOLETE = 20

    def _dropped_messages(self):
        """Every message the translation catalogues mark as obsolete.

        msgmerge comments a msgid out with "#~" when it is no longer in
        the source, so each one is a label that used to be in the program
        and is not any more.  The template carries none of them - it is
        regenerated from scratch - so the catalogues are what holds this.
        """
        obsolete = set()
        messages = os.path.join(ROOT, 'mcomix', 'messages')
        for language in os.listdir(messages):
            catalogue = os.path.join(messages, language, 'LC_MESSAGES',
                                     'mcomix.po')
            if not os.path.isfile(catalogue):
                continue
            with open(catalogue, encoding='utf-8') as fp:
                for line in fp:
                    line = line.rstrip('\n')
                    if line.startswith('#~ msgid "') and line.endswith('"'):
                        obsolete.add(line[len('#~ msgid "'):-1])
        return obsolete

    def test_the_catalogues_do_hold_some_dropped_messages(self):
        """So that a comparison against an empty set cannot pass for a
        comparison that found nothing wrong."""
        self.assertTrue(self._dropped_messages())

    def test_the_page_documents_no_option_the_dialog_has_dropped(self):
        """"Use archive thumbnail as application icon" stayed on the page
        for as long as it took the option to be removed, and longer.

        A label that gained or lost its trailing colon leaves the old
        spelling behind as an obsolete message while the option is still
        there, so anything that matches a label the dialog shows now is a
        re-spelling rather than a removal.
        """
        current = {label.rstrip(':') for label in self._option_labels()}
        quoted = sorted(text for text in self._dropped_messages()
                        if len(text) >= self.SHORTEST_OBSOLETE
                        and text.rstrip(':') not in current
                        and text in self.page)
        self.assertEqual([], quoted)


class DocumentationPageTest(unittest.TestCase):

    """Documentation.md against the defaults and menus it quotes.

    The page said "Fit to size" resizes to 1200px in height, which was the
    shape of that setting before it became four spinners with quite
    different defaults.  A number or a menu label quoted in prose goes
    stale silently, so the ones the page names are checked against the
    program.
    """

    PAGE = 'Documentation.md'

    #: Each default the page quotes, against the preference holding it.
    QUOTED_DEFAULTS = (
        'fit to size width wide',
        'fit to size height wide',
        'fit to size width other',
        'fit to size height other',
        'number of pixels to scroll per slideshow event',
    )

    #: The menu items the page tells the reader to use, all of which
    #: ui.py builds: the View menu's, the ones that edit a book, and the
    #: Tools menu's.
    QUOTED_MENU_ITEMS = ('Toolbar', 'Menubar', 'Statusbar', 'Scrollbars',
                         'Hide all', 'Stretch small images',
                         'Edit archive', 'Delete page', 'Undo',
                         'Enhance image', 'Transform image',
                         'Keep transformation', 'Auto-rotate image')

    #: The labels of the dialogs the page describes, which live in the
    #: dialogs rather than in the menus, against the module each is built
    #: in.  A label short enough to be part of another word, such as "OK",
    #: could not be looked for on the page, so it is not listed.
    QUOTED_DIALOG_LABELS = {
        edit_dialog: ('Apply', 'Save As', 'Cancel', 'Import',
                      'Images', 'Comment files'),
        edit_image_area: ('Remove from archive',),
        edit_comment_area: ('Remove from archive',),
        enhance_dialog: ('Automatically adjust contrast',
                         'Invert image colors', 'Revert'),
    }

    #: The preferences the page names, as the dialog labels them.
    QUOTED_PREFERENCES = (
        'Save an edited archive in the format it was opened in',
        'Automatically rotate images according to their metadata',
    )

    def setUp(self):
        self.page = read_page(self.PAGE)

    def test_the_page_quotes_the_current_defaults(self):
        wrong = [name for name in self.QUOTED_DEFAULTS
                 if str(preferences.prefs[name]) not in self.page]
        self.assertEqual([], wrong)

    def test_the_page_quotes_the_slideshow_delay_in_seconds(self):
        """The preference is in milliseconds and the page is in seconds,
        so this one cannot be compared as it stands."""
        self.assertEqual(3000, preferences.prefs['slideshow delay'])
        self.assertIn('three seconds', self.page)

    def test_the_view_menu_has_the_items_the_page_names(self):
        """ui.py holds each label with its mnemonic underscore, which the
        page does not write."""
        with open(ui.__file__) as fp:
            source = fp.read()
        missing = [item for item in self.QUOTED_MENU_ITEMS
                   if item not in source.replace('_', '')]
        self.assertEqual([], missing)

    def test_the_page_names_those_items(self):
        """So that the check above cannot pass against a page that has
        stopped mentioning them."""
        missing = [item for item in self.QUOTED_MENU_ITEMS
                   if item.lower() not in self.page.lower()]
        self.assertEqual([], missing)

    def test_the_bars_are_under_the_submenu_the_page_names(self):
        """The page sends the reader to "View -> Toolbars" for the bars
        and for "Hide all".  A revision of the page, and of this class'
        docstring, once said there is no such submenu, which the label
        checks above could not catch: "Toolbar" is in ui.py either way."""
        view = dict(item for item in ui._MENUBAR
                    if isinstance(item, tuple))['menu_view']
        toolbars = dict(item for item in view
                        if isinstance(item, tuple))['menu_toolbars']
        self.assertEqual({'menubar', 'toolbar', 'statusbar', 'scrollbar',
                          'thumbnails', 'hide_all'}, set(toolbars) - {None})
        labels = {node.args[0].value: translated(node.args[2])
                  for node in ast.walk(parse_module(ui))
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Name)
                  and node.func.id == '_Entry' and len(node.args) > 2
                  and isinstance(node.args[0], ast.Constant)}
        path = '"%s &rarr; %s"' % (labels['menu_view'].replace('_', ''),
                                   labels['menu_toolbars'].replace('_', ''))
        self.assertIn(path, self.page)

    def test_the_dialogs_have_the_labels_the_page_names(self):
        """The sections on the archive editor and on enhancing the image
        quote buttons and menu items by name; a renamed button would leave
        the only instructions a reader has pointing at nothing.

        Only a translated string that is the whole label counts, without
        its mnemonic underscore and a trailing colon or ellipsis: the
        source as a whole would also match a tooltip that repeats the
        words, as the one for "Automatically adjust contrast" does."""
        for module, labels in self.QUOTED_DIALOG_LABELS.items():
            strings = {text.replace('_', '').rstrip(':.')
                       for text in map(translated,
                                       ast.walk(parse_module(module)))
                       if text is not None}
            for label in labels:
                with self.subTest(module=module.__name__, label=label):
                    self.assertIn(label, strings)

    def test_the_page_names_those_labels(self):
        missing = [label
                   for labels in self.QUOTED_DIALOG_LABELS.values()
                   for label in labels
                   if label.lower() not in self.page.lower()]
        self.assertEqual([], missing)

    def test_the_page_names_the_metadata_file_and_its_two_fields(self):
        """MComix writes PageCount and Pages into every archive it
        saves, and nothing else about the comic."""
        self.assertIn(comicinfo.NAME, self.page)
        with open(comicinfo.__file__) as fp:
            source = fp.read()
        for field in ('PageCount', 'Pages'):
            with self.subTest(field=field):
                self.assertIn("'%s'" % field, source)
                self.assertIn(field, self.page)

    def test_the_page_quotes_the_preferences_as_the_dialog_labels_them(self):
        """Which format a save is written in, and whether a page is
        turned the way its metadata says, are preferences' to decide, so
        the page has to name them as the dialog does."""
        with open(preferences_dialog.__file__) as fp:
            source = fp.read()
        for label in self.QUOTED_PREFERENCES:
            with self.subTest(label=label):
                self.assertIn(label, source)
                self.assertIn(label, self.page)


class DependenciesTest(unittest.TestCase):

    """The dependency list on Installation.md against pyproject.toml.

    The list, then on Home.md, asked for Python 3.7, PyGObject 3.36,
    PyCairo 1.16 and Pillow 6.0 while the project required 3.12, 3.46,
    1.25 and 10.1 - every one of them raised without the page being
    touched, and each one understated tells a reader their system will do
    when it will not.
    """

    PAGE = 'Installation.md'

    #: Each distribution named in pyproject.toml against the name the page
    #: writes it under, where the two differ.
    SPELLINGS: dict[str, str] = {}

    def setUp(self):
        self.page = read_page(self.PAGE)
        with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as fp:
            self.project = tomllib.load(fp)

    def _floors(self):
        """{distribution: minimum version} over the required and the
        optional dependencies alike, for the ones that state a floor."""
        requirements = list(self.project['project']['dependencies'])
        for extra in self.project['project'].get(
                'optional-dependencies', {}).values():
            requirements.extend(extra)
        floors = {}
        for requirement in requirements:
            name, _, floor = requirement.partition('>=')
            if floor:
                floors[name.strip()] = floor.strip()
        return floors

    def test_the_page_asks_for_the_python_the_project_requires(self):
        required = self.project['project']['requires-python']
        self.assertEqual('>=3.12', required,
                         'the floor moved; the page needs the new one')
        self.assertIn('Python 3.12', self.page)

    def test_the_page_asks_for_the_versions_the_project_requires(self):
        """The floor has to appear somewhere on the page, which is enough:
        raising one leaves the old number behind and fails this, and the
        page names each distribution once.  Only the distributions the page
        mentions are checked - one it does not is not its business."""
        wrong = {}
        for name, floor in self._floors().items():
            spelling = self.SPELLINGS.get(name, name)
            if spelling in self.page and floor not in self.page:
                wrong[spelling] = floor
        self.assertEqual({}, wrong)

    def test_the_page_names_the_dependencies_this_test_looks_for(self):
        """So that dropping one from the page quietly drops it out of the
        comparison rather than being checked against nothing."""
        self.assertEqual(['PyGObject', 'pycairo', 'Pillow', 'PyMuPDF'],
                         list(self._floors()),
                         'the dependency list changed; check the page too')
        missing = [self.SPELLINGS.get(name, name) for name in self._floors()
                   if self.SPELLINGS.get(name, name) not in self.page]
        self.assertEqual([], missing)


class MaintenancePageTest(unittest.TestCase):

    """Maintenance.md against the files and paths its recipes name.

    Every command on this page is run by hand at release time, months
    apart, so a path that has moved is found by a maintainer in the middle
    of a release rather than by anyone reading.  The page also carried an
    MSYS2 package - python-ujson, "needed to process pyproject.toml
    projects" - that nothing in the tree has required since setuptools
    started reading TOML with the standard library's tomllib.
    """

    PAGE = 'Maintenance.md'


    #: Every path the page names as a file in the repository.
    NAMED_PATHS = (
        'ChangeLog.md',
        'mcomix/constants.py',
        'mcomix/messages/mcomix.pot',
        'win32/build_pyinstaller.py',
        'win32/build_msi.py',
        'win32/mcomix.nuspec',
    )

    def setUp(self):
        self.page = read_page(self.PAGE)
        self.root = ROOT

    def test_every_file_the_page_names_is_there(self):
        missing = [path for path in self.NAMED_PATHS
                   if not os.path.isfile(os.path.join(self.root, path))]
        self.assertEqual([], missing)

    def test_the_page_names_those_files(self):
        """So that a path dropped from the page leaves the check above
        asserting something that is no longer documented."""
        missing = [path for path in self.NAMED_PATHS
                   if path not in self.page]
        self.assertEqual([], missing)

    def test_the_version_is_where_the_snippet_greps_for_it(self):
        """The translation snippet reads the version with a grep of
        mcomix/constants.py, so the assignment has to stay there and stay
        greppable."""
        with open(os.path.join(self.root, 'mcomix', 'constants.py')) as fp:
            source = fp.read()
        self.assertRegex(source, r"(?m)^VERSION = '[^']+'$")
        self.assertIn('grep VERSION mcomix/constants.py', self.page)

    def test_the_checksum_goes_where_the_page_says(self):
        with open(os.path.join(self.root, 'win32', 'build_msi.py')) as fp:
            builder = fp.read()
        self.assertIn('win32/tools/checksum.sha256', builder)
        self.assertIn('win32/tools/checksum.sha256', self.page)
        # The page says it is deliberately not kept in Git.
        with open(os.path.join(self.root, '.gitignore')) as fp:
            self.assertIn('win32/tools/checksum.sha256', fp.read())

    def test_the_xgettext_globs_reach_every_translatable_module(self):
        """The snippet passes three globs to xgettext.  A module outside
        them that calls _() would have its strings left out of the
        template, and nothing would say so until a translator noticed."""
        globs = ('mcomix/*.py', 'mcomix/archive/*.py', 'mcomix/library/*.py')
        for glob in globs:
            self.assertIn(glob, self.page)
        covered = set()
        for glob in globs:
            covered.update(os.path.normpath(path)
                           for path in glob_module.glob(
                               os.path.join(self.root, glob)))
        missed = []
        for directory, _subdirectories, names in os.walk(
                os.path.join(self.root, 'mcomix')):
            for name in names:
                if not name.endswith('.py'):
                    continue
                path = os.path.normpath(os.path.join(directory, name))
                if path in covered:
                    continue
                with open(path) as fp:
                    source = fp.read()
                if 'from mcomix.i18n import _' in source:
                    missed.append(os.path.relpath(path, self.root))
        self.assertEqual([], sorted(missed))

    def test_the_msys2_packages_are_the_ones_the_build_script_names(self):
        """The list a maintainer installs from is on this page, and the
        list the build script documents is in win32/build_pyinstaller.py.
        They had drifted apart: the page asked for python3-pillow,
        python3 and python3-gobject, which MSYS2 renamed years ago, and
        for mingw-w64-x86_64-mypy, which nothing in the build runs.
        """
        script = os.path.join(self.root, 'win32', 'build_pyinstaller.py')
        with open(script) as fp:
            source = fp.read()
        pattern = r'mingw-w64-x86_64-[\w-]+'
        self.assertEqual(sorted(set(re.findall(pattern, source))),
                         sorted(set(re.findall(pattern, self.page))))

    def test_the_msys2_list_is_not_empty(self):
        """So that a rewritten build script cannot turn the comparison
        above into one between two empty sets."""
        self.assertGreater(
            len(set(re.findall(r'mingw-w64-x86_64-[\w-]+', self.page))), 5)

    def test_the_page_no_longer_asks_for_ujson(self):
        """setuptools>=77 is the build backend and reads pyproject.toml
        with tomllib, which Python has had since 3.11 - two versions below
        this project's floor."""
        self.assertNotIn('ujson', self.page)


class InstallationPageTest(unittest.TestCase):

    """Installation.md against the extras and paths it tells a reader to
    use."""

    PAGE = 'Installation.md'

    def setUp(self):
        self.page = read_page(self.PAGE)
        with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as fp:
            self.project = tomllib.load(fp)

    def test_the_extras_the_page_names_exist(self):
        """The page tells the reader to install .[fileformats] and
        .[dev]."""
        extras = self.project['project']['optional-dependencies']
        for extra in ('fileformats', 'dev'):
            self.assertIn(extra, extras)
            self.assertIn('.[%s]' % extra, self.page)

    def test_the_page_names_every_extra_there_is(self):
        """An extra nobody is told about is one nobody installs."""
        missing = [extra for extra
                   in self.project['project']['optional-dependencies']
                   if '.[%s]' % extra not in self.page]
        self.assertEqual([], missing)

    def test_the_page_no_longer_asks_for_ujson(self):
        self.assertNotIn('ujson', self.page)


def read_pages():
    """{page name: text} for every page of the documentation."""
    return {name[:-len('.md')]: read_page(name)
            for name in sorted(os.listdir(DOCS)) if name.endswith('.md')}


def images_shown():
    """The file name of every image the pages show."""
    return {name for page in read_pages().values()
            for name in IMAGE_LINK.findall(page)}


class ImagesTest(unittest.TestCase):

    """docs/images against the images the pages show."""

    def setUp(self):
        self.shown = images_shown()
        self.kept = {name for name in os.listdir(IMAGES)
                     if name != 'README.md'}

    def test_every_image_a_page_shows_is_kept(self):
        self.assertEqual(set(), self.shown - self.kept)

    def test_every_image_kept_is_shown_by_a_page(self):
        self.assertEqual(set(), self.kept - self.shown)

    def test_the_readme_credits_the_comic_they_show(self):
        """The screenshots show pages of a CC BY 4.0 comic, whose licence
        asks for the author, the licence and the change to be named."""
        with open(os.path.join(IMAGES, 'README.md'), encoding='utf-8') as fp:
            readme = fp.read()
        for required in ('Pepper&Carrot', 'David Revoy', 'scaled',
                         'https://creativecommons.org/licenses/by/4.0/'):
            with self.subTest(required=required):
                self.assertIn(required, readme)


# vim: expandtab:sw=4:ts=4
