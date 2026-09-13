"""sfwikisync, the tool under wiki/src that copies the wiki's pages to and
from SourceForge.

pull overwrites local files without asking and push publishes whatever
differs, and neither had a test.  Nothing here reaches the network: the
tool is imported against a stand-in for requests, which MComix does not
depend on, and each test says what the SourceForge API answers.
"""

import contextlib
import importlib
import io
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

#: wiki/src, which holds the sfwikisync package.
SOURCE = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), 'wiki', 'src')


def offline(*args, **kwargs):
    raise AssertionError('sfwikisync reached for the network')


def fake_requests():
    """A stand-in for requests with the names sfwikisync uses, whose get
    and post fail a test that has not said what the API answers."""
    requests = types.ModuleType('requests')
    requests.auth = types.ModuleType('requests.auth')
    requests.auth.AuthBase = type('AuthBase', (), {})
    requests.PreparedRequest = type('PreparedRequest', (), {})
    requests.HTTPError = type('HTTPError', (OSError,), {})
    requests.get = requests.post = offline
    return requests


def load():
    """sfwikisync's modules, imported against the stand-in for requests.

    Both are out of sys.modules again afterwards, so that no other test
    sees either of them.
    """
    requests = fake_requests()
    with mock.patch.dict(sys.modules, {'requests': requests,
                                       'requests.auth': requests.auth}), \
            mock.patch.object(sys, 'path', [SOURCE] + sys.path):
        return types.SimpleNamespace(
            main=importlib.import_module('sfwikisync.__main__'),
            client=importlib.import_module('sfwikisync.wikiclient'),
            page=importlib.import_module('sfwikisync.wikipage'),
            auth=importlib.import_module('sfwikisync.bearerauth'),
            requests=requests)


sfwikisync = load()
WikiPage = sfwikisync.page.WikiPage


class Response:

    """The parts of a requests.Response that sfwikisync reads."""

    def __init__(self, status_code=200, json=None):
        self.status_code = status_code
        self._json = json

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise sfwikisync.requests.HTTPError(self.status_code)


class FakeClient:

    """A WikiClient whose wiki is a dict, noting what it is sent."""

    def __init__(self, *pages):
        self.pages = {page.title: page for page in pages}
        self.uploads = []

    def pagenames(self):
        return list(self.pages)

    def page(self, pagename):
        return self.pages.get(pagename)

    def create_or_update_page(self, page):
        self.uploads.append(page)


class ArgumentsTest(unittest.TestCase):

    def parse(self, *arguments, token=None):
        """parse_arguments() over the arguments, with the token variable
        set to token, or unset."""
        with mock.patch.object(sys, 'argv', ['sfwikisync', *arguments]), \
                mock.patch.dict(os.environ):
            os.environ.pop(sfwikisync.main.TOKEN_VARIABLE, None)
            if token is not None:
                os.environ[sfwikisync.main.TOKEN_VARIABLE] = token
            return sfwikisync.main.parse_arguments()

    def refused(self, *arguments):
        """What parse_arguments() prints as it exits over the arguments."""
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), \
                self.assertRaises(SystemExit) as raised:
            self.parse(*arguments)
        self.assertEqual(2, raised.exception.code)
        return stderr.getvalue()

    def test_the_defaults(self):
        args = self.parse('-p', 'mcomix', 'pull')
        self.assertEqual(('mcomix', 'wiki', 'content', 'github', None, 'pull'),
                         (args.project, args.wikiname, args.contentdir,
                          args.outdir, args.bearertoken, args.operation))

    def test_push_without_a_token_is_refused(self):
        message = self.refused('-p', 'mcomix', 'push')
        self.assertIn(sfwikisync.main.TOKEN_VARIABLE, message)
        self.assertIn('--bearertoken', message)

    def test_push_reads_the_token_from_the_environment(self):
        args = self.parse('-p', 'mcomix', 'push', token='secret')
        self.assertEqual('secret', args.bearertoken)

    def test_a_token_on_the_command_line_comes_first(self):
        args = self.parse('-p', 'mcomix', '-b', 'given', 'push',
                          token='secret')
        self.assertEqual('given', args.bearertoken)

    def test_only_push_needs_a_token(self):
        for operation in ('pull', 'github'):
            with self.subTest(operation=operation):
                self.assertEqual(operation,
                                 self.parse('-p', 'mcomix',
                                            operation).operation)

    def test_the_project_and_a_known_operation_are_required(self):
        self.assertIn('--project', self.refused('pull'))
        self.assertIn('invalid choice', self.refused('-p', 'mcomix', 'sync'))


