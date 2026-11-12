@echo off
rem Double-click to start the LOR Sequencer in your browser.
rem The first start installs what it needs (a few minutes); later starts are quick.
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo The LOR Sequencer needs "uv" to run. Install it once by pasting this into PowerShell:
  echo.
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  echo.
  echo Then close this window and double-click "Start LOR Sequencer" again.
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo The LOR Sequencer needs FFmpeg to read songs.
  choice /m "Install FFmpeg now with winget"
  if errorlevel 2 (
    echo You can install it later with: winget install --id Gyan.FFmpeg -e
    pause
    exit /b 1
  )
  winget install --id Gyan.FFmpeg -e --accept-package-agreements --accept-source-agreements
  echo FFmpeg is installed. Close this window and double-click "Start LOR Sequencer" again.
  pause
  exit /b 0
)
echo Getting ready...
uv sync --locked --quiet
if errorlevel 1 (
  echo Setup did not finish. Run "uv run lor-sequence-builder doctor" in this folder for details.
  pause
  exit /b 1
)
echo Starting the LOR Sequencer. Keep this window open while you use it; close it to stop.
uv run lor-sequence-ui
pause
