#!/usr/bin/env python3
"""The Mac's single-window publisher; work continues in separate processes."""
import argparse
import ctypes
import fcntl
import json
import math
import platform
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import zipfile
from urllib.parse import urlsplit, unquote

import escape_pod_cast as p

HERE = Path(__file__).resolve().parent
SOURCE_REPO = 'udeudeude/Escape-Pod-Cast'
APP_VERSION = '0.6.0'
UPDATE_FILES = ('mac/escape_pod_cast.py', 'mac/app.py', 'mac/install.py')
CREAM, PANEL, INK, ORANGE = '#f7f2e8', '#fffcf6', '#172e3e', '#aa4824'
AUDIO_TYPES = ('.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg', '.opus', '.aif', '.aiff', '.mp4')


def transmission_position(job=None, updating=False):
    """A discrete process stage, never an invented completion percentage."""
    if updating:
        return 0, 'TUNING', ORANGE
    if not job or job['state'] == 'cancelled':
        return 0, 'READY', INK
    if job['state'] == 'failed':
        return 0, 'CHECK SIGNAL', '#963d32'
    if job['state'] == 'done':
        return (3, 'ON AIR', '#386451') if job['kind'] in ('file', 'youtube') else (0, 'READY', INK)
    if job['state'] == 'queued':
        return 0, 'WAITING', ORANGE
    stage = job.get('stage', '').lower()
    if any(word in stage for word in ('upload', 'feed', 'episode', 'playback', 'delivery', 'enclosure', 'publishing')):
        return 2, 'TRANSMITTING', ORANGE
    return 1, 'PREPARING', ORANGE


