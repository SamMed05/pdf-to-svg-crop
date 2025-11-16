# PDF to SVG Cropper (GUI)

A minimal desktop app to view a PDF, select an area visually, and export that selection as an SVG (vector) snippet. Also supports copying the SVG code to clipboard.

Built with Python + Tkinter + PyMuPDF.

## Features

- Open multi-page PDFs
- Page navigation (Prev/Next)
- Click-and-drag selection rectangle
- Export selection to `.svg` (vector) using MuPDF clipping
- Copy SVG code to clipboard

## Requirements

- Python 3.9+
- Windows, macOS, or Linux

## Setup

```pwsh
# From project root
python -m venv .venv
. .venv/Scripts/Activate.ps1
pip install -r requirements.txt
```

## Run

```pwsh
python main.py
```

## How it works

- The page is rendered as an image preview for fast UI.
- The selected rectangle is mapped back to PDF points.
- A new in-memory one-page PDF is created with that clip applied, and then converted to SVG via MuPDF (`page.get_svg_image()`).

## Notes

- SVG export preserves vectors; text may be converted to paths depending on PDF content.
- If your selection is empty or outside the page, export is disabled.
