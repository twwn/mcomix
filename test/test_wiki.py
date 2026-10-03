"""Whether the pages under docs/ describe the program as it is.

The manual is the only documentation a reader has, and nothing checked it
against the code: the page of keys turned out to name the German key "Pos1"
for Home and to describe a keybinding editor that had not existed for two
GTK versions, and the preferences page documented an option that had been
removed while missing six that had been added.  These tests read both
sides, so an option or a tab added to the program has to be written down.
"""

import ast
import glob as glob_module
import gzip
import os
import re
import tomllib
import unittest

from mcomix import comicinfo
from mcomix import constants
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
    with open(module.__file__, encoding='utf-8') as fp:
        return ast.parse(fp.read())


def translated(node):
    """The string inside a _('...') call, or None for anything else."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == '_' and node.args
            and isinstance(node.args[0], ast.Constant)):
        return node.args[0].value
    return None


class PreferencesPageTest(unittest.TestCase):

    """preferences.md against the dialog it documents."""

    PAGE = 'preferences.md'

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
        self.assertEqual(5, len(self._tab_titles()))
        self.assertEqual(6, len(self._tab_builders()))

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


class ManualTest(unittest.TestCase):

    """The manual against the defaults and menus it quotes.

    The manual said "Fit to size" resizes to 1200px in height, which was
    the shape of that setting before it became four spinners with quite
    different defaults.  A number or a menu label quoted in prose goes
    stale silently, so the ones the manual names are checked against the
    program.  The manual is three pages, read here as one: which page a
    label is on is the pages' business, that it is on one is this test's.
    """

    PAGES = ('reading.md', 'editing.md', 'library.md')

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
        self.page = '\n'.join(map(read_page, self.PAGES))

    def test_the_page_quotes_the_current_defaults(self):
        wrong = [name for name in self.QUOTED_DEFAULTS
                 if str(preferences._DEFAULTS[name]) not in self.page]
        self.assertEqual([], wrong)

    def test_the_page_quotes_the_slideshow_delay_in_seconds(self):
        """The preference is in milliseconds and the page is in seconds,
        so this one cannot be compared as it stands."""
        self.assertEqual(3000, preferences._DEFAULTS['slideshow delay'])
        self.assertIn('three seconds', self.page)

    def test_the_view_menu_has_the_items_the_page_names(self):
        """ui.py holds each label with its mnemonic underscore, which the
        page does not write."""
        with open(ui.__file__, encoding='utf-8') as fp:
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
        path = '"%s → %s"' % (labels['menu_view'].replace('_', ''),
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
        with open(comicinfo.__file__, encoding='utf-8') as fp:
            source = fp.read()
        for field in ('PageCount', 'Pages'):
            with self.subTest(field=field):
                self.assertIn("'%s'" % field, source)
                self.assertIn(field, self.page)

    def test_the_page_quotes_the_preferences_as_the_dialog_labels_them(self):
        """Which format a save is written in, and whether a page is
        turned the way its metadata says, are preferences' to decide, so
        the page has to name them as the dialog does."""
        with open(preferences_dialog.__file__, encoding='utf-8') as fp:
            source = fp.read()
        for label in self.QUOTED_PREFERENCES:
            with self.subTest(label=label):
                self.assertIn(label, source)
                self.assertIn(label, self.page)


class DependenciesTest(unittest.TestCase):

    """The dependency list on install.md against pyproject.toml.

    The list, then on Home.md, asked for Python 3.7, PyGObject 3.36,
    PyCairo 1.16 and Pillow 6.0 while the project required 3.12, 3.46,
    1.25 and 10.1 - every one of them raised without the page being
    touched, and each one understated tells a reader their system will do
    when it will not.
    """

    PAGE = 'install.md'

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


class NamedPathsMixin:

    """The files a page of recipes names, which have to be there.

    Every command on these pages is run by hand, some of them at release
    time, months apart, so a path that has moved is found by a maintainer
    in the middle of a release rather than by anyone reading.
    """

    #: The page, and every path it names as a file in the repository.
    PAGE = ''
    NAMED_PATHS: tuple[str, ...] = ()

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


class DevelopmentPageTest(NamedPathsMixin, unittest.TestCase):

    """development.md against the files and paths its recipes name."""

    PAGE = 'development.md'

    NAMED_PATHS = (
        'mcomix/constants.py',
        'mcomix/messages/mcomix.pot',
        'mcomix/preferences_dialog.py',
        'test/test_messages.py',
        'test/test_wiki.py',
    )

    def test_the_version_is_where_the_snippet_greps_for_it(self):
        """The translation snippet reads the version with a grep of
        mcomix/constants.py, so the assignment has to stay there and stay
        greppable."""
        with open(os.path.join(self.root, 'mcomix', 'constants.py'),
                  encoding='utf-8') as fp:
            source = fp.read()
        self.assertRegex(source, r"(?m)^VERSION = '[^']+'$")
        self.assertIn('grep VERSION mcomix/constants.py', self.page)

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
                with open(path, encoding='utf-8') as fp:
                    source = fp.read()
                if 'from mcomix.i18n import _' in source:
                    missed.append(os.path.relpath(path, self.root))
        self.assertEqual([], sorted(missed))


class ReleasingPageTest(NamedPathsMixin, unittest.TestCase):

    """releasing.md against the files and paths its recipes name.

    The page, then Maintenance.md, also carried an MSYS2 package -
    python-ujson, "needed to process pyproject.toml projects" - that
    nothing in the tree has required since setuptools started reading
    TOML with the standard library's tomllib.
    """

    PAGE = 'releasing.md'

    NAMED_PATHS = (
        'ChangeLog.md',
        'mcomix/constants.py',
        'share/man/man1/mcomix.1.gz',
        'share/metainfo/mcomix.metainfo.xml',
        'win32/build_pyinstaller.py',
        'win32/build_msi.py',
        'win32/mcomix.nuspec',
        '.github/workflows/release.yml',
        '.github/workflows/publish.yml',
    )

    def test_the_checksum_goes_where_the_page_says(self):
        with open(os.path.join(self.root, 'win32', 'build_msi.py'),
                  encoding='utf-8') as fp:
            builder = fp.read()
        self.assertIn('win32/tools/checksum.sha256', builder)
        self.assertIn('win32/tools/checksum.sha256', self.page)
        # The page says it is deliberately not kept in Git.
        with open(os.path.join(self.root, '.gitignore'),
                  encoding='utf-8') as fp:
            self.assertIn('win32/tools/checksum.sha256', fp.read())

    def test_the_msys2_packages_are_the_ones_the_build_script_names(self):
        """The list a maintainer installs from is on this page, and the
        list the build script documents is in win32/build_pyinstaller.py.
        They had drifted apart: the page asked for python3-pillow,
        python3 and python3-gobject, which MSYS2 renamed years ago, and
        for mingw-w64-x86_64-mypy, which nothing in the build runs.  The
        release workflow installs its own copy, and the Windows build
        failed on GitHub when MSYS2 stopped building one of them for the
        environment all three named.
        """
        pattern = r'mingw-w64-ucrt-x86_64-[\w-]+'
        page = sorted(set(re.findall(pattern, self.page)))
        for name in (os.path.join('win32', 'build_pyinstaller.py'),
                     os.path.join('.github', 'workflows', 'release.yml')):
            with self.subTest(name=name), \
                    open(os.path.join(self.root, name),
                         encoding='utf-8') as fp:
                self.assertEqual(page,
                                 sorted(set(re.findall(pattern, fp.read()))))

    def test_the_build_is_for_the_environment_the_packages_are_for(self):
        with open(os.path.join(self.root, '.github', 'workflows',
                               'release.yml'), encoding='utf-8') as fp:
            self.assertIn('msystem: UCRT64', fp.read())
        self.assertIn('UCRT64 shell', self.page)
        self.assertNotRegex(self.page, r'mingw-w64-x86_64-')

    def test_the_msys2_list_is_not_empty(self):
        """So that a rewritten build script cannot turn the comparison
        above into one between two empty sets."""
        self.assertGreater(
            len(set(re.findall(r'mingw-w64-ucrt-x86_64-[\w-]+', self.page))), 5)

    def test_the_page_no_longer_asks_for_ujson(self):
        """setuptools>=77 is the build backend and reads pyproject.toml
        with tomllib, which Python has had since 3.11 - two versions below
        this project's floor."""
        self.assertNotIn('ujson', self.page)


