"""Observe a native foreground executable locally, without reading window text.

The character catalog owns app/provider mappings. Browsers and terminals are
unknown here: an executable alone cannot identify their active AI tab/task.
"""
import ctypes
from ctypes import wintypes
import os
import time


class ForegroundProcess:
    def __init__(self):
        self._identity = None
        self._name = None
        self._expires = 0.0
        self._user = self._kernel = None
        if os.name != 'nt':
            return
        try:
            self._user = ctypes.WinDLL('user32', use_last_error=True)
            self._kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            self._user.GetForegroundWindow.restype = wintypes.HWND
            self._user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            self._kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            self._kernel.OpenProcess.restype = wintypes.HANDLE
            self._kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                               wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        except (OSError, AttributeError):
            self._user = self._kernel = None

    def current(self, now=None):
        """Return only basename or None. Never launch programs or retain paths."""
        if self._user is None or self._kernel is None:
            return None
        now = time.monotonic() if now is None else now
        try:
            hwnd = self._user.GetForegroundWindow()
            pid = wintypes.DWORD()
            if not hwnd or not self._user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)):
                return None
            identity = (hwnd, pid.value)
            if identity == self._identity and now < self._expires:
                return self._name
            name = None
            handle = self._kernel.OpenProcess(0x1000, False, pid.value)
            if handle:
                try:
                    buf = ctypes.create_unicode_buffer(32768)
                    length = wintypes.DWORD(len(buf))
                    if self._kernel.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(length)):
                        name = os.path.basename(buf.value).lower()
                finally:
                    self._kernel.CloseHandle(handle)
            self._identity, self._name, self._expires = identity, name, now + 2.0
            return name
        except (OSError, ValueError, AttributeError):
            return None
