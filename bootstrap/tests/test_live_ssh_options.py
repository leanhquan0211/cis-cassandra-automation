"""Credential and host-key boundaries needed by a real password-protected VM."""
import contextlib
import io
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from checks.platform import collector
from cis_lab import cli

ROOT = Path(__file__).resolve().parents[2]


class LiveSSHOptionsTests(unittest.TestCase):
    def test_password_is_stdin_only_and_not_python_source(self):
        password = "unit-test-secret-DO-NOT-LOG"
        completed = subprocess.CompletedProcess([], 0, '{}', '')
        with patch.object(collector.subprocess, 'run', return_value=completed) as command:
            collector.collect_ssh('node', {}, user='labadmin', become=True,
                                  become_password=password, ssh_config='/tmp/config with spaces')
        argv = command.call_args.args[0]
        self.assertNotIn(password, repr(argv))
        self.assertEqual(command.call_args.kwargs['input'], password + '\n')
        self.assertEqual(argv[argv.index('-F') + 1], '/tmp/config with spaces')
        self.assertIn('StrictHostKeyChecking=yes', argv)
        remote = shlex.split(argv[-1])
        self.assertEqual(remote[:6], ['sudo', '-S', '-p', '', '--', 'python3'])
        self.assertEqual(remote[6], '-c')
        compile(remote[7], '<remote-collector>', 'exec')
        self.assertNotIn(password, remote[7])

    def test_bad_sudo_input_cannot_run_an_unprivileged_fallback(self):
        for become, password in ((False, 'secret'), (True, ''), (True, 'two\nlines'), (True, 'nul\0')):
            with self.subTest(become=become, password_length=len(password)):
                with patch.object(collector.subprocess, 'run') as command:
                    facts = collector.collect_ssh('node', {}, user='labadmin', become=become,
                                                  become_password=password)
                command.assert_not_called()
                self.assertTrue(all(not entry['ok'] for entry in facts.values()))

    def test_wrong_password_remains_error_without_secret_evidence(self):
        response = subprocess.CompletedProcess([], 1, '', 'password=unit-test-secret')
        with patch.object(collector.subprocess, 'run', return_value=response):
            facts = collector.collect_ssh('node', {}, user='labadmin', become=True,
                                          become_password='unit-test-secret')
        self.assertNotIn('unit-test-secret', json.dumps(facts))
        self.assertTrue(all(not entry['ok'] for entry in facts.values()))

    def test_noninteractive_sudo_contract_preserved(self):
        with patch.object(collector.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{}', '')) as command:
            collector.collect_ssh('node', {}, user='labadmin', become=True)
        self.assertTrue(command.call_args.args[0][-1].startswith('sudo -n -- python3 - '))
        self.assertIn('def collect(', command.call_args.kwargs['input'])

    def invoke(self, *arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return cli.main(list(arguments))

    def test_fixture_or_missing_become_never_prompts(self):
        for flags in (['--fixture', str(ROOT/'checks/platform/fixtures/good.json'), '--become'], []):
            with patch.object(cli.getpass, 'getpass') as prompt, patch.object(cli, 'collect_ssh') as ssh:
                code = self.invoke('audit', '--inventory', str(ROOT/'inventories/dev.yml'),
                                   '--limit', 'cass-dev1', '--modules', 'platform', '--ask-become-pass',
                                   '--policy', str(ROOT/'bootstrap/fixture-policy.yml'), *flags)
                self.assertEqual(code, 2)
                prompt.assert_not_called()
                ssh.assert_not_called()

    def test_live_prompt_propagates_secret_without_persisting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            config = directory/'ssh-config'
            config.write_text('Host cass-dev1\n HostName 192.0.2.1\n')
            facts = json.loads((ROOT/'checks/platform/fixtures/good.json').read_text())['nodes']['cass-dev1']
            with patch.object(cli.getpass, 'getpass', return_value='unit-test-secret') as prompt:
                with patch.object(cli, 'collect_ssh', return_value=facts) as ssh:
                    code = self.invoke('audit', '--inventory', str(ROOT/'inventories/dev.yml'),
                                       '--limit', 'cass-dev1', '--modules', 'platform', '--become',
                                       '--ask-become-pass', '--ssh-config', str(config),
                                       '--policy', str(ROOT/'bootstrap/fixture-policy.yml'),
                                       '--out', str(directory/'audit'))
            self.assertEqual(code, 0)
            prompt.assert_called_once()
            self.assertEqual(ssh.call_args.kwargs['become_password'], 'unit-test-secret')
            self.assertEqual(ssh.call_args.kwargs['ssh_config'], str(config))
            for filename in ('results.json', 'run.json'):
                self.assertNotIn('unit-test-secret', (directory/'audit'/filename).read_text())
            self.assertEqual(json.loads((directory/'audit/run.json').read_text())['source_mode'], 'ssh')

    def test_invalid_ssh_config_rejected_before_prompt_or_network(self):
        with patch.object(cli.getpass, 'getpass') as prompt, patch.object(cli, 'collect_ssh') as ssh:
            code = self.invoke('preflight', '--ssh-config', '/does-not-exist', '--become', '--ask-become-pass')
        self.assertEqual(code, 2)
        prompt.assert_not_called()
        ssh.assert_not_called()

    def test_password_prompt_cannot_fall_back_to_echoed_input(self):
        with patch.object(cli.getpass, 'getpass', side_effect=cli.getpass.GetPassWarning('no terminal')):
            with patch.object(cli, 'collect_ssh') as ssh:
                code = self.invoke('audit', '--inventory', str(ROOT/'inventories/dev.yml'),
                                   '--limit', 'cass-dev1', '--modules', 'platform', '--become',
                                   '--ask-become-pass', '--policy', str(ROOT/'bootstrap/fixture-policy.yml'))
        self.assertEqual(code, 2)
        ssh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
