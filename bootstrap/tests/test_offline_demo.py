"""Exercise the complete public fixture demonstration, including its I/O guards."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import tempfile
import unittest

from bootstrap import offline_demo
from cis_lab import cli


class OfflineDemoTests(unittest.TestCase):
    def test_three_node_demo_never_changes_services_and_produces_review_artifacts(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            out = Path(directory) / 'demo'
            self.assertEqual(offline_demo.main(['--out', str(out)]), 0)
            summary = cli.read_json(out / 'summary.json')
            self.assertEqual(summary['cases']['good']['counts'], {'PASS': 7})
            self.assertEqual(summary['cases']['bad']['counts'], {'FAIL': 7})
            self.assertEqual(summary['cases']['read_error']['counts'], {'ERROR': 7})
            self.assertEqual(summary['cases']['mixed_three_nodes']['counts'], {'PASS': 7, 'FAIL': 7, 'ERROR': 7})
            self.assertEqual(summary['cases']['team_policy']['counts'], {'PASS': 6, 'NEEDS_REVIEW': 1})
            self.assertEqual(summary['plan']['actions'], 7)
            self.assertEqual(summary['plan']['blocked_results'], 7)
            self.assertEqual(summary['plan']['action_targets'], ['cass-dev2'])
            self.assertFalse(summary['node_changes_performed'])
            self.assertEqual(summary['service_verification'], 'not performed')
            receipt = cli.read_json(out / 'mixed/dry-run.json')
            self.assertEqual(receipt['approval_checks'], 'PASS')
            self.assertFalse(receipt['execution_ready'])
            self.assertIn('UNRESOLVED_AUDIT_RESULTS', receipt['blocked_reasons'])

    def test_demo_does_not_overwrite_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()):
            out = Path(directory)
            marker = out / 'keep.txt'
            marker.write_text('keep')
            self.assertEqual(offline_demo.main(['--out', str(out)]), 2)
            self.assertEqual(marker.read_text(), 'keep')
            self.assertEqual(list(out.iterdir()), [marker])


if __name__ == '__main__':
    unittest.main()
