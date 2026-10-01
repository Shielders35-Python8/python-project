"""지원하는 버전 비교와 판정 불가를 외부 호출 없이 구분한다."""

import unittest

from source.services.processor import version_matches_range
from source.databases.schemas.service_package_entity import build_service_package_schema
from source.services.version_comparison import VERSION_PARSERS


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
            ("1.2.0.0", "== 1.2", True),
            ("1.2.0.1", "> 1.2", True),
            ("0.0", "= 0", True),
        ):
            with self.subTest(version=version, expression=expression):
                self.assertIs(version_matches_range(version, expression), expected)

    def test_requested_prerelease_range_includes_both_boundaries(self):
        expression = ">= 3.0.0-alpha.1, <= 3.0.0-beta.1"
        for ecosystem in (None, "npm"):
            for version, expected in (
                ("2.9.9", False), ("3.0.0-alpha", False), ("3.0.0-alpha.0", False),
                ("3.0.0-alpha.1", True), ("3.0.0-alpha.2", True),
                ("3.0.0-alpha.10", True), ("3.0.0-beta", True),
                ("3.0.0-beta.1", True), ("3.0.0-beta.2", False),
                ("3.0.0-rc.1", False), ("3.0.0", False),
            ):
                with self.subTest(ecosystem=ecosystem, version=version):
                    self.assertIs(version_matches_range(version, expression, ecosystem), expected)

    def test_semver_prerelease_precedence_and_numeric_identifiers(self):
        ordered = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta",
                   "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11",
                   "1.0.0-rc.1", "1.0.0"]
        for lower, upper in zip(ordered, ordered[1:]):
            with self.subTest(lower=lower, upper=upper):
                self.assertIs(version_matches_range(lower, f"< {upper}", "npm"), True)
                self.assertIs(version_matches_range(upper, f"<= {lower}", "npm"), False)
        for version, expression, expected in (
            ("1.0-rc.1", "< 1.0", True),
            ("1.0", ">= 1.0-beta.1, < 2.0", True),
            ("1.0.0-2", "< 1.0.0-10", True),
            ("1.0.0-10", "< 1.0.0-alpha", True),
            ("1.0.0-alpha.2", "!= 1.0.0-alpha.2", False),
            ("1.0.0-alpha.2", "> 1.0.0-alpha.2", False),
            ("1.5.0-beta.1", ">= 1, < 2", True),
            ("1.0.0+build.1", "= 1.0.0+build.2", True),
            ("1.0.0+build.1", "!= 1.0", False),
            ("3.0.0-beta.1+001", "<= 3.0.0-beta.1", True),
        ):
            with self.subTest(version=version, expression=expression):
                self.assertIs(version_matches_range(version, expression, "npm"), expected)

    def test_python_uses_pep440_version_ordering(self):
        for ecosystem in ("pip", "PyPI"):
            for version, expression, expected in (
                ("3.0.0a1", ">= 3.0.0-alpha.1, <= 3.0.0-beta.1", True),
                ("3.0.0b1", ">= 3.0.0-alpha.1, <= 3.0.0-beta.1", True),
                ("3.0.0rc1", ">= 3.0.0-alpha.1, <= 3.0.0-beta.1", False),
                ("0.54.0a1", "< 0.54.0", True),
                ("1.0.dev1", "< 1.0a1", True),
                ("1.0.post1", "> 1.0", True),
                ("1!1.0", "> 9.0", True),
                ("1.0+build.1", "> 1.0", True),
                ("1.0.0", "= 1.0", True),
            ):
                with self.subTest(ecosystem=ecosystem, version=version, expression=expression):
                    self.assertIs(version_matches_range(version, expression, ecosystem), expected)

    def test_ecosystems_do_not_use_each_others_version_rules(self):
        for ecosystem, version, expression in (
            ("npm", "1.0a1", "< 2.0"),
            ("pip", "1.0.0-alpha.beta", "< 2.0"),
            ("other", "release-latest", "< 2.0-beta.1"),
            ("composer", "dev-main", "< 2.0"),
        ):
            with self.subTest(ecosystem=ecosystem, version=version):
                self.assertIsNone(version_matches_range(version, expression, ecosystem))
        self.assertIs(version_matches_range("1.2.3.4", ">= 1.2, < 2", "maven"), True)

    def test_every_registered_ecosystem_handles_the_reported_range(self):
        options = build_service_package_schema("test-source")["ecosystem"]["select"]["options"]
        self.assertEqual({option["name"] for option in options}, set(VERSION_PARSERS))
        expression = ">= 3.0.0-alpha.1, <= 3.0.0-beta.1"
        for option in options:
            for version, expected in (
                ("2.9.4", False), ("3.0.0-alpha.1", True), ("3.0.0-alpha.2", True),
                ("3.0.0-beta.1", True), ("3.0.0-beta.2", False), ("3.0.0", False),
            ):
                with self.subTest(ecosystem=option["name"], version=version):
                    self.assertIs(version_matches_range(version, expression, option["name"]), expected)

    def test_native_ecosystem_ordering(self):
        cases = (
            ("nuget", "1.0.0-Alpha.1", "== 1.0.0-alpha.1", True),
            ("nuget", "1.0.0.1-alpha", "> 1.0.0", True),
            ("nuget", "01.02.03.0+build.1", "== 1.2.3+build.2", True),
            ("maven", "3.0.0.Final", "== 3.0.0", True),
            ("maven", "3.0.0.GA", "== 3.0.0.RELEASE", True),
            ("maven", "3.0.0-rc1", "< 3.0.0-SNAPSHOT", True),
            ("maven", "3.0.0-SNAPSHOT", "< 3.0.0", True),
            ("maven", "3.0.0-sp1", "> 3.0.0", True),
            ("rubygems", "1.0.0.rc1", "< 1.0.0", True),
            ("rubygems", "1.0.0.pre.10", "> 1.0.0.pre.2", True),
            ("rubygems", "1.0.0.1", "> 1.0.0", True),
            ("go", "v0.0.0-20260512171108-5e8f99f40a8a", "< 0.1.0", True),
            ("go", "v0.0.0-20260512171108-5e8f99f40a8a",
             "> 0.0.0-20260511171108-5e8f99f40a8a", True),
            ("go", "v2.0.0+incompatible", "== 2.0.0", True),
            ("composer", "v1.0.0-dev", "< 1.0.0-alpha", True),
            ("composer", "1.0.0RC2", "> 1.0.0-beta10, < 1.0", True),
            ("composer", "1.0.0-rc1-dev", "< 1.0.0-RC1", True),
            ("composer", "1.0.0-p1", "> 1.0.0", True),
            ("composer", "1.0.0-patch1", "== 1.0.0-pl1", True),
            ("composer", "1.0.0.1-beta2", "> 1.0.0, < 1.0.0.1", True),
            ("composer", "1.0.0+build1", "== 1.0.0+build2", True),
            ("pub", "1.2.3+2", "< 1.2.3+10", True),
            ("pub", "1.2.3+2", "== 1.2.3+10", False),
            ("pub", "1.2.3", "< 1.2.3+1", True),
            ("pub", "01.02.03-alpha.01+02", "== 1.2.3-alpha.1+2", True),
            ("rust", "1.0.0-rc.2", "< 1.0.0-rc.10", True),
            ("erlang", "1.0.0-rc.1", "< 1.0.0", True),
            ("swift", "v1.0.0-beta.1", "< 1.0.0", True),
            ("actions", "v3.0.0-beta.1", "<= 3.0.0-beta.1", True),
            ("other", "1.0.0-rc.1", "< 1.0.0", True),
        )
        for ecosystem, version, expression, expected in cases:
            with self.subTest(ecosystem=ecosystem, version=version, expression=expression):
                self.assertIs(version_matches_range(version, expression, ecosystem), expected)

    def test_aliases_and_unicode_comparators(self):
        for ecosystem in (" NuGet ", "PyPI", "Cargo", "Hex", "Golang", "GitHub Actions", "Dart", "gem"):
            with self.subTest(ecosystem=ecosystem):
                self.assertIs(version_matches_range("3.0.0-beta.1", "≥ 3.0.0-alpha.1, ≤ 3.0.0-beta.1", ecosystem), True)

    def test_unsupported_inputs_remain_unknown_in_every_ecosystem(self):
        for ecosystem in VERSION_PARSERS:
            for version, expression in (
                ("latest", "< 2.0"), ("abc123def456", "< 2.0"),
                ("1.0", "< 2.0 || >= 3.0"), ("1.0", "^1.0"), ("1.0", "1.*"),
                ("1.0", "~1.0"), ("1.0", "===1.0"), ("1.0", "< 2.0,"),
                ("1.0", ">= 2, < 3.0-beta..1"), (None, "< 2.0"),
            ):
                with self.subTest(ecosystem=ecosystem, version=version, expression=expression):
                    self.assertIsNone(version_matches_range(version, expression, ecosystem))

    def test_unsupported_or_missing_input_is_unknown(self):
        for version, expression in (
            ("1.0.0-alpha.01", "< 2.0"),
            ("1.0", ">= 1.0-beta..1, < 2.0"),
            ("1.0.0-", "< 2.0"), ("1.0.0+", "< 2.0"),
            ("1.0.0.1-alpha", "< 2.0"),
            ("1.0", "< 3.0.0.Final"),
            ("1.0", "< 0.54.0a1"),
            ("1.0", "< 2.0 || >= 3.0"),
            ("1.0", "^1.0"), ("1.0", "~1.0"), ("1.0", "1.*"),
            ("1.0", "===1.0"), ("1.0", "< 2 >= 1"),
            (None, "< 2.0"), ("", "< 2.0"),
            (1.0, "< 2.0"), ("1.0", 2.0),
            ("1.0", None), ("1.0", ""), ("1.0", "< 2.0,"),
        ):
            with self.subTest(version=version, expression=expression):
                self.assertIsNone(version_matches_range(version, expression))

    def test_unsupported_clause_is_unknown_regardless_of_condition_order(self):
        for ecosystem in (None, "npm", "pip", "maven"):
            for expression in (">= 2.0, < 3.0-beta..1", "< 3.0-beta..1, >= 2.0"):
                with self.subTest(ecosystem=ecosystem, expression=expression):
                    self.assertIsNone(version_matches_range("1.0", expression, ecosystem))
