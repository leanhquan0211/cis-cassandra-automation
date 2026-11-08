"""Offline regression tests. Nothing in this suite connects to a VM."""

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from checks.platform import checker, collector
from cis_lab import cli
from config import render

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'checks/platform/fixtures'
POLICY = render.load_mapping(ROOT / 'bootstrap/fixture-policy.yml')
GOOD = json.loads((FIXTURES / 'good.json').read_text())['nodes']['cass-dev1']


class EvaluatorTests(unittest.TestCase):
    def rows(self, facts=None, policy=None):
        rows = checker.run_all_checks('cass-dev1', POLICY if policy is None else policy,
                                      facts=GOOD if facts is None else facts, run_id='fixture-run')
        cli.validate_results(rows)
        return {r['control_id']: r for r in rows}

    def test_good_schema_and_context(self):
        rows = self.rows()
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(r['status'] == 'PASS' and r['run_id'] == 'fixture-run' for r in rows.values()))
        self.assertEqual(rows['1.1']['cis_status'], 'M')
        self.assertEqual(rows['1.6']['cis_status'], 'M')

    def test_known_bad_is_fail(self):
        facts = json.loads((FIXTURES / 'bad.json').read_text())['nodes']['cass-dev1']
        self.assertTrue(all(r['status'] == 'FAIL' for r in self.rows(facts).values()))

    def test_read_error_is_error(self):
        facts = json.loads((FIXTURES / 'read_error.json').read_text())['nodes']['cass-dev1']
        self.assertTrue(all(r['status'] == 'ERROR' for r in self.rows(facts).values()))

    def test_partial_read_error_affects_only_dependent_controls(self):
        facts = deepcopy(GOOD)
        facts['service'] = {'ok': False, 'error': 'PermissionError'}
        rows = self.rows(facts)
        self.assertEqual({c for c, r in rows.items() if r['status'] == 'ERROR'}, {'1.5', '3.4'})
        self.assertEqual(sum(r['status'] == 'PASS' for r in rows.values()), 5)

    def test_no_data_does_not_audit_laptop(self):
        self.assertTrue(all(r['status'] == 'ERROR' for r in self.rows({}).values()))

    def test_missing_python_policy_is_review(self):
        rows = self.rows(policy=render.load_mapping(ROOT / 'policies/lab.yml'))
        self.assertEqual(rows['1.3']['status'], 'NEEDS_REVIEW')
        self.assertEqual(sum(r['status'] == 'PASS' for r in rows.values()), 6)

    def test_missing_dedicated_policy_is_review(self):
        policy = deepcopy(POLICY)
        del policy['platform']['dedicated_user']
        self.assertEqual(self.rows(policy=policy)['1.1']['status'], 'NEEDS_REVIEW')
        self.assertEqual(self.rows(policy=policy)['3.4']['status'], 'NEEDS_REVIEW')

    def test_missing_account_is_fail(self):
        facts = deepcopy(GOOD)
        facts['account']['data'] = {'exists': False}
        self.assertEqual(self.rows(facts)['1.1']['status'], 'FAIL')
        self.assertEqual(self.rows(facts)['3.4']['status'], 'FAIL')

    def test_service_stopped_or_wrong_process_fails(self):
        for field, value in [('active', False), ('pid', 0), ('is_cassandra', False), ('uid', 0)]:
            facts = deepcopy(GOOD)
            facts['service']['data'][field] = value
            with self.subTest(field=field):
                self.assertEqual(self.rows(facts)['1.5']['status'], 'FAIL')
                self.assertEqual(self.rows(facts)['3.4']['status'], 'FAIL')

    def test_systemd_identity_cannot_hide_runtime_root(self):
        facts = deepcopy(GOOD)
        facts['service']['data']['uid'] = 0
        self.assertEqual(self.rows(facts)['1.5']['status'], 'FAIL')

    def test_wrong_group_or_unit_fails_dedication(self):
        for field in ('gid', 'unit_user', 'unit_group'):
            facts = deepcopy(GOOD)
            facts['service']['data'][field] = 999 if field == 'gid' else 'other'
            self.assertEqual(self.rows(facts)['3.4']['status'], 'FAIL')

    def test_wrong_vendor_or_patch_fails(self):
        for field, value in [('version', '1.8.0_462'), ('vendor', 'other')]:
            facts = deepcopy(GOOD)
            facts['java']['data'][field] = value
            self.assertEqual(self.rows(facts)['1.2']['status'], 'FAIL')

    def test_conflicting_baseline_policy_is_rejected(self):
        for key, value, control in [('required_java_version', '17', '1.2'),
                                    ('required_cassandra_major', '5.0', '1.4')]:
            policy = deepcopy(POLICY)
            policy['platform'][key] = value
            self.assertEqual(self.rows(policy=policy)[control]['status'], 'ERROR')

    def test_unapproved_clock_source_is_fail(self):
        facts = deepcopy(GOOD)
        facts['clock']['data']['source'] = 'unapproved'
        self.assertEqual(self.rows(facts)['1.6']['status'], 'FAIL')

    def test_clock_absolute_boundary_and_review(self):
        for offset, expected in [(-100, 'PASS'), (100, 'PASS'), (-100.01, 'FAIL'), (100.01, 'FAIL'),
                                 (None, 'NEEDS_REVIEW'), ('bad', 'ERROR'), (float('nan'), 'ERROR')]:
            facts = deepcopy(GOOD)
            facts['clock']['data']['offset_ms'] = offset
            with self.subTest(offset=offset):
                self.assertEqual(self.rows(facts)['1.6']['status'], expected)

    def test_malformed_data_is_error(self):
        for section, field, value, control in [('account', 'uid', '998', '1.1'),
                                               ('service', 'active', 'true', '1.5'),
                                               ('python', 'version', 'garbage', '1.3'),
                                               ('clock', 'synchronized', None, '1.6')]:
            facts = deepcopy(GOOD)
            facts[section]['data'][field] = value
            self.assertEqual(self.rows(facts)[control]['status'], 'ERROR')

    def test_masking_structured_and_string_evidence(self):
        value = {'keystore_password': 'sensitive', 'nested': ['password=hidden token: xyz']}
        output = json.dumps(checker.redact(value))
        for secret in ('sensitive', 'hidden', 'xyz'):
            self.assertNotIn(secret, output)
        self.assertIn('***', output)