class ExtrasTest(unittest.TestCase):

    """The extras install.md and development.md tell a reader to install,
    against pyproject.toml."""

    PAGES = ('install.md', 'development.md')

    #: An extra as the pages write it: in brackets after "." or a source
    #: archive, several of them separated by commas.
    EXTRAS = re.compile(r'(?:\.|\.tar\.gz)\[([\w,-]+)\]')

    def setUp(self):
        self.named = set()
        for page in map(read_page, self.PAGES):
            for extras in self.EXTRAS.findall(page):
                self.named.update(extras.split(','))
        with open(os.path.join(ROOT, 'pyproject.toml'), 'rb') as fp:
            self.extras = set(
                tomllib.load(fp)['project']['optional-dependencies'])

    def test_the_extras_the_pages_name_exist(self):
        self.assertEqual(set(), self.named - self.extras)

    def test_the_pages_name_every_extra_there_is(self):
        """An extra nobody is told about is one nobody installs."""
        self.assertEqual(set(), self.extras - self.named)

    def test_the_pages_no_longer_ask_for_ujson(self):
        for name in self.PAGES:
            with self.subTest(name=name):
                self.assertNotIn('ujson', read_page(name))


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


#: The Markdown files a reader follows links through, relative to ROOT.
MARKDOWN = ('README.md', 'CONTRIBUTING.md', 'SECURITY.md', 'ChangeLog.md',
            os.path.join('.github', 'PULL_REQUEST_TEMPLATE.md'),
            os.path.join('docs', '*.md'), os.path.join('docs', '*', '*.md'))

