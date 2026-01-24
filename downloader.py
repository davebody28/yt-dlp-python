#!/usr/bin/env python3
"""
yt-dlp Python launcher
- GUI app to paste URLs, choose output format/dir, and track status
- auto-downloads yt-dlp.exe and ffmpeg if missing (bin/)
- runs several yt-dlp processes in parallel (one process per URL)
- streams output to GUI and writes logs (logs/)
- converts best audio -> selected format, embeds metadata & cover
"""

import base64
import os
import sys
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Empty, Queue

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from icon_data import ICO_BASE64, PNG_BASE64

# ---------------- CONFIG ----------------
BASE = Path(__file__).resolve().parent
BIN = BASE / "bin"
ICON_CACHE_DIR = BASE / "cache"
DEFAULT_DOWNLOADS_DIR = None
if sys.platform.startswith("win"):
    DEFAULT_DOWNLOADS_DIR = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Downloads"
OUT = DEFAULT_DOWNLOADS_DIR if DEFAULT_DOWNLOADS_DIR else (BASE / "downloads")
LOGS = BASE / "logs"
YT_DLP_EXE = BIN / "yt-dlp.exe"
FFMPEG_EXE = BIN / "ffmpeg.exe"

URLS_FILE = BASE / "urls.txt"
LOG_FILE = LOGS / "yt-dlp.log"
ERR_LOG_FILE = LOGS / "yt-dlp-errors.log"

# parallelism: how many simultaneous URL processes
MAX_WORKERS = 4

# yt-dlp fragment parallelism (inside each process)
PARALLEL_FRAGMENTS = "16"
CONCURRENT_FRAGMENTS = "16"

# audio options
DEFAULT_AUDIO_FORMAT = "mp3"
AUDIO_QUALITY = "0"  # best VBR

# download sources
YTDLP_RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_VERSION_FILE = BIN / "ffmpeg.version"
ICON_URL = "https://avatars.githubusercontent.com/u/79589310?v=4"

AUDIO_FORMATS = ["mp3", "aac", "flac", "webm", "mp4"]
PLAYLIST_MODES = {"single": "Single file", "playlist": "Playlist (all items)"}
LOG_LOCK = threading.Lock()
# ----------------------------------------

def ensure_dirs():
    for d in (BIN, OUT, LOGS, ICON_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # ensure logs exist
    LOG_FILE.touch(exist_ok=True)
    ERR_LOG_FILE.touch(exist_ok=True)

def download_file(url: str, dest: Path):
    print(f"Downloading {url} -> {dest.name} ...")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request) as response, dest.open("wb") as handle:
            handle.write(response.read())
    except Exception as e:
        print(f"ERROR downloading {url}: {e}")
        raise

def png_to_ico(png_data: bytes) -> bytes:
    if not png_data.startswith(b"\x89PNG"):
        raise ValueError("Icon data is not a PNG")
    width = int.from_bytes(png_data[16:20], "big")
    height = int.from_bytes(png_data[20:24], "big")
    w = width if width < 256 else 0
    h = height if height < 256 else 0
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png_data), 22)
    return header + entry + png_data

def ensure_icon_files():
    png_path = ICON_CACHE_DIR / "app.png"
    ico_path = ICON_CACHE_DIR / "app.ico"
    if png_path.exists() and ico_path.exists():
        return png_path, ico_path
    try:
        download_file(ICON_URL, png_path)
        ico_path.write_bytes(png_to_ico(png_path.read_bytes()))
    except Exception:
        return None, None
    return png_path, ico_path

def get_remote_last_modified(url: str):
    try:
        request = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(request) as response:
            return response.headers.get("Last-Modified")
    except Exception:
        return None

def read_version_stamp():
    if FFMPEG_VERSION_FILE.exists():
        return FFMPEG_VERSION_FILE.read_text(encoding="utf-8").strip()
    return None

def write_version_stamp(value: str | None):
    if value:
        FFMPEG_VERSION_FILE.write_text(value, encoding="utf-8")

