#!/usr/bin/env python3
"""
yt-dlp Python launcher
- reads urls.txt
- auto-downloads yt-dlp.exe and ffmpeg if missing (bin/)
- runs several yt-dlp processes in parallel (one process per URL)
- streams output to console and writes logs (logs/)
- uses download archive to avoid duplicates
- converts best audio -> mp3, embeds metadata & cover
"""

import os
import sys
import shutil
import subprocess
import urllib.request
import zipfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------- CONFIG ----------------
BASE = Path(__file__).resolve().parent
BIN = BASE / "bin"
OUT = BASE / "downloads"
LOGS = BASE / "logs"
YT_DLP_EXE = BIN / "yt-dlp.exe"
FFMPEG_EXE = BIN / "ffmpeg.exe"

URLS_FILE = BASE / "urls.txt"
ARCHIVE_FILE = BASE / "archive.txt"
LOG_FILE = LOGS / "yt-dlp.log"
ERR_LOG_FILE = LOGS / "yt-dlp-errors.log"

# parallelism: how many simultaneous URL processes
MAX_WORKERS = 4

# yt-dlp fragment parallelism (inside each process)
PARALLEL_FRAGMENTS = "16"
CONCURRENT_FRAGMENTS = "16"

# audio options
AUDIO_FORMAT = "mp3"
AUDIO_QUALITY = "0"  # best VBR

# download sources
YTDLP_RELEASE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
# ----------------------------------------

def ensure_dirs():
    for d in (BIN, OUT, LOGS):
        d.mkdir(parents=True, exist_ok=True)
    # ensure archive and logs exist
    ARCHIVE_FILE.touch(exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    ERR_LOG_FILE.touch(exist_ok=True)

def download_file(url: str, dest: Path):
    print(f"Downloading {url} -> {dest.name} ...")
    try:
        urllib.request.urlretrieve(url, str(dest))
    except Exception as e:
        print(f"ERROR downloading {url}: {e}")
        raise

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
    if not FFMPEG_EXE.exists():
        zpath = BIN / "ffmpeg.zip"
        download_file(FFMPEG_ZIP_URL, zpath)
        try:
            with zipfile.ZipFile(zpath, 'r') as z:
                z.extractall(BIN)
            # find ffmpeg.exe in extracted tree
            found = None
            for p in BIN.rglob("ffmpeg.exe"):
                found = p
                break
            if not found:
                raise FileNotFoundError("ffmpeg.exe not found inside archive")
            shutil.copy2(found, FFMPEG_EXE)
            print("ffmpeg extracted.")
        finally:
            try:
                zpath.unlink()
            except Exception:
                pass

def read_urls():
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

def run_yt_dlp_for_url(url: str, index: int):
    """
    Runs yt-dlp.exe as a subprocess for a single URL.
    Streams stdout/stderr to console with prefix and appends to log files.
    Returns (url, returncode).
    """
    # build command
    # output template: title only (no uploader prefix)
    outtmpl = f"{OUT / '%(title)s.%(ext)s'}"
    cmd = [
        str(YT_DLP_EXE),
        "-f", "bestaudio/best",
        "--js-runtimes", "node",
        "--extract-audio",
        "--audio-format", AUDIO_FORMAT,
        "--audio-quality", AUDIO_QUALITY,
        "-o", outtmpl,
        "--download-archive", str(ARCHIVE_FILE),
        "-N", PARALLEL_FRAGMENTS,
        "--concurrent-fragments", CONCURRENT_FRAGMENTS,
        "--ffmpeg-location", str(BIN),
        "--add-metadata",
        "--embed-thumbnail",
        "--progress",
        "--newline",
        "--ignore-errors",
        "--no-mtime",
        "--restrict-filenames",
        url
    ]

    prefix = f"[{index}] "

    # open subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, universal_newlines=True)
    # stream lines
    retcode = None
    try:
        with LOG_FILE.open("a", encoding="utf-8") as logf:
            logf.write(f"\n\n=== START {time.strftime('%Y-%m-%d %H:%M:%S')} URL={url}\n")
            for line in proc.stdout:
                # write to console with prefix
                out_line = line.rstrip("\n")
                print(prefix + out_line)
                # write to log
                logf.write(out_line + "\n")
            proc.wait()
            retcode = proc.returncode
            logf.write(f"=== END returncode={retcode}\n")
    except Exception as e:
        # write error log
        with ERR_LOG_FILE.open("a", encoding="utf-8") as ef:
            ef.write(f"ERROR for {url}: {e}\n")
        if proc and proc.poll() is None:
            proc.kill()
        retcode = -1

    return (url, retcode)

def main():
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
        # not fatal, but ffmpeg is needed for conversion; warn user
        print("Warning: ffmpeg missing or failed to extract. Conversion may fail.")

    urls = read_urls()
    print(f"Loaded {len(urls)} URLs. Starting up to {MAX_WORKERS} parallel downloads.")
    start_time = time.time()
    results = []

    # use ThreadPoolExecutor to manage parallel processes and streaming
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as exe:
        futures = {exe.submit(run_yt_dlp_for_url, url, i+1): url for i, url in enumerate(urls)}
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

if __name__ == "__main__":
    main()