class CollectorTests(unittest.TestCase):
    def test_version_parsers(self):
        with patch.object(collector, 'command', return_value='openjdk version "1.8.0_472"\nOpenJDK Runtime Environment (Temurin)(build 1.8.0_472-b08)'):
            self.assertEqual(collector.java_facts('/opt/temurin8/bin/java')['vendor'], 'Temurin')
        with patch.object(collector, 'command', return_value='Python 3.10.12\n'):
            self.assertEqual(collector.python_facts('/usr/bin/python3')['version'], '3.10.12')
        with patch.object(collector, 'command', return_value='ReleaseVersion: 4.0.19\n'):
            self.assertEqual(collector.cassandra_facts('/opt/cassandra/bin/nodetool')['version'], '4.0.19')

    def test_unparseable_output_is_error(self):
        with patch.object(collector, 'command', return_value='unexpected secret=must-not-leak'):
            for fn in (lambda: collector.java_facts('java'), lambda: collector.python_facts('python'),
                       lambda: collector.cassandra_facts('nodetool'), collector.clock_facts):
                result = collector.probe(fn)
                self.assertFalse(result['ok'])
                self.assertNotIn('must-not-leak', json.dumps(result))

    def test_process_timeout_nonzero_and_permission_errors(self):
        for exc in [PermissionError('secret=must-not-leak'), FileNotFoundError(),
                    subprocess.TimeoutExpired(['java'], 15, stderr='secret=must-not-leak')]:
            with patch.object(collector, 'command', side_effect=exc):
                result = collector.probe(lambda: collector.java_facts('java'))
                self.assertFalse(result['ok'])
                self.assertNotIn('must-not-leak', json.dumps(result))
        with patch.object(collector.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, '', 'secret=private')):
            self.assertFalse(collector.probe(lambda: collector.command(['java']))['ok'])

    def test_chrony_signed_offset_and_unsync(self):
        output = 'Stratum : 3\nSystem time : 0.0025 seconds slow of NTP time\nLeap status : Normal\n'
        with patch.object(collector, 'command', return_value=output):
            self.assertEqual(collector.clock_facts()['offset_ms'], 2.5)
            self.assertTrue(collector.clock_facts()['synchronized'])
        with patch.object(collector, 'command', return_value=output.replace('Normal', 'Not synchronised')):
            self.assertFalse(collector.clock_facts()['synchronized'])

    def test_missing_chrony_requires_offset_review(self):
        with patch.object(collector, 'command', side_effect=[FileNotFoundError(), 'yes\n']):
            self.assertIsNone(collector.clock_facts()['offset_ms'])

    def test_unknown_account_is_observed_absence(self):
        with patch.object(collector.pwd, 'getpwnam', side_effect=KeyError):
            self.assertEqual(collector.account_facts('missing', 'missing'), {'exists': False})

    def test_runtime_java_is_selected(self):
        runtime = deepcopy(GOOD['service']['data'])
        with patch.object(collector, 'service_facts', return_value=runtime), \
             patch.object(collector, 'java_facts', return_value={}) as java, \
             patch.object(collector, 'os_facts', return_value={}), \
             patch.object(collector, 'account_facts', return_value={}), \
             patch.object(collector, 'python_facts', return_value={}), \
             patch.object(collector, 'cassandra_facts', return_value={}), \
             patch.object(collector, 'clock_facts', return_value={}):
            collector.collect({})
            java.assert_called_once_with(runtime['exe'])

    def test_service_reads_actual_proc_identity(self):
        props = 'LoadState=loaded\nActiveState=active\nUser=cassandra\nGroup=cassandra\nMainPID=1234\n'
        with patch.object(collector, 'command', return_value=props), \
             patch.object(Path, 'read_text', return_value='Uid:\t0\t998\t998\t998\nGid:\t0\t998\t998\t998\n'), \
             patch.object(Path, 'read_bytes', return_value=b'java\0org.apache.cassandra.service.CassandraDaemon\0'), \
             patch.object(collector.os, 'readlink', return_value='/opt/temurin8/bin/java'):
            facts = collector.service_facts('cassandra.service')
            self.assertEqual(facts['uid'], 998)
            self.assertTrue(facts['is_cassandra'])

    def test_malformed_systemd_output_is_error_absent_unit_is_observed(self):
        with patch.object(collector, 'command', return_value='unexpected'):
            self.assertFalse(collector.probe(lambda: collector.service_facts('cassandra.service'))['ok'])
        with patch.object(collector, 'command', return_value='LoadState=not-found\n'):
            self.assertFalse(collector.service_facts('cassandra.service')['active'])

    def test_ssh_failure_never_exposes_stderr_or_passes(self):
        for response in (subprocess.CompletedProcess([], 255, '', 'password=private'),
                         subprocess.CompletedProcess([], 0, 'not json', '')):
            with patch.object(collector.subprocess, 'run', return_value=response) as call:
                facts = collector.collect_ssh('node', {}, user='labadmin')
                self.assertTrue(all(not entry['ok'] for entry in facts.values()))
                self.assertNotIn('private', json.dumps(facts))
                argv = call.call_args.args[0]
                self.assertIn('StrictHostKeyChecking=yes', argv)
                self.assertNotIn('shell', call.call_args.kwargs)


