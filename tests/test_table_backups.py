"""Every DynamoDB table has point-in-time recovery.

PITR sat disabled on all 47 tables for a year, filed LOW because of cost. The cost argument was correct --
the tables hold under a megabyte between them, so continuous backups run to a fraction of a cent a month.
What was wrong was treating cost as the whole question. Before launch a bad delete costs a test fixture;
after it costs a merchant's order history, and there is no way back from a DynamoDB delete without this.

It is asserted here rather than left to a console toggle because the failure is silent and only discovered
at the moment it is too late to fix.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "template.yaml").read_text(encoding="utf-8")

TABLE_BLOCKS = re.compile(
    r"^  ([A-Za-z0-9]+):\n    Type: AWS::DynamoDB::Table\n(.*?)(?=^  [A-Za-z0-9]+:\n    Type: |\Z)",
    re.M | re.S)


class EveryTableIsRecoverableTests(unittest.TestCase):
    def test_every_table_enables_point_in_time_recovery(self):
        missing = []
        for name, body in TABLE_BLOCKS.findall(TEMPLATE):
            if "PointInTimeRecoveryEnabled: true" not in body:
                missing.append(name)
        self.assertEqual(
            missing, [],
            f"These tables have no point-in-time recovery: {missing}. A DynamoDB delete is "
            "unrecoverable without it, and it costs a fraction of a cent a month.")

    def test_the_guard_is_actually_looking_at_tables(self):
        """A regex that matches nothing passes the test above for the wrong reason."""
        self.assertGreater(len(TABLE_BLOCKS.findall(TEMPLATE)), 40)


if __name__ == "__main__":
    unittest.main()
