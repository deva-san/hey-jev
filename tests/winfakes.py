"""Stand-ins for the Windows-only modules, so the unit tests also run on Linux and macOS (the cloud CI, a reviewer's Mac).

tests/support.py installs them before any project import, and only when sys.platform != "win32": on Windows the real
winreg, ctypes.windll, winrt, pycaw, comtypes and sounddevice are used and nothing here runs. Every stand-in does
nothing or fails the way a missing thing fails on Windows (a registry key that isn't there raises OSError), so a test
that reaches one by mistake fails loudly instead of acting on a PC. Tests that need the real Windows behaviour skip
with needs_windows."""
import ctypes
import os
import importlib.abc
import importlib.machinery
import sys
import types
import unittest

needs_windows = unittest.skipUnless(sys.platform == "win32", "needs Windows: the real Win32, registry or audio APIs")


class NotOnThisPlatform(RuntimeError):
    pass


class _Function:
    """A Win32 function: takes argtypes/restype like ctypes does, and returns 0 (FALSE, NULL) when called."""

    def __init__(self, name):
        self.__name__ = name
        self.argtypes, self.restype, self.errcheck = None, None, None

    def __call__(self, *_, **__):
        return 0


class _DLL:
    def __init__(self, name, *_, **__):
        self._name = name

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        fn = _Function(f"{self._name}.{name}")
        setattr(self, name, fn)
        return fn


class _Loader:
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        dll = _DLL(name)
        setattr(self, name, dll)
        return dll


def _fake_ctypes():
    for name, value in (("WinDLL", _DLL), ("OleDLL", _DLL), ("windll", _Loader()), ("oledll", _Loader()),
                        ("WINFUNCTYPE", ctypes.CFUNCTYPE), ("HRESULT", ctypes.c_long),
                        ("get_last_error", lambda: 0), ("set_last_error", lambda _v: 0),
                        ("FormatError", lambda code=0: f"error {code}"),
                        ("WinError", lambda code=0, descr=None: OSError(code, descr or f"error {code}"))):
        if not hasattr(ctypes, name):
            setattr(ctypes, name, value)


def _missing(*_, **__):
    raise FileNotFoundError(2, "The system cannot find the file specified (registry stand-in)")


def _fake_winreg():
    reg = types.ModuleType("winreg")
    reg.__doc__ = "Stand-in: an empty registry. Every key is missing, and nothing can be written."
    reg.HKEY_CLASSES_ROOT, reg.HKEY_CURRENT_USER, reg.HKEY_LOCAL_MACHINE, reg.HKEY_USERS = (
        0x80000000, 0x80000001, 0x80000002, 0x80000003)
    reg.KEY_READ, reg.KEY_WRITE, reg.KEY_ALL_ACCESS, reg.KEY_SET_VALUE, reg.KEY_QUERY_VALUE = (
        0x20019, 0x20006, 0xF003F, 0x0002, 0x0001)
    reg.KEY_WOW64_64KEY, reg.KEY_WOW64_32KEY = 0x0100, 0x0200
    reg.REG_SZ, reg.REG_EXPAND_SZ, reg.REG_BINARY, reg.REG_DWORD, reg.REG_MULTI_SZ, reg.REG_QWORD = 1, 2, 3, 4, 7, 11
    for name in ("OpenKey", "OpenKeyEx", "CreateKey", "CreateKeyEx", "QueryValueEx", "QueryValue", "QueryInfoKey",
                 "EnumKey", "EnumValue", "SetValueEx", "SetValue", "DeleteValue", "DeleteKey", "DeleteKeyEx",
                 "ConnectRegistry", "ExpandEnvironmentStrings"):
        setattr(reg, name, _missing)
    reg.CloseKey = lambda *_: None
    return reg


class _Anything:
    """Any attribute of a fake package: a class to import, a constant, a function. Using it raises."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Anything(f"{self._name}.{name}")

    def __call__(self, *_, **__):
        raise NotOnThisPlatform(f"{self._name} is Windows-only (test stand-in)")

    def __repr__(self):
        return f"<stand-in {self._name}>"


class _FakePackage(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Anything(f"{self.__name__}.{name}")


class _FakeFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Serves winrt, pycaw, comtypes, sounddevice and pynput (which needs an X display off Windows), and any module
    under them, as _FakePackage."""
    ROOTS = ("winrt", "pycaw", "comtypes", "sounddevice", "pynput")

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in self.ROOTS:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _FakePackage(spec.name)
        module.__path__ = []
        module.WINDOWS_STAND_IN = True
        return module

    def exec_module(self, module):
        if module.__name__ == "sounddevice":
            module.PortAudioError = type("PortAudioError", (Exception,), {})
            module.default = types.SimpleNamespace(device=(None, None), samplerate=None, channels=(None, None))


def _windows_basename():
    """os.path.basename that also splits at a backslash, like ntpath: the project reads program paths Windows gives
    (C:\\Program Files\\...\\WhatsApp.exe) and names the program by its basename. Only in the test process, where
    no real file has a backslash in its name."""
    import posixpath
    plain = posixpath.basename

    def basename(p):
        p = os.fspath(p)
        return plain(p.replace("\\", "/")) if isinstance(p, str) else plain(p)
    posixpath.basename = basename


def install():
    """Put the stand-ins in place. Only off Windows: on Windows this does nothing."""
    if sys.platform == "win32":
        return
    _fake_ctypes()
    sys.modules.setdefault("winreg", _fake_winreg())
    _windows_basename()
    if not hasattr(os, "startfile"):
        os.startfile = _Anything("os.startfile")  # tests patch it; called unpatched, it raises
    for root in _FakeFinder.ROOTS:
        sys.modules.pop(root, None)  # a real sounddevice without PortAudio would fail to import anyway
    if not any(isinstance(f, _FakeFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _FakeFinder())
