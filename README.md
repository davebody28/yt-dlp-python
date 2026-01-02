# yt-dlp Python downloader

## How to
yt-dlp Python downloader

How to run (Windows):
1. Put your URLs (one per line) into urls.txt
2. Run run.bat (double-click) or run in terminal:
   python downloader.py
3. Watch console output (progress). Logs are written to logs/yt-dlp.log and logs/yt-dlp-errors.log
4. MP3 files appear in downloads/

Notes:
- Binaries (yt-dlp.exe and ffmpeg.exe) will be downloaded to bin/ automatically on first run.
- If you see JS runtime warnings for YouTube, install Node.js (recommended).
- Public hosting of this service is discouraged due to policy/abuse risk; run locally or in a secured private environment.

> [!IMPORTANT]
> Software used:
> * Python
> * Node.js
> * yt-dlp
> * ffmpeg

## Directory structure
```
yt-dlp-python/
│
├── downloader.py        # główny skrypt Python (uruchamiasz)
├── run.bat              # Windows: launcher (uruchamia python)
├── urls.txt             # lista URL (jeden per linia)
├── archive.txt          # download archive (yt-dlp will fill it)
├── README.md
├── .gitignore
│
├── downloads/           # miejsce docelowe - tu trafią mp3
├── logs/
│   ├── yt-dlp.log
│   └── yt-dlp-errors.log
└── bin/
    ├── yt-dlp.exe       # automatycznie pobierane (po pierwszym uruchomieniu)
    └── ffmpeg.exe       # automatycznie pobierane (po pierwszym uruchomieniu)
```
