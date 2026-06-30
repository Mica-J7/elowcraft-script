# Elowcraft - Chat Highlights

Streamlit app that detects highlight moments in Twitch VODs by analyzing chat activity spikes, and downloads the corresponding video clips automatically.

Elowcraft analyzes a Twitch VOD's chat replay to automatically surface candidate highlight moments — it downloads the chat log, detects spikes in message activity relative to a rolling baseline, groups nearby spikes into moments, and lets you preview and download the matching video clips individually or in bulk.

## Features

- Download a VOD's chat replay and detect activity spikes against a rolling baseline
- Merge nearby spikes into highlight moments, with top emotes and sample messages
- Jump straight to a moment on Twitch via a timestamped link
- Download clips per moment or in bulk (only the ones missing) via `yt-dlp`
- Export a text report of all detected moments
- Manage downloaded data (chat files and clips) per VOD, with size breakdown and one-click cleanup

## Setup

1. Create and activate a virtual environment, then install dependencies:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. Download [TwitchDownloaderCLI](https://github.com/lay295/TwitchDownloaderCLI) (used for chat downloads) and place the executable at:
   ```
   tools/TwitchDownloaderCLI/TwitchDownloaderCLI.exe
   ```

## Usage

### Streamlit app

```
launch_app.bat
```
or directly:
```
.venv\Scripts\streamlit run src\app.py
```

Paste a VOD URL or ID, click **Valider**, and review the detected moments. Download clips individually or in bulk from the same screen, and manage previously downloaded data from the **Gestion des données** tab.

### Command line

```
.venv\Scripts\python src\find_highlights.py <vod-url-or-id> --extract-clips
```

Run with `--help` for all available options (bin size, spike threshold, clip pre/post-roll, etc).

## Data

Downloaded chat logs, reports, and clips are stored under `data/` (gitignored). `data/clips/<vod_id>/` can grow large — clean it up from the app's data management tab when no longer needed.
