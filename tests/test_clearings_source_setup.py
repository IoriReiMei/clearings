# SPDX-License-Identifier: MIT
# Copyright (c) 2026 The Hermit. See LICENSE for the full MIT notice.
"""Portable launch and fork checks; fictional trees and intercepted network only."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import clearings_local as local


class SourceSetupChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='clearings-source-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'A source copy with spaces'
        (self.folder / 'tools').mkdir(parents=True)
        for name in ('clearings_local.py', 'clearings_commit.py', 'clearings_tray.py'):
            shutil.copy2(ROOT / 'tools' / name, self.folder / 'tools' / name)
        for name in ('clearings.py', 'clearings.json', 'Start_Clearings.sh'):
            shutil.copy2(ROOT / name, self.folder / name)
        app = ROOT / ('LC_CHECKLIST.html' if (ROOT / 'LC_CHECKLIST.html').exists() else 'index.html')
        shutil.copy2(app, self.folder / 'index.html')

    def config(self, repository):
        (self.folder / 'clearings.json').write_text(json.dumps(
            {'schemaVersion': 1, 'updateRepository': repository}), encoding='utf-8')

    def command(self, *args):
        return subprocess.run([sys.executable, '-B', str(self.folder / 'clearings.py'), *args],
                              cwd=self.folder.parent, capture_output=True, text=True, timeout=20)

    def test_clean_source_check_and_version_do_not_create_workspace(self):
        before = {str(p.relative_to(self.folder)) for p in self.folder.rglob('*')}
        result = self.command('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('18765', result.stdout)
        self.assertIn('IoriReiMei/clearings', result.stdout)
        version = self.command('--version')
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertEqual(version.stdout.strip(), 'Clearings ' + local.VERSION)
        self.assertEqual(before, {str(p.relative_to(self.folder)) for p in self.folder.rglob('*')})

    def test_working_layout_keeps_its_existing_origin(self):
        (self.folder / 'index.html').rename(self.folder / 'LC_CHECKLIST.html')
        result = self.command('--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('8765', result.stdout)

    def test_incomplete_source_and_bad_configuration_have_useful_errors(self):
        (self.folder / 'tools/clearings_tray.py').unlink()
        result = self.command('--check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('Extract the complete source ZIP', result.stderr)
        shutil.copy2(ROOT / 'tools/clearings_tray.py', self.folder / 'tools/clearings_tray.py')
        (self.folder / 'clearings.json').write_text('{broken', encoding='utf-8')
        result = self.command('--check')
        self.assertEqual(result.returncode, 1)
        self.assertIn('clearings.json', result.stderr)
        self.assertNotIn('Traceback', result.stderr)

    def test_fork_and_disabled_configuration(self):
        for repository in ('Example-Owner/my_clearings', None):
            self.config(repository)
            self.assertEqual(local.read_release_config(self.folder)['updateRepository'], repository)
            result = self.command('--check')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(repository or 'disabled', result.stdout)

    def test_invalid_sources_never_contact_any_release_feed(self):
        values = ['https://github.com/owner/repo', 'owner/repo/extra', 'owner/..',
                  'owner/repo?token=secret', 'a@b/repo', '', 12, True]
        for repository in values:
            with self.subTest(repository=repository):
                self.config(repository)
                with patch.object(local, 'ROOT', self.folder), patch.object(local.urllib.request.OpenerDirector, 'open') as opened:
                    self.assertEqual(local.AppUpdateCheck().check()['status'], 'configuration-error')
                    opened.assert_not_called()
        (self.folder / 'clearings.json').unlink()
        with patch.object(local, 'ROOT', self.folder), patch.object(local.urllib.request.OpenerDirector, 'open') as opened:
            self.assertEqual(local.AppUpdateCheck().check()['status'], 'configuration-error')
            opened.assert_not_called()
        for broken in (b'{invalid', b'[' * 2000 + b']' * 2000, b'x' * 8193,
                       b'{"schemaVersion":true,"updateRepository":null}'):
            (self.folder / 'clearings.json').write_bytes(broken)
            with patch.object(local, 'ROOT', self.folder), patch.object(local.urllib.request.OpenerDirector, 'open') as opened:
                self.assertEqual(local.AppUpdateCheck().check()['status'], 'configuration-error')
                opened.assert_not_called()

    def test_fork_changes_clear_cached_upstream_result_and_null_disables_network(self):
        checker = local.AppUpdateCheck()
        def reply(request, **kwargs):
            stream = io.BytesIO(b'{"tag_name":"v0.4.8","draft":false,"prerelease":false}')
            stream.status = 200
            stream.geturl = lambda: request.full_url
            return stream
        with patch.object(local, 'ROOT', self.folder), patch.object(local.urllib.request.OpenerDirector, 'open', side_effect=reply) as opened:
            original = checker.check()
            self.config('Example-Owner/custom-clearings')
            fork = checker.check()
            self.assertEqual(opened.call_count, 2)
            self.assertNotEqual(fork['pageUrl'], original['pageUrl'])
            self.assertEqual(opened.call_args.args[0].full_url, 'https://api.github.com/repos/Example-Owner/custom-clearings/releases/latest')
            self.assertEqual(fork['repository'], 'Example-Owner/custom-clearings')
            self.assertEqual(checker.check(), fork)
            self.assertEqual(opened.call_count, 2)
            self.config(None)
            self.assertEqual(checker.check()['status'], 'disabled')
            self.assertEqual(opened.call_count, 2)

    def test_configuration_is_embedded_without_executable_markup(self):
        html = (self.folder / 'index.html').read_text(encoding='utf-8')
        self.config('Example-Owner/custom-clearings')
        embedded = local.embed_release_config(html, local.read_release_config(self.folder))
        self.assertIn('"updateRepository":"Example-Owner/custom-clearings"', embedded)
        hostile = local.embed_release_config(html, {'error': '</script><script>alert(1)</script>'})
        self.assertNotIn('"error":"</script>', hostile)

    def test_platform_wrapper_passes_check_from_another_directory(self):
        env = {**os.environ, 'CLEARINGS_PYTHON': sys.executable}
        if os.name == 'nt':
            wrapper = ROOT / ('docs/GITHUB_START_CLEARINGS.cmd' if (ROOT / 'docs/GITHUB_START_CLEARINGS.cmd').exists() else 'Start_Clearings.cmd')
            shutil.copy2(wrapper, self.folder / 'Start_Clearings.cmd')
            command = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(self.folder / 'Start_Clearings.cmd'), '--check']
        else:
            command = ['sh', str(self.folder / 'Start_Clearings.sh'), '--check']
        result = subprocess.run(command, cwd=self.folder.parent, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn('source is ready', result.stdout)


if __name__ == '__main__':
    unittest.main()
