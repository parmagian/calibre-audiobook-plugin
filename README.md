# Calibre Audiobook Generator Plugin

A Calibre plugin that generates high-quality audiobooks (M4B with chapters, or MP3) from your ebooks using modern Text-to-Speech (TTS) engines.

![License](https://img.shields.io/badge/license-GPL-blue.svg)
![Calibre](https://img.shields.io/badge/Calibre-5.0+-green.svg)

## Screenshots

### Main Toolbar
![Toolbar](screenshots/toolbar.png)

### Cassette Emblem on Library Covers
![Emblem](screenshots/emblem.png)

### Configuration Settings
![Configuration](screenshots/config.png)

## Features

- **Multiple TTS Engines**: 
  - **Kokoro** (Default): A natural-sounding open-source voice that runs offline on your computer. Needs [uv](https://docs.astral.sh/uv/) and [ffmpeg](https://ffmpeg.org/) (`brew install uv ffmpeg`). The first run downloads ~350 MB.
  - **Kokoro Cloud**: The same Kokoro voice run on [OpenRouter](https://openrouter.ai/hexgrad/kokoro-82m) instead of your computer: faster and easier on the battery. Paid per character (well under $1 for a typical novel); paste your OpenRouter API key in the plugin settings. Needs ffmpeg.
  - **Edge TTS**: Uses Microsoft Edge's neural voices (needs internet).
  - **gTTS**: Google Text-to-Speech fallback.
- **Expanded Language Support**: Support for English, Spanish (Latam & Spain), Portuguese, French, and Italian.
- **Smart Language Detection**: Automatically detects book language from metadata (supports 2/3-letter ISO codes).
- **Flexible Storage Modes**: 
  - **Internal**: Keeps generated audiobooks inside Calibre's book folders.
  - **External (Unified)**: Collects all audiobooks into a single folder outside Calibre.
- **Voice Selection**: Choose between Male and Female neural voices.
- **Skips front and back matter**: Table of contents, copyright, title pages, dedications, acknowledgments, notes, index, "About the Author" and ads for other books are not read. Introductions, prefaces, forewords and prologues are kept.
- **Chapters and cover**: M4B output has a chapter marker per section plus the book cover and tags (needs ffmpeg).
- **Retries**: Failed pieces are retried, and you are told if any part is still missing.
- **Library Integration**: Automatically adds the generated audiobook as a new format to your existing Calibre book entry.
- **Progress Tracking**: Real-time status updates in Calibre's status bar and a progress dialog.
- **Clean Extraction**: Automatically strips HTML tags, scripts, and styles from EPUBs to ensure clean audio.

## Installation

### Prerequisites
- [Calibre](https://calibre-ebook.com/) installed on your system.
- An active internet connection (required for TTS generation).

### Installation via Calibre
1. Download the latest release (ZIP file).
2. Open Calibre and go to **Preferences > Advanced > Plugins**.
3. Click **Load plugin from file** and select the downloaded ZIP.
4. Restart Calibre.
5. Add the "Audiobook Generator" button to your toolbar:
   - Go to **Preferences > Interface > Toolbars & menus**.
   - Select **The main toolbar**.
   - Find **Audiobook Generator** in the left column and move it to the right.
   - Click **Apply** and restart Calibre.

### Installation for Developers (CLI)
If you are developing or testing the plugin:
```bash
# Clone the repository
git clone https://github.com/yourusername/calibre-audiobook.git
cd calibre-audiobook

# Install dependencies into the vendor folder (requires pip)
pip install -r PipFile -t vendor

# Install into Calibre
calibre-customize -b .
```

## Configuration

You can customize the plugin by going to **Preferences > Advanced > Plugins > User interface action plugins > Audiobook Generator > Customize plugin**.

Available settings:
- **TTS Engine**: Choose between Edge TTS and gTTS.
- **Voice Gender**: Select Male or Female (primarily for Edge TTS).
- **Target Language**: Set the default language for speech synthesis.
- **Detect language from book**: Automatically switch TTS language based on book metadata.
- **Storage Mode**: Toggle between storing in Calibre or a unified external folder.
- **Unified Folder**: Select the destination for your audiobooks when in External mode.

## Usage

1. Select a book in your Calibre library (must have an **EPUB** format).
2. Click the **Audiobook Generator** button in the toolbar.
3. Confirm the generation details in the dialog.
4. Wait for the process to finish (check the status bar for progress).
5. The **M4B** (or MP3) format will be added to the book's available formats in the right-hand panel.

## Development

The project uses a `vendor/` directory to bundle pure-Python dependencies, ensuring portability across different Calibre installations without requiring users to install Python packages manually.

Dependencies are tracked in the `Pipfile`.

## Credits

- **Author**: Miguel Aguero
- **Libraries**: [edge-tts](https://github.com/rany2/edge-tts), [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), [gTTS](https://github.com/pndurette/gTTS), [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/)

## License

This project is licensed under the GNU General Public License (GPL) - see the LICENSE file for details.