class TapeDeck:
    """Scrollable tape labels with real focusable buttons, not painted text controls.

    The small Treeview-compatible surface keeps queue selection/recovery unchanged.
    Keyboard users can Tab/Return/Space or move with the arrow keys.
    """
    def __init__(self, parent, tk):
        self.tk = tk
        self.canvas = tk.Canvas(parent, background='#ded5bf', highlightthickness=1,
                                highlightbackground=INK, height=180, takefocus=0)
        self.items, self.buttons, self.selected = {}, {}, None
        self.on_select = None
        self.canvas.bind('<Configure>', lambda event: self.draw())
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<Button-4>', lambda event: self.canvas.yview_scroll(-1, 'units'))
        self.canvas.bind('<Button-5>', lambda event: self.canvas.yview_scroll(1, 'units'))

    def grid(self, **options):
        self.canvas.grid(**options)

    def bind(self, event, callback):
        self.on_select = callback

    def configure(self, **options):
        self.canvas.configure(**options)

    def yview(self, *args):
        return self.canvas.yview(*args)

    def wheel(self, event):
        delta = event.delta
        if delta:
            step = max(1, abs(delta) // 120) if sys.platform != 'darwin' else min(4, abs(delta))
            self.canvas.yview_scroll(-step if delta > 0 else step, 'units')
        return 'break'

    def get_children(self):
        return tuple(self.items)

    def exists(self, iid):
        return iid in self.items

    def item(self, iid):
        return self.items[iid]

    def selection(self):
        return (self.selected,) if self.selected in self.items else ()

    def delete(self, *ids):
        for iid in ids:
            self.items.pop(iid, None)
            button = self.buttons.pop(iid, None)
            if button:
                button.destroy()

    def insert(self, parent, index, iid, text, values, number=1):
        self.items[iid] = {'text': text, 'values': list(values), 'number': number}

    def sync(self, entries):
        """Keep focusable buttons and scrolling when queue status changes."""
        wanted = {entry['id'] for entry in entries}
        self.delete(*(key for key in self.items if key not in wanted))
        self.items = {entry['id']: {'text': entry['label'], 'values': [entry['status']],
                                   'number': entry['number']} for entry in entries}
        self.draw()

    def selection_set(self, iid):
        self.selected = iid
        for key, button in self.buttons.items():
            button.configure(background='#f3dfb9' if key == iid else PANEL)

    def choose(self, iid):
        self.selection_set(iid)
        if self.on_select:
            self.on_select()

    def move(self, iid, step):
        keys = list(self.items)
        index = max(0, min(len(keys)-1, keys.index(iid) + step))
        target = keys[index]
        self.buttons[target].focus_set()
        self.choose(target)
        height = max(1, self.canvas.winfo_height())
        top, bottom = index * 94, (index + 1) * 94
        current = self.canvas.canvasy(0)
        if top < current or bottom > current + height:
            self.canvas.yview_moveto(max(0, top-8) / max(1, len(keys)*94+12))
        return 'break'

    def draw(self):
        c = self.canvas
        offset = c.yview()[0]
        c.delete('all')
        width = max(400, c.winfo_width())
        if not self.items:
            c.create_text(24, 35, text='THE TAPE RACK IS EMPTY', anchor='w', fill=INK,
                          font=('Courier', 13, 'bold'))
            c.create_text(24, 62, text='Feed the hatch a track. It will appear here.', anchor='w', fill=INK,
                          font=('Helvetica', 12))
        for index, (iid, item) in enumerate(self.items.items()):
            y = index * 94 + 10
            c.create_polygon(19, y+4, width-23, y+4, width-11, y+15, width-11, y+77,
                             width-23, y+87, 19, y+87, 9, y+77, 9, y+15,
                             fill='#bcb39f', outline='')
            c.create_polygon(17, y, width-25, y, width-15, y+10, width-15, y+73,
                             width-25, y+83, 17, y+83, 7, y+73, 7, y+10,
                             fill=PANEL, outline=INK, width=1)
            c.create_rectangle(14, y+12, 19, y+71, fill=ORANGE, outline='')
            c.create_text(30, y+11, text=f"EPC / {item['number']:03d}     PERSONAL TRANSMISSION", anchor='w',
                          font=('Courier', 9, 'bold'), fill=ORANGE)
            button = self.buttons.get(iid)
            if button is None:
                button = self.tk.Button(c, command=lambda key=iid: self.choose(key),
                                        anchor='w', justify='left', relief='flat', borderwidth=0,
                                        foreground=INK, activeforeground=INK, activebackground='#f3dfb9',
                                        highlightthickness=2, highlightcolor=ORANGE, highlightbackground=PANEL,
                                        font=('Helvetica', 12, 'bold'), padx=4, takefocus=True)
                button.bind('<Up>', lambda event, key=iid: self.move(key, -1))
                button.bind('<Down>', lambda event, key=iid: self.move(key, 1))
                button.bind('<MouseWheel>', self.wheel)
                self.buttons[iid] = button
            # Long filenames remain available in the selectable detail text.
            title = item['text']
            limit = max(24, int((width-150)/8))
            title = title if len(title) <= limit else title[:limit-1] + '…'
            button.configure(text=title + '\n' + item['values'][0],
                             background='#f3dfb9' if iid == self.selected else PANEL)
            c.create_window(28, y+23, window=button, anchor='nw', width=width-148, height=53)
            for x in (width-98, width-48):
                c.create_oval(x-14, y+30, x+14, y+58, outline=INK, width=2)
                c.create_oval(x-4, y+40, x+4, y+48, fill=INK, outline='')
            c.create_line(width-84, y+44, width-62, y+44, fill=ORANGE, width=2)
            c.create_text(width-73, y+70, text='SIDE A', fill=INK, font=('Courier', 9))
        c.configure(scrollregion=(0, 0, width, max(c.winfo_height(), len(self.items)*94+12)), yscrollincrement=24)
        c.yview_moveto(offset)


def drop_inputs(values):
    """Validate a drag without publishing, preserving spaces and Unicode in paths."""
    accepted, rejected = [], []
    for value in values:
        value = str(value).strip()
        try:
            parsed = urlsplit(value)
            if parsed.scheme == 'file':
                if parsed.netloc not in ('', 'localhost'):
                    raise ValueError('Only local files can be dropped.')
                value = unquote(parsed.path)
            path = Path(value)
            if path.is_file():
                if path.suffix.lower() in p.LINK_TYPES:
                    item = ('youtube', p.link_file(path))
                elif path.suffix.lower() in AUDIO_TYPES:
                    item = ('file', str(path.resolve()))
                else:
                    raise ValueError('This is not a supported audio track or saved YouTube link.')
            else:
                item = ('youtube', p.youtube_url(value)[0])
            if item not in accepted:
                accepted.append(item)
        except (p.Failure, OSError, ValueError) as exc:
            rejected.append(str(exc))
    return accepted, rejected


class _Point(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]


class _Size(ctypes.Structure):
    _fields_ = [('width', ctypes.c_double), ('height', ctypes.c_double)]


class _Rect(ctypes.Structure):
    _fields_ = [('origin', _Point), ('size', _Size)]


class MacDropZone:
    """A transparent Cocoa dragging destination over the Tk drop panel.

    Uses only macOS frameworks; callbacks stay alive as long as their ObjC class.
    No clipboard polling, browser access, third-party Tk binaries, or permissions.
    """
    instances, callbacks = {}, []

    def __init__(self, window):
        self.window, self.view = window, None
        ctypes.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
        self.objc = ctypes.CDLL('/usr/lib/libobjc.A.dylib')
        for name, args, result in (
            ('objc_getClass', [ctypes.c_char_p], ctypes.c_void_p),
            ('sel_registerName', [ctypes.c_char_p], ctypes.c_void_p),
            ('objc_allocateClassPair', [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t], ctypes.c_void_p),
            ('class_addMethod', [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p], ctypes.c_bool),
            ('objc_registerClassPair', [ctypes.c_void_p], None)):
            fn = getattr(self.objc, name)
            fn.argtypes, fn.restype = args, result
        cls = self.objc.objc_getClass(b'EPCPodcastDropView')
        if not cls:
            cls = self.objc.objc_allocateClassPair(self.objc.objc_getClass(b'NSView'), b'EPCPodcastDropView', 0)
            bool_encoding = b'c@:@' if platform.machine() == 'x86_64' else b'B@:@'
            for name, result, encoding, action in (
                ('draggingEntered:', ctypes.c_ulong, b'Q@:@', 'preview'),
                ('draggingUpdated:', ctypes.c_ulong, b'Q@:@', 'preview'),
                ('draggingExited:', None, b'v@:@', 'exit'),
                ('prepareForDragOperation:', ctypes.c_bool, bool_encoding, 'prepare'),
                ('performDragOperation:', ctypes.c_bool, bool_encoding, 'perform'),
                ('concludeDragOperation:', None, b'v@:@', 'exit')):
                def callback(receiver, selector, sender, action=action):
                    instance = MacDropZone.instances.get(receiver)
                    if not instance:
                        return False
                    try:
                        return instance.event(action, sender)
                    except Exception as exc:
                        print('Window drop failed:', exc, flush=True)
                        return False
                fn = ctypes.CFUNCTYPE(result, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(callback)
                self.callbacks.append(fn)
                self.objc.class_addMethod(cls, self.sel(name), ctypes.cast(fn, ctypes.c_void_p), encoding)
            self.objc.objc_registerClassPair(cls)
        self.cls = cls
        self.attach_attempts = 0
        window.root.after_idle(self.attach)

    def sel(self, name):
        return self.objc.sel_registerName(name.encode())

    def send(self, obj, name, *args, result=ctypes.c_void_p, types=()):
        fn = ctypes.CFUNCTYPE(result, ctypes.c_void_p, ctypes.c_void_p, *types)(
            ctypes.cast(self.objc.objc_msgSend, ctypes.c_void_p).value)
        return fn(obj, self.sel(name), *args)

    def string(self, value):
        return self.send(self.objc.objc_getClass(b'NSString'), 'stringWithUTF8String:', value.encode(),
                         types=(ctypes.c_char_p,))

    def text(self, value):
        raw = self.send(value, 'UTF8String', result=ctypes.c_char_p)
        return raw.decode('utf-8') if raw else ''

    def array(self, values):
        array = self.send(self.objc.objc_getClass(b'NSMutableArray'), 'array')
        for value in values:
            self.send(array, 'addObject:', value, result=None, types=(ctypes.c_void_p,))
        return array

    def bounds(self, view):
        # Intel's 32-byte structure return uses objc_msgSend_stret; arm64 does not.
        if platform.machine() == 'x86_64':
            rect = _Rect()
            fn = ctypes.CFUNCTYPE(None, ctypes.POINTER(_Rect), ctypes.c_void_p, ctypes.c_void_p)(
                ctypes.cast(self.objc.objc_msgSend_stret, ctypes.c_void_p).value)
            fn(ctypes.byref(rect), view, self.sel('bounds'))
            return rect
        return self.send(view, 'bounds', result=_Rect)

    def attach(self):
        if not self.window.root.winfo_exists():
            return
        app = self.send(self.objc.objc_getClass(b'NSApplication'), 'sharedApplication')
        windows = self.send(app, 'windows')
        count = self.send(windows, 'count', result=ctypes.c_ulong)
        for index in range(count):
            native = self.send(windows, 'objectAtIndex:', index, types=(ctypes.c_ulong,))
            if self.text(self.send(native, 'title')) == 'Escape Pod Cast':
                self.parent = self.send(native, 'contentView')
                self.view = self.send(self.send(self.cls, 'alloc'), 'initWithFrame:', _Rect(), types=(_Rect,))
                self.instances[self.view] = self
                kinds = ['public.file-url', 'public.url', 'public.utf8-plain-text',
                         'NSURLPboardType', 'NSFilenamesPboardType', 'NSStringPboardType']
                self.send(self.view, 'registerForDraggedTypes:', self.array(map(self.string, kinds)),
                          result=None, types=(ctypes.c_void_p,))
                self.send(self.parent, 'addSubview:', self.view, result=None, types=(ctypes.c_void_p,))
                self.resize()
                return
        self.attach_attempts += 1
        if self.attach_attempts < 10:
            self.window.root.after(200, self.attach)
        else:
            self.window.drop_hint = 'Use Add audio or paste a link below'
            self.window.draw_drop()

    def resize(self):
        if not self.view:
            return
        zone, root = self.window.drop_zone, self.window.root
        bounds = self.bounds(self.parent)
        x, y = zone.winfo_rootx() - root.winfo_rootx(), zone.winfo_rooty() - root.winfo_rooty()
        width, height = zone.winfo_width(), zone.winfo_height()
        if not self.send(self.parent, 'isFlipped', result=ctypes.c_bool):
            y = bounds.size.height - y - height
        rect = _Rect(_Point(bounds.origin.x + x, bounds.origin.y + y), _Size(width, height))
        self.send(self.view, 'setFrame:', rect, result=None, types=(_Rect,))

    def values(self, sender):
        board = self.send(sender, 'draggingPasteboard')
        urls = self.send(board, 'readObjectsForClasses:options:',
                         self.array([self.objc.objc_getClass(b'NSURL')]), None,
                         types=(ctypes.c_void_p, ctypes.c_void_p))
        count = self.send(urls, 'count', result=ctypes.c_ulong) if urls else 0
        if count:
            return [self.text(self.send(self.send(urls, 'objectAtIndex:', i, types=(ctypes.c_ulong,)),
                                        'absoluteString')) for i in range(count)]
        paths = self.send(board, 'propertyListForType:', self.string('NSFilenamesPboardType'), types=(ctypes.c_void_p,))
        if paths:
            count = self.send(paths, 'count', result=ctypes.c_ulong)
            return [self.text(self.send(paths, 'objectAtIndex:', i, types=(ctypes.c_ulong,))) for i in range(count)]
        for kind in ('public.url', 'public.utf8-plain-text', 'NSStringPboardType'):
            value = self.send(board, 'stringForType:', self.string(kind), types=(ctypes.c_void_p,))
            if value:
                lines = self.text(value).splitlines()
                return [line for line in lines if line.startswith(('https://', 'http://', 'file://'))]
        return []

    def event(self, action, sender):
        # Cocoa calls this outside _tkinter's ENTER_PYTHON/LEAVE_PYTHON pair.
        # Even root.after_idle() is a Tcl call: it clears _tkinter's saved
        # thread state and can abort the next timer with NULL tstate.
        # Only pass ordinary Python data here. The Tk timer consumes it later.
        if action == 'exit':
            self.window.drop_messages.put(('preview', (None, False)))
            return
        values = self.values(sender)
        accepted, _ = drop_inputs(values)
        if self.window.updating:
            accepted = []
        if action == 'perform':
            if accepted:
                self.window.drop_messages.put(('drop', tuple(values)))
            self.window.drop_messages.put(('preview', (None, False)))
        elif action == 'preview':
            caption = 'Release to publish' if accepted else 'Drop audio tracks or a YouTube video link'
            self.window.drop_messages.put(('preview', (caption, bool(accepted))))
        return bool(accepted)

    def close(self):
        if self.view:
            self.instances.pop(self.view, None)
            self.send(self.view, 'removeFromSuperview', result=None)
            self.send(self.view, 'release', result=None)
            self.view = None


def submit_inputs(files=(), youtube=None, tools=False):
    jobs = [p.create_job('file', path) for path in files]
    if youtube is not None:
        jobs.append(p.create_job('youtube', youtube))
    if tools:
        jobs.append(p.create_job('tools'))
    return jobs


def connection():
    try:
        return json.loads(p.CONFIG.read_text())
    except (OSError, ValueError):
        return {}


def open_log():
    path = p.HOME / 'Status.log'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    subprocess.Popen(['/usr/bin/open', str(path)])


def launch_worker(job):
    p.HOME.mkdir(parents=True, exist_ok=True)
    with (p.HOME / 'Status.log').open('a') as log:
        return subprocess.Popen([sys.executable, str(HERE / 'escape_pod_cast.py'),
                                 '--job', job['id']], stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True)


def fetch_update(destination, report):
    """Pin the download to one official GitHub commit; extract only app files."""
    report('Checking for the latest app version…')
    url = 'https://api.github.com/repos/' + SOURCE_REPO + '/git/ref/heads/main'
    if sys.platform == 'darwin':
        status, data, _ = p.mac_transfer(url)
        if status != 200:
            raise p.Failure('GitHub could not supply the update. Check your connection and retry.')
    else:
        data = p.public_bytes(url)
    try:
        sha = json.loads(data)['object']['sha']
        if not p.re.fullmatch(r'[0-9a-f]{40}', sha):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise p.Failure('The app update could not be verified.') from None
    report('Downloading the app update…')
    archive = destination / 'update.zip'
    result = subprocess.run(['/usr/bin/curl', '-q', '--fail', '--silent', '--show-error',
                             '--location', '--proto', '=https', '--proto-redir', '=https',
                             '--connect-timeout', '15', '--max-time', '180', '--retry', '2',
                             '--max-filesize', str(8 * 1024 ** 2), '--output', str(archive),
                             'https://github.com/' + SOURCE_REPO + '/archive/' + sha + '.zip'],
                            capture_output=True, text=True)
    if result.returncode:
        raise p.NetworkFailure('The update download failed. Check your connection and retry.')
    report('Preparing the setup window…')
    try:
        with zipfile.ZipFile(archive) as bundle:
            root = 'Escape-Pod-Cast-' + sha + '/'
            for name in UPDATE_FILES:
                info = bundle.getinfo(root + name)
                if not 0 < info.file_size <= 1024 * 1024:
                    raise ValueError()
                path = destination / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(bundle.read(info))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise p.Failure('The update archive is incomplete. Nothing was installed; retry.') from None
    return destination / 'mac/install.py'


class Window:
    def __init__(self, root, tk, ttk, dialogs):
        self.root, self.tk, self.ttk, self.dialogs = root, tk, ttk, dialogs
        self.worker, self.worker_id, self.selected, self.updating = None, None, None, False
        self.messages = queue.Queue()
        self.drop_messages = queue.Queue()
        self.jobs, self.last_rows = {}, None
        self.pulsing = False
        self.focus_stamp = 0
        root.title('Escape Pod Cast')
        root.geometry(f'860x{max(680, min(800, root.winfo_screenheight() - 100))}')
        root.minsize(650, 680)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.option_add('*Font', 'Helvetica 13')
        root.configure(background=CREAM)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', background=CREAM, foreground=INK)
        style.configure('TButton', padding=(12, 7), background=PANEL)
        style.map('TButton', background=[('active', '#e9e1d3')])
        style.configure('Primary.TButton', background=ORANGE, foreground='white')
        style.map('Primary.TButton', background=[('active', '#893b20')], foreground=[('disabled', '#ddd6ca')])
        style.configure('TEntry', fieldbackground=PANEL, padding=5)
        style.configure('Horizontal.TProgressbar', background=ORANGE, troughcolor='#e5ded0')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=16)
        body.grid(sticky='nsew')
        body.columnconfigure(0, weight=1)
        body.rowconfigure(5, weight=1)
        faceplate = ttk.Frame(body)
        faceplate.grid(row=0, sticky='ew')
        ttk.Label(faceplate, text='escape pod cast', font=('Helvetica', 28, 'bold')).pack(side='left')
        ttk.Label(faceplate, text='PERSONAL RADIO\nMODEL 006 / SIDE A', justify='right',
                  font=('Courier', 10, 'bold'), foreground=ORANGE).pack(side='right')
        ttk.Label(body, text='A small machine for sending sound to your pocket.',
                  font=('Helvetica', 12)).grid(row=1, sticky='w', pady=(0, 8))
        self.drop_hint = 'Drop here — publishing starts automatically'
        self.drop_preview = (None, False)
        self.hatch_pulse = 0
        self.hatch_motion = 0
        self.lamp_tick = False
        self.drop_zone = tk.Canvas(body, height=154, background=CREAM, highlightthickness=0)
        self.drop_zone.grid(row=2, sticky='ew')
        self.drop_zone.bind('<Configure>', lambda event: self.draw_drop())
        self.drop_bridge = None
        if sys.platform == 'darwin':
            try:
                self.drop_bridge = MacDropZone(self)
            except (OSError, AttributeError) as exc:
                print('Window drop support unavailable:', exc, flush=True)
                self.drop_hint = 'Use Add audio or paste a link below'
        else:
            self.drop_hint = 'Use Add audio or paste a link below'
        links = ttk.Frame(body)
        links.grid(row=3, sticky='ew', pady=(6, 8))
        links.columnconfigure(1, weight=1)
        ttk.Button(links, text='Add audio…', command=self.add_audio).grid(row=1, column=0, padx=(0, 12))
        ttk.Label(links, text='LINK INPUT / YouTube', font=('Courier', 10, 'bold')).grid(row=0, column=1, sticky='w', pady=(0, 3))
        self.link = tk.StringVar()
        self.link_entry = ttk.Entry(links, textvariable=self.link)
        self.link_entry.grid(row=1, column=1, sticky='ew', padx=(0, 8))
        self.link_entry.bind('<Return>', lambda event: self.add_youtube())
        ttk.Button(links, text='Paste', command=self.paste_link).grid(row=1, column=2, padx=(0, 8))
        ttk.Button(links, text='Get audio', style='Primary.TButton', command=self.add_youtube).grid(row=1, column=3)
        heading = ttk.Frame(body)
        heading.grid(row=4, sticky='ew', pady=(0, 6))
        ttk.Label(heading, text='THE TAPE RACK', font=('Courier', 12, 'bold')).pack(side='left')
        self.summary = tk.StringVar(value='Ready to add your first episode')
        ttk.Label(heading, textvariable=self.summary, font=('Helvetica', 11)).pack(side='right')
        table = ttk.Frame(body)
        table.grid(row=5, sticky='nsew')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.table = TapeDeck(table, tk)
        self.table.grid(sticky='nsew')
        self.table.bind('<<TreeviewSelect>>', self.select_job)
        scrollbar = ttk.Scrollbar(table, orient='vertical', command=self.table.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.table.configure(yscrollcommand=scrollbar.set)
        detail = ttk.Frame(body, padding=(0, 10, 0, 8))
        detail.grid(row=6, sticky='ew')
        detail.columnconfigure(0, weight=1)
        self.stage = tk.StringVar(value='Add a file or paste a video link to begin.')
        self.stage_label = ttk.Label(detail, textvariable=self.stage, font=('Helvetica', 14, 'bold'), wraplength=740)
        self.stage_label.grid(sticky='w')
        self.progress = ttk.Progressbar(detail, mode='indeterminate')
        # Kept as the task-state controller; the radio lamp replaces the stock bar.
        self.explanation = tk.StringVar(value='Progress and any retry instructions appear here. Your originals stay on your Mac.')
        explanation_frame = ttk.Frame(detail)
        explanation_frame.grid(row=2, sticky='ew')
        explanation_frame.columnconfigure(0, weight=1)
        self.explanation_text = tk.Text(explanation_frame, height=3, wrap='word',
                                        borderwidth=0, highlightthickness=0, state='disabled', background=CREAM, foreground=INK)
        self.explanation_text.grid(row=0, column=0, sticky='ew')
        explanation_scroll = ttk.Scrollbar(explanation_frame, orient='vertical', command=self.explanation_text.yview)
        explanation_scroll.grid(row=0, column=1, sticky='ns')
        self.explanation_text.configure(yscrollcommand=explanation_scroll.set)
        self.explanation.trace_add('write', self.update_explanation)
        self.update_explanation()
        self.retry = ttk.Button(detail, text='Retry selected item', command=self.retry_selected, state='disabled')
        self.retry.grid(row=3, sticky='w', pady=(10, 0))
        self.remove = ttk.Button(detail, text='Remove from queue', command=self.remove_selected, state='disabled')
        self.remove.grid(row=3, sticky='e', pady=(10, 0))
        bottom = ttk.Frame(body)
        bottom.grid(row=7, sticky='ew')
        ttk.Button(bottom, text='Connect iPhone…', command=self.connect_phone).pack(side='left')
        ttk.Button(bottom, text='Copy podcast link', command=self.copy_feed).pack(side='left', padx=8)
        ttk.Button(bottom, text='Settings & help…', command=self.settings).pack(side='right')
        self.connection_text = tk.StringVar()
        self.connection_label = ttk.Label(body, textvariable=self.connection_text, wraplength=740)
        self.connection_label.grid(row=8, sticky='w', pady=(8, 0))
        self.privacy_label = ttk.Label(body, text='Unlisted, publicly accessible audio · removed from GitHub after 14 days',
                                       wraplength=740, font=('Helvetica', 10))
        self.privacy_label.grid(row=9, sticky='w', pady=(4, 0))
        root.bind('<Configure>', self.resize)
        root.bind('<Command-o>', lambda event: self.add_audio())
        root.bind('<Command-q>', lambda event: self.close())
        root.bind('<Control-o>', lambda event: self.add_audio())
        self.refresh()
        root.bind('<Destroy>', self.destroy_drop, add='+')
        root.after(75, self.process_drop_messages)
        root.after(450, self.animate_radio)

    def process_drop_messages(self):
        preview, drops = None, []
        while True:
            try:
                kind, value = self.drop_messages.get_nowait()
            except queue.Empty:
                break
            if kind == 'preview':
                preview = value
            elif kind == 'drop':
                drops.append(value)
        if preview is not None:
            self.drop_preview = preview
            self.draw_drop(*preview)
        for values in drops:
            if not self.updating:
                self.queue_drop(values)
        self.root.after(75, self.process_drop_messages)

    def destroy_drop(self, event):
        if event.widget is self.root and self.drop_bridge:
            self.drop_bridge.close()

    def draw_drop(self, caption=None, active=False):
        canvas = self.drop_zone
        if caption is None and not active:
            caption, active = self.drop_preview
        width = max(canvas.winfo_width(), 600)
        canvas.delete('all')
        right = width - 226
        middle = (right+12)/2
        fill = '#f1d6a8' if active or self.hatch_pulse else '#e8dfcc'
        # Enamel hatch: an actual oval opening, orange gasket and inset shadow.
        canvas.create_oval(8, 11, right, 149, fill='#b5ac98', outline=INK, width=2)
        canvas.create_oval(8, 5, right, 143, fill=fill, outline=ORANGE if active else INK, width=3)
        canvas.create_oval(18, 15, right-10, 133, outline=ORANGE, width=1)
        for x in (35, right-27):
            canvas.create_oval(x-4, 70, x+4, 78, fill=PANEL, outline=INK)
            canvas.create_line(x-2, 74, x+2, 74, fill=INK)
        canvas.create_text(middle, 33, text='01 / AUDIO INTAKE', fill=ORANGE, font=('Courier', 10, 'bold'))
        canvas.create_text(middle, 65, text='FEED ME AUDIO', fill=INK, font=('Helvetica', 25, 'bold'))
        canvas.create_text(middle, 93, text='tracks + YouTube video links', fill=INK, font=('Courier', 10))
        motion = getattr(self, 'hatch_motion', 0)
        if motion:
            shutter = motion * (right-60) / 6
            canvas.create_rectangle(middle-shutter, 48, middle+shutter, 98,
                                    fill=INK, outline=ORANGE, width=2)
            if motion == 3:
                canvas.create_text(middle, 73, text='TRACK RECEIVED', fill=PANEL,
                                   font=('Courier', 12, 'bold'))
        note = 'CLICK. TRACK RECEIVED.' if self.hatch_pulse else caption or self.drop_hint
        # Two short lines fit the narrowest supported window.
        if note == self.drop_hint and 'Drop here' in note:
            note = 'DROP HERE / AUTO-PUBLISH'
        canvas.create_text(middle, 116, text=note, fill=ORANGE if active else INK,
                           font=('Helvetica', 10, 'bold'))
        self.draw_dial(canvas, width)
        if self.drop_bridge:
            self.drop_bridge.resize()

    def draw_dial(self, canvas, width):
        cx, cy = width-110, 81
        job = next((item for item in self.jobs.values() if item['state'] == 'running'),
                   self.jobs.get(self.selected))
        position, label, color = transmission_position(job, self.updating)
        canvas.create_text(cx, 9, text='02 / TRANSMISSION', fill=ORANGE, font=('Courier', 10, 'bold'))
        canvas.create_oval(cx-53, cy-53, cx+53, cy+53, fill=INK, outline=INK, width=2)
        canvas.create_oval(cx-47, cy-47, cx+47, cy+47, fill=PANEL, outline='#b9af99')
        angles = (150, 110, 70, 30)
        for index, angle in enumerate(angles):
            r = math.radians(angle)
            canvas.create_line(cx+36*math.cos(r), cy-36*math.sin(r),
                               cx+43*math.cos(r), cy-43*math.sin(r), fill=ORANGE, width=2)
            canvas.create_text(cx+29*math.cos(r), cy-29*math.sin(r), text=str(index),
                               fill=INK, font=('Courier', 9))
        angle = math.radians(angles[position])
        canvas.create_line(cx, cy, cx+35*math.cos(angle), cy-35*math.sin(angle), fill=ORANGE, width=3)
        canvas.create_oval(cx-7, cy-7, cx+7, cy+7, fill=INK, outline='')
        canvas.create_text(cx, cy+26, text=label, fill=color, font=('Courier', 9, 'bold'))
        working = self.updating or any(item['state'] == 'running' for item in self.jobs.values())
        lamp = ORANGE if working and self.lamp_tick else '#aaa18c' if working else color
        canvas.create_oval(width-31, 35, width-19, 47, fill=lamp, outline=INK)
        canvas.create_text(cx, 145, text='0 READY · 1 PREP · 2 TX · 3 ON AIR',
                           fill=INK, font=('Courier', 7))

    def animate_radio(self):
        self.lamp_tick = not self.lamp_tick
        self.draw_drop()
        self.root.after(450, self.animate_radio)

    def acknowledge_drop(self):
        self.hatch_pulse += 1
        stamp = self.hatch_pulse
        phases = iter((1, 2, 3, 3, 2, 1, 0))
        def step():
            if self.hatch_pulse != stamp:
                return
            self.hatch_motion = next(phases)
            if not self.hatch_motion:
                self.hatch_pulse = 0
            self.draw_drop()
            if self.hatch_motion:
                self.root.after(80, step)
        step()

    def queue_drop(self, values):
        accepted, rejected = drop_inputs(values)
        jobs = []
        active = {(job['kind'], job['source']): job for job in p.list_jobs()
                  if job['state'] in ('queued', 'running')}
        for kind, source in accepted:
            try:
                jobs.append(active.get((kind, source)) or p.create_job(kind, source))
            except (p.Failure, OSError, ValueError) as exc:
                rejected.append(str(exc))
        if jobs:
            self.selected = jobs[-1]['id']
            if hasattr(self, 'drop_zone'):
                self.acknowledge_drop()
        if rejected:
            self.show_error(f'{len(jobs)} item(s) added. Some items could not be added:\n' + '\n'.join(dict.fromkeys(rejected)))
        elif not jobs:
            self.show_error('Drop an audio file or a link to an individual YouTube video.')
        return bool(jobs)

    def resize(self, event):
        if event.widget is self.root:
            width = max(400, event.width - 60)
            for label in (self.stage_label, self.connection_label, self.privacy_label):
                label.configure(wraplength=width)

    def update_explanation(self, *args):
        content = self.explanation.get()
        if content == getattr(self, 'explanation_content', None):
            return  # Preserve text selection and scrolling while polling progress.
        self.explanation_content = content
        self.explanation_text.configure(state='normal')
        self.explanation_text.delete('1.0', 'end')
        self.explanation_text.insert('1.0', content)
        self.explanation_text.configure(state='disabled')

    def show_error(self, message):
        self.dialogs['message'].showerror('Escape Pod Cast', str(message), parent=self.root)

    def add_audio(self):
        paths = self.dialogs['file'].askopenfilenames(parent=self.root, title='Choose audio for your podcast',
                    filetypes=[('Audio and saved links', '*.mp3 *.m4a *.aac *.wav *.flac *.ogg *.opus *.aif *.aiff *.mp4 *.webloc *.url *.txt'),
                               ('All files', '*')])
        if paths:
            try:
                jobs = submit_inputs(paths)
                self.selected = jobs[-1]['id']
            except (p.Failure, OSError, ValueError) as exc:
                self.show_error(exc)

    def paste_link(self):
        try:
            text = self.root.clipboard_get()
            self.link.set(text.strip())
            self.link_entry.focus_set()
        except self.tk.TclError:
            self.show_error('The clipboard has no text. Copy the video link first.')

    def add_youtube(self):
        try:
            job = p.create_job('youtube', self.link.get())
            self.selected = job['id']
            self.link.set('')
        except (p.Failure, OSError, ValueError) as exc:
            self.show_error(exc)

    def select_job(self, event=None):
        selection = self.table.selection()
        if selection:
            self.selected = selection[0]
            self.render_detail()

    def render_detail(self):
        job = self.jobs.get(self.selected)
        if job is None:
            return
        stage = job.get('stage', 'Waiting')
        state = job['state']
        if state == 'running' and job.get('started'):
            try:
                elapsed = max(0, int((p.dt.datetime.now(p.dt.timezone.utc) - p.stamp(job['started'])).total_seconds()))
                stage += ' · %s:%02d elapsed' % divmod(elapsed, 60)
            except ValueError:
                pass
        self.stage.set(stage)
        self.retry.configure(state='normal' if state == 'failed' else 'disabled')
        self.remove.configure(state='normal' if state in ('queued', 'failed') else 'disabled')
        if state == 'failed':
            self.explanation.set(job['label'] + '\n' + job.get('error', '') + '\n\n' + job.get('help', ''))
        elif state in ('done', 'cancelled'):
            self.explanation.set(job['label'] + '\n' + job.get('message', 'Published. Refresh your show in Apple Podcasts.'))
        else:
            self.explanation.set(job['label'] + '\nKeep this Mac awake and connected. You can add more items; they wait their turn. '
                                 'Closing this window does not cancel publishing.')
        active = state in ('queued', 'running')
        if active and not self.pulsing:
            self.progress.configure(mode='indeterminate')
            self.progress.start(30)
            self.pulsing = True
        elif not active:
            self.progress.stop()
            self.progress.configure(mode='determinate', value=100 if state == 'done' else 0)
            self.pulsing = False

    def retry_selected(self):
        if self.selected:
            try:
                p.retry_job(self.selected)
            except (p.Failure, OSError, ValueError) as exc:
                self.show_error(exc)

    def remove_selected(self):
        if self.selected:
            try:
                p.cancel_job(self.selected)
            except (p.Failure, OSError, ValueError) as exc:
                self.show_error(exc)

    def copy_feed(self):
        url = connection().get('feed_url')
        if not url:
            self.show_error('Connect your GitHub copy in Settings first.')
            return False
        self.root.clipboard_clear()
        self.root.clipboard_append(url)
        # macOS clipboard persists after closing this Python window.
        if sys.platform == 'darwin':
            subprocess.run(['/usr/bin/pbcopy'], input=url, text=True, check=True)
        self.explanation.set('Podcast link copied. Use Connect iPhone for the three steps.')
        return True

    def connect_phone(self):
        if self.copy_feed():
            self.dialogs['message'].showinfo('Connect your iPhone',
                'Your podcast link is copied.\n\n'
                '1. On iPhone: Apple Podcasts → Library → ••• → Follow a Show by URL.\n'
                '2. Paste the link (Universal Clipboard can copy it between your Macs and iPhone).\n'
                '3. Enable automatic downloads for the show.\n\n'
                'If the feed is empty, publish a short episode first. Then check it plays with the iPhone offline. '
                'Apple controls when the show refreshes.', parent=self.root)

    def enqueue_action(self, kind):
        try:
            self.selected = p.create_job(kind)['id']
        except (p.Failure, OSError, ValueError) as exc:
            self.show_error(exc)

    def reconnect(self):
        if any(job['state'] in ('queued', 'running') for job in self.jobs.values()):
            self.show_error('Let the current task finish before changing the connection.')
            return
        subprocess.Popen([sys.executable, str(HERE / 'install.py')])

    def update_app(self):
        if self.updating:
            return
        if any(job['state'] in ('queued', 'running') for job in self.jobs.values()):
            self.show_error('Let queued publishing finish before updating the app.')
            return
        self.updating = True
        self.stage.set('Getting the latest app update')
        self.progress.configure(mode='indeterminate')
        self.progress.start(30)
        self.pulsing = True
        def task():
            try:
                with tempfile.TemporaryDirectory(prefix='epc-update-') as temp:
                    installer = fetch_update(Path(temp), lambda text: self.messages.put(('status', text)))
                    self.messages.put(('status', 'Follow the setup window and choose Update. Your connection and episodes are kept.'))
                    receipt = Path(temp) / 'setup-result.json'
                    result = subprocess.run([sys.executable, str(installer), '--result-file', str(receipt)])
                    if result.returncode:
                        raise p.Failure('The update did not finish. Your publishing history and originals are kept.')
                    if not receipt.exists():
                        self.messages.put(('status', 'Update cancelled. Your current app is still ready.'))
                        return
                self.messages.put(('updated', ''))
            except (p.Failure, OSError, ValueError) as exc:
                self.messages.put(('error', str(exc)))
            finally:
                self.messages.put(('update_finished', ''))
        threading.Thread(target=task, daemon=True).start()

    def settings(self):
        window = self.tk.Toplevel(self.root)
        window.title('Settings & help')
        window.geometry('570x510')
        frame = self.ttk.Frame(window, padding=22)
        frame.pack(fill='both', expand=True)
        config = connection()
        self.ttk.Label(frame, text='Your connection', font=('Helvetica', 17, 'bold')).pack(anchor='w')
        self.ttk.Label(frame, text='Escape Pod Cast ' + APP_VERSION).pack(anchor='w', pady=(4, 0))
        self.ttk.Label(frame, text=config.get('repo', 'Not connected'), wraplength=520).pack(anchor='w', pady=(5, 12))
        self.ttk.Button(frame, text='Check connection & feed', command=lambda: self.enqueue_action('check')).pack(anchor='w', pady=3)
        self.ttk.Button(frame, text='Reconnect GitHub…', command=self.reconnect).pack(anchor='w', pady=3)
        self.ttk.Button(frame, text='Set up / update YouTube…', command=lambda: self.enqueue_action('tools')).pack(anchor='w', pady=3)
        self.ttk.Button(frame, text='Update this app…', command=self.update_app).pack(anchor='w', pady=3)
        self.ttk.Separator(frame).pack(fill='x', pady=14)
        self.ttk.Button(frame, text='Open drop folder', command=self.open_folder).pack(anchor='w', pady=3)
        self.ttk.Button(frame, text='Open detailed publishing log', command=open_log).pack(anchor='w', pady=3)
        self.ttk.Label(frame, text='The drop folder is optional. Add audio and Get audio are the easiest ways to publish. '
                       'Only copy material you have permission to publicly host. '
                       'Restricted YouTube videos and live streams are unsupported.', wraplength=520).pack(anchor='w', pady=(14, 0))

    def finish_update(self):
        self.root.destroy()
        subprocess.Popen(['/usr/bin/open', str(Path.home() / 'Applications/Escape Pod Cast.app')])

    def open_folder(self):
        path = p.HOME / 'Drop Audio Here'
        path.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(['/usr/bin/open', str(path)])

    def refresh(self):
        try:
            while True:
                kind, message = self.messages.get_nowait()
                if kind == 'status':
                    self.stage.set(message)
                elif kind == 'error':
                    self.show_error(message)
                    if self.updating:
                        self.stage.set('Update did not finish')
                        self.explanation.set(message)
                elif kind == 'updated':
                    self.root.after_idle(self.finish_update)
                    return
                elif kind == 'update_finished':
                    self.updating = False
                    self.progress.stop()
                    self.progress.configure(mode='determinate', value=0)
                    self.pulsing = False
        except queue.Empty:
            pass
        jobs = p.list_jobs()
        self.jobs = {job['id']: job for job in jobs}
        queued = [job for job in jobs if job['state'] == 'queued']
        running = [job for job in jobs if job['state'] == 'running']
        failed = [job for job in jobs if job['state'] == 'failed']
        if not self.updating:
            if self.worker is not None and self.worker.poll() is not None:
                if self.worker.returncode and self.worker_id:
                    job = p.load_job(self.worker_id)
                    if job['state'] == 'queued' or (job['state'] == 'running' and job.get('pid') == self.worker.pid):
                        job.update(state='failed', stage='Interrupted', pid=None,
                                   error='The publisher stopped before reporting a result.',
                                   help='Click Retry. If this repeats, open the detailed publishing log in Settings.')
                        p.save_job(job)
                self.worker = None
                p.recover_jobs()
                jobs = p.list_jobs()
                self.jobs = {job['id']: job for job in jobs}
                queued = [job for job in jobs if job['state'] == 'queued']
                running = [job for job in jobs if job['state'] == 'running']
                failed = [job for job in jobs if job['state'] == 'failed']
            if self.worker is None and queued:
                try:
                    self.worker = launch_worker(queued[0])
                    self.worker_id = queued[0]['id']
                    self.selected = queued[0]['id']
                except OSError as exc:
                    job = queued[0]
                    job.update(state='failed', stage='Could not start', error=str(exc),
                               help='Reconnect or update the app in Settings, then retry.')
                    p.save_job(job)
                    self.show_error(exc)
        # Keep active/failed items visible; cap old completed rows only.
        visible = [job for job in jobs if job['state'] not in ('done', 'cancelled')] + [job for job in jobs if job['state'] in ('done', 'cancelled')][-30:]
        visible.sort(key=lambda job: job['created'], reverse=True)
        rows = [(job['id'], job['label'], job['state']) for job in visible]
        if rows != self.last_rows:
            names = {'queued': 'Waiting', 'running': 'Publishing…', 'failed': 'Needs attention',
                     'done': 'Done', 'cancelled': 'Removed'}
            numbers = {job['id']: index+1 for index, job in enumerate(jobs)}
            entries = []
            for job in visible:
                status = 'Published' if job['state'] == 'done' and job['kind'] in ('file', 'youtube') else names[job['state']]
                entries.append(dict(job, status=status, number=numbers[job['id']]))
            self.table.sync(entries)
            self.last_rows = rows
            if self.selected in self.jobs and self.table.exists(self.selected):
                self.table.selection_set(self.selected)
        if not self.selected and visible:
            self.selected = (running or queued or failed or visible)[0]['id']
            self.table.selection_set(self.selected)
        self.summary.set('%s waiting · %s working · %s need attention' % (len(queued), len(running), len(failed))
                         if jobs else 'Ready to add your first episode')
        config = connection()
        self.connection_text.set('Connected to ' + config['repo'] if config.get('repo') else 'Not connected — open Settings to connect your GitHub copy.')
        if not self.updating:
            self.render_detail()
        focus = p.HOME / 'show-window'
        if focus.exists() and focus.stat().st_mtime_ns != self.focus_stamp:
            self.focus_stamp = focus.stat().st_mtime_ns
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        self.root.after(500, self.refresh)

    def close(self):
        if self.updating:
            self.show_error('Finish or cancel the setup window before closing this update.')
            return
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--youtube')
    parser.add_argument('--youtube-setup', action='store_true')
    parser.add_argument('files', nargs='*')
    args = parser.parse_args()
    p.HOME.mkdir(parents=True, exist_ok=True)
    submit_inputs(args.files, args.youtube, args.youtube_setup)
    (p.HOME / 'show-window').touch()
    with (p.HOME / 'window.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return  # The existing window notices the new queue and focus request.
        p.recover_jobs()
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
        root = tk.Tk()
        Window(root, tk, ttk, {'file': filedialog, 'message': messagebox})
        root.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        # Native recovery even when this Python lacks the window toolkit.
        message = ('The app window could not open.\n\n' + str(exc) +
                   '\n\nRun START-HERE.command again. Python from python.org includes the window toolkit.')
        literal = '"' + message.replace('\\', '\\\\').replace('"', '\\"') + '"'
        subprocess.run(['/usr/bin/osascript', '-'], input='display dialog ' + literal +
                       ' buttons {"OK"} default button "OK" with title "Escape Pod Cast"', text=True)
        sys.exit(1)
