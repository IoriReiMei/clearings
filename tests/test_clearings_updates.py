# SPDX-License-Identifier: MIT
"""Public update checks use fake network responses and disposable loopback state."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import clearings_local as local


class Reply(io.BytesIO):
    status = 200
    def geturl(self):
        return local.AppUpdateCheck.URL


class UpdateChecks(unittest.TestCase):
    def fake(self, release):
        return patch.object(local.urllib.request.OpenerDirector, 'open',
                            return_value=Reply(json.dumps(release).encode()))

    def release(self, tag='v0.4.8', **extras):
        return {'tag_name': tag, 'draft': False, 'prerelease': False, **extras}

    def test_new_release_is_metadata_only_and_cached(self):
        checker = local.AppUpdateCheck()
        with self.fake(self.release(body='<script>bad</script>', html_url='https://unrelated.invalid/')) as opened:
            result = checker.check()
            self.assertEqual(result['status'], 'available')
            self.assertTrue(result['requiresRestart'])
            self.assertEqual(result['pageUrl'], checker.PAGE + '/tag/v0.4.8')
            self.assertEqual(checker.check(), result)
            self.assertEqual(opened.call_count, 1)
            request = opened.call_args.args[0]
            self.assertEqual(request.full_url, checker.URL)
            self.assertIsNone(request.data)
            self.assertNotIn('Authorization', request.headers)
            self.assertNotIn('X-clearings-token', request.headers)
            self.assertNotIn('body', result)

    def test_versions_compare_numerically_and_never_downgrade(self):
        for tag, status in [('v0.4.7', 'current'), ('0.4.6', 'current'), ('v0.4.10', 'available')]:
            with self.subTest(tag=tag), self.fake(self.release(tag)):
                self.assertEqual(local.AppUpdateCheck().check()['status'], status)

    def test_invalid_or_preview_releases_are_not_offered(self):
        for payload in [self.release('v0.5.0-beta'), self.release('v0.5.0/../../bad'), self.release(draft=True), self.release(prerelease=True), []]:
            with self.subTest(payload=payload), self.fake(payload):
                self.assertEqual(local.AppUpdateCheck().check()['status'], 'unavailable')

    def test_network_failure_does_not_install_or_interrupt(self):
        with patch.object(local.urllib.request.OpenerDirector, 'open', side_effect=TimeoutError):
            self.assertEqual(local.AppUpdateCheck().check()['status'], 'unavailable')

    def test_size_and_redirect_limits(self):
        with patch.object(local.urllib.request.OpenerDirector, 'open', return_value=Reply(b'x' * (local.AppUpdateCheck.LIMIT + 1))):
            self.assertEqual(local.AppUpdateCheck().check()['status'], 'unavailable')
        with self.assertRaises(ValueError):
            local.NoUpdateRedirects().redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/private')

    def test_http_404_and_rate_limit_are_quiet(self):
        for status, expected in [(404, 'no-release'), (403, 'unavailable'), (429, 'unavailable')]:
            with patch.object(local.urllib.request.OpenerDirector, 'open', side_effect=urllib.error.HTTPError(local.AppUpdateCheck.URL, status, '', {}, None)):
                self.assertEqual(local.AppUpdateCheck().check()['status'], expected)

    def test_parallel_check_does_not_wait_on_network(self):
        checker=local.AppUpdateCheck()
        with checker.lock:
            self.assertEqual(checker.check()['status'], 'checking')

    def test_http_endpoint_authenticates_before_any_outbound_request(self):
        with tempfile.TemporaryDirectory() as folder:
            bridge = local.Bridge(Path(folder)/'config')
            server = local.LocalServer(('127.0.0.1', 0), local.handler_for(bridge, 'fixture-token', 0))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            address = f'http://127.0.0.1:{server.server_port}/api/app-updates'
            try:
                with patch.object(local.AppUpdateCheck, 'check', return_value={'status':'current'}) as check:
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        urllib.request.urlopen(address)
                    self.assertEqual(caught.exception.code,403)
                    check.assert_not_called()
                    with urllib.request.urlopen(urllib.request.Request(address, headers={'X-Clearings-Token':'fixture-token'})) as response:
                        self.assertEqual(json.load(response), {'status':'current'})
                    self.assertEqual(check.call_count,1)
            finally:
                server.shutdown();server.server_close();worker.join(3)


if __name__ == '__main__':
    unittest.main()
