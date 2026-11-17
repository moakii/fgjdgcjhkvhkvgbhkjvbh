"""Offline wardrobe, saved custom outfits, and the Tk avatar editor."""
from pathlib import Path
import copy
import hashlib
import json
import re
import shutil
import tkinter as tk
from tkinter import ttk, colorchooser, messagebox
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk
from ui_fonts import UI_FONT
from launcher_view import configure_dialog_theme, rounded_button_style, PANEL, INK

ROOT = Path(__file__).resolve().parent
BODY_PARTS = ('Head', 'Torso', 'LeftArm', 'RightArm', 'LeftLeg', 'RightLeg')
BUNDLE_IDS = ('blocky', 'man', 'robloxian2', 'woman', 'roblox-boy', 'roblox-girl',
              'roblox-girl2', 'superhero', 'cool-punk-kid', 'action-figure')
DEFAULT_PROFILE = {'bundle': 'blocky', 'hats': [], 'shirt': None, 'pants': None,
                   'colors': {part: '#f8d5a3' for part in BODY_PARTS}}
SKIN_PALETTE = ('#f8d5a3', '#eab892', '#cc8e69', '#a36648', '#7c5035', '#5a3825',
                '#f2f3f3', '#e5e4df', '#a3a2a5', '#635f62', '#f5cd30', '#f8f8f8',
                '#0d69ac', '#4b974b', '#c4281c', '#6b327c', '#da867a', '#a2c4e8')


def validate_profile(profile):
    if not isinstance(profile, dict): raise ValueError('Invalid custom outfit.')
    hats = profile.get('hats', [])
    if not isinstance(hats, list) or len(hats) > 3 or len(set(map(str, hats))) != len(hats):
        raise ValueError('Choose up to three different hats.')
    if not isinstance(profile.get('colors', {}), dict): raise ValueError('Invalid custom skin colors.')
    bundle = profile.get('bundle', 'blocky')
    if bundle not in BUNDLE_IDS: raise ValueError('Choose one of the ten available body bundles.')
    result = {'bundle': bundle, 'hats': [str(item) for item in hats], 'shirt': None, 'pants': None, 'colors': {}}
    for category in ('shirt', 'pants'):
        if profile.get(category) is not None: result[category] = str(profile[category])
    for part in BODY_PARTS:
        color = profile.get('colors', {}).get(part, DEFAULT_PROFILE['colors'][part])
        if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError(f'Choose a valid {part} color.')
        result['colors'][part] = color.lower()
    return result


