@echo off
chcp 65001 >nul
title yt-dlp Python Downloader

echo ===============================
echo   yt-dlp PYTHON AUDIO DOWNLOADER
echo ===============================
echo.

python "%~dp0downloader.py"

echo.
echo ===============================
echo   ZAKOŃCZONE
echo ===============================
pause
