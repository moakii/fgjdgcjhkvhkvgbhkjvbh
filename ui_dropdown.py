"""Rounded, keyboard-accessible dropdown shared by Clienter windows."""
import time
import tkinter as tk
from tkinter import font as tkfont


def rounded(canvas, x1, y1, x2, y2, radius=6, **options):
    points = (x1+radius,y1,x2-radius,y1,x2,y1,x2,y1+radius,x2,y2-radius,x2,y2,
              x2-radius,y2,x1+radius,y2,x1,y2,x1,y2-radius,x1,y1+radius,x1,y1)
    return canvas.create_polygon(points, smooth=True, splinesteps=20, **options)


class Dropdown(tk.Canvas):
    def __init__(self, parent, variable, values, font, **kwargs):
        super().__init__(parent, bg='#e5e9f0', highlightthickness=0, takefocus=True, cursor='hand2', **kwargs)
        self.variable, self.values, self.text_font = variable, tuple(values), font
        self.popup = None
        self.highlighted = 0
        self.search = ''
        self.last_key = 0
        self.popup_geometry = None
        self.variable_trace = variable.trace_add('write', lambda *_: self.redraw())
        self.bind('<Configure>', lambda _: self.redraw())
        self.bind('<FocusIn>', lambda _: self.redraw())
        self.bind('<FocusOut>', lambda _: self.redraw())
        self.bind('<ButtonRelease-1>', self.toggle)
        for key in ('Return', 'space', 'Down', 'Up'):
            self.bind('<'+key+'>', self.toggle)
        self.bind('<KeyPress>', self.type_key, add='+')
        self.bind('<Destroy>', self.destroyed, add='+')
        self.owner = self.winfo_toplevel()
        self.owner_binding = self.owner.bind('<Configure>', self.owner_changed, add='+')

    def get(self): return self.variable.get()
    def set(self, value):
        if value not in self.values: raise ValueError('Unknown dropdown choice.')
        self.variable.set(value)

    def redraw(self):
        self.delete('all')
        width, height = self.winfo_width(), self.winfo_height()
        if width < 2 or height < 2: return
        border = '#0074bd' if self.popup or self.focus_get() == self else '#adb2b9'
        rounded(self, 1, 1, width-1, height-1, fill='white', outline=border, width=2)
        self.create_line(width-34, 3, width-34, height-3, fill='#d4dce6')
        text = self.get()
        font = tkfont.Font(font=self.text_font)
        while text and font.measure(text) > width-52:
            text = text[:-1]
        if text != self.get(): text = text[:-1] + '\u2026'
        self.create_text(9, height/2, text=text, font=self.text_font, fill='#34445f', anchor='w')
        middle = width-17
        points = ((middle-5,height/2+3,middle+5,height/2+3,middle,height/2-3) if self.popup else
                  (middle-5,height/2-3,middle+5,height/2-3,middle,height/2+3))
        self.create_polygon(points, fill='#34445f', outline='')

    def toggle(self, event=None):
        if self.popup:
            self.close(True)
        else:
            self.open()
        return 'break'

    def open(self):
        if self.popup or not self.values: return
        self.highlighted = self.values.index(self.get()) if self.get() in self.values else 0
        self.popup_geometry = self.owner_geometry()
        self.row_height = max(34, tkfont.Font(font=self.text_font).metrics('linespace')+14)
        height = len(self.values)*self.row_height+12
        width = max(180, self.winfo_width())
        width = min(width, self.winfo_screenwidth()-8)
        x = min(self.winfo_rootx(), self.winfo_screenwidth()-width-4)
        y = self.winfo_rooty()+self.winfo_height()+4
        if y+height > self.winfo_screenheight()-40:
            y = self.winfo_rooty()-height-4
        self.popup = tk.Toplevel(self, bg='#adb2b9')
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.transient(self.owner)
        self.popup.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        self.menu = tk.Canvas(self.popup, bg='#e5e9f0', highlightthickness=0, takefocus=True)
        self.menu.pack(fill='both', expand=True)
        self.menu.bind('<Motion>', self.hover)
        self.menu.bind('<ButtonRelease-1>', self.choose_mouse)
        self.menu.bind('<Escape>', lambda _: self.close(True))
        self.menu.bind('<Return>', lambda _: self.choose())
        self.menu.bind('<space>', lambda _: self.choose())
        self.menu.bind('<Down>', lambda _: self.move(1))
        self.menu.bind('<Up>', lambda _: self.move(-1))
        self.menu.bind('<Home>', lambda _: self.move_to(0))
        self.menu.bind('<End>', lambda _: self.move_to(len(self.values)-1))
        self.menu.bind('<Tab>', self.tab_next)
        self.menu.bind('<KeyPress>', self.type_key, add='+')
        self.popup.bind('<FocusOut>', lambda _: self.after(100, self.check_focus))
        self.popup.deiconify()
        self.popup.update_idletasks()
        # On Windows, an override-redirect popup can otherwise sit behind its
        # owner, whose activation also emits Configure without any resize.
        self.popup.attributes('-topmost', True)
        self.popup.lift()
        self.draw_menu()
        self.popup.grab_set()
        self.menu.focus_force()
        self.redraw()

    def draw_menu(self):
        if not self.popup: return
        canvas, width = self.menu, self.popup.winfo_width()
        canvas.delete('all')
        rounded(canvas, 1, 1, width-1, self.popup.winfo_height()-1, fill='white', outline='#adb2b9')
        for index, value in enumerate(self.values):
            top = 6+index*self.row_height
            selected, active = value == self.get(), index == self.highlighted
            if active or selected:
                rounded(canvas, 5, top, width-5, top+self.row_height, fill='#38b6ff' if active else '#e3efff', outline='')
            canvas.create_text(14, top+self.row_height/2, text=value, font=self.text_font,
                               fill='white' if active else '#34445f', anchor='w')
            if selected:
                canvas.create_text(width-20, top+self.row_height/2, text='\u2713',
                                   font=self.text_font, fill='white' if active else '#0074bd')

    def hover(self, event):
        index = (event.y-6)//self.row_height
        if 0 <= index < len(self.values) and index != self.highlighted:
            self.highlighted = index
            self.draw_menu()

    def choose_mouse(self, event):
        if not self.popup: return
        if not 0 <= event.x < self.popup.winfo_width() or not 6 <= event.y < 6+len(self.values)*self.row_height:
            self.close()
            return
        self.highlighted = (event.y-6)//self.row_height
        self.choose()

    def choose(self):
        value = self.values[self.highlighted]
        self.close(True)
        self.set(value)
        self.event_generate('<<ComboboxSelected>>')
        return 'break'

    def move(self, amount): return self.move_to((self.highlighted+amount)%len(self.values))
    def move_to(self, index):
        self.highlighted = index
        self.draw_menu()
        return 'break'

    def type_key(self, event):
        if not event.char or not event.char.isprintable() or event.char.isspace(): return
        now = time.monotonic()
        self.search = (self.search if now-self.last_key < .8 else '') + event.char.casefold()
        self.last_key = now
        for index, value in enumerate(self.values):
            if value.casefold().startswith(self.search):
                if self.popup: self.move_to(index)
                else: self.set(value)
                break

    def tab_next(self, event):
        self.close()
        self.tk_focusNext().focus_set()
        return 'break'

    def check_focus(self):
        if self.popup:
            focused = self.focus_get()
            if focused is None or focused.winfo_toplevel() != self.popup: self.close()

    def close(self, restore_focus=False):
        popup, self.popup = self.popup, None
        if popup:
            try: popup.grab_release()
            except tk.TclError: pass
            popup.destroy()
        if restore_focus and self.winfo_exists(): self.focus_set()
        if self.winfo_exists(): self.redraw()

    def owner_changed(self, event):
        if event.widget == self.owner and self.popup and self.owner_geometry() != self.popup_geometry:
            self.close()

    def owner_geometry(self):
        return (self.owner.winfo_rootx(), self.owner.winfo_rooty(), self.owner.winfo_width(), self.owner.winfo_height())

    def destroyed(self, event):
        if event.widget != self: return
        self.close()
        self.variable.trace_remove('write', self.variable_trace)
        self.owner.unbind('<Configure>', self.owner_binding)
