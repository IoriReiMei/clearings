# SPDX-License-Identifier: MPL-2.0
"""Windows notification-area presence for the running local helper.

Uses Windows APIs only. No startup registration, polling, network or user files.
The HTTP server owns this object's lifetime; stopping the server removes its icon.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import math
import os
import struct
import threading
import uuid


def icon_bitmap(size=32):
    """A small Clearings C, as an in-memory 32-bit Windows icon resource."""
    pixels=bytearray()
    for y in reversed(range(size)):
        for x in range(size):
            channels=[0,0,0,0]
            for sy in (.125,.375,.625,.875):
                for sx in (.125,.375,.625,.875):
                    px=(x+sx)*32/size-16;py=(y+sy)*32/size-16;r=math.hypot(px,py)
                    if r>15:continue
                    color=(71,101,76,255)
                    if 7<r<10.5 and not (px>4 and abs(py)<6):color=(244,247,238,255)
                    for i,c in enumerate(color):channels[i]+=c
            red,green,blue,alpha=[round(c/16) for c in channels]
            pixels.extend((blue,green,red,alpha))
    mask=bytes(((size+31)//32)*4*size)
    header=struct.pack('<IiiHHIIiiII',40,size,size*2,1,32,0,len(pixels),0,0,0,0)
    return header+pixels+mask


class WindowsTray:
    """One icon and message-pump thread, with explicit startup/cleanup checks."""
    CALLBACK=0x8001
    OPEN=1001
    STOP=1002

    def __init__(self, *, title, address, identity, open_app, stop_helper):
        if os.name!='nt':raise OSError('The notification-area helper is Windows-only')
        self.title=title;self.address=address;self.identity=identity
        self.open_app=open_app;self.stop_helper=stop_helper
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
        bind(self.user,'CreateIconFromResourceEx',[ctypes.c_void_p,w.DWORD,w.BOOL,w.DWORD,ctypes.c_int,ctypes.c_int,w.UINT],w.HICON)
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
        elif choice==self.STOP and not self._stopping:
            answer=self.user.MessageBoxW(self.hwnd,'Save any edits in your open Clearings tabs first.\n\nThis stops the background helper. Your tabs stay open, and saved workspace data is kept.\n\nStop the helper now?','Stop Clearings helper?',0x1|0x30|0x100)
            if answer==1:
                self._stopping=True
                threading.Thread(target=self.stop_helper,daemon=True).start()

    def _window_proc(self,hwnd,message,wp,lp):
        try:
            if message==self.taskbar_created:
                self._add();return 0
            if message==self.CALLBACK:
                event=lp&0xffff
                if event in (0x7b,0x400,0x401):self._menu()
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
            data=icon_bitmap();resource=ctypes.create_string_buffer(data)
            icon=self.user.CreateIconFromResourceEx(resource,len(data),True,0x00030000,32,32,0)
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