class ClientTest(unittest.TestCase):

    def setUp(self):
        self.client = sfwikisync.client.WikiClient('mcomix', 'wiki', 'secret')

    def test_the_urls_it_asks(self):
        base = 'https://sourceforge.net/rest/p/mcomix/wiki'
        self.assertEqual(base, self.client._generate_url(''))
        self.assertEqual(base + '/Home', self.client._generate_url('Home'))
        self.assertEqual(base + '/Home', self.client._generate_url('/Home'))

    def test_the_page_names(self):
        answer = Response(json={'pages': ['Home', 'Installation']})
        with mock.patch.object(sfwikisync.requests, 'get',
                               return_value=answer) as get:
            self.assertEqual(['Home', 'Installation'],
                             self.client.pagenames())
        get.assert_called_once_with(
            'https://sourceforge.net/rest/p/mcomix/wiki',
            timeout=sfwikisync.client.TIMEOUT)

    def test_a_page(self):
        answer = Response(json={'title': 'Home', 'text': 'Text\r\n',
                                'labels': [''], 'attachments': []})
        with mock.patch.object(sfwikisync.requests, 'get',
                               return_value=answer) as get:
            self.assertEqual(WikiPage('Home', 'Text\r\n', ['']),
                             self.client.page('Home'))
        get.assert_called_once_with(
            'https://sourceforge.net/rest/p/mcomix/wiki/Home',
            timeout=sfwikisync.client.TIMEOUT)

    def test_a_page_that_does_not_exist(self):
        with mock.patch.object(sfwikisync.requests, 'get',
                               return_value=Response(404)):
            self.assertIsNone(self.client.page('Nothing'))

    def test_a_page_is_posted_with_its_labels_and_the_token(self):
        with mock.patch.object(sfwikisync.requests, 'post',
                               return_value=Response()) as post:
            self.client.create_or_update_page(
                WikiPage('Home', 'Text\r\n', ['one', 'two']))
        (url, data), keywords = post.call_args
        self.assertEqual('https://sourceforge.net/rest/p/mcomix/wiki/Home',
                         url)
        self.assertEqual({'labels': 'one,two', 'text': 'Text\r\n'}, data)
        self.assertEqual('secret', keywords['auth'].bearertoken)
        self.assertEqual(sfwikisync.client.TIMEOUT, keywords['timeout'])

    def test_no_request_waits_without_end(self):
        """requests waits for an answer for as long as the connection
        stays open unless it is given a timeout, so pull and push could
        wait forever on a SourceForge that had stopped answering."""
        answer = Response(json={'pages': [], 'title': 'Home', 'text': '',
                                'labels': []})
        with mock.patch.object(sfwikisync.requests, 'get',
                               return_value=answer) as get, \
                mock.patch.object(sfwikisync.requests, 'post',
                                  return_value=Response()) as post:
            self.client.pagenames()
            self.client.page('Home')
            self.client.create_or_update_page(WikiPage('Home', '', []))
        calls = get.call_args_list + post.call_args_list
        self.assertEqual(3, len(calls))
        for call in calls:
            with self.subTest(url=call.args[0]):
                self.assertGreater(call.kwargs.get('timeout', 0), 0)

    def test_a_refused_token_raises(self):
        with mock.patch.object(sfwikisync.requests, 'post',
                               return_value=Response(401)), \
                self.assertRaises(PermissionError):
            self.client.create_or_update_page(WikiPage('Home', '', []))

    def test_an_upload_that_fails_otherwise_raises(self):
        """Only 401 was checked, so any other error status - a mistyped
        project, a failure on SourceForge's side - passed for a success,
        and push logged the page as updated."""
        for status in (400, 403, 404, 500):
            with self.subTest(status=status), \
                    mock.patch.object(sfwikisync.requests, 'post',
                                      return_value=Response(status)), \
                    self.assertRaises(sfwikisync.requests.HTTPError):
                self.client.create_or_update_page(WikiPage('Home', '', []))

    def test_the_token_goes_into_the_authorization_header(self):
        request = types.SimpleNamespace(headers={})
        self.assertIs(request,
                      sfwikisync.auth.BearerAuth('secret')(request))
        self.assertEqual({'Authorization': 'Bearer secret'}, request.headers)


