# yt-dlp Python downloader

## How to
How to run (Windows):
1. Run `run.bat` (double-click) or in terminal:
   `python downloader.py`
2. Paste URLs (one per line) into the app.
3. Pick output format (mp3/aac/flac/webm/mp4) and output directory.
4. Choose playlist mode: single video only or full playlist.
5. Click **Download** and watch the status; logs are available via the **Show logs** button.
6. Files appear in the selected output directory (default: your Windows Downloads folder).

CLI mode (optional):
1. Put your URLs (one per line) into `urls.txt`
2. Run `python downloader.py --cli` (optional: `--single` or `--playlist`)
3. Watch console output (progress). Logs are written to `logs/yt-dlp.log` and `logs/yt-dlp-errors.log`
4. Files appear in the default output directory (Downloads on Windows, `downloads/` elsewhere)

Notes:
- Binaries (yt-dlp.exe and ffmpeg.exe) will be downloaded to `bin/` automatically on first run.
- yt-dlp self-updates on each run; ffmpeg is refreshed when a new release ZIP is detected.
- App icon is embedded in `icon_data.py` and the app will try to fetch the GitHub avatar at first run and cache it in `cache/` for the title bar.
- If you see JS runtime warnings for YouTube, install Node.js (recommended).
- Public hosting of this service is discouraged due to policy/abuse risk; run locally or in a secured private environment.

> [!IMPORTANT]
> Software used:
> * Python
> * Node.js
> * yt-dlp
> * ffmpeg

## Build EXE (Windows)
Use PyInstaller to create a single executable. The EXE will still download yt-dlp/ffmpeg on first run.

```bash
pip install pyinstaller
python tools/write_icon.py
pyinstaller --onefile --windowed --icon app.ico --name yt-dlp-downloader downloader.py
```

## Directory structure
```
yt-dlp-python/
│
├── downloader.py        # główny skrypt Python (uruchamiasz)
├── run.bat              # Windows: launcher (uruchamia python)
├── urls.txt             # lista URL (jeden per linia)
├── icon_data.py         # wbudowana ikona (base64)
├── README.md
├── .gitignore
│
├── downloads/           # miejsce docelowe - tu trafią pliki (poza Windows)
├── logs/
│   ├── yt-dlp.log
│   └── yt-dlp-errors.log
├── cache/               # cache na ikony (pobierane z URL)
├── tools/
│   └── write_icon.py     # generuje app.ico lokalnie do builda EXE
└── bin/
    ├── yt-dlp.exe       # automatycznie pobierane (po pierwszym uruchomieniu)
    └── ffmpeg.exe       # automatycznie pobierane (po pierwszym uruchomieniu)
```
