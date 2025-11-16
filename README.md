# PDF to SVG Cropper

A simple desktop app to view PDFs, select areas, and export those selections as SVG (plus some customization options) or copy to the clipboard directly.

Built with Python + Tkinter + PyMuPDF.

![screenshot](screenshot.png)

## Features

**PDF Loading**
- Open local files or URLs (http/https)
- Open from `file://` links with page anchors (`#page=N`)
- Recent files history

**Navigation**
- Multi-page support with Prev/Next buttons (or arrow keys)
- Direct page number entry
- Ctrl+Scroll to zoom
- Scroll wheel to pan vertically
- Middle-button drag to pan in any direction

**Selection & Export**
- Click-and-drag selection rectangle
- Export to `.svg` file or copy to clipboard
- Text preservation (preserve as text vs paths)
- Remove manual character kerning
- Remove white backgrounds
- Convert to grayscale

## Requirements

- Python 3.9+
- Windows, macOS, or Linux

## Setup

```pwsh
python -m venv .venv
. .venv/Scripts/Activate.ps1  # Windows
pip install -r requirements.txt
```

## Run

```pwsh
python main.py
```

## Notes

- SVG export uses vector clipping for accurate results
- Downloaded PDFs from URLs are saved to temp directory
- Pan/zoom reset when changing pages
