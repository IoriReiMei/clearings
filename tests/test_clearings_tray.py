# SPDX-License-Identifier: MIT
# MIT License
#
# Copyright (c) 2026 The Hermit
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Tray behavior uses fakes; opt-in native checks use only a temporary icon."""
import ctypes
from ctypes import wintypes as w
import os
import threading
import unittest
from unittest.mock import Mock,patch
import test_clearings_local as fixtures
from clearings_tray import WindowsTray


class TrayCommands(unittest.TestCase):
    def tray(self):
        tray=object.__new__(WindowsTray)
        tray.hwnd=None;tray.user=Mock();tray.open_app=Mock();tray.stop_helper=Mock();tray._stopping=False
        return tray

    def test_open_dispatches_without_stopping(self):
        tray=self.tray();opened=threading.Event();tray.open_app=opened.set
        tray._command(tray.OPEN)
        self.assertTrue(opened.wait(1));tray.stop_helper.assert_not_called()

    def test_stop_cancel_keeps_helper_running(self):
        tray=self.tray();tray.user.MessageBoxW.return_value=2
        tray._command(tray.STOP)
        tray.stop_helper.assert_not_called();self.assertFalse(tray._stopping)
        self.assertIn('Save any edits',tray.user.MessageBoxW.call_args.args[1])

    def test_confirmed_stop_runs_once(self):
        tray=self.tray();tray.user.MessageBoxW.return_value=1
        stopped=threading.Event();tray.stop_helper=stopped.set
        tray._command(tray.STOP);self.assertTrue(stopped.wait(1))
        tray._command(tray.STOP);tray.user.MessageBoxW.assert_called_once()


class TrayLifetime(unittest.TestCase):
    setUp=fixtures.BridgeChecks.setUp
    tearDown=fixtures.BridgeChecks.tearDown

    def test_server_starts_and_removes_its_tray(self):
        local=fixtures.local;server=Mock();tray=Mock()
        with patch.object(local,'_dpapi',side_effect=lambda data,protect:data[::-1]),patch.object(local,'WINDOWS_TRAY',True),patch.object(local,'LocalServer',return_value=server),patch.object(local,'WindowsTray',return_value=tray):
            tray.start.return_value=tray
            local.run_server(self.bridge,12345,False)
        tray.start.assert_called_once();server.serve_forever.assert_called_once()
        server.server_close.assert_called_once();tray.close.assert_called_once()

    def test_failed_tray_does_not_leave_server_or_publish_session(self):
        local=fixtures.local;server=Mock();tray=Mock();tray.start.side_effect=RuntimeError('tray unavailable')
        with patch.object(local,'_dpapi',side_effect=lambda data,protect:data[::-1]),patch.object(local,'WINDOWS_TRAY',True),patch.object(local,'LocalServer',return_value=server),patch.object(local,'WindowsTray',return_value=tray):
            with self.assertRaisesRegex(RuntimeError,'tray unavailable'):local.run_server(self.bridge,12345,False)
        server.serve_forever.assert_not_called();server.server_close.assert_called_once()
        self.assertFalse((self.bridge.root/'session.json').exists())

    def test_headless_opt_out_creates_no_tray(self):
        local=fixtures.local;server=Mock()
        with patch.object(local,'_dpapi',side_effect=lambda data,protect:data[::-1]),patch.object(local,'LocalServer',return_value=server),patch.object(local,'WindowsTray') as tray:
            local.run_server(self.bridge,12345,False,show_tray=False)
        tray.assert_not_called();server.server_close.assert_called_once()


@unittest.skipUnless(os.name=='nt' and os.environ.get('CLEARINGS_NATIVE_TRAY_TEST')=='1','opt-in Windows desktop fixture')
class NativeTray(unittest.TestCase):
    def test_shell_registration_explorer_restore_and_cleanup(self):
        import uuid,time
        tray=WindowsTray(title='Clearings tray check',address='test fixture only',identity='fixture-'+uuid.uuid4().hex,open_app=lambda:None,stop_helper=lambda:None)
        tray.start()
        class Identifier(ctypes.Structure):
            _fields_=[('cbSize',w.DWORD),('hWnd',w.HWND),('uID',w.UINT),('guidItem',type(tray.guid))]
        identifier=Identifier();identifier.cbSize=ctypes.sizeof(identifier);identifier.guidItem=tray.guid
        function=tray.shell.Shell_NotifyIconGetRect;function.argtypes=[ctypes.POINTER(Identifier),ctypes.POINTER(w.RECT)];function.restype=ctypes.c_long
        rect=w.RECT()
        try:
            self.assertEqual(function(ctypes.byref(identifier),ctypes.byref(rect)),0)
            self.assertGreater(rect.right,rect.left)
            # Simulate Explorer removing this fixture icon, not an Explorer restart.
            self.assertTrue(tray._notify(2));tray.registered=False
            tray.user.PostMessageW(tray.hwnd,tray.taskbar_created,0,0)
            deadline=time.monotonic()+3
            while not tray.registered and not tray.error and time.monotonic()<deadline:time.sleep(.02)
            self.assertIsNone(tray.error);self.assertTrue(tray.registered)
            self.assertEqual(function(ctypes.byref(identifier),ctypes.byref(rect)),0)
        finally:tray.close()
        self.assertFalse(tray.thread.is_alive());self.assertFalse(tray.registered)
        self.assertNotEqual(function(ctypes.byref(identifier),ctypes.byref(rect)),0)


if __name__=='__main__':unittest.main()
