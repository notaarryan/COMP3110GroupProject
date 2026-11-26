"""Tests for preprocess.py (LHDiff stage 1, P1). Standard library unittest only."""

from __future__ import annotations

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from preprocess import (  # noqa: E402
    detect_unchanged,
    get_context,
    gnu_diff_available,
    normalize,
    preprocess,
    preprocess_file,
    read_lines,
)

DATA = os.path.join(REPO_ROOT, "tests", "data")

# Backends that can run on this machine. Backend-independent tests loop over these.
BACKENDS = ["difflib"] + (["gnu"] if gnu_diff_available() else [])
NO_GNU = "GNU diff is not on PATH"


def data(name: str) -> str:
    return os.path.join(DATA, name)


class NormalizeTests(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(normalize("FileReader FR"), "filereader fr")

    def test_collapses_tabs_and_multiple_spaces(self):
        self.assertEqual(normalize("a\t\tb    c \t d"), "a b c d")

    def test_strips_leading_and_trailing_whitespace(self):
        self.assertEqual(normalize("   \tx = 1;\t  "), "x = 1;")

    def test_whitespace_only_line_becomes_empty(self):
        self.assertEqual(normalize(" \t  \t"), "")
        self.assertEqual(normalize(""), "")

    def test_slide21_example(self):
        self.assertEqual(normalize("      String line  =              null;"), "string line = null;")


class LineCountTests(unittest.TestCase):
    def test_counts_match_for_every_fixture(self):
        for name in sorted(os.listdir(DATA)):
            with self.subTest(fixture=name):
                version = preprocess_file(data(name))
                self.assertEqual(len(version.original), len(version.normalized))
                self.assertEqual(len(version), len(read_lines(data(name))))

    def test_blank_lines_are_kept_as_empty_strings(self):
        version = preprocess_file(data("blank_lines.txt"))
        self.assertEqual(len(version.original), 6)
        self.assertEqual(len(version.normalized), 6)
        self.assertEqual(version.normalized, ["first line", "", "", "", "last line", ""])

    def test_slide21_trailing_whitespace_normalized_away(self):
        version = preprocess_file(data("slide21.java"))
        self.assertEqual(len(version), 8)
        self.assertTrue(version.original[4].endswith(" "))
        self.assertEqual(version.normalized[4], "while(line = lr.readline()){")


class GetContextTests(unittest.TestCase):
    LINES = ["l0", "l1", "l2", "l3", "l4", "l5", "l6", "l7", "l8", "l9"]

    def test_excludes_target_line(self):
        context = get_context(self.LINES, 5)
        self.assertEqual(context, "l1 l2 l3 l4 l6 l7 l8 l9")
        self.assertNotIn("l5", context.split())

    def test_clamps_at_first_line(self):
        self.assertEqual(get_context(self.LINES, 0), "l1 l2 l3 l4")

    def test_clamps_at_last_line(self):
        self.assertEqual(get_context(self.LINES, 9), "l5 l6 l7 l8")

    def test_skips_blank_lines_in_window(self):
        lines = ["a", "", "b", "target", "", "c"]
        self.assertEqual(get_context(lines, 3), "a b c")

    def test_raises_index_error_out_of_range(self):
        for index in (-1, len(self.LINES), 100):
            with self.subTest(index=index):
                with self.assertRaises(IndexError):
                    get_context(self.LINES, index)
        with self.assertRaises(IndexError):
            get_context([], 0)


class SlideExampleTests(unittest.TestCase):
    @unittest.skipUnless(gnu_diff_available(), NO_GNU)
    def test_slide24_gnu(self):
        result = preprocess(data("slide24_old.java"), data("slide24_new.java"), backend="gnu")
        self.assertEqual(result.mapping, {0: [0], 1: [2], 3: [4], 7: [8]})
        self.assertEqual(result.left_list, [2, 4, 5, 6])
        self.assertEqual(result.right_list, [1, 3, 5, 6, 7])

    def test_slide24_difflib_picks_the_other_brace(self):
        # INTERFACE.md: difflib maps old 7 (not old 8) to new 9, 1-indexed.
        result = preprocess(data("slide24_old.java"), data("slide24_new.java"), backend="difflib")
        self.assertEqual(result.mapping, {0: [0], 1: [2], 3: [4], 6: [8]})

    def test_slide41_split_lines_stay_unmatched(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result = preprocess(data("split_old.java"), data("split_new.java"), backend=backend)
                self.assertIn(0, result.left_list)
                for new_index in (0, 1, 2):
                    self.assertIn(new_index, result.right_list)
                self.assertNotIn(0, result.mapping)


class BackendTests(unittest.TestCase):
    def test_difflib_runs_and_is_recorded(self):
        result = preprocess(data("slide24_old.java"), data("slide24_new.java"), backend="difflib")
        self.assertEqual(result.backend, "difflib")
        self.assertTrue(result.mapping)

    @unittest.skipUnless(gnu_diff_available(), NO_GNU)
    def test_gnu_runs_and_is_recorded(self):
        result = preprocess(data("slide24_old.java"), data("slide24_new.java"), backend="gnu")
        self.assertEqual(result.backend, "gnu")
        self.assertTrue(result.mapping)

    def test_auto_records_the_backend_that_ran(self):
        result = preprocess(data("slide24_old.java"), data("slide24_new.java"))
        self.assertEqual(result.backend, "gnu" if gnu_diff_available() else "difflib")

    def test_bogus_backend_raises_value_error(self):
        old = preprocess_file(data("slide24_old.java"))
        new = preprocess_file(data("slide24_new.java"))
        with self.assertRaises(ValueError):
            detect_unchanged(old, new, backend="bogus")


class EdgeCaseTests(unittest.TestCase):
    def test_empty_against_empty(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result = preprocess(data("empty.txt"), data("empty.txt"), backend=backend)
                self.assertEqual(result.mapping, {})
                self.assertEqual(result.left_list, [])
                self.assertEqual(result.right_list, [])

    def test_empty_against_one_line(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result = preprocess(data("empty.txt"), data("one_line.txt"), backend=backend)
                self.assertEqual(result.mapping, {})
                self.assertEqual(result.left_list, [])
                self.assertEqual(result.right_list, [0])

    def test_one_line_against_empty(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result = preprocess(data("one_line.txt"), data("empty.txt"), backend=backend)
                self.assertEqual(result.mapping, {})
                self.assertEqual(result.left_list, [0])
                self.assertEqual(result.right_list, [])

    def test_identical_files_map_every_line(self):
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result = preprocess(data("slide24_old.java"), data("slide24_old.java"), backend=backend)
                self.assertEqual(result.mapping, {i: [i] for i in range(8)})
                self.assertEqual(result.left_list, [])
                self.assertEqual(result.right_list, [])

    def test_ten_identical_braces_minus_one(self):
        # Ten "}" lines against nine: both backends pair the first nine in order
        # and leave the last old line unmatched. No crossings, nothing added.
        for backend in BACKENDS:
            with self.subTest(backend=backend):
                result = preprocess(data("braces_10.txt"), data("braces_9.txt"), backend=backend)
                self.assertEqual(result.mapping, {i: [i] for i in range(9)})
                self.assertEqual(result.left_list, [9])
                self.assertEqual(result.right_list, [])


if __name__ == "__main__":
    unittest.main()
