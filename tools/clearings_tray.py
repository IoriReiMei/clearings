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
"""Windows notification-area presence for the running local helper.

Uses Windows APIs only. Startup registration requires an explicit user choice.
No polling, network access or checklist-file writes.
The HTTP server owns this object's lifetime; stopping the server removes its icon.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import threading
import uuid


def icon_path():
    """Find the same reviewed icon in source and PyInstaller layouts."""
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))
    return root/'assets'/'Clearings.ico'


class WindowsStartup:
    """Own one exact command in this user's Run key; never change other entries.

    Registration is opt-in. Windows Startup Apps can independently disable it;
    this class never changes StartupApproved or any machine-wide setting.
    """
    RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'

    def __init__(self, *, name, command, required_files=(), registry=None):
        self.name = name
        self.command = command
        self.required_files = tuple(Path(path) for path in required_files)
        self._registry_override = registry
        if not name or len(name) > 100 or any(char in name for char in '\0\r\n'):
            raise ValueError('Invalid Clearings startup name')
        if not command or any(char in command for char in '\0\r\n'):
            raise ValueError('Invalid Clearings startup command')

    def _registry(self):
        if self._registry_override is not None:
            return self._registry_override
        if os.name != 'nt':
            return None
        import winreg
        return winreg

    def _problem(self):
        if len(self.command.encode('utf-16-le')) // 2 > 260:
            return 'This source/configuration path is too long for Windows startup. Use a shorter source path or the installed edition.'
        if any(not path.is_file() for path in self.required_files):
            return 'A required launcher or settings file is missing. Open a complete Clearings copy before enabling startup.'
        return None

    def _value(self, registry, key):
        try:
            return registry.QueryValueEx(key, self.name)
        except FileNotFoundError:
            return None

    def status(self):
        registry = self._registry()
        if registry is None:
            return {'supported': False, 'enabled': False, 'conflict': False,
                    'name': self.name, 'reason': 'Start with Windows is available on Windows only.'}
        try:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, self.RUN_KEY,
                                  0, registry.KEY_QUERY_VALUE) as key:
                current = self._value(registry, key)
        except FileNotFoundError:
            current = None
        owned = current == (self.command, registry.REG_SZ)
        conflict = current is not None and not owned
        return {'supported': True, 'enabled': owned, 'conflict': conflict,
                'name': self.name, 'command': self.command,
                'reason': ('Startup is configured for a different Clearings copy. Turn it off from that copy first.'
                           if conflict else self._problem()),
                'note': 'Windows Startup Apps may independently disable a registered entry.'}

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('Choose whether Windows startup is enabled')
        registry = self._registry()
        if registry is None:
            raise ValueError('Start with Windows is available on Windows only.')
        if enabled and self._problem():
            raise ValueError(self._problem())
        access = registry.KEY_QUERY_VALUE | registry.KEY_SET_VALUE
        try:
            key = (registry.CreateKeyEx(registry.HKEY_CURRENT_USER, self.RUN_KEY, 0, access)
                   if enabled else registry.OpenKey(registry.HKEY_CURRENT_USER, self.RUN_KEY, 0, access))
        except FileNotFoundError:
            return self.status()
        with key:
            current = self._value(registry, key)
            if current is not None and current != (self.command, registry.REG_SZ):
                raise ValueError('Startup is configured for a different Clearings copy. No startup entry was changed.')
            if enabled:
                registry.SetValueEx(key, self.name, 0, registry.REG_SZ, self.command)
            elif current is not None:
                registry.DeleteValue(key, self.name)
        result = self.status()
        if result['enabled'] != enabled or result['conflict']:
            raise OSError('Windows startup changed before it could be verified. Check the tray setting again.')
        return result

    def remove_if_owned(self):
        """Uninstall cleanup preserves an entry belonging to a different copy."""
        result = self.status()
        return self.set_enabled(False) if result['enabled'] else result


class WindowsTray:
    """One icon and message-pump thread, with explicit startup/cleanup checks."""
    CALLBACK=0x8001
    OPEN=1001
    STOP=1002
    STARTUP=1003

    def __init__(self, *, title, address, identity, open_app, stop_helper, startup=None):
        if os.name!='nt':raise OSError('The notification-area helper is Windows-only')
        self.title=title;self.address=address;self.identity=identity
        self.open_app=open_app;self.stop_helper=stop_helper
        self.startup=startup
        self.ready=threading.Event();self.error=None;self.hwnd=None
        self.registered=False;self.thread=None;self._stopping=False
        self.closing=threading.Event()
        self._configure_api()

    def _configure_api(self):
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.shell=ctypes.WinDLL('shell32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.WNDPROC=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
        class WNDCLASS(ctypes.Structure):
            _fields_=[('style',w.UINT),('lpfnWndProc',self.WNDPROC),('cbClsExtra',ctypes.c_int),('cbWndExtra',ctypes.c_int),('hInstance',w.HINSTANCE),('hIcon',w.HICON),('hCursor',w.HANDLE),('hbrBackground',w.HBRUSH),('lpszMenuName',w.LPCWSTR),('lpszClassName',w.LPCWSTR)]
        class GUID(ctypes.Structure):
            _fields_=[('a',w.DWORD),('b',w.WORD),('c',w.WORD),('d',ctypes.c_ubyte*8)]
        class NOTIFYICONDATA(ctypes.Structure):
            _fields_=[('cbSize',w.DWORD),('hWnd',w.HWND),('uID',w.UINT),('uFlags',w.UINT),('uCallbackMessage',w.UINT),('hIcon',w.HICON),('szTip',w.WCHAR*128),('dwState',w.DWORD),('dwStateMask',w.DWORD),('szInfo',w.WCHAR*256),('uVersion',w.UINT),('szInfoTitle',w.WCHAR*64),('dwInfoFlags',w.DWORD),('guidItem',GUID),('hBalloonIcon',w.HICON)]
        self.WNDCLASS=WNDCLASS;self.NOTIFYICONDATA=NOTIFYICONDATA
        self.guid=GUID.from_buffer_copy(uuid.uuid5(uuid.NAMESPACE_URL,'clearings-tray:'+self.identity).bytes_le)
        def bind(lib,name,args,result):
            fn=getattr(lib,name);fn.argtypes=args;fn.restype=result
        bind(self.kernel,'GetModuleHandleW',[w.LPCWSTR],w.HMODULE)
        bind(self.user,'RegisterClassW',[ctypes.POINTER(WNDCLASS)],w.ATOM)
        bind(self.user,'UnregisterClassW',[w.LPCWSTR,w.HINSTANCE],w.BOOL)
        bind(self.user,'CreateWindowExW',[w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,w.HMENU,w.HINSTANCE,w.LPVOID],w.HWND)
        bind(self.user,'DefWindowProcW',[w.HWND,w.UINT,w.WPARAM,w.LPARAM],ctypes.c_ssize_t)
        bind(self.user,'DestroyWindow',[w.HWND],w.BOOL)
        bind(self.user,'GetMessageW',[ctypes.POINTER(w.MSG),w.HWND,w.UINT,w.UINT],ctypes.c_int)
        bind(self.user,'TranslateMessage',[ctypes.POINTER(w.MSG)],w.BOOL)
        bind(self.user,'DispatchMessageW',[ctypes.POINTER(w.MSG)],ctypes.c_ssize_t)
        bind(self.user,'PostMessageW',[w.HWND,w.UINT,w.WPARAM,w.LPARAM],w.BOOL)
        bind(self.user,'PostQuitMessage',[ctypes.c_int],None)
        bind(self.user,'RegisterWindowMessageW',[w.LPCWSTR],w.UINT)
        bind(self.user,'LoadImageW',[w.HINSTANCE,w.LPCWSTR,w.UINT,ctypes.c_int,ctypes.c_int,w.UINT],w.HICON)
        bind(self.user,'DestroyIcon',[w.HICON],w.BOOL)
        bind(self.user,'CreatePopupMenu',[],w.HMENU)
        bind(self.user,'AppendMenuW',[w.HMENU,w.UINT,ctypes.c_size_t,w.LPCWSTR],w.BOOL)
        bind(self.user,'SetMenuDefaultItem',[w.HMENU,w.UINT,w.UINT],w.BOOL)
        bind(self.user,'DestroyMenu',[w.HMENU],w.BOOL)
        bind(self.user,'GetCursorPos',[ctypes.POINTER(w.POINT)],w.BOOL)
        bind(self.user,'SetForegroundWindow',[w.HWND],w.BOOL)
        bind(self.user,'TrackPopupMenu',[w.HMENU,w.UINT,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.HWND,ctypes.c_void_p],w.UINT)
        bind(self.user,'MessageBoxW',[w.HWND,w.LPCWSTR,w.LPCWSTR,w.UINT],ctypes.c_int)
        bind(self.shell,'Shell_NotifyIconW',[w.DWORD,ctypes.POINTER(NOTIFYICONDATA)],w.BOOL)

    def _notify(self,command):
        return bool(self.shell.Shell_NotifyIconW(command,ctypes.byref(self.nid)))

    def _add(self):
        if not self._notify(0):raise OSError('Windows could not display the Clearings tray icon')
        self.registered=True;self.nid.uVersion=4
        if not self._notify(4):raise OSError('Windows could not configure the Clearings tray icon')

    def _menu(self):
        menu=self.user.CreatePopupMenu()
        if not menu:raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.user.AppendMenuW(menu,0x2,0,self.title)
            self.user.AppendMenuW(menu,0x2,0,'Running locally · '+self.address)
            self.user.AppendMenuW(menu,0x800,0,None)
            self.user.AppendMenuW(menu,0,self.OPEN,'Open Clearings')
            if self.startup is not None:
                try:
                    state=self.startup.status()
                    available=state['supported'] and not state['conflict'] and (state['enabled'] or not state['reason'])
                    flags=(0x8 if state['enabled'] else 0) | (0 if available else 0x2)
                    label='Start helper with Windows' if available else 'Start helper with Windows (unavailable)'
                except (OSError,ValueError):
                    flags=0x2;label='Windows startup setting unavailable'
                self.user.AppendMenuW(menu,flags,self.STARTUP,label)
            self.user.AppendMenuW(menu,0,self.STOP,'Stop helper…')
            self.user.SetMenuDefaultItem(menu,self.OPEN,False)
            point=w.POINT();self.user.GetCursorPos(ctypes.byref(point))
            self.user.SetForegroundWindow(self.hwnd)
            choice=self.user.TrackPopupMenu(menu,0x100|0x2,point.x,point.y,0,self.hwnd,None)
            self.user.PostMessageW(self.hwnd,0,0,0)
            self._notify(3)
            self._command(choice)
        finally:self.user.DestroyMenu(menu)

    def _command(self,choice):
        if choice==self.OPEN:
            threading.Thread(target=self.open_app,daemon=True).start()
        elif choice==self.STARTUP and self.startup is not None:
            try:
                self.startup.set_enabled(not self.startup.status()['enabled'])
            except (OSError,ValueError) as exc:
                self.user.MessageBoxW(self.hwnd,str(exc),'Clearings startup setting',0x30)
        elif choice==self.STOP and not self._stopping:
            answer=self.user.MessageBoxW(self.hwnd,'Save any edits in your open Clearings tabs first.\n\nClearings will back up its last saved workspace and editor draft before stopping. Use Save and quit in the page to include your latest edits. Your tabs stay open.\n\nStop the helper now?','Stop Clearings helper?',0x1|0x30|0x100)
            if answer==1:
                self._stopping=True
                threading.Thread(target=self._stop_with_feedback,daemon=True).start()

    def _stop_with_feedback(self):
        try:
            if self.stop_helper() is not False:
                return
        except Exception as exc:
            self.error=exc
        self._stopping=False
        self.user.MessageBoxW(self.hwnd,'The helper stayed open because its backup could not finish.\n\nOpen Clearings to save or export your work, then try again.','Clearings is still running',0x30)

    def _window_proc(self,hwnd,message,wp,lp):
        try:
            if message==self.taskbar_created:
                self._add();return 0
            if message==self.CALLBACK:
                event=lp&0xffff
                # NIN_SELECT from the first click must not open a blocking menu
                # before Windows can deliver the double-click. Keyboard activation
                # opens the app too; WM_CONTEXTMENU keeps the right-click menu.
                if event in (0x203,0x401):self._command(self.OPEN)
                elif event==0x7b:self._menu()
                return 0
            if message==0x10: # WM_CLOSE from the server's finally block.
                self.user.DestroyWindow(hwnd);return 0
            if message==0x2: # WM_DESTROY
                if self.registered:self._notify(2);self.registered=False
                self.user.PostQuitMessage(0);return 0
            return self.user.DefWindowProcW(hwnd,message,wp,lp)
        except Exception as exc:
            self.error=exc
            # Never leave a running helper silently without its requested icon.
            threading.Thread(target=self.stop_helper,daemon=True).start()
            self.user.PostMessageW(hwnd,0x10,0,0)
            return 0

    def _run(self):
        instance=None;class_name=None;icon=None
        try:
            instance=self.kernel.GetModuleHandleW(None)
            self.taskbar_created=self.user.RegisterWindowMessageW('TaskbarCreated')
            if not self.taskbar_created:raise ctypes.WinError(ctypes.get_last_error())
            self.proc=self.WNDPROC(self._window_proc)
            class_name='ClearingsTray-'+uuid.uuid4().hex
            wc=self.WNDCLASS();wc.lpfnWndProc=self.proc;wc.hInstance=instance;wc.lpszClassName=class_name
            if not self.user.RegisterClassW(ctypes.byref(wc)):raise ctypes.WinError(ctypes.get_last_error())
            self.hwnd=self.user.CreateWindowExW(0,class_name,self.title,0,0,0,0,0,None,None,instance,None)
            if not self.hwnd:raise ctypes.WinError(ctypes.get_last_error())
            # A hidden top-level window receives Explorer's TaskbarCreated message.
            # Keep this owned handle for Explorer restoration and destroy it on exit.
            artwork=icon_path()
            if not artwork.is_file():raise FileNotFoundError(f'Missing Clearings tray icon: {artwork}')
            icon=self.user.LoadImageW(None,str(artwork),1,32,32,0x10) # IMAGE_ICON, LR_LOADFROMFILE
            if not icon:raise ctypes.WinError(ctypes.get_last_error())
            self.nid=self.NOTIFYICONDATA();self.nid.cbSize=ctypes.sizeof(self.nid)
            self.nid.hWnd=self.hwnd;self.nid.uID=1;self.nid.uFlags=0x1|0x2|0x4|0x20|0x80
            self.nid.uCallbackMessage=self.CALLBACK;self.nid.hIcon=icon;self.nid.guidItem=self.guid
            self.nid.szTip=(self.title+'\nRunning locally · '+self.address)[:127]
            if self.closing.is_set():return
            self._add();self.ready.set()
            if self.closing.is_set():return
            message=w.MSG()
            while True:
                result=self.user.GetMessageW(ctypes.byref(message),None,0,0)
                if result==0:break
                if result==-1:raise ctypes.WinError(ctypes.get_last_error())
                self.user.TranslateMessage(ctypes.byref(message));self.user.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.error=exc
            if self.ready.is_set() and not self.closing.is_set():
                threading.Thread(target=self.stop_helper,daemon=True).start()
        finally:
            if self.registered:self._notify(2);self.registered=False
            if self.hwnd:self.user.DestroyWindow(self.hwnd);self.hwnd=None
            if icon:self.user.DestroyIcon(icon)
            if class_name and instance:self.user.UnregisterClassW(class_name,instance)
            self.ready.set()

    def start(self):
        self.thread=threading.Thread(target=self._run,name='Clearings tray',daemon=True);self.thread.start()
        if not self.ready.wait(5):
            self.close();raise RuntimeError('Windows did not start the Clearings tray icon')
        if self.error:
            self.close();raise RuntimeError(str(self.error)) from self.error
        return self

    def close(self):
        self.closing.set()
        if self.hwnd:self.user.PostMessageW(self.hwnd,0x10,0,0)
        if self.thread and self.thread is not threading.current_thread():self.thread.join(5)