class RendererTests(unittest.TestCase):
    def test_merge_preserves_unowned_and_does_not_alias_inputs(self):
        base = {'authenticator': 'PasswordAuthenticator', 'custom_option': True}
        updates = {'data_file_directories': ['/var/lib/cassandra/data']}
        merged = render.merge_cassandra_yaml(base, updates, 'TV1')
        merged['data_file_directories'].append('/other')
        self.assertEqual(updates['data_file_directories'], ['/var/lib/cassandra/data'])
        self.assertEqual(merged['authenticator'], base['authenticator'])
        self.assertTrue(merged['custom_option'])

    def test_cross_namespace_unknown_key_and_owner_rejected(self):
        for owner, values in [('TV1', {'authenticator': 'AllowAllAuthenticator'}),
                              ('TV2', {'audit_logging_options': {}}),
                              ('TV4', {'authenticator': 'x'}),
                              ('TV1', {'unknown': True}), ('BAD', {'cluster_name': 'x'})]:
            with self.subTest(owner=owner, values=values), self.assertRaises(PermissionError):
                render.merge_cassandra_yaml({}, values, owner)

    def test_null_and_conflicting_interface_rejected(self):
        for base, updates in [({}, {'cluster_name': None}),
                              ({'listen_address': 'localhost'}, {'listen_interface': 'eth0'})]:
            with self.assertRaises(ValueError):
                render.merge_cassandra_yaml(base, updates, 'TV1' if not base else 'TV3')

    def test_duplicate_and_unsafe_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'test.yml'
            for source in ('TV1: {}\nTV1: {}', '!!python/object/apply:os.system ["false"]',
                           'TV1: {cluster_name: a, cluster_name: b}'):
                file.write_text(source)
                with self.assertRaises((ValueError, render.yaml.YAMLError)):
                    render.load_mapping(file)

    def test_offline_cli_atomic_and_same_path_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            base, updates, out = [Path(directory) / name for name in ('base.yml', 'updates.yml', 'candidate.yml')]
            base.write_text('cluster_name: original\nauthenticator: PasswordAuthenticator\n')
            updates.write_text('TV1: {cluster_name: CISLab}\n')
            self.assertEqual(render.main(['--base', str(base), '--updates', str(updates), '--out', str(out)]), 0)
            self.assertEqual(render.load_mapping(out)['cluster_name'], 'CISLab')
            self.assertIn('original', base.read_text())
            self.assertEqual(out.stat().st_mode & 0o777, 0o600)
            updates.write_text('TV1: {authenticator: WRONG}\n')
            before = out.read_bytes()
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                render.main(['--base', str(base), '--updates', str(updates), '--out', str(out)])
            self.assertEqual(out.read_bytes(), before)
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                render.main(['--base', str(base), '--updates', str(updates), '--out', str(base)])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)

    def invoke(self, *args):
        self.stdout, self.stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return cli.main(list(args))

    def audit(self, fixture='good', *, policy='bootstrap/fixture-policy.yml', modules='platform'):
        return self.invoke('audit', '--inventory', str(ROOT / 'inventories/dev.yml'), '--limit', 'cass-dev1',
                           '--policy', str(ROOT / policy), '--fixture', str(FIXTURES / (fixture + '.json')),
                           '--modules', modules, '--out', str(self.out))

    def test_fixture_statuses_provenance_and_no_network(self):
        with patch.object(cli, 'collect_ssh', side_effect=AssertionError('must not connect')):
            for fixture, status, code in [('good', 'PASS', 0), ('bad', 'FAIL', 1), ('read_error', 'ERROR', 2)]:
                with self.subTest(fixture=fixture):
                    self.assertEqual(self.audit(fixture), code)
                    rows = cli.read_json(self.out / 'results.json')
                    self.assertTrue(all(r['status'] == status for r in rows))
                    self.assertEqual(cli.read_json(self.out / 'run.json')['source_mode'], 'fixture')
                    self.assertEqual(len({r['run_id'] for r in rows}), 1)

    def test_default_policy_review_exit_code(self):
        self.assertEqual(self.audit(policy='policies/lab.yml'), 3)

    def test_all_modules_show_real_coverage(self):
        self.assertEqual(self.audit(modules=','.join(cli.REGISTRY)), 3)
        rows = cli.read_json(self.out / 'results.json')
        self.assertEqual(len(rows), 20)
        self.assertEqual(sum(r['status'] == 'NOT_IMPLEMENTED' for r in rows), 13)

    def test_preflight_fixture_pass_fail_and_error(self):
        for fixture, code in [('good', 0), ('bad', 1), ('read_error', 2)]:
            self.assertEqual(self.invoke('preflight', '--inventory', str(ROOT / 'inventories/dev.yml'),
                                        '--limit', 'cass-dev1', '--policy', str(ROOT / 'bootstrap/fixture-policy.yml'),
                                        '--fixture', str(FIXTURES / (fixture + '.json'))), code)
            self.assertEqual(json.loads(self.stdout.getvalue())['ready'], code == 0)

    def test_missing_fixture_does_not_fallback_to_ssh(self):
        with patch.object(cli, 'collect_ssh', side_effect=AssertionError('network forbidden')):
            self.assertEqual(self.invoke('audit', '--fixture', '/nonexistent/fixture.json'), 2)

    def test_missing_selected_fixture_node_is_error(self):
        self.assertEqual(self.invoke('audit', '--fixture', str(FIXTURES / 'good.json')), 2)

    def test_live_ssh_failure_results_are_error(self):
        errors = {name: {'ok': False, 'error': 'SSH_FAILED'} for name in GOOD}
        with patch.object(cli, 'collect_ssh', return_value=errors):
            self.assertEqual(self.invoke('audit', '--inventory', str(ROOT / 'inventories/dev.yml'),
                                        '--limit', 'cass-dev1', '--modules', 'platform', '--out', str(self.out)), 2)
        self.assertTrue(all(r['status'] == 'ERROR' for r in cli.read_json(self.out / 'results.json')))
        self.assertEqual(cli.read_json(self.out / 'run.json')['source_mode'], 'ssh')

    def test_module_stub_crash_and_contract_failure(self):
        target = 'checks.auth.checker.run_all_checks'
        for value, expected in [([], 'NOT_IMPLEMENTED'), ([{}], 'ERROR')]:
            with patch(target, return_value=value):
                rows = cli.dispatch('auth', 'node', POLICY, {}, 'run', 'policy', False)
                self.assertTrue(all(r['status'] == expected for r in rows))
        for exception in (RuntimeError, AttributeError, ImportError):
            with patch(target, side_effect=exception('password=hidden')):
                rows = cli.dispatch('auth', 'node', POLICY, {}, 'run', 'policy', False)
                self.assertTrue(all(r['status'] == 'ERROR' for r in rows))
                self.assertNotIn('hidden', json.dumps(rows))
        with patch.object(cli.importlib, 'import_module', side_effect=ModuleNotFoundError(name='driver_missing')):
            rows = cli.dispatch('auth', 'node', POLICY, {}, 'run', 'policy', False)
            self.assertTrue(all(r['status'] == 'ERROR' for r in rows))
        with patch.object(cli.importlib, 'import_module', side_effect=ModuleNotFoundError(name='checks.auth.checker')):
            rows = cli.dispatch('auth', 'node', POLICY, {}, 'run', 'policy', False)
            self.assertTrue(all(r['status'] == 'NOT_IMPLEMENTED' for r in rows))

    def test_plan_only_fail_and_provenance_hash(self):
        self.audit('bad')
        plan = self.out / 'plan.json'
        self.assertEqual(self.invoke('plan', '--input', str(self.out / 'results.json'), '--out', str(plan)), 0)
        document = cli.read_json(plan)
        self.assertEqual(document['source_mode'], 'fixture')
        self.assertEqual(len(document['actions']), 7)
        self.assertTrue(all(not a['executable'] for a in document['actions']))
        (self.out / 'results.json').write_text((self.out / 'results.json').read_text() + '\n')
        self.assertEqual(self.invoke('plan', '--input', str(self.out / 'results.json'), '--out', str(plan)), 2)

    def test_read_errors_do_not_become_plan_actions(self):
        self.audit('read_error')
        plan = self.out / 'plan.json'
        self.assertEqual(self.invoke('plan', '--input', str(self.out / 'results.json'), '--out', str(plan)), 0)
        self.assertEqual(cli.read_json(plan)['actions'], [])
        self.assertEqual(cli.read_json(plan)['blocked_results'], 7)

    def test_apply_rejects_fixture_even_with_matching_approval(self):
        self.audit('bad')
        plan, approval = self.out / 'plan.json', self.out / 'approval.json'
        self.invoke('plan', '--input', str(self.out / 'results.json'), '--out', str(plan))
        document = cli.read_json(plan)
        now = datetime.now(timezone.utc)
        cli.dump(approval, {'approval_id': 'fixture-approval', 'plan_id': document['plan_id'], 'target_environment': 'dev',
                            'plan_hash': hashlib.sha256(plan.read_bytes()).hexdigest(), 'approved_by': 'reviewer',
                            'approved_at': now.isoformat(),
                            'expires_at': (now + timedelta(minutes=5)).isoformat(),
                            'approved_controls': sorted({a['control_id'] for a in document['actions']}),
                            'approved_targets': sorted({a['target'] for a in document['actions']}),
                            'approved_action_ids': [a['action_id'] for a in document['actions']],
                            'test_only': False, 'reason': 'Unit test; no backend or node execution'})
        with self.assertRaisesRegex(ValueError, 'SSH audit'):
            cli.apply(type('Args', (), {'plan': str(plan), 'approval': str(approval)})())
        document['source_mode'] = 'ssh'
        cli.dump(plan, document)
        self.assertEqual(self.invoke('apply', '--plan', str(plan), '--approval', str(approval)), 2)
        approved = cli.read_json(approval)
        approved['plan_hash'] = hashlib.sha256(plan.read_bytes()).hexdigest()
        cli.dump(approval, approved)
        with self.assertRaisesRegex(ValueError, 'No apply backend'):
            cli.apply(type('Args', (), {'plan': str(plan), 'approval': str(approval)})())
        approved['expires_at'] = (now - timedelta(seconds=1)).isoformat()
        cli.dump(approval, approved)
        self.assertEqual(self.invoke('apply', '--plan', str(plan), '--approval', str(approval)), 2)

    def test_report_stub_does_not_claim_success(self):
        self.audit()
        self.assertEqual(self.invoke('report', '--input', str(self.out / 'results.json'),
                                     '--out', str(self.out / 'report.html')), 2)
        self.assertFalse((self.out / 'report.html').exists())

    def test_inventory_unsafe_host_unknown_limit_and_duplicates(self):
        for name in ('-oProxyCommand=bad', 'node;id', '$(id)'):
            file = self.out / 'inventory.yml'
            file.write_text('all:\n  vars: {ansible_user: labadmin}\n  children:\n    cassandra_nodes:\n      hosts:\n        node:\n          ansible_host: ' + name + '\n')
            with self.assertRaises(ValueError):
                cli.inventory_nodes(file)
        with self.assertRaises(ValueError):
            cli.inventory_nodes(ROOT / 'inventories/dev.yml', 'not-in-inventory')

    def test_result_schema_rejects_invalid_duplicate_and_empty(self):
        rows = checker.run_all_checks('node', POLICY, facts=GOOD)
        for bad in ([], rows + rows, [{**rows[0], 'status': 'OK'}], [{**rows[0], 'timestamp_utc': 'wrong'}]):
            with self.assertRaises((ValueError, cli.jsonschema.ValidationError)):
                cli.validate_results(bad)

    def test_json_duplicate_keys_and_nonfinite_rejected(self):
        file = self.out / 'test.json'
        for source in ('{"a": 1, "a": 2}', '{"a": NaN}'):
            file.write_text(source)
            with self.assertRaises(ValueError):
                cli.read_json(file)


if __name__ == '__main__':
    unittest.main()