#: The files that link to the repository on GitHub from outside it: the
#: program, its packages and metadata, and the workflows.
LINKING = MARKDOWN + (
    os.path.join('mcomix', '**', '*.py'), 'pyproject.toml',
    os.path.join('win32', '*.nuspec'), os.path.join('share', '**', '*.xml'),
    os.path.join('share', 'man', 'man1', '*.gz'),
    os.path.join('.github', '**', '*.yml'))

#: The manual page, as the source archive carries it.
MAN_PAGE = os.path.join(ROOT, 'share', 'man', 'man1', 'mcomix.1.gz')

#: An inline link or image in Markdown: its target, without the title
#: that may follow it.
LINK = re.compile(r'\]\(([^)\s]+)(?:\s+"[^"]*")?\)')

#: A link to a file of this repository as GitHub shows it, and as it
#: serves it raw.
GITHUB_LINK = re.compile(
    r'https://github\.com/twwn/mcomix/blob/main/([^\s)"\'<>#]+)(?:#([\w-]+))?'
    r'|https://raw\.githubusercontent\.com/twwn/mcomix/main/([^\s)"\'<>#]+)')

#: A link to a page of the manual as GitHub Pages serves it
#: (.github/workflows/pages.yml): the file's path with .html for .md,
#: and a directory for its README.md.  A path ends in a letter, a digit
#: or a slash, so that the full stop of a sentence is not part of it.
PAGES_LINK = re.compile(
    r'https://twwn\.github\.io/mcomix/([\w./-]*[\w/])?(?:#([\w-]+))?')


def expand(patterns):
    """The files under ROOT the glob <patterns> match."""
    return sorted({path for pattern in patterns
                   for path in glob_module.glob(os.path.join(ROOT, pattern),
                                                recursive=True)})


def read_text(path):
    """The text of <path>, unpacked if it is gzipped."""
    if path.endswith('.gz'):
        with gzip.open(path, 'rt', encoding='utf-8') as fp:
            return fp.read()
    with open(path, encoding='utf-8') as fp:
        return fp.read()


def anchors(path):
    """The anchors GitHub gives the headings of the Markdown file <path>.

    It lowercases a heading, drops everything but letters, digits,
    underscores, hyphens and spaces, and turns the spaces into hyphens; a
    heading that comes out as an earlier one did gets -1, -2 and so on.
    Lines inside a fenced code block are not headings, whatever they
    start with."""
    with open(path, encoding='utf-8') as fp:
        lines = fp.read().splitlines()
    found = set()
    fenced = False
    for line in lines:
        if line.startswith('```'):
            fenced = not fenced
            continue
        heading = re.match(r'#{1,6} (.*?)#*$', line)
        if fenced or not heading:
            continue
        anchor = re.sub(r'[^\w\- ]', '', heading.group(1).strip().lower())
        anchor = anchor.replace(' ', '-')
        taken, number = anchor, 0
        while taken in found:
            number += 1
            taken = '%s-%d' % (anchor, number)
        found.add(taken)
    return found


