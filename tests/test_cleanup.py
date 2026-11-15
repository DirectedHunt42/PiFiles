import os
import tempfile
import unittest
from pathlib import Path

import app


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        app.DATA_DIR = Path(self.temporary_directory.name) / "share"
        app.DATA_DIR.mkdir()
        app.EXTENSION_CLEANUP_FILE = Path(self.temporary_directory.name) / "extension-cleanup.json"

    def make_file(self, name, size, modified):
        path = app.DATA_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        os.utime(path, (modified, modified))
        return path

    def test_removes_oldest_files_only_until_threshold(self):
        oldest = self.make_file("oldest.bin", 4, 1)
        middle = self.make_file("middle.bin", 3, 2)
        newest = self.make_file("newest.bin", 2, 3)

        deleted = app.cleanup_folder("", {"threshold_bytes": 5, "strategy": "oldest"})

        self.assertEqual(deleted, 1)
        self.assertFalse(oldest.exists())
        self.assertTrue(middle.exists())
        self.assertTrue(newest.exists())

    def test_removes_newest_file_first(self):
        oldest = self.make_file("oldest.bin", 4, 1)
        newest = self.make_file("newest.bin", 4, 3)

        deleted = app.cleanup_folder("", {"threshold_bytes": 4, "strategy": "newest"})

        self.assertEqual(deleted, 1)
        self.assertTrue(oldest.exists())
        self.assertFalse(newest.exists())

    def test_largest_files_are_removed_first(self):
        largest = self.make_file("largest.bin", 4, 1)
        smallest = self.make_file("smallest.bin", 2, 2)
        remaining = self.make_file("remaining.bin", 3, 3)

        deleted = app.cleanup_folder("", {"threshold_bytes": 5, "strategy": "largest"})

        self.assertEqual(deleted, 1)
        self.assertFalse(largest.exists())
        self.assertTrue(smallest.exists())
        self.assertTrue(remaining.exists())

    def test_smallest_files_are_removed_first(self):
        smallest = self.make_file("smallest.bin", 2, 1)
        middle = self.make_file("middle.bin", 3, 2)
        largest = self.make_file("largest.bin", 4, 3)

        deleted = app.cleanup_folder("", {"threshold_bytes": 5, "strategy": "smallest"})

        self.assertEqual(deleted, 2)
        self.assertFalse(smallest.exists())
        self.assertFalse(middle.exists())
        self.assertTrue(largest.exists())

    def test_does_not_follow_symbolic_links(self):
        outside_directory = Path(self.temporary_directory.name) / "outside"
        outside_directory.mkdir()
        protected_file = outside_directory / "protected.bin"
        protected_file.write_bytes(b"protected")
        try:
            (app.DATA_DIR / "linked").symlink_to(outside_directory, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"Creating a symbolic link is unavailable: {error}")

        deleted = app.cleanup_folder("", {"threshold_bytes": 1, "strategy": "oldest"})

        self.assertEqual(deleted, 0)
        self.assertTrue(protected_file.exists())

    def test_rejects_parent_path_segments(self):
        with self.assertRaises(ValueError):
            app.resolve_share_directory("../outside")

    def test_removes_matching_files_older_than_minimum_age_recursively(self):
        now = 50000
        old_file = self.make_file("old.TMP", 1, now - 1801)
        boundary_file = self.make_file("nested/boundary.tmp", 1, now - 1800)
        recent_file = self.make_file("recent.tmp", 1, now - 1799)
        other_file = self.make_file("other.log", 1, now - 9000)
        outside_file = Path(self.temporary_directory.name) / "outside.tmp"
        outside_file.write_text("outside")
        os.utime(outside_file, (now - 9000, now - 9000))

        deleted = app.cleanup_files_by_extension(
            [{"extension": ".tmp", "min_age_seconds": 1800}],
            now=now,
        )

        self.assertEqual(deleted, 2)
        self.assertFalse(old_file.exists())
        self.assertFalse(boundary_file.exists())
        self.assertTrue(recent_file.exists())
        self.assertTrue(other_file.exists())
        self.assertTrue(outside_file.exists())

    def test_extension_rules_are_case_insensitive_and_saved_normalized(self):
        app.save_extension_cleanup_rules([{"extension": ".TMP", "min_age_seconds": 30}])

        self.assertEqual(
            app.load_extension_cleanup_rules(),
            [{"extension": ".tmp", "min_age_seconds": 30}],
        )

    def test_rejects_duplicate_extensions_and_invalid_ages(self):
        with self.assertRaises(ValueError):
            app.validate_extension_cleanup_rules([
                {"extension": ".tmp", "min_age_seconds": 30},
                {"extension": ".TMP", "min_age_seconds": 60},
            ])
        with self.assertRaises(ValueError):
            app.validate_extension_cleanup_rules([{"extension": ".tmp", "min_age_seconds": True}])


if __name__ == "__main__":
    unittest.main()
