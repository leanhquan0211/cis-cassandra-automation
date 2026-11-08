"""Regression tests for offline isolation, provenance and exact approval scope."""

from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cis_lab import cli
from config.render import load_mapping
from checks.platform.checker import run_all_checks

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'checks/platform/fixtures'
POLICY = ROOT / 'bootstrap/fixture-policy.yml'
INVENTORY = ROOT / 'inventories/dev.yml'


class RunnerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def invoke(self, *args):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return cli.main([str(arg) for arg in args])

    def audit(self, *, fixture='bad', out=None, real_mock=False):
        out = out or self.root / 'audit'
        args = ['audit', '--inventory', INVENTORY, '--policy', POLICY, '--limit', 'cass-dev1',
                '--modules', 'platform', '--out', out]
        if not real_mock:
            args += ['--fixture', FIXTURE / (fixture + '.json')]
        self.assertEqual(self.invoke(*args), {'bad': 1, 'good': 0, 'read_error': 2}[fixture], self.stderr.getvalue())
        return out

    def make_plan(self, *, fixture='bad', real_mock=False):
        out = self.audit(fixture=fixture, real_mock=real_mock)
        plan = self.root / 'plan.json'
        self.assertEqual(self.invoke('plan', '--input', out / 'results.json', '--out', plan), 0, self.stderr.getvalue())
        return plan, cli.read_json(plan)

    def make_approval(self, plan, document, *, test_only=True):
        path = self.root / 'approval.fixture.json'
        now = datetime.now(timezone.utc)
        value = {'approval_id': 'fixture-approval', 'plan_id': document['plan_id'],
                 'plan_hash': cli.file_hash(plan), 'target_environment': document['target_environment'],
                 'approved_by': 'fixture-reviewer', 'reason': 'Unit test only', 'test_only': test_only,
                 'approved_at': now.isoformat(), 'expires_at': (now + timedelta(minutes=5)).isoformat(),
                 'approved_controls': sorted({a['control_id'] for a in document['actions']}),
                 'approved_targets': sorted({a['target'] for a in document['actions']}),
                 'approved_action_ids': [a['action_id'] for a in document['actions']]}
        cli.dump(path, value)
        return path, value

    def test_null_and_malformed_fixture_never_connect(self):
        file = self.root / 'invalid.json'
        for value in (None, False, 0, [], {}, {'nodes': None}, {'nodes': []}, {'nodes': {'cass-dev1': None}}):
            file.write_text(json.dumps(value))
            for command in ('audit', 'preflight'):
                with self.subTest(value=value, command=command), patch.object(cli, 'collect_ssh') as ssh:
                    self.assertEqual(self.invoke(command, '--fixture', file, '--limit', 'cass-dev1',
                                                 '--inventory', INVENTORY, '--policy', POLICY,
                                                 '--out', self.root / 'out'), 2)
                    ssh.assert_not_called()

    def test_invalid_or_duplicate_module_rejected_before_ssh(self):
        for modules in ('unknown', 'platform,platform', 'platform,', ''):
            with patch.object(cli, 'collect_ssh') as ssh:
                self.assertEqual(self.invoke('audit', '--modules', modules, '--policy', POLICY,
                                             '--inventory', INVENTORY, '--out', self.root / 'out'), 2)
                ssh.assert_not_called()

    def test_empty_fixture_or_limit_cannot_fall_back_to_live_all_hosts(self):
        for option in ('--fixture', '--limit'):
            with patch.object(cli, 'collect_ssh') as ssh:
                self.assertEqual(self.invoke('audit', option, '', '--inventory', INVENTORY,
                                             '--policy', POLICY, '--out', self.root / 'out'), 2)
                ssh.assert_not_called()

    def test_preflight_bad_os_policy_cannot_pass_by_string_membership(self):
        policy = load_mapping(POLICY)
        policy['platform']['supported_os_distros'] = 'Ubuntu 22.04'
        file = self.root / 'policy.json'
        cli.dump(file, policy)
        self.assertEqual(self.invoke('preflight', '--inventory', INVENTORY, '--policy', file,
                                     '--fixture', FIXTURE / 'good.json', '--limit', 'cass-dev1'), 2)
        checks = json.loads(self.stdout.getvalue())['checks']
        self.assertEqual(next(c['status'] for c in checks if c['check'] == 'supported_os'), 'ERROR')

    def test_invalid_inventory_shapes_rejected_before_ssh(self):
        file = self.root / 'inventory.json'
        valid = load_mapping(INVENTORY)
        variants = []
        for field, value in [('vars', ['bad']), ('children', ['bad'])]:
            data = deepcopy(valid)
            data['all'][field] = value
            variants.append(data)
        data = deepcopy(valid)
        data['all']['children']['cassandra_nodes']['hosts']['cass-int3'] = ['bad']
        variants.append(data)
        data = deepcopy(valid)
        data['all']['children']['cassandra_nodes']['hosts']['cass-int3'] = {'platform_java': []}
        variants.append(data)
        for data in variants:
            file.write_text(json.dumps(data))
            with patch.object(cli, 'collect_ssh') as ssh:
                self.assertEqual(self.invoke('audit', '--inventory', file, '--policy', POLICY,
                                             '--out', self.root / 'out'), 2)
                ssh.assert_not_called()

    def test_wrong_result_owner_label_scope_or_nonfinite_is_rejected(self):
        facts = cli.read_json(FIXTURE / 'good.json')['nodes']['cass-dev1']
        row = run_all_checks('node', load_mapping(POLICY), facts=facts)[0]
        for changed in ({'owner': 'TV2'}, {'cis_status': 'A'}, {'scope': 'cluster'},
                        {'actual': {'number': float('inf')}}):
            with self.assertRaises((ValueError, cli.jsonschema.ValidationError)):
                cli.validate_results([{**row, **changed}])

    def test_nonfinite_exponents_are_rejected_at_read(self):
        file = self.root / 'overflow.json'
        file.write_text('{"value": 1e999}')
        with self.assertRaises(ValueError):
            cli.read_json(file)

    def test_plan_provenance_context_and_coverage_must_match(self):
        out = self.audit()
        path = out / 'run.json'
        original = cli.read_json(path)
        changes = [{'run_id': 'different'}, {'targets': ['other']}, {'counts': {'PASS': 7}},
                   {'policy_ref': 'wrong'}, {'modules': ['auth']}, {'modules': ['platform', 'platform']},
                   {'source_mode': 'ssh'}, {'modules': None}]
        for change in changes:
            cli.dump(path, {**original, **change})
            self.assertEqual(self.invoke('plan', '--input', out / 'results.json',
                                         '--out', self.root / 'invalid-plan.json'), 2)
            self.assertFalse((self.root / 'invalid-plan.json').exists())

    def test_mixed_audit_runs_cannot_be_planned(self):
        out = self.audit()
        rows = cli.read_json(out / 'results.json')
        rows[0]['run_id'] = 'another-run'
        cli.dump(out / 'results.json', rows)
        self.assertEqual(self.invoke('plan', '--input', out / 'results.json', '--out', self.root / 'plan.json'), 2)

    def test_template_is_incomplete_and_cannot_approve_itself(self):
        plan, document = self.make_plan()
        approval = self.root / 'template.json'
        self.assertEqual(self.invoke('approval-template', '--plan', plan, '--out', approval), 0)
        draft = cli.read_json(approval)
        self.assertEqual(draft['plan_hash'], cli.file_hash(plan))
        self.assertEqual(draft['approved_by'], '')
        self.assertEqual(draft['approved_action_ids'], [])
        self.assertIsNone(draft['approved_at'])
        self.assertTrue(draft['test_only'])
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)

    def test_valid_fixture_dry_run_is_explicitly_blocked_without_network(self):
        plan, document = self.make_plan()
        approval, _ = self.make_approval(plan, document)
        receipt = self.root / 'review.json'
        with patch.object(cli, 'collect_ssh') as ssh:
            self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval,
                                         '--out', receipt), 3)
            ssh.assert_not_called()
        review = cli.read_json(receipt)
        self.assertEqual(review['approval_checks'], 'PASS')
        self.assertFalse(review['execution_ready'])
        self.assertFalse(review['node_changes_performed'])
        self.assertEqual(review['source_mode'], 'fixture')
        self.assertIn('TEST_INPUT_ONLY', review['blocked_reasons'])
        self.assertIn('OWNER_BACKEND_REQUIRED', review['blocked_reasons'])
        self.assertEqual(self.invoke('apply', '--plan', plan, '--approval', approval), 2)

    def test_fixture_requires_test_only_even_in_dry_run(self):
        plan, document = self.make_plan()
        approval, value = self.make_approval(plan, document, test_only=False)
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)

    def test_approval_exact_scope_identity_and_types(self):
        plan, document = self.make_plan()
        approval, original = self.make_approval(plan, document)
        variants = [
            {'approved_targets': ['other-node']}, {'approved_action_ids': original['approved_action_ids'][:-1]},
            {'approved_action_ids': original['approved_action_ids'] * 2}, {'approved_controls': '1.1'},
            {'approved_controls': original['approved_controls'] + ['5.2']}, {'approved_by': '  '},
            {'approved_by': True}, {'approval_id': ''}, {'reason': ''}, {'test_only': 'true'},
            {'plan_id': 'wrong'}, {'target_environment': 'prod'}, {'plan_hash': '0' * 64}]
        for change in variants:
            with self.subTest(change=change):
                cli.dump(approval, {**original, **change})
                self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)

    def test_approval_timezone_lifetime_and_plan_creation(self):
        plan, document = self.make_plan()
        approval, original = self.make_approval(plan, document)
        now = datetime.now(timezone.utc)
        for change in ({'approved_at': now.replace(tzinfo=None).isoformat()},
                       {'expires_at': '2026-02-30T00:00:00Z'},
                       {'expires_at': now.isoformat()},
                       {'approved_at': (now + timedelta(hours=1)).isoformat()},
                       {'approved_at': (cli.timestamp(document['created_at']) - timedelta(seconds=1)).isoformat()}):
            cli.dump(approval, {**original, **change})
            self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)
        local = timezone(timedelta(hours=7))
        cli.dump(approval, {**original, 'approved_at': now.astimezone(local).isoformat(),
                            'expires_at': (now + timedelta(minutes=5)).astimezone(local).isoformat()})
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 3)

    def test_plan_mutation_invalidates_approval_even_if_whitespace_only(self):
        plan, document = self.make_plan()
        approval, _ = self.make_approval(plan, document)
        plan.write_text(plan.read_text() + '\n')
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)

    def test_review_hashes_identify_the_same_snapshots_that_were_validated(self):
        plan, document = self.make_plan()
        approval, _ = self.make_approval(plan, document)
        expected_plan, expected_approval = cli.file_hash(plan), cli.file_hash(approval)
        # Approval validation and its receipt must not re-read through file_hash.
        with patch.object(cli, 'file_hash', side_effect=AssertionError('second read')):
            self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 3)
        review = json.loads(self.stdout.getvalue())
        self.assertEqual(review['plan_sha256'], expected_plan)
        self.assertEqual(review['approval_sha256'], expected_approval)

    def test_unsafe_plan_payloads_cannot_be_enabled_by_approval(self):
        plan, original = self.make_plan()
        variants = []
        for key, value in [('owner', 'TV4'), ('module', 'observability_tls'), ('target', 'other'),
                           ('action_id', 'wrong'), ('scope', 'cluster'), ('executable', True),
                           ('command', 'arbitrary command payload')]:
            data = deepcopy(original)
            data['actions'][0][key] = value
            variants.append(data)
        for key, value in [('blocked_results', True), ('requires_approval', False),
                           ('actions', {}), ('result_counts', {'PASS': 7}), ('targets', [])]:
            variants.append({**original, key: value})
        for document in variants:
            cli.dump(plan, document)
            approval, _ = self.make_approval(plan, original)
            self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)

    def test_no_provenance_can_be_planned_but_not_applied_or_dry_run(self):
        out = self.audit()
        isolated = self.root / 'isolated'
        isolated.mkdir()
        results = isolated / 'results.json'
        results.write_bytes((out / 'results.json').read_bytes())
        plan = isolated / 'plan.json'
        self.assertEqual(self.invoke('plan', '--input', results, '--out', plan), 0)
        document = cli.read_json(plan)
        self.assertEqual(document['source_mode'], 'unknown')
        approval, _ = self.make_approval(plan, document)
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)

    def test_ssh_audit_dry_run_still_cannot_execute_missing_backends(self):
        facts = cli.read_json(FIXTURE / 'bad.json')['nodes']['cass-dev1']
        with patch.object(cli, 'collect_ssh', return_value=facts):
            plan, document = self.make_plan(real_mock=True)
        approval, value = self.make_approval(plan, document, test_only=False)
        with patch.object(cli, 'collect_ssh') as ssh:
            self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 3)
            self.assertEqual(self.invoke('apply', '--plan', plan, '--approval', approval), 2)
            self.assertIn('No apply backend', self.stderr.getvalue())
            ssh.assert_not_called()
        value['test_only'] = True
        cli.dump(approval, value)
        self.assertEqual(self.invoke('apply', '--plan', plan, '--approval', approval), 2)
        self.assertIn('Test-only', self.stderr.getvalue())

    def test_two_nodes_same_control_have_distinct_action_ids_and_exact_targets(self):
        facts = cli.read_json(FIXTURE / 'bad.json')['nodes']['cass-dev1']
        fixture = self.root / 'two.json'
        cli.dump(fixture, {'nodes': {'cass-dev1': facts, 'cass-dev2': facts}})
        out = self.root / 'two'
        self.assertEqual(self.invoke('audit', '--inventory', INVENTORY, '--policy', POLICY,
                                     '--fixture', fixture, '--limit', 'cass-dev1,cass-dev2',
                                     '--modules', 'platform', '--out', out), 1)
        plan = self.root / 'plan.json'
        self.assertEqual(self.invoke('plan', '--input', out / 'results.json', '--out', plan), 0)
        document = cli.read_json(plan)
        self.assertEqual(len({a['action_id'] for a in document['actions']}), 14)
        approval, value = self.make_approval(plan, document)
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 3)
        value['approved_targets'] = ['cass-dev1']
        cli.dump(approval, value)
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 2)

    def test_errors_are_blocked_not_turned_into_actions(self):
        plan, document = self.make_plan(fixture='read_error')
        self.assertEqual(document['blocked_results'], 7)
        self.assertEqual(document['actions'], [])
        approval, _ = self.make_approval(plan, document)
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval), 3)
        self.assertIn('UNRESOLVED_AUDIT_RESULTS', json.loads(self.stdout.getvalue())['blocked_reasons'])

    def test_outputs_cannot_destroy_audit_plan_approval_or_fixture(self):
        plan, document = self.make_plan()
        results = self.root / 'audit/results.json'
        before = results.read_bytes()
        for output in (results, self.root / 'audit/run.json'):
            self.assertEqual(self.invoke('plan', '--input', results, '--out', output), 2)
        self.assertEqual(results.read_bytes(), before)
        alias = self.root / 'results-alias.json'
        alias.hardlink_to(results)
        self.assertEqual(self.invoke('plan', '--input', results, '--out', alias), 2)
        self.assertEqual(results.read_bytes(), before)
        before = plan.read_bytes()
        self.assertEqual(self.invoke('approval-template', '--plan', plan, '--out', plan), 2)
        self.assertEqual(plan.read_bytes(), before)
        approval, _ = self.make_approval(plan, document)
        before = approval.read_bytes()
        self.assertEqual(self.invoke('apply', '--dry-run', '--plan', plan, '--approval', approval,
                                     '--out', approval), 2)
        self.assertEqual(approval.read_bytes(), before)
        fixture = self.root / 'good.json'
        fixture.write_bytes((FIXTURE / 'good.json').read_bytes())
        before = fixture.read_bytes()
        self.assertEqual(self.invoke('preflight', '--inventory', INVENTORY, '--policy', POLICY,
                                     '--limit', 'cass-dev1', '--fixture', fixture, '--out', fixture), 2)
        self.assertEqual(fixture.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