def ensure_yt_dlp():
    if not YT_DLP_EXE.exists():
        tmp = BIN / "yt-dlp.tmp.exe"
        download_file(YTDLP_RELEASE_URL, tmp)
        tmp.replace(YT_DLP_EXE)
        print("yt-dlp downloaded.")
    else:
        # try to self-update via downloaded binary; ignore errors
        try:
            subprocess.run([str(YT_DLP_EXE), "-U"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

def ensure_ffmpeg():
    remote_stamp = get_remote_last_modified(FFMPEG_ZIP_URL)
    local_stamp = read_version_stamp()
    needs_update = not FFMPEG_EXE.exists()
    if remote_stamp and remote_stamp != local_stamp:
        needs_update = True

    if needs_update:
        zpath = BIN / "ffmpeg.zip"
        download_file(FFMPEG_ZIP_URL, zpath)
        try:
            with zipfile.ZipFile(zpath, "r") as z:
                z.extractall(BIN)
            # find ffmpeg.exe in extracted tree
            found = None
            for p in BIN.rglob("ffmpeg.exe"):
                found = p
                break
            if not found:
                raise FileNotFoundError("ffmpeg.exe not found inside archive")
            shutil.copy2(found, FFMPEG_EXE)
            write_version_stamp(remote_stamp)
            print("ffmpeg extracted.")
        finally:
            try:
                zpath.unlink()
            except Exception:
                pass

def read_urls_from_file():
    if not URLS_FILE.exists():
        print("No urls.txt found. Create the file and put one URL per line.")
        sys.exit(1)
    lines = []
    with URLS_FILE.open(encoding="utf-8") as f:
        for l in f:
            l = l.strip()
            if not l or l.startswith("#"):
                continue
            lines.append(l)
    if not lines:
        print("urls.txt is empty (or only comments).")
        sys.exit(1)
    return lines

def read_urls_from_text(text: str):
    lines = []
    for l in text.splitlines():
        l = l.strip()
        if not l or l.startswith("#"):
            continue
        lines.append(l)
    return lines

def build_command(url: str, output_dir: Path, audio_format: str, playlist_mode: str):
    outtmpl = f"{output_dir / '%(title)s.%(ext)s'}"
    cmd = [
        str(YT_DLP_EXE),
        "-f",
        "bestaudio/best",
        "--js-runtimes",
        "node",
        "--extract-audio",
        "--audio-format",
        audio_format,
        "--audio-quality",
        AUDIO_QUALITY,
        "-o",
        outtmpl,
        "-N",
        PARALLEL_FRAGMENTS,
        "--concurrent-fragments",
        CONCURRENT_FRAGMENTS,
        "--ffmpeg-location",
        str(BIN),
        "--add-metadata",
        "--embed-metadata",
        "--embed-thumbnail",
        "--progress",
        "--newline",
        "--ignore-errors",
        "--no-mtime",
        "--restrict-filenames",
        url,
    ]
    if playlist_mode == "single":
        cmd.insert(-1, "--no-playlist")
    return cmd

def infer_status(line: str):
    lowered = line.lower()
    if "extracting audio" in lowered or "post-process" in lowered or "ffmpeg" in lowered:
        return "converting"
    if "adding metadata" in lowered or "embedding" in lowered:
        return "tagging"
    if "deleting original" in lowered:
        return "cleanup"
    if "warning" in lowered:
        return "warning"
    if "error" in lowered:
        return "error"
    if "[download]" in lowered or "%" in lowered or "destination" in lowered:
        return "downloading"
    return None

def log_line(message: str, log_handle):
    with LOG_LOCK:
        log_handle.write(message + "\n")
        log_handle.flush()

def queue_event(event_queue: Queue | None, payload: dict):
    if event_queue is not None:
        event_queue.put(payload)

def run_yt_dlp_for_url(
    url: str,
    index: int,
    output_dir: Path,
    audio_format: str,
    playlist_mode: str,
    event_queue: Queue | None = None,
):
    """
    Runs yt-dlp.exe as a subprocess for a single URL.
    Streams stdout/stderr to console/GUI with prefix and appends to log files.
    Returns (url, returncode).
    """
    cmd = build_command(url, output_dir, audio_format, playlist_mode)
    prefix = f"[{index}] "

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)
    retcode = None
    try:
        with LOG_FILE.open("a", encoding="utf-8") as logf:
            log_line(f"\n\n=== START {time.strftime('%Y-%m-%d %H:%M:%S')} URL={url}", logf)
            for line in proc.stdout:
                out_line = line.rstrip("\n")
                console_line = prefix + out_line
                print(console_line)
                log_line(console_line, logf)
                queue_event(event_queue, {"type": "log", "text": console_line})
                status = infer_status(out_line)
                if status:
                    queue_event(event_queue, {"type": "status", "index": index, "status": status})
            proc.wait()
            retcode = proc.returncode
            log_line(f"=== END returncode={retcode}", logf)
    except Exception as e:
        with ERR_LOG_FILE.open("a", encoding="utf-8") as ef:
            ef.write(f"ERROR for {url}: {e}\n")
        if proc and proc.poll() is None:
            proc.kill()
        retcode = -1

    return (url, retcode)

def cli_main():
    print("=== yt-dlp Python downloader ===")
    ensure_dirs()
    print("Ensuring yt-dlp and ffmpeg binaries...")
    try:
        ensure_yt_dlp()
    except Exception as e:
        print("Failed to ensure yt-dlp:", e)
        sys.exit(1)
    try:
        ensure_ffmpeg()
    except Exception as e:
        print("Failed to ensure ffmpeg:", e)
        print("Warning: ffmpeg missing or failed to extract. Conversion may fail.")

    urls = read_urls_from_file()
    playlist_mode = "playlist" if "--playlist" in sys.argv else "single" if "--single" in sys.argv else "playlist"
    print(f"Loaded {len(urls)} URLs. Starting up to {MAX_WORKERS} parallel downloads.")
    start_time = time.time()
    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {
            exe.submit(run_yt_dlp_for_url, url, i + 1, OUT, DEFAULT_AUDIO_FORMAT, playlist_mode): url
            for i, url in enumerate(urls)
        }
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                res = fut.result()
                results.append(res)
                if res[1] == 0:
                    print(f"[SUMMARY] {url} -> OK")
                else:
                    print(f"[SUMMARY] {url} -> FAILED (code {res[1]})")
            except Exception as e:
                print(f"[ERROR] {url} raised exception: {e}")
                with ERR_LOG_FILE.open("a", encoding="utf-8") as ef:
                    ef.write(f"Exception for {url}: {e}\n")

    elapsed = time.time() - start_time
    print("All done. Elapsed: {:.1f}s".format(elapsed))
    print("Logs:", LOG_FILE)
    print("Errors:", ERR_LOG_FILE)

class DownloaderGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("YouTube Audio Downloader")
        self.event_queue = Queue()
        self.executor = None
        self.worker_thread = None

        self.urls_text = None
        self.log_text = None
        self.status_tree = None

        self.output_dir_var = tk.StringVar(value=str(OUT))
        self.format_var = tk.StringVar(value=DEFAULT_AUDIO_FORMAT)
        self.playlist_var = tk.StringVar(value="single")

        self.start_button = None

        self.configure_theme()
        self.set_app_icon()
        self.build_ui()
        self.process_queue()

    def configure_theme(self):
        self.root.configure(bg="#1e1e1e")
        preferred_font = ("Segoe UI", 10) if sys.platform.startswith("win") else ("Arial", 10)
        self.root.option_add("*Font", preferred_font)
        self.download_font = (preferred_font[0], 12, "bold")
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#1e1e1e")
        style.configure("TLabel", background="#1e1e1e", foreground="#e0e0e0")
        style.configure("TButton", background="#2b2b2b", foreground="#e0e0e0")
        style.map("TButton", background=[("active", "#3a3a3a")])
        style.configure("TEntry", fieldbackground="#2b2b2b", foreground="#e0e0e0")
        style.configure("TCombobox", fieldbackground="#2b2b2b", foreground="#e0e0e0")
        style.map("TCombobox", fieldbackground=[("readonly", "#2b2b2b")])
        style.configure("TRadiobutton", background="#1e1e1e", foreground="#e0e0e0")
        style.configure("Treeview", background="#2b2b2b", foreground="#e0e0e0", fieldbackground="#2b2b2b")
        style.configure("Treeview.Heading", background="#1e1e1e", foreground="#e0e0e0")

    def set_app_icon(self):
        icon_loaded = False
        png_path, ico_path = ensure_icon_files()
        if sys.platform.startswith("win"):
            try:
                if ico_path and ico_path.exists():
                    self.root.iconbitmap(default=str(ico_path))
                    icon_loaded = True
                else:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".ico") as tmp:
                        tmp.write(base64.b64decode(ICO_BASE64))
                        self._icon_temp_path = tmp.name
                    self.root.iconbitmap(default=self._icon_temp_path)
                    icon_loaded = True
            except Exception:
                pass
        try:
            if png_path and png_path.exists():
                icon_image = tk.PhotoImage(file=str(png_path))
            else:
                icon_image = tk.PhotoImage(data=PNG_BASE64)
            self.root.iconphoto(True, icon_image)
            self._icon_image = icon_image
            icon_loaded = True
        except Exception:
            pass
        if not icon_loaded:
            fallback_ico = Path("app.ico")
            if fallback_ico.exists():
                try:
                    self.root.iconbitmap(default=str(fallback_ico))
                except Exception:
                    pass

    def build_ui(self):
        self.root.geometry("920x640")
        self.root.minsize(820, 560)

        header = ttk.Label(self.root, text="YouTube Audio Downloader", font=("Segoe UI", 14, "bold"))
        header.pack(anchor="w", padx=16, pady=(12, 4))

        urls_label = ttk.Label(self.root, text="Paste URLs (one per line):")
        urls_label.pack(anchor="w", padx=16)

        self.urls_text = ScrolledText(
            self.root,
            height=10,
            wrap=tk.WORD,
            background="#2b2b2b",
            foreground="#e0e0e0",
            insertbackground="#e0e0e0",
        )
        self.urls_text.pack(fill="x", padx=16, pady=(4, 12))

        options_frame = ttk.Frame(self.root)
        options_frame.pack(fill="x", padx=16)

        playlist_label = ttk.Label(options_frame, text="Playlist mode:")
        playlist_label.grid(row=0, column=0, sticky="w")

        playlist_single = ttk.Radiobutton(
            options_frame,
            text=PLAYLIST_MODES["single"],
            variable=self.playlist_var,
            value="single",
        )
        playlist_single.grid(row=0, column=1, sticky="w")

        playlist_all = ttk.Radiobutton(
            options_frame,
            text=PLAYLIST_MODES["playlist"],
            variable=self.playlist_var,
            value="playlist",
        )
        playlist_all.grid(row=0, column=2, sticky="w")

        format_label = ttk.Label(options_frame, text="Output format:")
        format_label.grid(row=0, column=3, sticky="w", padx=(16, 0))

        format_menu = ttk.Combobox(options_frame, textvariable=self.format_var, values=AUDIO_FORMATS, state="readonly", width=12)
        format_menu.grid(row=0, column=4, padx=(8, 0), sticky="w")

        output_label = ttk.Label(options_frame, text="Output directory:")
        output_label.grid(row=1, column=0, sticky="w", pady=(8, 0))

        output_entry = ttk.Entry(options_frame, textvariable=self.output_dir_var, width=50)
        output_entry.grid(row=1, column=1, columnspan=3, padx=(8, 8), pady=(8, 0), sticky="ew")

        browse_button = ttk.Button(options_frame, text="Browse", command=self.choose_output_dir)
        browse_button.grid(row=1, column=4, pady=(8, 0), sticky="w")

        self.start_button = tk.Button(
            options_frame,
            text="Download",
            command=self.start_downloads,
            background="#1db954",
            foreground="#ffffff",
            activebackground="#1ed760",
            activeforeground="#ffffff",
            font=self.download_font,
            padx=14,
            pady=8,
            borderwidth=0,
            highlightthickness=0,
        )
        self.start_button.grid(row=2, column=0, columnspan=5, pady=(12, 0), sticky="ew")

        options_frame.columnconfigure(1, weight=0)
        options_frame.columnconfigure(2, weight=0)
        options_frame.columnconfigure(3, weight=1)

        spacer = ttk.Frame(self.root)
        spacer.pack(fill="x", padx=16, pady=(10, 6))

        status_label = ttk.Label(self.root, text="Current downloads:")
        status_label.pack(anchor="w", padx=16, pady=(8, 2))

        self.status_tree = ttk.Treeview(self.root, columns=("status", "url"), show="headings", height=6)
        self.status_tree.heading("status", text="Status")
        self.status_tree.heading("url", text="URL")
        self.status_tree.column("status", width=120, anchor="w")
        self.status_tree.column("url", width=640, anchor="w")
        self.status_tree.pack(fill="both", padx=16, pady=(0, 10), expand=True)

        log_label = ttk.Label(self.root, text="Logs:")
        log_label.pack(anchor="w", padx=16)

        self.log_text = ScrolledText(
            self.root,
            height=8,
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#2b2b2b",
            foreground="#e0e0e0",
            insertbackground="#e0e0e0",
        )
        self.log_text.pack(fill="both", padx=16, pady=(4, 12), expand=True)

    def choose_output_dir(self):
        path = filedialog.askdirectory(initialdir=self.output_dir_var.get() or str(OUT))
        if path:
            self.output_dir_var.set(path)

    def set_controls_state(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.start_button.configure(state=state)

    def start_downloads(self):
        urls = read_urls_from_text(self.urls_text.get("1.0", tk.END))
        if not urls:
            messagebox.showwarning("Brak URL", "Wklej przynajmniej jeden adres URL.")
            return
        output_dir = Path(self.output_dir_var.get()).expanduser()
        audio_format = self.format_var.get()
        playlist_mode = self.playlist_var.get()
        if audio_format not in AUDIO_FORMATS:
            messagebox.showerror("Nieprawidłowy format", "Wybierz poprawny format audio.")
            return
        if playlist_mode not in PLAYLIST_MODES:
            messagebox.showerror("Nieprawidłowy tryb", "Wybierz tryb playlisty lub pojedynczego utworu.")
            return

        self.status_tree.delete(*self.status_tree.get_children())
        for i, url in enumerate(urls, start=1):
            self.status_tree.insert("", "end", iid=str(i), values=("queued", url))

        self.append_log("=== Start ===")
        self.set_controls_state(False)

        self.worker_thread = threading.Thread(
            target=self.run_downloads,
            args=(urls, output_dir, audio_format, playlist_mode),
            daemon=True,
        )
        self.worker_thread.start()

    def run_downloads(self, urls, output_dir: Path, audio_format: str, playlist_mode: str):
        ensure_dirs()
        try:
            ensure_yt_dlp()
        except Exception as e:
            queue_event(self.event_queue, {"type": "log", "text": f"Failed to ensure yt-dlp: {e}"})
            queue_event(self.event_queue, {"type": "done"})
            return
        try:
            ensure_ffmpeg()
        except Exception as e:
            queue_event(self.event_queue, {"type": "log", "text": f"Failed to ensure ffmpeg: {e}"})
            queue_event(self.event_queue, {"type": "log", "text": "Warning: ffmpeg missing or failed to extract. Conversion may fail."})

        output_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
            futures = {
                exe.submit(
                    run_yt_dlp_for_url,
                    url,
                    i + 1,
                    output_dir,
                    audio_format,
                    playlist_mode,
                    self.event_queue,
                ): (url, i + 1)
                for i, url in enumerate(urls)
            }
            for fut in as_completed(futures):
                url, index = futures[fut]
                try:
                    _, code = fut.result()
                    status = "done" if code == 0 else f"failed ({code})"
                    queue_event(self.event_queue, {"type": "status", "index": index, "status": status})
                except Exception as e:
                    queue_event(self.event_queue, {"type": "log", "text": f"[ERROR] {url} raised exception: {e}"})
                    queue_event(self.event_queue, {"type": "status", "index": index, "status": "error"})

        elapsed = time.time() - start_time
        queue_event(self.event_queue, {"type": "log", "text": f"All done. Elapsed: {elapsed:.1f}s"})
        queue_event(self.event_queue, {"type": "done"})

    def append_log(self, text: str):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def process_queue(self):
        while True:
            try:
                event = self.event_queue.get_nowait()
            except Empty:
                break
            if event.get("type") == "log":
                self.append_log(event.get("text", ""))
            elif event.get("type") == "status":
                index = str(event.get("index"))
                status = event.get("status")
                if self.status_tree.exists(index):
                    current = self.status_tree.item(index, "values")
                    self.status_tree.item(index, values=(status, current[1]))
            elif event.get("type") == "done":
                self.set_controls_state(True)
        self.root.after(200, self.process_queue)


def main():
    if "--cli" in sys.argv:
        cli_main()
        return
    root = tk.Tk()
    app = DownloaderGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
