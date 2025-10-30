import os
import subprocess
import sys
import unittest

import index_advisor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run(*argv):
    return subprocess.run([sys.executable, "-B", "-m", "index_advisor", *argv], cwd=ROOT,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)


class ModuleEntryPointTest(unittest.TestCase):
    def test_help(self):
        result = run("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Exit codes:", result.stdout)

    def test_version(self):
        result = run("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn(index_advisor.__version__, result.stdout)

    def test_usage_error_exit_code(self):
        self.assertEqual(run("--no-such-option").returncode, 3)
        self.assertEqual(run().returncode, 3)
