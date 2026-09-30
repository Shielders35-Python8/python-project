import copy
import json
import unittest
from uuid import NAMESPACE_URL, uuid5

from source.example.seed_service_packages import (
    MOCK_DIR, build_plan, package_key, row_properties, verify_result,
)


class SeedServicePackagesTests(unittest.TestCase):
    def setUp(self):
        self.packages = json.loads((MOCK_DIR / "service_package_mock.json").read_text(encoding="utf-8"))
        self.mock_services = json.loads((MOCK_DIR / "service_mock.json").read_text(encoding="utf-8"))
        self.services = [
            {**row, "page_id": str(uuid5(NAMESPACE_URL, f"live/{row['id']}"))}
            for row in self.mock_services
        ]
        page_map = {mock["page_id"]: live["page_id"]
                    for mock, live in zip(self.mock_services, self.services)}
        self.live_packages = [
            {**row, "page_id": str(uuid5(NAMESPACE_URL, f"live/{row['id']}")),
             "service_id": [page_map[value] for value in row["service_id"]]}
            for row in self.packages
        ]

    def plan(self, existing, target=500):
        return build_plan(self.packages, self.mock_services, self.services, existing, target)

    def test_500_unique_rows_and_real_service_relations(self):
        existing = copy.deepcopy(self.live_packages[:18])
        planned = self.plan(existing)
        self.assertEqual(len(planned), 482)
        self.assertEqual(len({package_key(row) for row in existing + planned}), 500)
        valid_pages = {row["page_id"] for row in self.services}
        self.assertTrue(all(set(row["service_id"]) <= valid_pages for row in planned))
        self.assertEqual(existing, self.live_packages[:18])
        self.assertNotIn("page_id", row_properties(planned[0]))

    def test_resume_partial_import_and_no_op_at_target(self):
        self.assertEqual(len(self.plan(self.live_packages[:137])), 363)
        self.assertEqual(self.plan(self.live_packages), [])
        self.assertEqual(self.plan(self.live_packages, target=490), [])

    def test_conflicting_id_stops_before_any_write(self):
        self.live_packages[0]["package_version"] = "123.456.789"
        with self.assertRaisesRegex(ValueError, "Conflicting package id"):
            self.plan(self.live_packages[:18])

    def test_missing_service_stops_before_any_write(self):
        self.services.pop()
        with self.assertRaises(KeyError):
            self.plan([])

    def test_same_package_with_different_id_is_not_duplicated(self):
        existing = copy.deepcopy(self.live_packages[:18])
        existing[0]["id"] = "CUSTOM-001"
        self.assertEqual(len(self.plan(existing)), 482)

    def test_verification_catches_missing_rows_bad_relations_and_edits(self):
        before = self.live_packages[:18]
        planned = self.plan(before)
        verify_result(before, self.live_packages, planned)
        with self.assertRaisesRegex(RuntimeError, "row count"):
            verify_result(before, self.live_packages[:-1], planned)
        changed = copy.deepcopy(self.live_packages)
        changed[-1]["service_id"] = [self.mock_services[0]["page_id"]]
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            verify_result(before, changed, planned)
        changed = copy.deepcopy(self.live_packages)
        changed[0]["vulnerability"] = "critical"
        with self.assertRaisesRegex(RuntimeError, "Existing row changed"):
            verify_result(before, changed, planned)


if __name__ == "__main__":
    unittest.main()
