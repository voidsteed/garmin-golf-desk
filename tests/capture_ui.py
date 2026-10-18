"""Developer-only capture of this app's own window, never the whole desktop."""

import argparse
import ctypes
import struct
import sys
import zlib
from ctypes import wintypes
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from golf_app import GolfApp


class Header(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("width", wintypes.LONG), ("height", wintypes.LONG),
                ("planes", wintypes.WORD), ("bits", wintypes.WORD), ("compression", wintypes.DWORD),
                ("image_size", wintypes.DWORD), ("xppm", wintypes.LONG), ("yppm", wintypes.LONG),
                ("used", wintypes.DWORD), ("important", wintypes.DWORD)]


def capture(root, path):
    user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
    user.GetAncestor.argtypes = [ctypes.c_void_p, wintypes.UINT]
    user.GetAncestor.restype = ctypes.c_void_p
    user.GetWindowDC.argtypes = [ctypes.c_void_p]
    user.GetWindowDC.restype = ctypes.c_void_p
    user.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
    user.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    user.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi.CreateCompatibleDC.restype = ctypes.c_void_p
    gdi.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi.SelectObject.restype = ctypes.c_void_p
    gdi.GetDIBits.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.POINTER(Header), wintypes.UINT]
    gdi.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi.DeleteDC.argtypes = [ctypes.c_void_p]
    hwnd = user.GetAncestor(root.winfo_id(), 2)
    rect = wintypes.RECT()
    user.GetWindowRect(hwnd, ctypes.byref(rect))
    w,h = rect.right-rect.left, rect.bottom-rect.top
    dc = user.GetWindowDC(hwnd)
    memory = gdi.CreateCompatibleDC(dc)
    bitmap = gdi.CreateCompatibleBitmap(dc,w,h)
    previous = gdi.SelectObject(memory,bitmap)
    try:
        if not user.PrintWindow(hwnd,memory,2):
            raise RuntimeError("App-window capture was unavailable")
        gdi.SelectObject(memory,previous)
        header = Header(ctypes.sizeof(Header),w,-h,1,32,0,w*h*4,0,0,0,0)
        buffer = ctypes.create_string_buffer(w*h*4)
        if not gdi.GetDIBits(memory,bitmap,0,h,buffer,ctypes.byref(header),0):
            raise RuntimeError("Could not read the app-window image")
        bgra = buffer.raw
        scanlines = []
        for y in range(h):
            source = bgra[y*w*4:(y+1)*w*4]
            row = bytearray(w*4)
            row[0::4],row[1::4],row[2::4],row[3::4] = source[2::4],source[1::4],source[0::4],b"\xff"*w
            scanlines.append(b"\x00"+row)
        def chunk(kind,payload):
            return struct.pack(">I",len(payload))+kind+payload+struct.pack(">I",zlib.crc32(kind+payload)&0xffffffff)
        png = b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",w,h,8,6,0,0,0))+chunk(b"IDAT",zlib.compress(b"".join(scanlines),6))+chunk(b"IEND",b"")
        path.write_bytes(png)
    finally:
        gdi.SelectObject(memory,previous)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(memory)
        user.ReleaseDC(hwnd,dc)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--exports",type=Path,help="Optional local export folder for the visual check")
    args = parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    app = GolfApp(export_dir=args.exports)
    failures = []
    app.root.report_callback_exception = lambda kind,value,tb: failures.append(kind.__name__)
    try:
        screens = [("improve","improve"),("strategy","improve"),("ev","improve"),("overview","overview"),("rounds","rounds"),("clubs","clubs"),("tee","game"),("putting","game"),("wedges","game"),("privacy","privacy")]
        for filename,page in screens:
            if page=="improve":
                app.improve_tab = "strategy" if filename=="strategy" else "ev" if filename=="ev" else "dashboard"
            if page=="game":
                app.game_tab = filename
            app.show_page(page)
            app.root.update_idletasks()
            app.root.update()
            capture(app.root,args.out/(filename+".png"))
            if filename=="improve":
                for fraction,suffix in ((0.42,"details"),(1.0,"holes")):
                    app.scroll.canvas.yview_moveto(fraction)
                    app.root.update_idletasks()
                    app.root.update()
                    capture(app.root,args.out/("improve-"+suffix+".png"))
            if filename=="ev":
                # Explicitly labeled illustrative inputs, never real player probabilities.
                app.ev_view.load_example()
                app.root.update_idletasks()
                app.root.update()
                app.scroll.canvas.yview_moveto(1)
                app.root.update_idletasks()
                app.root.update()
                capture(app.root,args.out/"ev-example.png")
        if failures:
            raise RuntimeError("An interface callback failed")
        print("All dashboard pages, game tabs and chart details rendered and were captured without signing in.")
    finally:
        app.close()


if __name__ == "__main__":
    main()
