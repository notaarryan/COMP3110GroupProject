from __future__ import annotations

import os
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

from similarity import (
    combined_similarity,
    content_similarity,
    context_similarity,
)


class ContentSimilarityTests(unittest.TestCase):
    def test_identical_and_empty_strings(self):
        self.assertEqual(content_similarity("abc", "abc"), 1.0)
        self.assertEqual(content_similarity("", ""), 1.0)
        self.assertEqual(content_similarity("abc", ""), 0.0)

    def test_normalized_levenshtein(self):
        self.assertAlmostEqual(content_similarity("kitten", "sitting"), 4 / 7)
        self.assertAlmostEqual(content_similarity("abc", "axc"), 2 / 3)
        self.assertEqual(content_similarity("a", "b"), 0.0)

    def test_is_symmetric_and_bounded(self):
        self.assertEqual(content_similarity("abcdef", "abc"), content_similarity("abc", "abcdef"))
        for a, b in (("x", "y"), ("", "code"), ("same", "same")):
            self.assertGreaterEqual(content_similarity(a, b), 0.0)
            self.assertLessEqual(content_similarity(a, b), 1.0)


class ContextSimilarityTests(unittest.TestCase):
    def test_identical_and_disjoint_contexts(self):
        self.assertEqual(context_similarity("int total = 1", "int total = 1"), 1.0)
        self.assertEqual(context_similarity("alpha beta", "gamma delta"), 0.0)

    def test_cosine_uses_token_counts_without_order(self):
        self.assertAlmostEqual(context_similarity("foo bar", "bar foo"), 1.0)
        self.assertAlmostEqual(context_similarity("a a b", "a b b"), 0.8)

    def test_empty_contexts_and_case(self):
        self.assertEqual(context_similarity("", " \t "), 1.0)
        self.assertEqual(context_similarity("code", ""), 0.0)
        self.assertEqual(context_similarity("Foo", "foo"), 1.0)


class CombinedSimilarityTests(unittest.TestCase):
    def test_applies_agreed_weights(self):
        self.assertAlmostEqual(combined_similarity("abc", "axc", "foo", "foo"), 0.8)

    def test_identical_inputs_score_one(self):
        self.assertEqual(combined_similarity("line", "line", "nearby", "nearby"), 1.0)


if __name__ == "__main__":
    unittest.main()
