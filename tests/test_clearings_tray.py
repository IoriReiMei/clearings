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
import base64
import ctypes
from ctypes import wintypes as w
import hashlib
import io
import os
from pathlib import Path
import re
import struct
import sys
import threading
import tempfile
import unittest
from unittest.mock import Mock,patch
import test_clearings_local as fixtures
from clearings_tray import WindowsTray,WindowsStartup,icon_path


class TrayArtwork(unittest.TestCase):
    def test_source_artwork_matches_browser_brand_and_has_windows_sizes(self):
        root=Path(__file__).resolve().parents[1]
        png=(root/'assets'/'Clearings.png').read_bytes()
        self.assertEqual(hashlib.sha256(png).hexdigest(),
                         '721d33078041e4a1852525dd0c336fbe6f7d2d0c50968fc27072e24d12d68824')
        html=(root/'index.html' if (root/'index.html').exists() else root/'LC_CHECKLIST.html').read_text(encoding='utf-8')
        embedded=re.search(r'data:image/png;base64,([A-Za-z0-9+/=]+)',html)
        self.assertIsNotNone(embedded)
        self.assertEqual(base64.b64decode(embedded.group(1)),png)
        ico=icon_path().read_bytes()
        reserved,kind,count=struct.unpack_from('<HHH',ico)
        self.assertEqual((reserved,kind,count),(0,1,9))
        sizes=set()
        for index in range(count):
            width,height,_,_,_,_,length,offset=struct.unpack_from('<BBBBHHII',ico,6+16*index)
            size=(width or 256,height or 256)
            self.assertEqual(size[0],size[1])
            self.assertGreater(length,8)
            self.assertLessEqual(offset+length,len(ico))
            image=ico[offset:offset+length]
            self.assertTrue(image.startswith(b'\x89PNG\r\n\x1a\n') or image.startswith(b'\x28\x00\x00\x00'))
            sizes.add(size[0])
        self.assertEqual(sizes,{16,20,24,32,40,48,64,128,256})

    def test_packaged_icon_uses_bundle_resource_directory(self):
        with patch.object(sys,'_MEIPASS',str(Path('packaged-runtime')),create=True):
            self.assertEqual(icon_path(),Path('packaged-runtime')/'assets'/'Clearings.ico')


class TrayCommands(unittest.TestCase):
    def tray(self):
        tray=object.__new__(WindowsTray)
        tray.hwnd=None;tray.user=Mock();tray.open_app=Mock();tray.stop_helper=Mock();tray._stopping=False;tray.startup=None
        tray.title='Clearings fixture';tray.address='fixture only'
        return tray

    def test_double_click_opens_once_without_first_click_menu(self):
        tray=self.tray();tray.taskbar_created=0xc000;tray._command=Mock();tray._menu=Mock()
        for event in (0x400,0x203,0x400):
            tray._window_proc(None,tray.CALLBACK,0,(1<<16)|event)
        tray._command.assert_called_once_with(tray.OPEN)
        tray._menu.assert_not_called();tray.stop_helper.assert_not_called()

    def test_keyboard_opens_and_right_click_keeps_menu(self):
        tray=self.tray();tray.taskbar_created=0xc000;tray._command=Mock();tray._menu=Mock()
        tray._window_proc(None,tray.CALLBACK,0,(1<<16)|0x401)
        tray._command.assert_called_once_with(tray.OPEN)
        tray._window_proc(None,tray.CALLBACK,0,(1<<16)|0x7b)
        tray._menu.assert_called_once();tray.stop_helper.assert_not_called()

    def test_startup_toggle_and_failure_never_stop_helper(self):
        tray=self.tray();tray.startup=Mock()
        tray.startup.status.return_value={'enabled':False}
        tray._command(tray.STARTUP)
        tray.startup.set_enabled.assert_called_once_with(True)
        tray.startup.status.return_value={'enabled':True}
        tray.startup.set_enabled.side_effect=PermissionError('Windows refused the startup change')
        tray._command(tray.STARTUP)
        self.assertIn('Windows refused',tray.user.MessageBoxW.call_args.args[1])
        tray.stop_helper.assert_not_called()

    def test_startup_menu_reflects_registration_and_read_errors(self):
        tray=self.tray();tray.startup=Mock();tray._notify=Mock();tray._command=Mock()
        tray.user.CreatePopupMenu.return_value=1;tray.user.TrackPopupMenu.return_value=0
        tray.startup.status.return_value={'supported':True,'enabled':True,'conflict':False,'reason':None}
        tray._menu()
        self.assertIn((1,0x8,tray.STARTUP,'Start helper with Windows'),
                      [call.args for call in tray.user.AppendMenuW.call_args_list])
        tray.user.AppendMenuW.reset_mock()
        tray.startup.status.side_effect=PermissionError('blocked')
        tray._menu()
        self.assertIn((1,0x2,tray.STARTUP,'Windows startup setting unavailable'),
                      [call.args for call in tray.user.AppendMenuW.call_args_list])
        tray.stop_helper.assert_not_called()

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

    def test_failed_backup_keeps_tray_available_and_explains(self):
        tray=self.tray();tray._stopping=True;tray.stop_helper.return_value=False
        tray._stop_with_feedback()
        self.assertFalse(tray._stopping)
        self.assertIn('backup could not finish',tray.user.MessageBoxW.call_args.args[1])


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


