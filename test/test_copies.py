"""No function is written out twice, nor a run of steps in the tests.

Copied set-ups, tear-downs and helpers drift apart: a fix lands in one
copy and the others keep the bug, and a reader cannot tell a deliberate
difference from an accident.  A body that is needed twice belongs in one
place - in test/__init__.py for the tests (MComixTest and the helpers
beside it), or a base class or module function of its own file - and
docs/development.md lists what is there already.
"""

import ast
import collections
import os
import unittest

#: Bodies smaller than this many ast nodes may repeat: a two-line
#: getter, a call with its arguments.  Every pair of this size or more
#: found when the test was written was folded into one.
MINIMUM_NODES = 30

#: Consecutive statements that may repeat inside the tests' functions:
#: the steps one test takes before what it checks, written out again by
#: the next.  Fewer than this are often a protocol the tests walk
#: through on purpose, step by step.  Every run of this length found
#: when the check was written was folded into a helper.
MINIMUM_STEPS = 6

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bodies():
    """Each function under mcomix/ and test/ of MINIMUM_NODES or more,
    by its body dumped with the docstring left out."""
    places = collections.defaultdict(list)
    for top in ('mcomix', 'test'):
        for folder, folders, files in os.walk(os.path.join(_ROOT, top)):
            folders[:] = sorted(name for name in folders
                                if name not in ('tmp', 'files', '__pycache__'))
            for name in sorted(files):
                if not name.endswith('.py'):
                    continue
                path = os.path.join(folder, name)
                with open(path, encoding='utf-8') as source:
                    tree = ast.parse(source.read(), path)
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.FunctionDef,
                                             ast.AsyncFunctionDef)):
                        continue
                    body = node.body
                    if (body and isinstance(body[0], ast.Expr)
                            and isinstance(body[0].value, ast.Constant)
                            and isinstance(body[0].value.value, str)):
                        body = body[1:]
                    size = sum(1 for statement in body
                               for _ in ast.walk(statement))
                    if size < MINIMUM_NODES:
                        continue
                    key = ast.dump(ast.Module(body=body, type_ignores=[]))
                    places[key].append('%s:%d %s' % (
                        os.path.relpath(path, _ROOT), node.lineno, node.name))
    return places


def _step_runs():
    """Each run of MINIMUM_STEPS consecutive statements in a block of
    test/, by its statements dumped, and where it starts."""
    places = collections.defaultdict(set)
    folder = os.path.join(_ROOT, 'test')
    for name in sorted(os.listdir(folder)):
        if not name.endswith('.py'):
            continue
        path = os.path.join(folder, name)
        with open(path, encoding='utf-8') as source:
            tree = ast.parse(source.read(), path)
        for node in ast.walk(tree):
            for field in ('body', 'orelse', 'finalbody'):
                block = getattr(node, field, None)
                if not isinstance(block, list) or len(block) < MINIMUM_STEPS:
                    continue
                dumps = [ast.dump(statement) for statement in block]
                for start in range(len(block) - MINIMUM_STEPS + 1):
                    key = tuple(dumps[start:start + MINIMUM_STEPS])
                    places[key].add('%s:%d' % (os.path.relpath(path, _ROOT),
                                               block[start].lineno))
    return places


class CopiesTest(unittest.TestCase):

    def test_no_function_body_is_written_out_twice(self):
        copies = [places for places in _bodies().values() if len(places) > 1]
        self.assertEqual([], copies,
                         'the same body in more than one place; keep one '
                         'and call it from the others')

    def test_no_run_of_steps_is_written_out_twice_in_the_tests(self):
        copies = sorted(sorted(places) for places in _step_runs().values()
                        if len(places) > 1)
        self.assertEqual([], copies,
                         'the same %d steps in more than one place; make '
                         'them a helper of the class, the file or '
                         'test/__init__.py' % MINIMUM_STEPS)


# vim: expandtab:sw=4:ts=4