class FolderTest(unittest.TestCase):

    """A test with a content folder of its own."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.content = pathlib.Path(directory.name)


class PullTest(FolderTest):

    def test_every_page_is_written_into_its_file(self):
        client = FakeClient(WikiPage('Home', 'Home page\n', []),
                            WikiPage('Installation', 'Installing\n', []))
        with self.assertLogs(level='INFO'):
            sfwikisync.main.pull(client, str(self.content))
        self.assertEqual(['Home.md', 'Installation.md'],
                         sorted(path.name for path in self.content.iterdir()))
        self.assertEqual('Installing\n',
                         (self.content / 'Installation.md').read_text())

    def test_a_file_edited_locally_is_overwritten(self):
        (self.content / 'Home.md').write_text('Not pushed yet\n')
        with self.assertLogs(level='INFO'):
            sfwikisync.main.pull(FakeClient(WikiPage('Home', 'Wiki\n', [])),
                                 str(self.content))
        self.assertEqual('Wiki\n', (self.content / 'Home.md').read_text())

    def test_pages_are_written_with_the_repository_line_endings(self):
        """The API keeps page text with Windows line endings.  Written as
        they came, they made every line of every page show as changed after
        a pull, as in the wiki's first import in 2023."""
        with self.assertLogs(level='INFO'):
            sfwikisync.main.pull(
                FakeClient(WikiPage('Home', 'One\r\nTwo\r\n', [])),
                str(self.content))
        self.assertEqual(b'One\nTwo\n',
                         (self.content / 'Home.md').read_bytes())

    def test_pages_are_written_and_read_as_utf8(self):
        """Whatever the locale's encoding is, which on Windows is not
        UTF-8."""
        text = 'Café → マンガ\n'
        with self.assertLogs(level='INFO'):
            sfwikisync.main.pull(FakeClient(WikiPage('Home', text, [])),
                                 str(self.content))
        self.assertEqual(text.encode('utf-8'),
                         (self.content / 'Home.md').read_bytes())
        self.assertEqual(text.replace('\n', '\r\n'),
                         sfwikisync.main.read_page_text(
                             self.content / 'Home.md'))

    def test_a_page_just_pulled_is_no_change_to_push(self):
        client = FakeClient(WikiPage('Home', 'Café\r\nTwo\r\n', ['']))
        with self.assertLogs(level='INFO'):
            sfwikisync.main.pull(client, str(self.content))
            sfwikisync.main.push(client, str(self.content))
        self.assertEqual([], client.uploads)

    def test_a_page_that_cannot_be_downloaded_is_skipped(self):
        client = FakeClient(WikiPage('Home', 'Home page\n', []))
        client.pagenames = lambda: ['Gone', 'Home']
        with self.assertLogs(level='ERROR') as logs:
            sfwikisync.main.pull(client, str(self.content))
        self.assertIn("'Gone'", '\n'.join(logs.output))
        self.assertEqual(['Home.md'],
                         [path.name for path in self.content.iterdir()])


