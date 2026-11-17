"""Register the bundled Source Sans faces for this process only."""
from pathlib import Path
import ctypes
import os
from tkinter import font as tkfont

UI_FONT = 'Source Sans 3'
_loaded = False


def load_fonts():
    global _loaded
    if _loaded:
        return
    if os.name == 'nt':
        add_font = ctypes.WinDLL('gdi32', use_last_error=True).AddFontResourceExW
        add_font.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        add_font.restype = ctypes.c_int
        for name in ('SourceSans3-Regular.ttf', 'SourceSans3-Bold.ttf'):
            path = Path(__file__).resolve().parent / 'Fonts' / name
            if not path.is_file():
                raise FileNotFoundError(f'Missing interface font: {path}')
            if not add_font(str(path), 0x10, None):  # FR_PRIVATE; no system installation.
                raise OSError(f'Could not load interface font: {path}')
    _loaded = True


def configure_fonts(root):
    # Named fonts cover native Tk controls, dialogs, menus and combobox lists.
    for name in ('TkDefaultFont', 'TkTextFont', 'TkFixedFont', 'TkMenuFont',
                 'TkHeadingFont', 'TkCaptionFont', 'TkSmallCaptionFont',
                 'TkIconFont', 'TkTooltipFont'):
        font = tkfont.nametofont(name, root=root)
        font.configure(family=UI_FONT)
    root.option_add('*Font', (UI_FONT, 10))
    root.option_add('*TCombobox*Listbox.font', (UI_FONT, 10))
