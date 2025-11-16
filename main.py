import io
import json
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageTk


class PdfToSvgCropper(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF to SVG Cropper")
        self.minsize(800, 900)

        # State
        self.doc = None
        self.pdf_path = None
        self.page_index = 0
        self.scale = 1.0
        self.zoom_level = 1.0  # User zoom multiplier
        self.auto_fit = True  # Whether to auto-fit to window
        self.photo = None  # keep reference
        self.selection_rect_id = None
        self.sel_start = None
        self.sel_end = None
        self.recent_files_path = Path.home() / ".pdf_to_svg_recent.json"
        self.recent_files = self._load_recent_files()
        self.preserve_text = tk.BooleanVar(value=True)
        self.remove_kerning = tk.BooleanVar(value=False)
        self.remove_background = tk.BooleanVar(value=False)
        self.convert_grayscale = tk.BooleanVar(value=False)

        # UI
        self._build_ui()

        # re-render on resize
        self.canvas.bind("<Configure>", self._on_canvas_resize)

    def _build_ui(self):
        # Top controls
        top = ttk.Frame(self, padding="4")
        top.pack(side=tk.TOP, fill=tk.X)

        btn_open = ttk.Button(top, text="Open PDF", command=self.open_pdf)
        btn_open.pack(side=tk.LEFT, padx=4, pady=4)

        btn_recent = ttk.Button(top, text="Open Recent", command=self.open_recent)
        btn_recent.pack(side=tk.LEFT, padx=2, pady=4)

        ttk.Label(top, text="URL:").pack(side=tk.LEFT, padx=(12, 2))
        self.url_entry = ttk.Entry(top, width=30)
        self.url_entry.pack(side=tk.LEFT, padx=2)
        self.url_entry.bind("<Return>", lambda e: self.open_from_url())
        btn_open_url = ttk.Button(top, text="Open", command=self.open_from_url)
        btn_open_url.pack(side=tk.LEFT, padx=2)

        ttk.Label(top, text="Page:").pack(side=tk.LEFT, padx=(12, 2))
        self.page_entry = ttk.Entry(top, width=5)
        self.page_entry.pack(side=tk.LEFT, padx=2)
        self.page_entry.bind("<Return>", lambda e: self.goto_page())
        self.page_label = ttk.Label(top, text="/-")
        self.page_label.pack(side=tk.LEFT, padx=0)

        btn_prev = ttk.Button(top, text="<", command=self.prev_page, width=2)
        btn_prev.pack(side=tk.LEFT, padx=(8, 2))

        btn_next = ttk.Button(top, text=">", command=self.next_page, width=2)
        btn_next.pack(side=tk.LEFT, padx=2)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)

        self.text_check = ttk.Checkbutton(top, text="Preserve text", variable=self.preserve_text)
        self.text_check.pack(side=tk.LEFT, padx=4)

        self.kern_check = ttk.Checkbutton(top, text="Remove manual kerns", variable=self.remove_kerning)
        self.kern_check.pack(side=tk.LEFT, padx=4)

        self.bg_check = ttk.Checkbutton(top, text="Remove background", variable=self.remove_background)
        self.bg_check.pack(side=tk.LEFT, padx=4)

        self.gray_check = ttk.Checkbutton(top, text="Grayscale", variable=self.convert_grayscale)
        self.gray_check.pack(side=tk.LEFT, padx=4)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)

        btn_export = ttk.Button(top, text="Export Selection as SVG…", command=self.export_selection_as_svg)
        btn_export.pack(side=tk.LEFT, padx=4)

        btn_copy = ttk.Button(top, text="Copy SVG to Clipboard", command=self.copy_svg_to_clipboard)
        btn_copy.pack(side=tk.LEFT, padx=2)

        # Canvas for page preview
        self.canvas = tk.Canvas(self, bg="#2b2b2b", highlightthickness=0)
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Mouse bindings for selection
        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        
        # Mouse wheel zoom (Ctrl + scroll)
        self.canvas.bind("<Control-MouseWheel>", self._on_zoom)
        # For Linux
        self.canvas.bind("<Control-Button-4>", self._on_zoom)
        self.canvas.bind("<Control-Button-5>", self._on_zoom)

    # -------------------- PDF handling --------------------
    def _load_recent_files(self):
        """Load recent files list from disk"""
        try:
            if self.recent_files_path.exists():
                with open(self.recent_files_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Filter out files that no longer exist
                    return [p for p in data if Path(p).exists()]
        except Exception:
            pass
        return []

    def _save_recent_files(self):
        """Save recent files list to disk"""
        try:
            with open(self.recent_files_path, "w", encoding="utf-8") as f:
                json.dump(self.recent_files, f)
        except Exception:
            pass

    def _add_to_recent(self, path):
        """Add a file to recent list (move to top if already present)"""
        path = str(Path(path).absolute())
        if path in self.recent_files:
            self.recent_files.remove(path)
        self.recent_files.insert(0, path)
        # Keep only last 10
        self.recent_files = self.recent_files[:10]
        self._save_recent_files()

    def open_pdf(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(
                title="Open PDF",
                filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            )
        if not path:
            return
        try:
            self.doc = fitz.open(path)
            self.pdf_path = path
            self.page_index = 0
            self._add_to_recent(path)
            self._update_page_label()
            self._render_current_page()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open PDF:\n{e}")
            self.doc = None
            self.pdf_path = None

    def open_recent(self):
        """Show menu of recent files"""
        if not self.recent_files:
            messagebox.showinfo("Open Recent", "No recent files")
            return
        # Create popup menu
        menu = tk.Menu(self, tearoff=0)
        for fpath in self.recent_files:
            fname = Path(fpath).name
            menu.add_command(label=fname, command=lambda p=fpath: self.open_pdf(p))
        try:
            menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        finally:
            menu.grab_release()

    def open_from_url(self):
        """Open PDF from URL or file:// link"""
        from urllib.parse import urlparse, unquote, parse_qs
        import tempfile
        import urllib.request
        
        url = self.url_entry.get().strip()
        if not url:
            return
        
        try:
            parsed = urlparse(url)
            target_page = None
            
            # Extract page number from fragment (#page=123)
            if parsed.fragment:
                if parsed.fragment.startswith('page='):
                    try:
                        target_page = int(parsed.fragment.split('=')[1]) - 1  # Convert to 0-indexed
                    except (ValueError, IndexError):
                        pass
            
            # Handle file:// URLs
            if parsed.scheme == 'file':
                # Decode percent-encoded path
                file_path = unquote(parsed.path)
                # On Windows, remove leading slash from /C:/path
                if os.name == 'nt' and file_path.startswith('/') and len(file_path) > 2 and file_path[2] == ':':
                    file_path = file_path[1:]
                
                if not Path(file_path).exists():
                    messagebox.showerror("Error", f"File not found: {file_path}")
                    return
                
                self.open_pdf(file_path)
            
            # Handle http:// and https:// URLs
            elif parsed.scheme in ('http', 'https'):
                # Download to temporary file
                with urllib.request.urlopen(url.split('#')[0]) as response:
                    pdf_data = response.read()
                
                # Save to temp file
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
                temp_file.write(pdf_data)
                temp_file.close()
                
                self.open_pdf(temp_file.name)
            
            else:
                messagebox.showerror("Error", f"Unsupported URL scheme: {parsed.scheme}")
                return
            
            # Jump to page if specified in fragment
            if target_page is not None and self.doc:
                if 0 <= target_page < self.doc.page_count:
                    self.page_index = target_page
                    self._update_page_label()
                    self._render_current_page()
        
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open from URL:\n{e}")

    def _update_page_label(self):
        if self.doc:
            self.page_label.config(text=f"/{self.doc.page_count}")
            self.page_entry.delete(0, tk.END)
            self.page_entry.insert(0, str(self.page_index + 1))
        else:
            self.page_label.config(text="/-")
            self.page_entry.delete(0, tk.END)

    def prev_page(self):
        if not self.doc:
            return
        if self.page_index > 0:
            self.page_index -= 1
            self._update_page_label()
            self._render_current_page()

    def next_page(self):
        if not self.doc:
            return
        if self.page_index < self.doc.page_count - 1:
            self.page_index += 1
            self._update_page_label()
            self._render_current_page()

    def goto_page(self):
        """Jump to page number entered in entry field"""
        if not self.doc:
            return
        try:
            page_num = int(self.page_entry.get())
            if 1 <= page_num <= self.doc.page_count:
                self.page_index = page_num - 1
                self._update_page_label()
                self._render_current_page()
            else:
                messagebox.showwarning("Go to Page", f"Page must be between 1 and {self.doc.page_count}")
        except ValueError:
            messagebox.showwarning("Go to Page", "Please enter a valid page number")

    def _on_canvas_resize(self, _event):
        # re-render to fit new size
        if self.doc:
            self._render_current_page()

    def _render_current_page(self):
        if not self.doc:
            return
        page = self.doc.load_page(self.page_index)
        page_rect = page.rect

        # choose scale to fit canvas width while keeping aspect; fallback if canvas not realized yet
        c_w = max(self.canvas.winfo_width(), 1)
        c_h = max(self.canvas.winfo_height(), 1)
        if c_w <= 1 or c_h <= 1:
            # likely not realized; schedule later
            self.after(50, self._render_current_page)
            return

        # Calculate base scale
        if self.auto_fit:
            # fit to width with some padding
            padding = 16
            target_w = max(c_w - padding * 2, 100)
            base_scale = target_w / page_rect.width
        else:
            # Use previous base scale or default
            base_scale = getattr(self, 'base_scale', 1.0)
        
        # Store base scale for when auto_fit is disabled
        self.base_scale = base_scale
        
        # Apply user zoom
        self.scale = base_scale * self.zoom_level

        mat = fitz.Matrix(self.scale, self.scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        # Convert to PIL image
        img_data = pix.tobytes("png")
        pil_img = Image.open(io.BytesIO(img_data))
        self.photo = ImageTk.PhotoImage(pil_img)

        self.canvas.delete("all")
        # center horizontally
        x_off = (c_w - self.photo.width()) // 2
        y_off = max((c_h - self.photo.height()) // 2, 0)
        self.canvas.create_image(x_off, y_off, anchor=tk.NW, image=self.photo, tags=("page",))

        # Store image origin to map between canvas and image coords
        self.img_origin = (x_off, y_off)

        # Reset selection
        self._clear_selection()

    # -------------------- Selection handling --------------------
    def _on_zoom(self, event):
        """Handle Ctrl+scroll wheel zoom"""
        if not self.doc:
            return
        
        # Determine zoom direction
        if event.num == 4 or event.delta > 0:  # Scroll up / zoom in
            zoom_factor = 1.1
        elif event.num == 5 or event.delta < 0:  # Scroll down / zoom out
            zoom_factor = 0.9
        else:
            return
        
        # Update zoom level
        new_zoom = self.zoom_level * zoom_factor
        # Clamp zoom level between 0.1x and 10x
        new_zoom = max(0.1, min(10.0, new_zoom))
        
        if new_zoom != self.zoom_level:
            self.zoom_level = new_zoom
            self.auto_fit = False  # Disable auto-fit when user zooms
            self._render_current_page()
    
    def _on_mouse_down(self, event):
        if not self.doc or not hasattr(self, "img_origin"):
            return
        x0 = event.x - self.img_origin[0]
        y0 = event.y - self.img_origin[1]
        if not self._point_inside_image(x0, y0):
            return
        self.sel_start = (max(0, x0), max(0, y0))
        self.sel_end = self.sel_start
        self._draw_selection()

    def _on_mouse_drag(self, event):
        if self.sel_start is None or not hasattr(self, "img_origin"):
            return
        x1 = event.x - self.img_origin[0]
        y1 = event.y - self.img_origin[1]
        self.sel_end = (x1, y1)
        self._draw_selection()

    def _on_mouse_up(self, _event):
        # Finalize selection
        pass

    def _draw_selection(self):
        self._remove_selection_rect()
        if self.sel_start is None or self.sel_end is None:
            return
        x0, y0 = self.sel_start
        x1, y1 = self.sel_end
        # clamp to image bounds if we know size
        if self.photo:
            w, h = self.photo.width(), self.photo.height()
            x0 = min(max(0, x0), w)
            y0 = min(max(0, y0), h)
            x1 = min(max(0, x1), w)
            y1 = min(max(0, y1), h)
        rx0, ry0 = min(x0, x1), min(y0, y1)
        rx1, ry1 = max(x0, x1), max(y0, y1)
        # draw rectangle relative to canvas with offset
        ox, oy = getattr(self, "img_origin", (0, 0))
        self.selection_rect_id = self.canvas.create_rectangle(
            rx0 + ox,
            ry0 + oy,
            rx1 + ox,
            ry1 + oy,
            outline="#00e1ff",
            width=2,
        )

    def _remove_selection_rect(self):
        if self.selection_rect_id is not None:
            self.canvas.delete(self.selection_rect_id)
            self.selection_rect_id = None

    def _clear_selection(self):
        self.sel_start = None
        self.sel_end = None
        self._remove_selection_rect()

    def _point_inside_image(self, x, y):
        if not self.photo:
            return False
        return 0 <= x < self.photo.width() and 0 <= y < self.photo.height()

    def _get_selection_rect_image_coords(self):
        if self.sel_start is None or self.sel_end is None or not self.photo:
            return None
        x0, y0 = self.sel_start
        x1, y1 = self.sel_end
        w, h = self.photo.width(), self.photo.height()
        # clamp
        x0 = min(max(0, x0), w)
        y0 = min(max(0, y0), h)
        x1 = min(max(0, x1), w)
        y1 = min(max(0, y1), h)
        rx0, ry0 = min(x0, x1), min(y0, y1)
        rx1, ry1 = max(x0, x1), max(y0, y1)
        if rx1 - rx0 < 1 or ry1 - ry0 < 1:
            return None
        return (rx0, ry0, rx1, ry1)

    # -------------------- SVG export --------------------
    def _selection_pdf_rect(self):
        sel = self._get_selection_rect_image_coords()
        if not sel or not self.doc:
            return None
        x0, y0, x1, y1 = sel
        # map image px to PDF points
        px_to_pt = 1.0 / max(self.scale, 1e-6)
        left = x0 * px_to_pt
        top = y0 * px_to_pt
        right = x1 * px_to_pt
        bottom = y1 * px_to_pt
        return fitz.Rect(left, top, right, bottom)

    def _svg_from_selection(self):
        if not self.doc:
            raise RuntimeError("No PDF open")
        clip_rect = self._selection_pdf_rect()
        if not clip_rect:
            raise RuntimeError("No valid selection to export")
        if clip_rect.width <= 0 or clip_rect.height <= 0:
            raise RuntimeError("Selection has zero size")

        # Create in-memory one-page PDF with the clipped area
        src_pno = self.page_index
        out = fitz.open()
        page = out.new_page(width=clip_rect.width, height=clip_rect.height)
        # target rect is the full new page
        target = fitz.Rect(0, 0, clip_rect.width, clip_rect.height)
        page.show_pdf_page(target, self.doc, src_pno, clip=clip_rect)
        # Use text preservation mode if checkbox is enabled
        svg = page.get_svg_image(text_as_path=not self.preserve_text.get())
        
        # Remove manual kerning if requested
        if self.preserve_text.get() and self.remove_kerning.get():
            svg = self._remove_svg_kerning(svg)
        
        # Remove background if requested
        if self.remove_background.get():
            svg = self._remove_svg_background(svg)
        
        # Convert to grayscale if requested
        if self.convert_grayscale.get():
            svg = self._convert_svg_grayscale(svg)
        
        out.close()
        return svg

    def _remove_svg_kerning(self, svg):
        """Remove individual character positioning from SVG text elements"""
        import re
        # Find text elements with x/y arrays (manual positioning)
        # Merge characters into single text element at starting position
        def merge_text_spans(match):
            full_tag = match.group(0)
            # Extract x and y arrays
            x_match = re.search(r'x="([^"]+)"', full_tag)
            y_match = re.search(r'y="([^"]+)"', full_tag)
            # Extract text content
            text_match = re.search(r'>([^<]+)<', full_tag)
            
            if x_match and y_match and text_match:
                x_vals = x_match.group(1).split()
                y_vals = y_match.group(1).split()
                text = text_match.group(1)
                
                # Use first position only, remove individual char positioning
                if len(x_vals) > 0 and len(y_vals) > 0:
                    first_x = x_vals[0]
                    first_y = y_vals[0]
                    # Rebuild text element with single position
                    new_tag = re.sub(r'x="[^"]+"', f'x="{first_x}"', full_tag)
                    new_tag = re.sub(r'y="[^"]+"', f'y="{first_y}"', new_tag)
                    return new_tag
            
            return full_tag
        
        # Pattern to match text elements with coordinate arrays
        pattern = r'<text[^>]*x="[^"]*\s[^"]*"[^>]*y="[^"]*"[^>]*>[^<]+</text>'
        svg = re.sub(pattern, merge_text_spans, svg)
        
        return svg

    def _remove_svg_background(self, svg):
        """Remove white/background rectangles and paths from SVG"""
        import re
        lines = svg.split('\n')
        filtered_lines = []
        
        for line in lines:
            # Skip white/light colored backgrounds
            is_white = ('fill="#ffffff"' in line or 'fill="#fff"' in line or 
                       'fill="rgb(255,255,255)"' in line or 'fill="white"' in line)
            
            if is_white:
                # Skip rect elements that are backgrounds
                if '<rect' in line and ('x="0"' in line or 'y="0"' in line):
                    continue
                # Skip path elements that are large backgrounds (typically have large dimensions in the d attribute)
                if '<path' in line:
                    # Check if it's a large rectangular path (H and V commands with large values)
                    if re.search(r'[HV]\s*\d{3,}', line):  # H or V with 3+ digit numbers
                        continue
            
            filtered_lines.append(line)
        
        return '\n'.join(filtered_lines)

    def _convert_svg_grayscale(self, svg):
        """Convert all colors in SVG to grayscale"""
        import re
        
        def rgb_to_gray(match):
            rgb_str = match.group(1)
            values = rgb_str.split(',')
            if len(values) == 3:
                r, g, b = [int(v.strip()) for v in values]
                # Standard grayscale conversion formula
                gray = int(0.299 * r + 0.587 * g + 0.114 * b)
                return f'rgb({gray},{gray},{gray})'
            return match.group(0)
        
        # Convert rgb() colors
        svg = re.sub(r'rgb\(([^)]+)\)', rgb_to_gray, svg)
        
        # Convert hex colors
        def hex_to_gray(match):
            hex_color = match.group(1)
            if len(hex_color) == 6:
                r = int(hex_color[0:2], 16)
                g = int(hex_color[2:4], 16)
                b = int(hex_color[4:6], 16)
                gray = int(0.299 * r + 0.587 * g + 0.114 * b)
                gray_hex = f'{gray:02x}'
                return f'#{gray_hex}{gray_hex}{gray_hex}'
            return match.group(0)
        
        svg = re.sub(r'#([0-9a-fA-F]{6})', hex_to_gray, svg)
        
        return svg

    def export_selection_as_svg(self):
        try:
            svg = self._svg_from_selection()
        except Exception as e:
            messagebox.showwarning("Export SVG", str(e))
            return
        path = filedialog.asksaveasfilename(
            title="Save SVG",
            defaultextension=".svg",
            filetypes=[("SVG", "*.svg")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
            messagebox.showinfo("Export SVG", f"Saved: {path}")
        except Exception as e:
            messagebox.showerror("Export SVG", f"Failed to save SVG:\n{e}")

    def copy_svg_to_clipboard(self):
        try:
            svg = self._svg_from_selection()
        except Exception as e:
            messagebox.showwarning("Copy SVG", str(e))
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(svg)
            self.update()  # ensure clipboard set
            messagebox.showinfo("Copy SVG", "SVG code copied to clipboard")
        except Exception as e:
            messagebox.showerror("Copy SVG", f"Failed to copy SVG:\n{e}")


def main():
    app = PdfToSvgCropper()
    app.mainloop()


if __name__ == "__main__":
    main()