class PushTest(FolderTest):

    def push(self, client):
        with self.assertLogs(level='INFO') as logs:
            sfwikisync.main.push(client, str(self.content))
        return '\n'.join(logs.output)

    def test_a_page_the_file_matches_is_left_alone(self):
        """The API keeps the text with Windows line endings and the file
        has Unix ones, which is no difference."""
        (self.content / 'Home.md').write_text('One\nTwo\n')
        client = FakeClient(WikiPage('Home', 'One\r\nTwo\r\n', ['']))
        self.assertIn("No change to 'Home'", self.push(client))
        self.assertEqual([], client.uploads)

    def test_a_changed_page_is_uploaded_with_its_labels(self):
        (self.content / 'Home.md').write_text('New\n')
        client = FakeClient(WikiPage('Home', 'Old\r\n', ['manual']))
        self.assertIn("Updated 'Home'", self.push(client))
        self.assertEqual([WikiPage('Home', 'New\r\n', ['manual'])],
                         client.uploads)

    def test_a_new_page_is_created_without_labels(self):
        (self.content / 'New_Page.md').write_text('New\n')
        client = FakeClient()
        self.push(client)
        self.assertEqual([WikiPage('New_Page', 'New\r\n', [])],
                         client.uploads)

    def test_windows_line_endings_are_not_doubled(self):
        (self.content / 'Home.md').write_bytes(b'One\r\nTwo\r\n')
        self.assertEqual('One\r\nTwo\r\n', sfwikisync.main.read_page_text(
            self.content / 'Home.md'))

    def test_only_markdown_files_are_pages(self):
        (self.content / 'notes.txt').write_text('Not a page\n')
        (self.content / 'Home.md').write_text('Home\n')
        client = FakeClient()
        self.push(client)
        self.assertEqual(['Home'], [page.title for page in client.uploads])


class MainTest(FolderTest):

    def main(self, *arguments):
        """main() over the arguments, with no client able to reach the
        network, without the handler it would give the root logger, and
        without a token from the environment the tests run in."""
        with mock.patch.object(sys, 'argv', ['sfwikisync', *arguments]), \
                mock.patch.dict(os.environ), \
                mock.patch.object(sfwikisync.main.logging, 'basicConfig'), \
                mock.patch.object(sfwikisync.main, 'WikiClient') as client:
            os.environ.pop(sfwikisync.main.TOKEN_VARIABLE, None)
            return sfwikisync.main.main(), client

    def test_github_converts_without_a_client(self):
        (self.content / 'Home.md').write_text('Home\n===\n\n[TOC]\n\nText\n')
        output = self.content / 'out'
        with self.assertLogs(level='INFO'):
            status, client = self.main('-p', 'mcomix', '-d', str(self.content),
                                       '-o', str(output), 'github')
        self.assertEqual(0, status)
        client.assert_not_called()
        self.assertEqual('Home\n===\n\nText\n',
                         (output / 'Home.md').read_text())

    def test_github_writes_nothing_for_a_page_out_of_shape(self):
        (self.content / 'Home.md').write_text('[[img src="shot.png"]]\n')
        output = self.content / 'out'
        with self.assertLogs(level='ERROR') as logs:
            status, _client = self.main('-p', 'mcomix', '-d',
                                        str(self.content), '-o', str(output),
                                        'github')
        self.assertEqual(1, status)
        self.assertIn('Home.md:1:', '\n'.join(logs.output))
        self.assertFalse(output.exists())

    def test_pull_and_push_go_to_the_project_wiki(self):
        for operation, token in (('pull', None), ('push', 'secret')):
            arguments = ['-p', 'mcomix', '-w', 'docs', '-d', 'folder']
            if token:
                arguments += ['-b', token]
            with self.subTest(operation=operation), \
                    mock.patch.object(sfwikisync.main, operation) as run:
                status, client = self.main(*arguments, operation)
            self.assertEqual(0, status)
            client.assert_called_once_with('mcomix', 'docs', token)
            run.assert_called_once_with(client.return_value, 'folder')

# vim: expandtab:sw=4:ts=4
