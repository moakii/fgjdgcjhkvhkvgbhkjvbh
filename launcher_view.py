"""Reference-image layout for the Clienter launcher."""
import tkinter as tk
from tkinter import ttk, font as tkfont
from tkinter.scrolledtext import ScrolledText
from pathlib import Path
from PIL import Image, ImageOps, ImageTk, ImageFilter, ImageDraw
from ui_fonts import UI_FONT
from ui_dropdown import Dropdown

ROOT = Path(__file__).resolve().parent
PANEL = '#e5e9f0'
INK = '#34445f'
BORDER = '#adb2b9'


def build(app, appearances, load_profile):
    app.geometry('1000x820')
    app.minsize(980, 800)
    configure_dialog_theme(app)
    app.reference_font = tkfont.Font(app, family=UI_FONT, size=15)
    app.reference_heading = tkfont.Font(app, family=UI_FONT, size=17)
    app.reference_log_font = tkfont.Font(app, family=UI_FONT, size=14)
    style = ttk.Style(app)
    style.configure('Launch.TCombobox', font=app.reference_font, fieldbackground='#ffffff',
                    background='#ffffff', foreground=INK, arrowcolor=INK, arrowsize=34,
                    borderwidth=3, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(4, 2))
    style.map('Launch.TCombobox', fieldbackground=[('readonly', '#ffffff')], foreground=[('readonly', INK)])
    app.reference_button_images = []
    for name, color, hover, foreground in (
            ('Cyan', '#38b6ff', '#169ee9', '#ffffff'),
            ('Green', '#00bf63', '#00a453', '#ffffff'),
            ('Red', '#ff3131', '#e32020', '#ffffff'),
            ('Gray', '#adb2b9', '#989fa9', INK)):
        button_style = f'{name}.Launch.TButton'
        style.configure(button_style, font=app.reference_font, background=color, foreground=foreground,
                        padding=0, borderwidth=0, relief='flat', focusthickness=1, focuscolor=foreground)
        style.map(button_style, background=[('disabled', '#bdc7d3'), ('pressed', hover), ('active', hover)],
                  foreground=[('disabled', '#eaf0f5'), ('!disabled', foreground)])
        images = []
        for fill in (color, hover, '#bdc7d3'):
            surface = Image.new('RGBA', (12, 12), PANEL)
            ImageDraw.Draw(surface).rounded_rectangle((0, 0, 11, 11), radius=3, fill=fill)
            images.append(ImageTk.PhotoImage(surface, master=app))
        app.reference_button_images.extend(images)
        element = f'{name}.Launch.surface'
        style.element_create(element, 'image', images[0], ('disabled', images[2]),
                             ('pressed', images[1]), ('active', images[1]), border=4, sticky='nsew')
        style.layout(button_style, [(element, {'sticky': 'nsew', 'children': [
            ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])

    app.backdrop = tk.Canvas(app, bg='#557c8d', highlightthickness=0)
    app.backdrop.pack(fill='both', expand=True)
    app.background_source = None
    app.background_photo = None
    app.background_resize = None
    app.background_item = app.backdrop.create_image(0, 0, anchor='nw')
    app.image_ops, app.image_tk = ImageOps, ImageTk
    try:
        with Image.open(ROOT/'background.png') as image:
            app.background_source = image.convert('RGB')
    except OSError as error:
        app.events.put(f'Background unavailable: {error}')
    with Image.open(ROOT/'logos/clienter.png') as image:
        app.reference_logo_source = image.convert('RGBA')
    app.reference_stripe = app.backdrop.create_rectangle(28, 33, 38, 133, fill='#658ace', outline='')
    app.reference_logo_shadow = app.backdrop.create_image(62, 19, anchor='nw')
    app.reference_logo_item = app.backdrop.create_image(70, 27, anchor='nw')
    controls = tk.Frame(app.backdrop, bg=PANEL)
    console = tk.Frame(app.backdrop, bg=PANEL)
    app.controls_window = app.backdrop.create_window(22, 160, window=controls, anchor='nw')
    app.console_window = app.backdrop.create_window(429, 160, window=console, anchor='nw')
    app.reference_items = []
    app.fields, app.buttons = {}, []

    def position(widget, column, x, y, width, height):
        app.reference_items.append((widget, column, x, y, width, height))
        return widget

    def heading(parent, column, text, y):
        widget = tk.Label(parent, text=text, font=app.reference_heading, bg='#0074bd', fg='white', borderwidth=0)
        return position(widget, column, 0, y, 395 if column == 0 else 728, 56)

    def label(parent, column, text, x, y, width, muted=False):
        widget = tk.Label(parent, text=text, font=app.reference_font, bg=PANEL,
                          fg='#737373' if muted else INK, anchor='w', borderwidth=0)
        return position(widget, column, x, y, width, 30)

    def entry(parent, column, variable, x, y, width, readonly=False, height=44):
        border = tk.Frame(parent, bg=BORDER)
        widget = tk.Entry(border, textvariable=variable, font=app.reference_font, bg='white',
                          fg=INK, readonlybackground='white', disabledforeground=INK,
                          insertbackground=INK, relief='flat', borderwidth=0,
                          state='readonly' if readonly else 'normal')
        widget.place(x=4, y=3, relwidth=1, relheight=1, width=-8, height=-6)
        border.entry = widget
        return position(border, column, x, y, width, height)

    def button(parent, column, text, action, color, x, y, width, height=44, managed=True):
        widget = ttk.Button(parent, text=text, style=f'{color}.Launch.TButton',
                            command=lambda: app.run(action))
        position(widget, column, x, y, width, height)
        if managed: app.buttons.append(widget)
        return widget

    heading(controls, 0, 'Player', 0)
    heading(controls, 0, 'World', 326)
    heading(console, 1, 'Play together', 0)
    heading(console, 1, 'Session notes', 326)
    label(controls, 0, 'Username', 20, 70, 355)
    app.fields['username'] = tk.StringVar(value='Player')
    entry(controls, 0, app.fields['username'], 20, 105, 355)
    label(controls, 0, 'Character', 20, 162, 355)
    app.fields['rig'] = tk.StringVar(value='Bacon Hair')
    character = Dropdown(controls, variable=app.fields['rig'], values=appearances, font=app.reference_font)
    app.character_dropdown = character
    position(character, 0, 20, 197, 355, 44)
    app.custom_avatar = load_profile()
    app.avatar_editor = None
    app.custom_controls = tk.Frame(controls, bg=PANEL)
    app.custom_button = ttk.Button(app.custom_controls, text='Customize...',
                                   style='Cyan.Launch.TButton', command=app.open_custom_editor)
    app.custom_button.pack(fill='both', expand=True)
    app.apply_character_button = button(controls, 0, 'Wear this character', app.apply_rig, 'Green', 20, 256, 355)
    app.fields['rig'].trace_add('write', app.toggle_custom_controls)
    app.map = tk.StringVar()
    entry(controls, 0, app.map, 20, 408, 355)
    # File picking runs on Tk's UI thread.
    choose = ttk.Button(controls, text='Choose map', style='Gray.Launch.TButton', command=app.select_map)
    position(choose, 0, 20, 467, 355, 44)
    button(controls, 0, 'Host this world', app.host, 'Cyan', 20, 527, 355)
    button(controls, 0, 'Open ROBLOX', app.backend.join, 'Green', 20, 587, 355)
    position(tk.Frame(controls, bg='#b5bbc4'), 0, 22, 655, 351, 1)
    app.connection_toggle = ttk.Button(controls, text='Connection Settings', style='Cyan.Launch.TButton')
    position(app.connection_toggle, 0, 20, 681, 355, 44)
    build_connection_dialog(app)

    label(console, 1, 'Host a map, then share an invite. No router setup needed.', 28, 70, 675, True)
    app.invite_link = tk.StringVar()
    entry(console, 1, app.invite_link, 28, 105, 527, True)
    copy = ttk.Button(console, text='Copy', style='Cyan.Launch.TButton', command=app.copy_invite)
    position(copy, 1, 568, 105, 135, 44)
    button(console, 1, 'Share game', app.backend.share_game, 'Cyan', 28, 161, 170)
    label(console, 1, 'Join a friend (Paste the full invite link)', 28, 218, 675, True)
    app.join_address = tk.StringVar()
    entry(console, 1, app.join_address, 28, 253, 527)
    button(console, 1, 'Join', app.join_remote, 'Green', 568, 253, 135)
    # Reference section bars meet at the same height on both columns.
    # The two input rows fit above Session notes at y=326.
    app.status = tk.StringVar(value='Ready when you are')
    app.status.trace_add('write', lambda *_: app.title('Clienter | ' + app.status.get()))
    output_border = tk.Frame(console, bg=BORDER)
    position(output_border, 1, 28, 408, 675, 222)
    app.output = ScrolledText(output_border, state='disabled', bg='white', fg=INK,
                              insertbackground=INK, relief='flat', borderwidth=0,
                              padx=10, pady=10, font=app.reference_log_font, wrap='word')
    app.output.place(x=3, y=3, relwidth=1, relheight=1, width=-6, height=-6)
    def scroll_notes(first, last):
        app.output.vbar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            app.output.vbar.pack_forget()
        else:
            app.output.vbar.pack(side='right', fill='y')
    app.output.configure(yscrollcommand=scroll_notes)
    app.output.tag_configure('error', foreground='#c42121')
    app.output.tag_configure('success', foreground='#008644')
    for text, action, color, x, y, width in (
            ('Start backend', app.start, 'Cyan', 28, 640, 338),
            ('Stop game', app.backend.stop_game, 'Red', 377, 640, 326),
            ('Stop all', app.backend.stop, 'Red', 28, 685, 338),
            ('Restore settings', app.restore, 'Green', 377, 685, 326)):
        button(console, 1, text, action, color, x, y, width, 40)
    app.backdrop.bind('<Configure>', app.resize_background)


def build_connection_dialog(app):
    dialog = tk.Toplevel(app)
    app.connection_dialog = dialog
    dialog.withdraw()
    dialog.title('Connection settings')
    dialog.transient(app)
    dialog.resizable(False, False)
    dialog.protocol('WM_DELETE_WINDOW', dialog.withdraw)
    dialog.configure(bg=PANEL)
    tk.Label(dialog, text='Connection Settings', bg='#0074bd', fg='white',
             font=(UI_FONT, 17), pady=10).pack(fill='x')
    content = ttk.Frame(dialog, padding=20)
    content.pack(fill='both', expand=True)
    ttk.Label(content, text='Stop the session before changing ports.', style='Muted.TLabel').pack(anchor='w', pady=(6, 16))
    ports = ttk.Frame(content)
    ports.pack(fill='x')
    for column, (label, key, default) in enumerate((('HTTP', 'web', '80'), ('SOAP', 'soap', '64989'), ('GAME', 'game', '53640'))):
        variable = app.fields[key] = tk.StringVar(value=default)
        ttk.Label(ports, text=label, style='Muted.TLabel').grid(row=0, column=column, sticky='w')
        ttk.Entry(ports, textvariable=variable, width=7).grid(row=1, column=column, padx=(0, 8), pady=(4, 0))
    ttk.Button(content, text='Done', style='Primary.TButton', command=dialog.withdraw).pack(fill='x', pady=(18, 0))
    def show():
        dialog.geometry(f'+{app.winfo_rootx()+80}+{app.winfo_rooty()+160}')
        dialog.deiconify()
        dialog.lift()
    app.connection_toggle.configure(command=show)


def configure_dialog_theme(root):
    """Shared reference palette for the secondary windows and their controls."""
    style = ttk.Style(root)
    for name in ('TFrame', 'Card.TFrame'):
        style.configure(name, background=PANEL)
    style.configure('TLabel', background=PANEL, foreground=INK, font=(UI_FONT, 11))
    style.configure('Muted.TLabel', background=PANEL, foreground='#737373', font=(UI_FONT, 10))
    style.configure('Section.TLabel', background=PANEL, foreground=INK, font=(UI_FONT, 13, 'bold'))
    style.configure('TEntry', foreground=INK, fieldbackground='white', bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, borderwidth=2, padding=6, font=(UI_FONT, 11))
    for name, color, hover in (('TButton', '#38b6ff', '#169ee9'),
                              ('Primary.TButton', '#00bf63', '#00a453'),
                              ('Danger.TButton', '#ff3131', '#e32020')):
        style.configure(name, background=color, foreground='white', padding=(12, 8),
                        borderwidth=0, font=(UI_FONT, 11))
        style.map(name, background=[('disabled', '#bdc7d3'), ('active', hover)],
                  foreground=[('disabled', '#eef1f5'), ('!disabled', 'white')])
        rounded_button_style(root, name, color, hover, 'white')


def rounded_button_style(root, name, color, hover, foreground, font=None, padding=(12, 8)):
    """Keep rounded ttk surfaces alive on the root, across dialog reopenings."""
    master = root._root()
    style = ttk.Style(root)
    if not hasattr(master, '_rounded_dialog_surfaces'):
        master._rounded_dialog_surfaces = {}
    element = 'Clienter.' + name + '.surface'
    if element not in master._rounded_dialog_surfaces:
        images = []
        for fill in (color, hover, '#bdc7d3'):
            surface = Image.new('RGBA', (16, 16), PANEL)
            ImageDraw.Draw(surface).rounded_rectangle((0, 0, 15, 15), radius=5, fill=fill)
            images.append(ImageTk.PhotoImage(surface, master=master))
        master._rounded_dialog_surfaces[element] = images
        style.element_create(element, 'image', images[0], ('disabled', images[2]),
                             ('pressed', images[1]), ('active', images[1]), border=6, sticky='nsew')
    style.configure(name, foreground=foreground, font=font or (UI_FONT, 11), padding=padding, borderwidth=0)
    style.map(name, foreground=[('disabled', '#eef1f5'), ('!disabled', foreground)])
    style.layout(name, [(element, {'sticky': 'nsew', 'children': [
        ('Button.padding', {'sticky': 'nsew', 'children': [('Button.label', {'sticky': 'nsew'})]})]})])


def layout(app, width, height):
    scale = min(width/1185, height/1029)
    margin, gap = 22*scale, 12*scale
    available = width - (22+28)*scale - gap
    left_width = available * 395/1123
    right_width = available - left_width
    top, panel_height = 160*scale, 744*scale
    app.backdrop.coords(app.controls_window, margin, top)
    app.backdrop.coords(app.console_window, margin+left_width+gap, top)
    app.backdrop.itemconfigure(app.controls_window, width=round(left_width), height=round(panel_height))
    app.backdrop.itemconfigure(app.console_window, width=round(right_width), height=round(panel_height))
    for widget, column, x, y, w, h in app.reference_items:
        horizontal = left_width/395 if column == 0 else right_width/728
        widget.place(x=round(x*horizontal), y=round(y*scale), width=round(w*horizontal), height=max(1, round(h*scale)))
    horizontal = left_width/395
    if app.fields['rig'].get() == 'Custom':
        app.custom_controls.place(x=round(20*horizontal), y=round(256*scale), width=round(170*horizontal), height=round(44*scale))
        app.apply_character_button.place(x=round(200*horizontal), width=round(175*horizontal))
    else:
        app.custom_controls.place_forget()
    app.reference_font.configure(size=max(11, round(15*scale)))
    app.reference_heading.configure(size=max(12, round(17*scale)))
    app.reference_log_font.configure(size=max(10, round(14*scale)))
    app.backdrop.coords(app.reference_stripe, 28*scale, 33*scale, 38*scale, 133*scale)
    app.backdrop.coords(app.reference_logo_item, 72*scale, 29*scale)
    app.backdrop.coords(app.reference_logo_shadow, 62*scale, 19*scale)
    if app.background_resize is not None:
        app.after_cancel(app.background_resize)
    def paint():
        app.paint_background(width, height)
        logo = app.reference_logo_source.copy()
        logo.thumbnail((max(1, round(290*scale)), max(1, round(100*scale))), Image.Resampling.LANCZOS)
        pad = max(1, round(10*scale))
        shadow = Image.new('RGBA', (logo.width+2*pad, logo.height+2*pad))
        silhouette = Image.new('RGBA', logo.size, '#000000')
        silhouette.putalpha(logo.getchannel('A').point(lambda alpha: round(alpha*.8)))
        shadow.alpha_composite(silhouette, (pad+round(2*scale), pad+round(2*scale)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(max(1, 3*scale)))
        app.header_logo_shadow = ImageTk.PhotoImage(shadow, master=app)
        app.backdrop.itemconfigure(app.reference_logo_shadow, image=app.header_logo_shadow)
        app.header_logo = ImageTk.PhotoImage(logo, master=app)
        app.backdrop.itemconfigure(app.reference_logo_item, image=app.header_logo)
    app.background_resize = app.after(75, paint)