class FakeRegistry:
    """The tests cannot reach the real registry, even when running on Windows."""
    HKEY_CURRENT_USER=1
    KEY_QUERY_VALUE=1
    KEY_SET_VALUE=2
    REG_SZ=1

    def __init__(self):
        self.values={};self.exists=False;self.calls=[]

    def __enter__(self):return self
    def __exit__(self,*args):return False

    def OpenKey(self,hive,path,reserved,access):
        assert hive==self.HKEY_CURRENT_USER and path==WindowsStartup.RUN_KEY
        self.calls.append(('open',path,access))
        if not self.exists:raise FileNotFoundError()
        return self

    def CreateKeyEx(self,hive,path,reserved,access):
        assert hive==self.HKEY_CURRENT_USER and path==WindowsStartup.RUN_KEY
        self.calls.append(('create',path,access));self.exists=True
        return self

    def QueryValueEx(self,key,name):
        if name not in self.values:raise FileNotFoundError()
        return self.values[name]

    def SetValueEx(self,key,name,reserved,kind,command):
        self.calls.append(('set',name));self.values[name]=(command,kind)

    def DeleteValue(self,key,name):
        self.calls.append(('delete',name));del self.values[name]


class StartupRegistration(unittest.TestCase):
    def setUp(self):
        self.registry=FakeRegistry()
        self.registration=WindowsStartup(name='Clearings fixture',
            command='"C:\\Fictional folder\\Clearings.exe" serve --no-browser',registry=self.registry)

    def test_opt_in_toggle_preserves_other_apps_and_never_writes_on_read(self):
        self.assertFalse(self.registration.status()['enabled'])
        self.assertFalse(self.registry.exists)
        self.registry.values['Another app']=('unrelated',1)
        self.assertTrue(self.registration.set_enabled(True)['enabled'])
        self.assertEqual(self.registry.values['Clearings fixture'],(self.registration.command,1))
        self.assertIn('--no-browser',self.registration.command)
        self.assertFalse(self.registration.set_enabled(False)['enabled'])
        self.assertEqual(self.registry.values,{'Another app':('unrelated',1)})

    def test_disabling_absent_registration_creates_nothing(self):
        self.registration.set_enabled(False)
        self.assertFalse(self.registry.exists)
        self.assertFalse(any(call[0] in ('create','set','delete') for call in self.registry.calls))

    def test_foreign_command_and_wrong_type_are_never_replaced_or_removed(self):
        self.registry.exists=True
        for value in (('some other command',1),(self.registration.command,2)):
            self.registry.values['Clearings fixture']=value
            self.assertTrue(self.registration.status()['conflict'])
            for enabled in (True,False):
                with self.assertRaisesRegex(ValueError,'different Clearings copy'):
                    self.registration.set_enabled(enabled)
            self.registration.remove_if_owned()
            self.assertEqual(self.registry.values['Clearings fixture'],value)

    def test_uninstall_removes_exact_owned_entry_only(self):
        self.registration.set_enabled(True)
        self.registry.values['Clearings working']=('another edition',1)
        self.registration.remove_if_owned()
        self.assertEqual(self.registry.values,{'Clearings working':('another edition',1)})

    def test_long_command_missing_launcher_and_nonboolean_are_refused(self):
        too_long=WindowsStartup(name='Long fixture',command='x'*261,registry=self.registry)
        with self.assertRaisesRegex(ValueError,'too long'):too_long.set_enabled(True)
        with tempfile.TemporaryDirectory() as folder:
            missing=WindowsStartup(name='Missing fixture',command='fictional',
                required_files=[Path(folder)/'absent.exe'],registry=self.registry)
            with self.assertRaisesRegex(ValueError,'missing'):missing.set_enabled(True)
        with self.assertRaisesRegex(ValueError,'whether'):self.registration.set_enabled('yes')
        self.assertFalse(self.registry.exists)

    def test_missing_launcher_does_not_prevent_disabling_owned_entry(self):
        self.registration.set_enabled(True)
        self.registration.required_files=(Path('does-not-exist-startup-fixture.exe'),)
        self.assertTrue(self.registration.status()['enabled'])
        self.assertFalse(self.registration.set_enabled(False)['enabled'])

    def test_access_error_is_reported_without_fallback_writes(self):
        with patch.object(self.registry,'OpenKey',side_effect=PermissionError('access denied')):
            with self.assertRaises(PermissionError):self.registration.status()
        self.assertFalse(self.registry.exists)

    def test_source_command_quotes_paths_and_keeps_custom_config_and_port(self):
        local=fixtures.local
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);python=root/'Python with spaces'/'python.exe'
            python.parent.mkdir();python.touch();python.with_name('pythonw.exe').touch()
            custom=root/'Custom config'
            with patch.object(local.sys,'executable',str(python)),patch.object(local.sys,'frozen',False,create=True), \
                    patch.dict(local.os.environ,{'LOCALAPPDATA':str(root/'Default data'),'CLEARINGS_CONFIG_DIR':str(custom)}):
                registration=local.windows_startup(local.config_dir(),12345)
            self.assertIn('"'+str(python.with_name('pythonw.exe'))+'"',registration.command)
            self.assertIn('--config-dir "'+str(custom.resolve())+'"',registration.command)
            self.assertIn('--port 12345',registration.command)
            self.assertIn('serve --no-browser',registration.command)
            self.assertFalse(custom.exists())

    def test_default_source_and_native_use_same_origin_without_redundant_paths(self):
        local=fixtures.local
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);default=root/('Clearings-Release' if local.CHANNEL=='release' else 'Clearings')
            with patch.dict(local.os.environ,{'LOCALAPPDATA':str(root)}):
                with patch.object(local.sys,'frozen',False,create=True):
                    source=local.windows_startup(default,local.PORT)
                with patch.object(local.sys,'frozen',True,create=True),patch.object(local,'PROGRAM',root/'Clearings.exe'):
                    native=local.windows_startup(default,local.PORT)
            for registration in (source,native):
                self.assertNotIn('--config-dir',registration.command)
                self.assertNotIn('--port',registration.command)
                self.assertTrue(registration.command.endswith('serve --no-browser'))
            self.assertNotIn('python',native.command.lower())
            self.assertNotIn('ClearingsCLI',native.command)
            self.assertFalse(default.exists())

    def test_cli_startup_does_not_construct_bridge_or_start_helper(self):
        local=fixtures.local;registration=Mock()
        for action in ('status','enable','disable','remove-owned'):
            registration.reset_mock()
            registration.status.return_value={'enabled':False}
            registration.set_enabled.return_value={'enabled':action=='enable'}
            registration.remove_if_owned.return_value={'enabled':False}
            with patch.object(local.sys,'argv',['clearings_local.py','startup',action]), \
                    patch.object(local.sys,'stdout',io.StringIO()),patch.object(local,'windows_startup',return_value=registration), \
                    patch.object(local,'Bridge') as bridge,patch.object(local,'run_server') as server:
                local.main()
            bridge.assert_not_called();server.assert_not_called()
            if action in ('enable','disable'):
                registration.set_enabled.assert_called_once_with(action=='enable')


@unittest.skipUnless(os.name=='nt' and os.environ.get('CLEARINGS_NATIVE_TRAY_TEST')=='1','opt-in Windows desktop fixture')
class NativeTray(unittest.TestCase):
    def test_double_click_through_owned_windows_message_loop(self):
        import uuid
        opened=threading.Event();calls=[]
        def open_fixture():calls.append('open');opened.set()
        tray=WindowsTray(title='Clearings click check',address='test fixture only',
            identity='fixture-'+uuid.uuid4().hex,open_app=open_fixture,stop_helper=lambda:None)
        tray.start()
        try:
            for event in (0x400,0x203,0x400):
                self.assertTrue(tray.user.PostMessageW(tray.hwnd,tray.CALLBACK,0,(1<<16)|event))
            self.assertTrue(opened.wait(2))
            self.assertIsNone(tray.error)
        finally:tray.close()
        self.assertEqual(calls,['open'])
        self.assertFalse(tray.thread.is_alive())

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