class LinksTest(unittest.TestCase):

    """Every link between the pages, and into the repository, against
    the files and headings it names.

    The documentation moved to other file names, which GitHub does not
    redirect: a page, the README, the external commands dialog and the
    build script still named the old ones, and nothing would have said
    so until a reader followed one.
    """

    def _broken(self, path, target, fragment):
        """Why <target>#<fragment>, linked from <path>, leads nowhere, or
        None if it leads somewhere."""
        if not os.path.exists(target):
            return 'no such file'
        if fragment and target.endswith('.md') \
                and fragment not in anchors(target):
            return 'no such heading'
        return None

    def test_every_relative_link_leads_somewhere(self):
        broken = []
        followed = 0
        for path in expand(MARKDOWN):
            with open(path, encoding='utf-8') as fp:
                text = fp.read()
            for link in LINK.findall(text):
                if re.match(r'[a-z]+:', link):
                    continue
                name, _, fragment = link.partition('#')
                target = (os.path.normpath(os.path.join(
                    os.path.dirname(path), name)) if name else path)
                followed += 1
                why = self._broken(path, target, fragment)
                if why:
                    broken.append('%s: %s (%s)' % (
                        os.path.relpath(path, ROOT), link, why))
        self.assertEqual([], broken)
        self.assertGreater(followed, 50, 'the links were not found')

    def test_every_link_to_the_repository_leads_somewhere(self):
        """The program, its packages and its metadata link to files on
        the main branch; those links outlive the release they came in."""
        broken = []
        followed = 0
        for path in expand(LINKING):
            for match in GITHUB_LINK.finditer(read_text(path)):
                name, fragment, raw = match.groups()
                target = os.path.join(ROOT, name or raw)
                followed += 1
                why = self._broken(path, target, fragment)
                if why:
                    broken.append('%s: %s (%s)' % (
                        os.path.relpath(path, ROOT), match.group(0), why))
        self.assertEqual([], broken)
        self.assertGreater(followed, 5, 'the links were not found')

    def test_every_link_to_the_site_leads_somewhere(self):
        """The metadata, the packages and the external commands dialog
        link to the manual on GitHub Pages, which is built from the
        pages here under the same paths."""
        broken = []
        followed = 0
        for path in expand(LINKING):
            for match in PAGES_LINK.finditer(read_text(path)):
                name, fragment = match.groups()
                name = name or ''
                if name == '' or name.endswith('/'):
                    name += 'README.md'
                elif name.endswith('.html'):
                    name = name[:-len('.html')] + '.md'
                followed += 1
                why = self._broken(path, os.path.join(ROOT, name), fragment)
                if why:
                    broken.append('%s: %s (%s)' % (
                        os.path.relpath(path, ROOT), match.group(0), why))
        self.assertEqual([], broken)
        self.assertGreater(followed, 3, 'the links were not found')

    def test_the_anchors_are_made_as_github_makes_them(self):
        """So that the test above compares links with the anchors GitHub
        gives, rather than with its own idea of them."""
        path = os.path.join(DOCS, 'reading.md')
        found = anchors(path)
        for anchor in ('the-window', 'double-page-and-manga-mode',
                       'fit-modes'):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, found)
        self.assertIn('comicinfoxml',
                      anchors(os.path.join(DOCS, 'editing.md')))



class ManPageTest(unittest.TestCase):

    """The manual page against the program it describes.

    It went on naming MComix 4.0.0 after the version became 26.09, and
    sent its readers to MComix 3's manual and bug tracker on SourceForge.
    """

    def setUp(self):
        self.page = read_text(MAN_PAGE)

    def test_the_page_names_the_version(self):
        title = re.search(r'(?m)^\.TH .*$', self.page)
        self.assertIsNotNone(title)
        self.assertIn('"MComix %s"' % constants.VERSION, title.group(0))

    def test_the_page_sends_its_readers_here(self):
        urls = re.findall(r'(?m)^\.UR (\S+)', self.page)
        self.assertTrue(urls, 'the page links nowhere')
        self.assertEqual([], [url for url in urls if not url.startswith(
            'https://github.com/twwn/mcomix/')])


# vim: expandtab:sw=4:ts=4
