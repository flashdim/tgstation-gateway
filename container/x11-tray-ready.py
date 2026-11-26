#!/usr/bin/env python3
import ctypes
import sys


def main():
    x11 = ctypes.CDLL("libX11.so.6")
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XGetSelectionOwner.restype = ctypes.c_ulong
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]

    display = x11.XOpenDisplay(None)
    if not display:
        return 1
    try:
        name = f"_NET_SYSTEM_TRAY_S{x11.XDefaultScreen(display)}".encode("ascii")
        atom = x11.XInternAtom(display, name, 1)
        return 0 if atom and x11.XGetSelectionOwner(display, atom) else 1
    finally:
        x11.XCloseDisplay(display)


if __name__ == "__main__":
    sys.exit(main())
