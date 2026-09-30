"""지원하는 버전 비교와 판정 불가를 외부 호출 없이 구분한다."""

import unittest

from source.services.processor import version_matches_range


class VersionComparisonTests(unittest.TestCase):
    def test_numeric_ranges_preserve_comparison_and_zero_padding(self):
        for version, expression, expected in (
            ("1.5", ">= 1.0, < 2.0", True),
            ("2.0", ">= 1.0, < 2.0", False),
            ("1.2", "= 1.2.0", True),
            ("1.2.0", "!= 1.2", False),
            ("1.10", "> 1.9", True),
            (" 1.2.0 ", " <= 1.2, >= 1.2.0 ", True),
            ("1.0", "1.0", True),
        ):
            with self.subTest(version=version, expression=expression):
                self.assertIs(version_matches_range(version, expression), expected)

    def test_unsupported_or_missing_input_is_unknown(self):
        for version, expression in (
            ("1.0-rc.1", "< 2.0"),
            ("1.0", ">= 1.0-beta.1, < 2.0"),
            ("1.0", "< 3.0.0.Final"),
            ("1.0", "< 0.0.0-20260512171108-5e8f99f40a8a"),
            ("1.0", "< 0.54.0a1"),
            ("1.0", "< 2.0 || >= 3.0"),
            (None, "< 2.0"), ("", "< 2.0"),
            ("1.0", None), ("1.0", ""), ("1.0", "< 2.0,"),
        ):
            with self.subTest(version=version, expression=expression):
                self.assertIsNone(version_matches_range(version, expression))

    def test_unsupported_clause_is_unknown_regardless_of_condition_order(self):
        for expression in (">= 2.0, < 3.0-beta.1", "< 3.0-beta.1, >= 2.0"):
            with self.subTest(expression=expression):
                self.assertIsNone(version_matches_range("1.0", expression))