def load_profile():
    try:
        return validate_profile(json.loads((ROOT / 'custom_avatar.json').read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError):
        return copy.deepcopy(DEFAULT_PROFILE)


def save_profile(profile):
    profile = validate_profile(profile)
    temporary = ROOT / 'custom_avatar.json.tmp'
    temporary.write_text(json.dumps(profile, indent=2), encoding='utf-8')
    temporary.replace(ROOT / 'custom_avatar.json')


class Wardrobe:
    def __init__(self):
        self.root = ROOT / 'assets/wardrobe'
        try:
            self.catalog = json.loads((self.root / 'catalog.json').read_text(encoding='utf-8'))
        except (OSError, ValueError) as error:
            raise ValueError('Wardrobe assets are missing. Run python tools/setup_wardrobe.py.') from error
        if {item['id'] for item in self.catalog.get('bundles', [])} != set(BUNDLE_IDS):
            raise ValueError('Body bundles are missing. Run python tools/setup_bundles.py.')
        self.items = {category: {item['id']: item for item in self.catalog[category]}
                      for category in ('hats', 'shirts', 'pants', 'bundles')}

    def payload(self, profile):
        profile = validate_profile(profile)
        result = {'hats': [], 'shirt': None, 'pants': None, 'colors': {}}
        bundle = self.items['bundles'].get(profile['bundle'])
        if bundle is None: raise ValueError('Body bundle cache is missing. Run python tools/setup_bundles.py.')
        result['bundle'] = bundle['id']
        result['body_meshes'] = copy.deepcopy(bundle['parts'])
        for category, ids in (('hats', profile['hats']), ('shirts', [profile['shirt']]), ('pants', [profile['pants']])):
            for item_id in ids:
                if item_id is None: continue
                item = self.items[category].get(item_id)
                if item is None: raise ValueError(f'This {category} item is no longer in the offline wardrobe: {item_id}')
                filename = item['file']
                path = Path(filename)
                if path.is_absolute() or '..' in path.parts or filename not in self.catalog['files']:
                    raise ValueError('Invalid cached wardrobe path.')
                if category == 'hats': result['hats'].append(filename)
                else: result['shirt' if category == 'shirts' else 'pants'] = filename
        for part, color in profile['colors'].items():
            result['colors'][part] = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        return result

    def install(self, runtime):
        for filename, metadata in self.catalog['files'].items():
            if filename.startswith('thumbnails/'): continue
            relative = Path(filename)
            if relative.is_absolute() or '..' in relative.parts: raise ValueError('Invalid wardrobe file path.')
            source = self.root / relative
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() != metadata['sha256']:
                raise ValueError(f'Wardrobe cache integrity check failed: {filename}')
            for folder in ('RobloxPlayer', 'RCCService'):
                target = Path(runtime) / folder / 'content/wardrobe' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or target.read_bytes() != data: shutil.copy2(source, target)


class AvatarEditor(tk.Toplevel):
    PAGE_SIZE = 12

    def __init__(self, parent, profile, on_save):
        self.wardrobe = Wardrobe()
        super().__init__(parent)
        self.title('Clienter | Customize your avatar')
        self.geometry('1080x800')
        self.minsize(990, 760)
        self.configure(bg=PANEL)
        self.transient(parent)
        configure_dialog_theme(self)
        for name, color in (('Item.Avatar.TButton', '#ffffff'), ('Selected.Avatar.TButton', '#d4e2fa')):
            rounded_button_style(self, name, color, '#e3ecfb', INK, font=(UI_FONT, 9), padding=(2, 2))
            ttk.Style(self).configure(name, wraplength=115, anchor='center')
        style = ttk.Style(self)
        style.configure('Avatar.Title.TLabel', background=PANEL, foreground=INK, font=(UI_FONT, 16, 'bold'))
        style.configure('Avatar.TNotebook', background=PANEL, borderwidth=0)
        style.configure('Avatar.TNotebook.Tab', background='white', foreground=INK, padding=(12, 9))
        style.map('Avatar.TNotebook.Tab', background=[('selected', '#0074bd')], foreground=[('selected', 'white')])
        self.profile = validate_profile(copy.deepcopy(profile))
        self.on_save = on_save
        self.photos = []
        self.preview_photos = []
        self.page = 0
        self.category = 'hats'
        tk.Label(self, text='Customize avatar', bg='#0074bd', fg='white',
                 font=(UI_FONT, 17), pady=10).pack(fill='x')
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='10 body bundles  /  100 hats  /  100 shirts  /  100 pants  /  Your colors',
                  style='Muted.TLabel').pack(anchor='w', pady=(2, 16))
        # Reserve the footer before the expanding browser, even at minimum size.
        footer = ttk.Frame(outer)
        footer.pack(side='bottom', fill='x', pady=(16, 0))
        ttk.Label(footer, text='Up to 3 hats. Save, then wear it in the launcher.',
                  style='Muted.TLabel').pack(side='left')
        ttk.Button(footer, text='Cancel', style='Danger.TButton', command=self.destroy).pack(side='right')
        ttk.Button(footer, text='Save outfit', style='Primary.TButton', command=self.save).pack(side='right', padx=8)
        body = ttk.Frame(outer)
        body.pack(fill='both', expand=True)
        preview = ttk.Frame(body, style='Card.TFrame', padding=16)
        preview.pack(side='left', fill='y', padx=(0, 16))
        tk.Label(preview, text='Your outfit', bg='#0074bd', fg='white', font=(UI_FONT, 12), pady=7).pack(fill='x')
        self.preview = tk.Canvas(preview, width=230, height=290, bg='white', highlightthickness=2, highlightbackground='#adb2b9')
        self.preview.pack(pady=(12, 8))
        ttk.Label(preview, text='2D outfit preview · body shown in-game', wraplength=230, style='Muted.TLabel').pack()
        self.summary = tk.StringVar()
        summary = ScrolledText(preview, width=24, height=5, wrap='word', state='disabled',
                               bg=PANEL, fg=INK, relief='flat', borderwidth=0, font=(UI_FONT, 10))
        summary.pack(fill='both', expand=True, pady=8)
        def update_summary(*_):
            summary.configure(state='normal')
            summary.delete('1.0', 'end')
            summary.insert('1.0', self.summary.get())
            summary.configure(state='disabled')
        self.summary.trace_add('write', update_summary)
        ttk.Button(preview, text='Reset outfit', style='Danger.TButton', command=self.reset).pack(side='bottom', fill='x', before=self.preview)
        ttk.Button(preview, text='Remove all hats', command=self.clear_hats).pack(side='bottom', fill='x', pady=(0, 6), before=self.preview)
        browser = ttk.Frame(body, style='Card.TFrame', padding=16)
        browser.pack(side='left', fill='both', expand=True)
        tk.Label(browser, text='Wardrobe', bg='#0074bd', fg='white', font=(UI_FONT, 12), pady=7).pack(fill='x', pady=(0, 8))
        self.tabs = ttk.Notebook(browser, style='Avatar.TNotebook')
        self.tabs.pack(fill='both', expand=True)
        self.tab_frames = {}
        for category, label in (('hats', 'Hats'), ('shirts', 'Shirts'), ('pants', 'Pants'),
                                ('bundles', 'Body bundles'), ('skin', 'Skin colors')):
            frame = ttk.Frame(self.tabs, style='Card.TFrame', padding=8)
            self.tabs.add(frame, text=label)
            self.tab_frames[category] = frame
        # One browser is moved between category tabs; all images are loaded locally.
        self.browser = ttk.Frame(self.tabs, style='Card.TFrame')
        self.bundle_hint = ttk.Label(self.browser, text='Body shape only; hats, clothes and skin colors stay selected.',
                                     style='Muted.TLabel', wraplength=600)
        search_row = ttk.Frame(self.browser, style='Card.TFrame')
        search_row.pack(fill='x', pady=(0, 8))
        self.search = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.search).pack(side='left', fill='x', expand=True)
        ttk.Button(search_row, text='Clear', command=lambda: self.search.set('')).pack(side='left', padx=(8, 0))
        self.item_grid = ttk.Frame(self.browser, style='Card.TFrame')
        self.item_grid.pack(fill='both', expand=True)
        for column in range(4): self.item_grid.columnconfigure(column, weight=1, uniform='item')
        for row in range(3): self.item_grid.rowconfigure(row, weight=1, uniform='item')
        # Tk interprets text-only button dimensions in characters/lines, but
        # image buttons use pixels. Give every tile an image to keep units equal.
        self.blank_thumbnail = tk.PhotoImage(master=self, width=64, height=64)
        navigation = ttk.Frame(self.browser, style='Card.TFrame')
        navigation.pack(side='bottom', fill='x', pady=(8, 0), before=self.item_grid)
        self.previous = ttk.Button(navigation, text='Previous', command=lambda: self.change_page(-1))
        self.previous.pack(side='left')
        self.page_label = ttk.Label(navigation, style='Muted.TLabel')
        self.page_label.pack(side='left', expand=True)
        self.next = ttk.Button(navigation, text='Next', command=lambda: self.change_page(1))
        self.next.pack(side='right')
        self.make_skin_tab()
        self.tabs.bind('<<NotebookTabChanged>>', self.change_tab)
        self.search.trace_add('write', lambda *_: self.search_changed())
        self.change_tab()
        self.draw_preview()

    def make_skin_tab(self):
        frame = self.tab_frames['skin']
        ttk.Label(frame, text='Color each body part', style='Section.TLabel').pack(anchor='w', pady=(4, 12))
        self.color_buttons = {}
        for part in BODY_PARTS:
            row = ttk.Frame(frame, style='Card.TFrame')
            row.pack(fill='x', pady=4)
            ttk.Label(row, text=re.sub(r'([a-z])([A-Z])', r'\1 \2', part), width=14).pack(side='left')
            button = ttk.Button(row, width=12, command=lambda p=part: self.pick_color(p))
            button.pack(side='left')
            self.color_buttons[part] = button
        ttk.Label(frame, text='Quick palette · set every body part', style='Muted.TLabel').pack(anchor='w', pady=(24, 10))
        palette = ttk.Frame(frame, style='Card.TFrame')
        palette.pack(anchor='w')
        for index, color in enumerate(SKIN_PALETTE):
            ttk.Button(palette, text=' ', width=5, style=self.color_style(color),
                      command=lambda c=color: self.set_all_colors(c)).grid(row=index // 6, column=index % 6, padx=4, pady=4)
        ttk.Label(frame, text='The 2016 engine uses its closest available BrickColor.',
                  style='Muted.TLabel').pack(anchor='w', pady=14)

    def color_style(self, color):
        name = 'Color' + color[1:] + '.Avatar.TButton'
        brightness = sum(int(color[i:i+2], 16) for i in (1, 3, 5))/3
        rounded_button_style(self, name, color, color, '#101820' if brightness > 140 else '#ffffff', padding=(8, 6))
        return name

    def change_tab(self, _event=None):
        self.category = tuple(self.tab_frames)[self.tabs.index(self.tabs.select())]
        self.page = 0
        self.browser.pack_forget()
        if self.category != 'skin':
            self.browser.pack(in_=self.tab_frames[self.category], fill='both', expand=True)
            if self.category == 'bundles': self.bundle_hint.pack(side='bottom', fill='x', pady=(8, 0), before=self.item_grid)
            else: self.bundle_hint.pack_forget()
            self.render_items()

    def search_changed(self):
        self.page = 0
        if self.category != 'skin': self.render_items()

    def change_page(self, delta):
        self.page += delta
        self.render_items()

    def render_items(self):
        for child in self.item_grid.winfo_children(): child.destroy()
        self.photos = []
        query = self.search.get().strip().casefold()
        entries = list(self.wardrobe.catalog[self.category])
        if self.category != 'bundles': entries.insert(0, {'id': None, 'name': 'None', 'creator': ''})
        entries = [e for e in entries if not query or query in (e['name'] + ' ' + e.get('creator', '')).casefold()]
        pages = max(1, (len(entries) + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self.page = min(max(0, self.page), pages - 1)
        if not entries:
            ttk.Label(self.item_grid, text='No matches. Try another search.', style='Muted.TLabel').grid(row=0, column=0, columnspan=4, pady=30)
        for index, item in enumerate(entries[self.page * self.PAGE_SIZE:(self.page + 1) * self.PAGE_SIZE]):
            if self.category == 'hats': chosen = item['id'] in self.profile['hats']
            else: chosen = item['id'] == self.profile[{'shirts': 'shirt', 'pants': 'pants', 'bundles': 'bundle'}[self.category]]
            tile = ttk.Frame(self.item_grid, style='Card.TFrame', width=130, height=138)
            tile.grid(row=index // 4, column=index % 4, sticky='nsew', padx=3, pady=3)
            tile.pack_propagate(False)
            photo = None
            if item.get('thumbnail'):
                try:
                    with Image.open(self.wardrobe.root / item['thumbnail']) as source:
                        source.thumbnail((64, 64))
                        photo = ImageTk.PhotoImage(source.copy(), master=self)
                    self.photos.append(photo)
                except OSError: pass
            label = ('✓ ' if chosen else '') + item['name']
            button = ttk.Button(tile, text=label, image=photo or self.blank_thumbnail, compound='top',
                                style='Selected.Avatar.TButton' if chosen else 'Item.Avatar.TButton',
                                cursor='hand2', command=lambda i=item: self.select_item(i))
            button.pack(fill='both', expand=True)
        self.page_label.configure(text=f'{self.page + 1} / {pages}  ·  {len(entries)} items')
        self.previous.configure(state='normal' if self.page else 'disabled')
        self.next.configure(state='normal' if self.page + 1 < pages else 'disabled')

    def select_item(self, item):
        item_id = item['id']
        if self.category == 'hats':
            if item_id is None: self.profile['hats'] = []
            elif item_id in self.profile['hats']: self.profile['hats'].remove(item_id)
            elif len(self.profile['hats']) < 3: self.profile['hats'].append(item_id)
            else:
                messagebox.showinfo('Hat limit', 'Remove a selected hat before adding another. You can wear three hats.', parent=self)
                return
        else: self.profile[{'shirts': 'shirt', 'pants': 'pants', 'bundles': 'bundle'}[self.category]] = item_id
        self.render_items()
        self.draw_preview()

    def clear_hats(self):
        self.profile['hats'] = []
        if self.category == 'hats': self.render_items()
        self.draw_preview()

    def reset(self):
        self.profile = copy.deepcopy(DEFAULT_PROFILE)
        if self.category != 'skin': self.render_items()
        self.draw_preview()

    def pick_color(self, part):
        _, color = colorchooser.askcolor(self.profile['colors'][part], title=f'{part} color', parent=self)
        if color:
            self.profile['colors'][part] = color
            self.draw_preview()

    def set_all_colors(self, color):
        self.profile['colors'] = {part: color for part in BODY_PARTS}
        self.draw_preview()

    def draw_preview(self):
        canvas = self.preview
        canvas.delete('all')
        self.preview_photos = []
        boxes = {'Head': (89, 36, 141, 88), 'Torso': (66, 92, 164, 190),
                 'RightArm': (16, 92, 62, 190), 'LeftArm': (168, 92, 214, 190),
                 'RightLeg': (66, 194, 113, 282), 'LeftLeg': (117, 194, 164, 282)}
        for part, box in boxes.items():
            canvas.create_rectangle(*box, fill=self.profile['colors'][part], outline='#182639', width=2)
        # Classic template front panels, scaled from the standard 585 x 559 atlas.
        for category, key, crops in (
            ('shirts', 'shirt', {'Torso': (231, 74, 359, 202), 'RightArm': (165, 355, 229, 483), 'LeftArm': (361, 355, 425, 483)}),
            ('pants', 'pants', {'Torso': (231, 74, 359, 202), 'RightLeg': (165, 355, 229, 483), 'LeftLeg': (361, 355, 425, 483)})):
            item = self.wardrobe.items[category].get(self.profile[key])
            if not item: continue
            try:
                with Image.open(self.wardrobe.root / item['file']) as source:
                    image = source.convert('RGBA').resize((585, 559))
                    for part, crop in crops.items():
                        x, y, right, bottom = boxes[part]
                        texture = image.crop(crop).resize((right - x, bottom - y))
                        photo = ImageTk.PhotoImage(texture, master=self)
                        self.preview_photos.append(photo)
                        canvas.create_image(x, y, image=photo, anchor='nw')
            except OSError: pass
        canvas.create_oval(101, 55, 105, 60, fill='#172136', outline='')
        canvas.create_oval(125, 55, 129, 60, fill='#172136', outline='')
        canvas.create_arc(102, 58, 129, 78, start=195, extent=150, style='arc', outline='#172136', width=2)
        # Hat thumbnails are shown above the mannequin; placement is applied in-game.
        for index, hat_id in enumerate(self.profile['hats']):
            item = self.wardrobe.items['hats'].get(hat_id)
            if item and item.get('thumbnail'):
                try:
                    with Image.open(self.wardrobe.root / item['thumbnail']) as source:
                        source.thumbnail((46, 46))
                        photo = ImageTk.PhotoImage(source.copy(), master=self)
                    self.preview_photos.append(photo)
                    canvas.create_image(40 + index * 75, 20, image=photo)
                except OSError: pass
        names = ['Body: ' + self.wardrobe.items['bundles'][self.profile['bundle']]['name']]
        names += [self.wardrobe.items['hats'][i]['name'] for i in self.profile['hats'] if i in self.wardrobe.items['hats']]
        for category, key in (('shirts', 'shirt'), ('pants', 'pants')):
            item = self.wardrobe.items[category].get(self.profile[key])
            names.append(item['name'] if item else 'No ' + key)
        self.summary.set('\n'.join(names or ['No hats selected']))
        for part, button in self.color_buttons.items():
            color = self.profile['colors'][part]
            button.configure(style=self.color_style(color), text=color.upper())

    def save(self):
        try:
            self.wardrobe.payload(self.profile)
            save_profile(self.profile)
            self.on_save(copy.deepcopy(self.profile))
        except (ValueError, OSError) as error:
            messagebox.showerror('Save outfit', str(error), parent=self)
            return
        self.destroy()
