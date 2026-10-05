#!/usr/bin/env python3
"""The Mac's single-window publisher; work continues in separate processes."""
import argparse
import fcntl
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import zipfile

import escape_pod_cast as p

HERE = Path(__file__).resolve().parent
SOURCE_REPO = 'udeudeude/Escape-Pod-Cast'
APP_VERSION = '0.4.0'
UPDATE_FILES = ('mac/escape_pod_cast.py', 'mac/app.py', 'mac/install.py')


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
        self.jobs, self.last_rows = {}, None
        self.pulsing = False
        self.focus_stamp = 0
        root.title('Escape Pod Cast')
        root.geometry('820x700')
        root.minsize(650, 620)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.option_add('*Font', 'Helvetica 13')
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        body = ttk.Frame(root, padding=20)
        body.grid(sticky='nsew')
        body.columnconfigure(0, weight=1)
        body.rowconfigure(5, weight=1)
        ttk.Label(body, text='Escape Pod Cast', font=('Helvetica', 26, 'bold')).grid(sticky='w')
        ttk.Label(body, text='Audio on your Mac → episodes on your iPhone',
                  font=('Helvetica', 14)).grid(row=1, sticky='w', pady=(4, 12))
        actions = ttk.Frame(body)
        actions.grid(row=2, sticky='ew')
        ttk.Button(actions, text='Add audio…', command=self.add_audio).pack(side='left', padx=(0, 12))
        ttk.Label(actions, text='You can also drop audio or saved links onto the app icon.').pack(side='left')
        links = ttk.Frame(body)
        links.grid(row=3, sticky='ew', pady=(10, 12))
        links.columnconfigure(0, weight=1)
        ttk.Label(links, text='YouTube video link').grid(row=0, column=0, sticky='w', pady=(0, 5))
        self.link = tk.StringVar()
        self.link_entry = ttk.Entry(links, textvariable=self.link)
        self.link_entry.grid(row=1, column=0, sticky='ew', padx=(0, 8))
        self.link_entry.bind('<Return>', lambda event: self.add_youtube())
        ttk.Button(links, text='Paste', command=self.paste_link).grid(row=1, column=1, padx=(0, 8))
        ttk.Button(links, text='Get audio', command=self.add_youtube).grid(row=1, column=2)
        heading = ttk.Frame(body)
        heading.grid(row=4, sticky='ew', pady=(0, 6))
        ttk.Label(heading, text='Recent activity', font=('Helvetica', 14, 'bold')).pack(side='left')
        self.summary = tk.StringVar(value='Ready to add your first episode')
        ttk.Label(heading, textvariable=self.summary).pack(side='right')
        table = ttk.Frame(body)
        table.grid(row=5, sticky='nsew')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.table = ttk.Treeview(table, columns=('state',), show='tree headings', selectmode='browse', height=7)
        self.table.heading('#0', text='Audio / action', anchor='w')
        self.table.heading('state', text='Status', anchor='w')
        self.table.column('#0', width=460, minwidth=240)
        self.table.column('state', width=150, minwidth=110, stretch=False)
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
        self.progress.grid(row=1, sticky='ew', pady=(9, 7))
        self.explanation = tk.StringVar(value='Progress and any retry instructions appear here. Your originals stay on your Mac.')
        explanation_frame = ttk.Frame(detail)
        explanation_frame.grid(row=2, sticky='ew')
        explanation_frame.columnconfigure(0, weight=1)
        self.explanation_text = tk.Text(explanation_frame, height=4, wrap='word',
                                        borderwidth=0, highlightthickness=0, state='disabled')
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
                                       wraplength=740)
        self.privacy_label.grid(row=9, sticky='w', pady=(4, 0))
        root.bind('<Configure>', self.resize)
        root.bind('<Command-o>', lambda event: self.add_audio())
        root.bind('<Command-q>', lambda event: self.close())
        root.bind('<Control-o>', lambda event: self.add_audio())
        self.refresh()

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
            self.explanation.set(job.get('error', '') + '\n\n' + job.get('help', ''))
        elif state in ('done', 'cancelled'):
            self.explanation.set(job.get('message', 'Published. Refresh your show in Apple Podcasts.'))
        else:
            self.explanation.set('Keep this Mac awake and connected. You can add more items; they wait their turn. '
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
            self.table.delete(*self.table.get_children())
            names = {'queued': 'Waiting', 'running': 'Publishing…', 'failed': 'Needs attention',
                     'done': 'Done', 'cancelled': 'Removed'}
            for job in visible:
                status = 'Published' if job['state'] == 'done' and job['kind'] in ('file', 'youtube') else names[job['state']]
                self.table.insert('', 'end', iid=job['id'], text=job['label'], values=(status,))
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
