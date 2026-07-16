import io
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageTk


class PdfToSvgCropper(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF to SVG Cropper")
        self.minsize(800, 700)

        # State
        self.doc = None
        self.pdf_path = None
        self.page_index = 0
        self.scale = 1.0
        self.zoom_level = 1.0  # User zoom multiplier
        self.auto_fit = True  # Whether to auto-fit to window
        self.pan_offset = [0, 0]  # Pan offset [x, y]
        self.pan_start = None  # For middle-button drag
        self.photo = None  # keep reference
        self.selection_rect_id = None
        self.sel_start = None
        self.sel_end = None
        self.recent_files_path = Path.home() / ".pdf_to_svg_recent.json"
        self.recent_files = self._load_recent_files()
        self.preserve_text = tk.BooleanVar(value=True)
        self.remove_kerning = tk.BooleanVar(value=False)
        self.space_threshold_ratio = tk.DoubleVar(value=0.35)  # Threshold sensitivity for word space reconstruction
        self.remove_background = tk.BooleanVar(value=False)
        self.convert_grayscale = tk.BooleanVar(value=False)
        self.font_handling = tk.StringVar(value="keep")

        # UI
        self._build_ui()

        # re-render on resize
        self.canvas.bind("<Configure>", self._on_canvas_resize)

    def _set_status(self, message, duration=3000):
        """Set status bar message and clear after duration (ms)"""
        self.status_bar.config(text=message)
        if duration > 0:
            self.after(duration, lambda: self.status_bar.config(text="Ready"))

    def _build_ui(self):
        # Top controls
        top = ttk.Frame(self, padding="4")
        top.pack(side=tk.TOP, fill=tk.X)

        # Create style for icon buttons
        style = ttk.Style()
        style.configure('Icon.TButton', font=('Segoe UI Emoji', 14))

        btn_open = ttk.Button(top, text="📁", command=self.open_pdf, style='Icon.TButton', width=3)
        btn_open.pack(side=tk.LEFT, padx=4, pady=4)
        self._create_tooltip(btn_open, "Open PDF")

        btn_recent = ttk.Button(top, text="🕒", command=self.open_recent, style='Icon.TButton', width=3)
        btn_recent.pack(side=tk.LEFT, padx=2, pady=4)
        self._create_tooltip(btn_recent, "Open Recent")

        btn_svg_editor = ttk.Button(top, text="📝", command=self.open_svg_editor, style='Icon.TButton', width=3)
        btn_svg_editor.pack(side=tk.LEFT, padx=2, pady=4)
        self._create_tooltip(btn_svg_editor, "SVG Editor")

        ttk.Label(top, text="URL:").pack(side=tk.LEFT, padx=(12, 2))
        self.url_entry = ttk.Entry(top, width=25)
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

        # Open detailed popup window for kerning settings
        btn_kern_options = ttk.Button(top, text="Kerning Options", command=self.open_kerning_options)
        btn_kern_options.pack(side=tk.LEFT, padx=4)
        self._create_tooltip(btn_kern_options, "Configure manual kerning reconstruction settings")

        self.bg_check = ttk.Checkbutton(top, text="Remove bg", variable=self.remove_background)
        self.bg_check.pack(side=tk.LEFT, padx=4)

        self.gray_check = ttk.Checkbutton(top, text="Grayscale", variable=self.convert_grayscale)
        self.gray_check.pack(side=tk.LEFT, padx=4)

        ttk.Label(top, text="Fonts:").pack(side=tk.LEFT, padx=(12, 2))
        self.font_combo = ttk.Combobox(top, textvariable=self.font_handling, width=12, state="readonly")
        self.font_combo['values'] = ('Keep original', 'Web-safe fonts')
        self.font_combo.current(0)
        self.font_combo.pack(side=tk.LEFT, padx=2)

        ttk.Separator(top, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=2)

        btn_preview = ttk.Button(top, text="👁", command=self.preview_selection_as_svg, style='Icon.TButton', width=3)
        btn_preview.pack(side=tk.LEFT, padx=4)
        self._create_tooltip(btn_preview, "Preview & Edit Text before Export")

        btn_export = ttk.Button(top, text="💾", command=self.export_selection_as_svg, style='Icon.TButton', width=3)
        btn_export.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(btn_export, "Export Selection as SVG")

        btn_copy = ttk.Button(top, text="📋", command=self.copy_svg_to_clipboard, style='Icon.TButton', width=3)
        btn_copy.pack(side=tk.LEFT, padx=2)
        self._create_tooltip(btn_copy, "Copy SVG to Clipboard")

        # Status bar at bottom
        self.status_bar = ttk.Label(self, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

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
        
        # Mouse wheel pan (scroll without Ctrl)
        self.canvas.bind("<MouseWheel>", self._on_pan_scroll)
        # For Linux
        self.canvas.bind("<Button-4>", self._on_pan_scroll)
        self.canvas.bind("<Button-5>", self._on_pan_scroll)
        
        # Middle-button pan
        self.canvas.bind("<Button-2>", self._on_pan_start)
        self.canvas.bind("<B2-Motion>", self._on_pan_drag)
        self.canvas.bind("<ButtonRelease-2>", self._on_pan_end)
        
        # Keyboard navigation
        self.bind("<Left>", lambda e: self.prev_page())
        self.bind("<Right>", lambda e: self.next_page())
        self.bind("<Up>", lambda e: self.prev_page())
        self.bind("<Down>", lambda e: self.next_page())

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
            self.pan_offset = [0, 0]  # Reset pan
            self.zoom_level = 1.0  # Reset zoom
            self.auto_fit = True  # Re-enable auto-fit
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

    def open_svg_editor(self):
        """Open SVG editor dialog for manual SVG input"""
        editor_window = tk.Toplevel(self)
        editor_window.title("SVG Editor")
        editor_window.geometry("900x700")
        
        # Create main frame
        main_frame = ttk.Frame(editor_window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Top controls
        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill=tk.X, pady=(0, 5))
        
        ttk.Label(controls_frame, text="Paste SVG code below, adjust settings in main window, then click Process:").pack(side=tk.LEFT)
        
        btn_process = ttk.Button(controls_frame, text="Process & Preview", 
                                command=lambda: self._process_svg_input(text_input, preview_canvas, editor_window, bg_var))
        btn_process.pack(side=tk.RIGHT, padx=5)
        
        btn_export = ttk.Button(controls_frame, text="💾 Export", 
                               command=lambda: self._export_processed_svg(editor_window))
        btn_export.pack(side=tk.RIGHT, padx=5)
        
        btn_copy = ttk.Button(controls_frame, text="📋 Copy", 
                             command=lambda: self._copy_processed_svg(editor_window))
        btn_copy.pack(side=tk.RIGHT, padx=5)
        
        # Options summary frame
        options_frame = ttk.Frame(main_frame)
        options_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Show active processing options from main window
        ttk.Label(options_frame, text="Active options:", font=('', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        
        options_text = self._get_active_options_text()
        options_label = ttk.Label(options_frame, text=options_text, font=('', 9), foreground="#0066cc")
        options_label.pack(side=tk.LEFT)
        
        # Store reference to update options label
        editor_window.options_label = options_label
        
        # Preview background selector (pack in reverse order for right alignment)
        bg_var = tk.StringVar(value="Checkerboard")
        bg_combo = ttk.Combobox(options_frame, textvariable=bg_var, width=12, state="readonly")
        bg_combo['values'] = ('White', 'Dark gray', 'Checkerboard')
        bg_combo.current(2)
        bg_combo.pack(side=tk.RIGHT)
        ttk.Label(options_frame, text="Preview bg:").pack(side=tk.RIGHT, padx=(10, 5))
        bg_combo.bind('<<ComboboxSelected>>', 
                     lambda e: self._update_preview_background(preview_canvas, bg_var.get()))
        
        # Create paned window for input/preview
        paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # Left side: SVG input
        left_frame = ttk.Frame(paned)
        paned.add(left_frame, weight=1)
        
        ttk.Label(left_frame, text="Input SVG:").pack(anchor=tk.W)
        
        text_input = tk.Text(left_frame, wrap=tk.NONE, font=('Consolas', 10))
        text_input.pack(fill=tk.BOTH, expand=True)
        
        # Add scrollbars
        v_scroll = ttk.Scrollbar(text_input, orient=tk.VERTICAL, command=text_input.yview)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text_input.config(yscrollcommand=v_scroll.set)
        
        h_scroll = ttk.Scrollbar(left_frame, orient=tk.HORIZONTAL, command=text_input.xview)
        h_scroll.pack(fill=tk.X)
        text_input.config(xscrollcommand=h_scroll.set)
        
        # Right side: Preview
        right_frame = ttk.Frame(paned)
        paned.add(right_frame, weight=1)
        
        ttk.Label(right_frame, text="Preview:").pack(anchor=tk.W)
        
        preview_canvas = tk.Canvas(right_frame, bg="white")
        preview_canvas.pack(fill=tk.BOTH, expand=True)
        
        # Store reference to processed SVG and background
        editor_window.processed_svg = None
        
        # Bind Ctrl+Enter to process
        text_input.bind('<Control-Return>', 
                       lambda e: self._process_svg_input(text_input, preview_canvas, editor_window, bg_var))
    
    def _get_active_options_text(self):
        """Get text description of active processing options"""
        options = []
        if self.remove_kerning.get():
            options.append(f"Remove kerns (th: {self.space_threshold_ratio.get():.2f})")
        if self.remove_background.get():
            options.append("Remove bg")
        if self.convert_grayscale.get():
            options.append("Grayscale")
        if self.preserve_text.get():
            font_mode = self.font_combo.get()
            if font_mode == 'Web-safe fonts':
                options.append("Web-safe fonts")
            else:
                options.append("Keep fonts")
        
        return ", ".join(options) if options else "None"
    
    def _process_svg_input(self, text_widget, canvas, window, bg_var):
        """Process SVG from text input and display preview"""
        # Update active options display
        if hasattr(window, 'options_label'):
            window.options_label.config(text=self._get_active_options_text())
        
        svg_code = text_widget.get("1.0", tk.END).strip()
        
        if not svg_code:
            messagebox.showwarning("Empty Input", "Please paste SVG code first")
            return
        
        try:
            # Apply same processing as PDF export
            processed_svg = svg_code
            
            # Apply kerning removal if enabled
            if self.remove_kerning.get():
                processed_svg = self._remove_svg_kerning(processed_svg)
            
            # Apply background removal if enabled
            if self.remove_background.get():
                processed_svg = self._remove_svg_background(processed_svg)
            
            # Apply grayscale if enabled
            if self.convert_grayscale.get():
                processed_svg = self._convert_svg_grayscale(processed_svg)
            
            # Apply font handling
            if self.preserve_text.get():
                font_mode = self.font_combo.get()
                if font_mode == 'Web-safe fonts':
                    processed_svg = self._replace_with_websafe_fonts(processed_svg)
            
            # Store processed SVG
            window.processed_svg = processed_svg
            
            # Render preview
            self._render_svg_preview(processed_svg, canvas, bg_var.get())
            
            self._set_status("✓ SVG processed successfully")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to process SVG:\n{e}")
            self._set_status(f"✗ Error processing SVG")
    
    def _render_svg_preview(self, svg_code, canvas, background="white", interactive=False):
        """Render SVG as preview in canvas with specified background"""
        try:
            from io import BytesIO
            import cairosvg
            from PIL import Image, ImageTk
            
            # Convert SVG to PNG with transparency
            png_data = cairosvg.svg2png(bytestring=svg_code.encode('utf-8'))
            
            # Load as PIL Image
            # img = Image.open(BytesIO(png_data)).convert('RGBA')
            # orig_w, orig_h = img.size
            
            # Resize to fit canvas
            canvas_width = canvas.winfo_width()
            canvas_height = canvas.winfo_height()
            
            # if canvas_width > 1 and canvas_height > 1:
            #     img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)
            
            img = Image.open(BytesIO(png_data)).convert('RGBA')
            orig_w, orig_h = img.size

            # fit to canvas first
            if canvas_width > 1 and canvas_height > 1:
                img.thumbnail((canvas_width - 20, canvas_height - 20), Image.Resampling.LANCZOS)

            # apply interactive zoom
            zoom = getattr(canvas, 'zoom', 1.0)
            if zoom != 1.0:
                img = img.resize(
                    (int(img.size[0] * zoom), int(img.size[1] * zoom)),
                    Image.Resampling.LANCZOS
                )
                
            cx = canvas_width // 2 + getattr(canvas, 'pan_x', 0)
            cy = canvas_height // 2 + getattr(canvas, 'pan_y', 0)
            
            # Create background based on selection
            bg_img = Image.new('RGBA', img.size)
            
            if background.lower() == 'white':
                bg_img.paste((255, 255, 255, 255), (0, 0, img.size[0], img.size[1]))
            elif background.lower() == 'dark gray':
                bg_img.paste((60, 60, 60, 255), (0, 0, img.size[0], img.size[1]))
            elif background.lower() == 'checkerboard':
                # Create checkerboard pattern
                checker_size = 10
                for y in range(0, img.size[1], checker_size):
                    for x in range(0, img.size[0], checker_size):
                        color = (220, 220, 220, 255) if (x // checker_size + y // checker_size) % 2 == 0 else (255, 255, 255, 255)
                        bg_img.paste(color, (x, y, min(x + checker_size, img.size[0]), min(y + checker_size, img.size[1])))
            
            # Composite SVG over background
            bg_img.paste(img, (0, 0), img)
            
            # Convert to PhotoImage
            photo = ImageTk.PhotoImage(bg_img)
            
            # Update canvas background color
            if background.lower() == 'white':
                canvas.config(bg='#f0f0f0')
            elif background.lower() == 'dark gray':
                canvas.config(bg='#2b2b2b')
            else:
                canvas.config(bg='#cccccc')
            
            # Clear canvas and display
            canvas.delete("all")
            cx, cy = canvas_width // 2, canvas_height // 2
            canvas.create_image(cx, cy, image=photo, anchor=tk.CENTER)
            
            # Keep reference
            canvas.image = photo

            if interactive:
                thumb_w, thumb_h = img.size
                svg_w, svg_h = self._get_svg_dimensions_from_string(svg_code, orig_w, orig_h)
                canvas.preview_layout = {
                    'img_left': cx - thumb_w // 2,
                    'img_top': cy - thumb_h // 2,
                    'thumb_w': thumb_w,
                    'thumb_h': thumb_h,
                    'svg_w': svg_w,
                    'svg_h': svg_h,
                }
                self._draw_text_hit_regions(svg_code, canvas)
            
        except ImportError:
            # Fallback if cairosvg not available - just show text
            canvas.delete("all")
            canvas.create_text(canvas.winfo_width() // 2, canvas.winfo_height() // 2,
                             text="Preview requires 'cairosvg' package\n\npip install cairosvg",
                             justify=tk.CENTER, fill="gray")
        except Exception as e:
            canvas.delete("all")
            canvas.create_text(canvas.winfo_width() // 2, canvas.winfo_height() // 2,
                             text=f"Preview error:\n{str(e)[:100]}",
                             justify=tk.CENTER, fill="red")
    
    def _update_preview_background(self, canvas, background):
        """Update preview background when user changes selection"""
        # Re-render if we have processed SVG
        if hasattr(canvas, 'image') and canvas.image:
            # Find the window that owns this canvas
            window = canvas.winfo_toplevel()
            if hasattr(window, 'processed_svg') and window.processed_svg:
                self._render_svg_preview(window.processed_svg, canvas, background)
    
    def _export_processed_svg(self, window):
        """Export processed SVG to file"""
        if not hasattr(window, 'processed_svg') or not window.processed_svg:
            messagebox.showwarning("No SVG", "Please process SVG first")
            return
        
        path = filedialog.asksaveasfilename(
            title="Save SVG",
            defaultextension=".svg",
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
        )
        
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(window.processed_svg)
                self._set_status(f"✓ Saved to {Path(path).name}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save:\n{e}")
    
    def _copy_processed_svg(self, window):
        """Copy processed SVG to clipboard"""
        if not hasattr(window, 'processed_svg') or not window.processed_svg:
            messagebox.showwarning("No SVG", "Please process SVG first")
            return
        
        try:
            self.clipboard_clear()
            self.clipboard_append(window.processed_svg)
            self._set_status("✓ SVG copied to clipboard")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy:\n{e}")

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
            self.pan_offset = [0, 0]  # Reset pan on page change
            self._update_page_label()
            self._render_current_page()

    def next_page(self):
        if not self.doc:
            return
        if self.page_index < self.doc.page_count - 1:
            self.page_index += 1
            self.pan_offset = [0, 0]  # Reset pan on page change
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
                self.pan_offset = [0, 0]  # Reset pan on page change
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
        # center horizontally and apply pan offset
        x_off = (c_w - self.photo.width()) // 2 + self.pan_offset[0]
        y_off = max((c_h - self.photo.height()) // 2, 0) + self.pan_offset[1]
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
    
    def _on_pan_scroll(self, event):
        """Handle mouse wheel pan (without Ctrl)"""
        if not self.doc:
            return
        
        # Determine scroll direction and amount
        if hasattr(event, 'delta'):
            # Windows/macOS - use delta value directly for smooth scrolling
            delta_y = event.delta // 2  # Scale down for reasonable speed
        elif event.num == 4:  # Linux scroll up
            delta_y = 60
        elif event.num == 5:  # Linux scroll down
            delta_y = -60
        else:
            return
        
        self.pan_offset[1] += delta_y
        self.auto_fit = False
        self._render_current_page()
    
    def _on_pan_start(self, event):
        """Start middle-button pan"""
        if not self.doc:
            return
        self.pan_start = (event.x, event.y)
        self.canvas.config(cursor="fleur")  # Change cursor to move/pan cursor
    
    def _on_pan_drag(self, event):
        """Handle middle-button drag pan"""
        if self.pan_start is None:
            return
        
        dx = event.x - self.pan_start[0]
        dy = event.y - self.pan_start[1]
        
        self.pan_offset[0] += dx
        self.pan_offset[1] += dy
        self.pan_start = (event.x, event.y)
        self.auto_fit = False
        self._render_current_page()
    
    def _on_pan_end(self, event):
        """End middle-button pan"""
        self.pan_start = None
        self.canvas.config(cursor="")  # Reset cursor
    
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
        if not sel:
            # If no active selection, return the full page rectangle
            if self.doc:
                return self.doc[self.page_index].rect
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
            page = self.doc.load_page(self.page_index)
            clip_rect = page.rect
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
        
        # Handle fonts if requested
        if self.preserve_text.get():
            font_mode = self.font_combo.get()
            if font_mode == 'Web-safe fonts':
                svg = self._replace_with_websafe_fonts(svg)
        
        # Remove background if requested
        if self.remove_background.get():
            svg = self._remove_svg_background(svg)
        
        # Convert to grayscale if requested
        if self.convert_grayscale.get():
            svg = self._convert_svg_grayscale(svg)
        
        out.close()
        return svg

    def open_kerning_options(self):
        """Open a dialog to configure manual kerning reconstruction settings."""
        popup = tk.Toplevel(self)
        popup.title("Kerning Options")
        popup.geometry("450x380")
        popup.resizable(False, False)
        popup.transient(self)  # Keep on top of main window
        popup.grab_set()       # Modal dialog
        
        # Main container with padding
        frame = ttk.Frame(popup, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)
        
        # Section 1: What is kerning? (Description)
        desc_title = ttk.Label(frame, text="What is Manual Kerning?", font=('', 10, 'bold'))
        desc_title.pack(anchor=tk.W, pady=(0, 2))
        
        desc_text = (
            "Kerning is the spacing adjustment between individual characters. "
            "PDF documents often hardcode the exact coordinates of every single letter, "
            "which strips out natural word spaces and merges letters. "
            "Enabling this feature attempts to dynamically reconstruct spaces between words."
        )
        desc_label = ttk.Label(frame, text=desc_text, wrap=410, justify=tk.LEFT)
        desc_label.pack(anchor=tk.W, pady=(0, 15))
        
        # Divider
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(0, 15))
        
        # Section 2: Controls
        check_kern = ttk.Checkbutton(
            frame, 
            text="Enable manual kerning removal", 
            variable=self.remove_kerning,
            command=self._on_kerning_toggle
        )
        check_kern.pack(anchor=tk.W, pady=(0, 10))
        
        # Frame for threshold slider and its description
        self.slider_frame = ttk.Frame(frame)
        self.slider_frame.pack(fill=tk.X, pady=(5, 10))
        
        slider_label_frame = ttk.Frame(self.slider_frame)
        slider_label_frame.pack(fill=tk.X)
        
        ttk.Label(slider_label_frame, text="Space Threshold Ratio:").pack(side=tk.LEFT)
        
        # Value display
        val_label = ttk.Label(slider_label_frame, text=f"{self.space_threshold_ratio.get():.2f}", font=('', 9, 'bold'))
        val_label.pack(side=tk.LEFT, padx=5)
        
        # Slider
        slider = ttk.Scale(
            self.slider_frame, 
            from_=0.10, 
            to=1.00, 
            variable=self.space_threshold_ratio,
            orient=tk.HORIZONTAL,
            command=lambda val: val_label.config(text=f"{float(val):.2f}")
        )
        slider.pack(fill=tk.X, pady=(2, 5))
        slider.bind("<ButtonRelease-1>", lambda e: self._on_slider_release())
        
        slider_desc = (
            "Sensitivity threshold for inserting spaces. Lower values make the "
            "algorithm more aggressive (adding spaces for smaller gaps). "
            "Higher values require larger physical gaps to insert a space."
        )
        slider_desc_label = ttk.Label(self.slider_frame, text=slider_desc, wrap=410, justify=tk.LEFT, foreground="gray")
        slider_desc_label.pack(anchor=tk.W)
        
        # Initial state update based on checkbox
        self._update_slider_state()
        
        # Divider
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(10, 15))
        
        # Close button
        btn_close = ttk.Button(frame, text="OK", width=10, command=popup.destroy)
        btn_close.pack(anchor=tk.E)

    def _on_kerning_toggle(self):
        """Handle checkbox toggle inside kerning options popup."""
        self._update_slider_state()
        if self.doc:
            self._render_current_page()

    def _update_slider_state(self):
        """Enable/disable slider widgets based on checkbox state."""
        if hasattr(self, 'slider_frame') and self.slider_frame.winfo_exists():
            state = '!disabled' if self.remove_kerning.get() else 'disabled'
            for child in self.slider_frame.winfo_children():
                try:
                    if isinstance(child, ttk.Frame):
                        for subchild in child.winfo_children():
                            subchild.state([state])
                    else:
                        child.state([state])
                except Exception:
                    pass

    def _on_slider_release(self):
        """Update preview when slider is released."""
        if self.doc:
            self._render_current_page()

    def _remove_svg_kerning(self, svg):
        """Remove individual character positioning from SVG text elements and restore spaces"""
        import re
        import html
        
        # Relative weights of characters compared to a standard lowercase letter (weight = 1.0)
        # Added weights for common math italic / LaTeX letters like 'e', 'a', 'o', 'c', 's' 
        # to ensure correct spacing reconstruction after narrow characters.
        CHAR_WEIGHTS = {
            'w': 1.4, 'm': 1.4, 'W': 1.6, 'M': 1.6,
            'i': 0.4, 'l': 0.4, 't': 0.5, 'f': 0.5, 'j': 0.4, 'r': 0.6,
            'I': 0.4, '1': 0.6, ' ': 0.5,
            'e': 0.8, 'a': 0.85, 'o': 0.85, 'c': 0.8, 's': 0.8,
            '.': 0.3, ',': 0.3, ';': 0.3, ':': 0.3, '!': 0.3, '|': 0.3,
            '-': 0.5, '_': 0.6,
            '(': 0.5, ')': 0.5, '[': 0.5, ']': 0.5, '{': 0.5, '}': 0.5,
        }
        
        def get_char_weight(c):
            if c in CHAR_WEIGHTS:
                return CHAR_WEIGHTS[c]
            if c.isupper():
                return 1.2
            return 1.0

        def get_token_char(token):
            if token.startswith('&') and token.endswith(';'):
                decoded = html.unescape(token)
                return decoded[0] if decoded else ' '
            return token

        def merge_coords(match):
            attributes = match.group(1)
            inner_text = match.group(2)
            tag_name = "tspan" if "tspan" in match.group(0)[:10] else "text"
            
            x_match = re.search(r'x="([^"]+)"', attributes)
            y_match = re.search(r'y="([^"]+)"', attributes)
            
            new_attributes = attributes
            new_text = inner_text
            
            if x_match:
                try:
                    x_vals = [float(x) for x in x_match.group(1).split()]
                except ValueError:
                    x_vals = []
                    
                if len(x_vals) > 1:
                    # Keep only the first x coordinate in attributes
                    new_attributes = re.sub(r'x="[^"]+"', f'x="{x_vals[0]}"', new_attributes)
                    
                    # Tokenize the inner text into individual characters/entities
                    tokens = re.findall(r'&[a-zA-Z0-9#]+;|.', inner_text, flags=re.DOTALL)
                    
                    if len(tokens) == len(x_vals):
                        # Calculate actual physical gaps
                        gaps = [x_vals[i] - x_vals[i-1] for i in range(1, len(x_vals))]
                        
                        if gaps:
                            # Calculate normalized gaps based on character weights
                            normalized_gaps = []
                            for i in range(len(gaps)):
                                char = get_token_char(tokens[i])
                                weight = get_char_weight(char)
                                # Avoid division by zero
                                normalized_gaps.append(gaps[i] / max(weight, 0.1))
                            
                            # Find the median of the normalized gaps (represents the font's standard step)
                            median_norm = sorted(normalized_gaps)[len(normalized_gaps) // 2]
                            
                            # Retrieve the dynamic threshold ratio defined in the UI
                            space_threshold_ratio = self.space_threshold_ratio.get()
                            
                            new_tokens = []
                            for i, token in enumerate(tokens):
                                new_tokens.append(token)
                                if i < len(gaps):
                                    char = get_token_char(token)
                                    weight = get_char_weight(char)
                                    expected_gap = weight * median_norm
                                    actual_gap = gaps[i]
                                    
                                    # Check if the gap is significantly larger than expected
                                    if (actual_gap - expected_gap) > (space_threshold_ratio * median_norm):
                                        # Prevent duplicate spaces if either adjacent token is already a space
                                        next_token = tokens[i+1] if i + 1 < len(tokens) else ''
                                        if char != ' ' and get_token_char(next_token) != ' ':
                                            new_tokens.append(' ')
                                            
                            new_text = "".join(new_tokens)
            
            if y_match:
                try:
                    y_vals = [float(y) for y in y_match.group(1).split()]
                except ValueError:
                    y_vals = []
                if len(y_vals) > 1:
                    new_attributes = re.sub(r'y="[^"]+"', f'y="{y_vals[0]}"', new_attributes)
                    
            return f'<{tag_name}{new_attributes}>{new_text}</{tag_name}>'

        # Match only leaf elements containing plain text (to prevent nested match collision)
        tspan_pattern = r'<tspan([^>]*(?:x|y)="[^"]*\s[^"]*"[^>]*)>([^<]*)</tspan>'
        text_pattern = r'<text([^>]*(?:x|y)="[^"]*\s[^"]*"[^>]*)>([^<]*)</text>'
        
        # Process tspan first, then text elements
        svg = re.sub(tspan_pattern, merge_coords, svg, flags=re.DOTALL)
        svg = re.sub(text_pattern, merge_coords, svg, flags=re.DOTALL)
        
        return svg

    def _replace_with_websafe_fonts(self, svg):
        """Replace fonts with web-safe alternatives, handling attributes and CSS declarations."""
        import re
        from urllib.parse import unquote
        
        # Mapping of common fonts/keywords to web-safe equivalents
        font_mapping = {
            # Sans-serif fonts
            'calibri': 'Arial, Helvetica, sans-serif',
            'segoe': 'Arial, Helvetica, sans-serif',
            'tahoma': 'Verdana, Geneva, sans-serif',
            'trebuchet': 'Trebuchet MS, sans-serif',
            'lucida': 'Lucida Grande, Lucida Sans, sans-serif',
            'helvetica': 'Helvetica, Arial, sans-serif',
            'roboto': 'Arial, Helvetica, sans-serif',
            'arial': 'Arial, Helvetica, sans-serif',
            'verdana': 'Verdana, Geneva, sans-serif',
            'geneva': 'Verdana, Geneva, sans-serif',
            'sans-serif': 'Arial, Helvetica, sans-serif',
            
            # Serif fonts
            'cambria': 'Georgia, serif',
            'times': 'Times New Roman, Times, Georgia, serif',
            'palatino': 'Palatino Linotype, Georgia, serif',
            'garamond': 'Georgia, serif',
            'bookman': 'Georgia, serif',
            'georgia': 'Georgia, serif',
            'roman': 'Times New Roman, Times, Georgia, serif',
            'serif': 'Times New Roman, Times, Georgia, serif',
            
            # Monospace fonts
            'consolas': 'Courier New, Courier, monospace',
            'monaco': 'Courier New, Courier, monospace',
            'menlo': 'Courier New, Courier, monospace',
            'courier': 'Courier New, Courier, monospace',
            'monospace': 'Courier New, Courier, monospace',
        }
        
        def get_websafe_replacement(font_family_str):
            """Find a web-safe font replacement for a given font-family string."""
            # Decode percent-encoded names (e.g., "%2BCalibri" -> "+Calibri") and split fallbacks
            parts = [unquote(p.strip("'\" ")).strip() for p in font_family_str.split(',')]
            
            for part in parts:
                # Strip subset prefixes often found in PDFs (e.g., "BCDEEE+Calibri" -> "Calibri")
                name = part.split('+')[-1].strip()
                name_lower = name.lower()
                
                # Handle TeX/LaTeX Computer Modern fonts (e.g., CMMI9, CMR10, CMSY9, etc.)
                if name_lower.startswith('cm'):
                    if 'cmss' in name_lower:
                        return 'Arial, Helvetica, sans-serif'
                    elif 'cmtt' in name_lower:
                        return 'Courier New, Courier, monospace'
                    else:
                        return 'Times New Roman, Times, Georgia, serif'
                
                # Handle generic PDF font IDs (e.g., F1, F2, F12)
                if name_lower.startswith('f') and name_lower[1:].isdigit():
                    if name_lower == 'f3':
                        return 'Times New Roman, Times, Georgia, serif'
                    elif name_lower == 'f4':
                        return 'Courier New, Courier, monospace'
                    else:
                        return 'Arial, Helvetica, sans-serif'
                
                # Match known font keywords
                for original_lower, websafe in font_mapping.items():
                    if original_lower in name_lower:
                        return websafe
                
                # Heuristic matching for custom fonts without exact mapping
                if 'sans' in name_lower or 'gothic' in name_lower or 'screen' in name_lower:
                    return 'Arial, Helvetica, sans-serif'
                if 'serif' in name_lower or 'mincho' in name_lower:
                    return 'Times New Roman, Times, Georgia, serif'
                if 'mono' in name_lower or 'code' in name_lower or 'console' in name_lower or 'fixed' in name_lower:
                    return 'Courier New, Courier, monospace'
                    
            return None

        def replace_attribute(match):
            """Callback for font-family="..." SVG attributes (handles both single and double quotes)."""
            quote = match.group(1)
            font_family = match.group(2)
            replacement = get_websafe_replacement(font_family)
            if replacement:
                return f'font-family={quote}{replacement}{quote}'
            return match.group(0)

        def replace_css_font(match):
            """Callback for font-family:... CSS rules (safely replaces value and preserves terminator)."""
            font_family_str = match.group(1).strip()
            terminator = match.group(2)
            replacement = get_websafe_replacement(font_family_str)
            if replacement:
                return f'font-family:{replacement}{terminator}'
            return match.group(0)

        # Replace HTML/SVG inline attributes: font-family="FontName" or font-family='FontName'
        svg = re.sub(r'font-family=(["\'])([^"\']+)\1', replace_attribute, svg)

        # Replace CSS rules inside <style> blocks or style attributes using the corrected pattern
        css_pattern = r"""font-family\s*:\s*((?:[^;\}'"]|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')+)(;?)"""
        svg = re.sub(css_pattern, replace_css_font, svg)
        
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

    # -------------------- Export preview / text editor --------------------
    def _parse_svg_num(self, value, default=0.0):
        if value is None:
            return default
        try:
            return float(str(value).split()[0].replace('px', '').replace('pt', ''))
        except (ValueError, IndexError):
            return default

    def _parse_svg_root(self, svg):
        cleaned = re.sub(r'<\?xml[^?]*\?>', '', svg)
        cleaned = re.sub(r'<!DOCTYPE[^>]*>', '', cleaned, flags=re.IGNORECASE)
        return ET.fromstring(cleaned.strip())

    def _svg_to_string(self, root):
        return ET.tostring(root, encoding='unicode')

    def _local_tag(self, elem):
        return elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

    def _get_svg_dimensions_from_string(self, svg, fallback_w, fallback_h):
        try:
            root = self._parse_svg_root(svg)
            view_box = root.get('viewBox')
            if view_box:
                parts = view_box.split()
                if len(parts) == 4:
                    return float(parts[2]), float(parts[3])
            w = self._parse_svg_num(root.get('width'), fallback_w)
            h = self._parse_svg_num(root.get('height'), fallback_h)
            if w > 0 and h > 0:
                return w, h
        except ET.ParseError:
            pass
        return fallback_w, fallback_h

    def _get_svg_text_metrics(self, elem, parent=None):
        x = self._parse_svg_num(elem.get('x'))
        y = self._parse_svg_num(elem.get('y'))
        font_size = self._parse_svg_num(elem.get('font-size'), 12.0)
        style = elem.get('style', '')
        if style:
            m = re.search(r'font-size:\s*([\d.]+)', style)
            if m:
                font_size = float(m.group(1))
        if parent is not None and self._local_tag(elem) == 'tspan':
            if x == 0:
                x = self._parse_svg_num(parent.get('x'))
            if y == 0:
                y = self._parse_svg_num(parent.get('y'))
            if font_size == 12.0:
                pfs = self._parse_svg_num(parent.get('font-size'), 12.0)
                pstyle = parent.get('style', '')
                if pstyle:
                    m = re.search(r'font-size:\s*([\d.]+)', pstyle)
                    if m:
                        pfs = float(m.group(1))
                if pfs != 12.0:
                    font_size = pfs
        return x, y, font_size

    def _collect_editable_text_items(self, root):
        items = []
        for elem in root.iter():
            tag = self._local_tag(elem)
            if tag not in ('text', 'tspan'):
                continue
            text = elem.text
            if not text or not text.strip():
                continue
            if tag == 'text' and any(
                self._local_tag(child) == 'tspan' and (child.text or '').strip()
                for child in elem
            ):
                continue
            parent = None
            if tag == 'tspan':
                for candidate in root.iter():
                    if elem in list(candidate):
                        parent = candidate
                        break
            x, y, font_size = self._get_svg_text_metrics(elem, parent)
            items.append({
                'text': text,
                'x': x,
                'y': y,
                'font_size': font_size,
            })
        return items

    def _update_svg_text_at_index(self, svg, index, new_text):
        root = self._parse_svg_root(svg)
        items = []
        target = None
        for elem in root.iter():
            tag = self._local_tag(elem)
            if tag not in ('text', 'tspan'):
                continue
            text = elem.text
            if not text or not text.strip():
                continue
            if tag == 'text' and any(
                self._local_tag(child) == 'tspan' and (child.text or '').strip()
                for child in elem
            ):
                continue
            if len(items) == index:
                target = elem
                break
            items.append(elem)
        if target is None:
            raise IndexError("Text element not found")
        target.text = new_text
        return self._svg_to_string(root)

    def _draw_text_hit_regions(self, svg, canvas):
        if not hasattr(canvas, 'preview_layout'):
            canvas.text_hits = []
            return
        layout = canvas.preview_layout
        try:
            root = self._parse_svg_root(svg)
            items = self._collect_editable_text_items(root)
        except ET.ParseError:
            canvas.text_hits = []
            return

        zoom = getattr(canvas, 'zoom', 1.0)
        scale_x = (layout['thumb_w'] / max(layout['svg_w'], 1)) * zoom
        scale_y = (layout['thumb_h'] / max(layout['svg_h'], 1)) * zoom
        hits = []

        for idx, item in enumerate(items):
            fs = item['font_size'] * scale_y
            text_w = max(len(item['text']) * fs * 0.55, fs)
            text_h = fs * 1.3
            x0 = layout['img_left'] + item['x'] * scale_x + getattr(canvas, 'pan_x', 0)
            y0 = layout['img_top'] + item['y'] * scale_y - fs * 0.85 + getattr(canvas, 'pan_y', 0)
            x1 = x0 + text_w
            y1 = y0 + text_h
            hits.append((x0, y0, x1, y1, idx))
            canvas.create_rectangle(
                x0, y0, x1, y1,
                outline='#3399ff', width=1, dash=(3, 3),
                tags=('text_hit', f'hit_{idx}'),
            )

        canvas.text_hits = hits

    def _on_preview_text_click(self, event, window, canvas):
        if not hasattr(canvas, 'text_hits'):
            return
        for x0, y0, x1, y1, idx in canvas.text_hits:
            if x0 <= event.x <= x1 and y0 <= event.y <= y1:
                try:
                    root = self._parse_svg_root(window.current_svg)
                    items = self._collect_editable_text_items(root)
                    current = items[idx]['text']
                except (ET.ParseError, IndexError):
                    return
                new_text = simpledialog.askstring(
                    "Edit Text",
                    "Edit text content:",
                    initialvalue=current,
                    parent=window,
                )
                if new_text is None or new_text == current:
                    return
                try:
                    window.current_svg = self._update_svg_text_at_index(window.current_svg, idx, new_text)
                    self._refresh_export_preview(window)
                    window.status_label.config(text=f"Updated text #{idx + 1}")
                except Exception as e:
                    messagebox.showerror("Edit Text", str(e), parent=window)
                return

    def _refresh_export_preview(self, window):
        canvas = window.preview_canvas
        self._render_svg_preview(window.current_svg, canvas, window.bg_var.get(), interactive=True)
        count = len(getattr(canvas, 'text_hits', []))
        window.status_label.config(text=f"{count} editable text area(s) — click to edit")
        
    def _preview_zoom(self, event):
        c = event.widget

        if getattr(event, 'num', None) == 4 or getattr(event, 'delta', 0) > 0:
            factor = 1.1
        else:
            factor = 0.9

        c.zoom = max(0.2, min(8.0, c.zoom * factor))
        self._refresh_export_preview(c.winfo_toplevel())

    def _preview_pan_start(self, event):
        event.widget.drag_start = (event.x, event.y)
        event.widget.config(cursor='fleur')

    def _preview_pan_drag(self, event):
        c = event.widget
        if not c.drag_start:
            return

        dx = event.x - c.drag_start[0]
        dy = event.y - c.drag_start[1]

        c.pan_x += dx
        c.pan_y += dy
        c.drag_start = (event.x, event.y)

        self._refresh_export_preview(c.winfo_toplevel())

    def _preview_pan_end(self, event):
        event.widget.drag_start = None
        event.widget.config(cursor='hand2')

    def open_export_preview(self, svg):
        window = tk.Toplevel(self)
        window.title("Preview & Edit")
        window.geometry("900x700")
        window.transient(self)
        window.current_svg = svg

        main_frame = ttk.Frame(window, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        controls = ttk.Frame(main_frame)
        controls.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(
            controls,
            text="Click highlighted text areas to edit before exporting.",
        ).pack(side=tk.LEFT)

        btn_export = ttk.Button(
            controls, text="💾 Export",
            command=lambda: self._export_from_preview(window),
            style='Icon.TButton',
        )
        btn_export.pack(side=tk.RIGHT, padx=4)

        btn_copy = ttk.Button(
            controls, text="📋 Copy",
            command=lambda: self._copy_from_preview(window),
            style='Icon.TButton',
        )
        btn_copy.pack(side=tk.RIGHT, padx=4)

        window.bg_var = tk.StringVar(value="White")
        bg_combo = ttk.Combobox(controls, textvariable=window.bg_var, width=12, state="readonly")
        bg_combo['values'] = ('White', 'Dark gray', 'Checkerboard')
        bg_combo.current(0)
        bg_combo.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(controls, text="Background:").pack(side=tk.RIGHT)

        window.preview_canvas = tk.Canvas(main_frame, bg="white", cursor="hand2")
        
        window.preview_canvas.zoom = 1.0
        window.preview_canvas.pan_x = 0
        window.preview_canvas.pan_y = 0
        window.preview_canvas.drag_start = None
        
        # Ctrl + wheel = zoom
        window.preview_canvas.bind('<Control-MouseWheel>', self._preview_zoom)
        window.preview_canvas.bind('<Control-Button-4>', self._preview_zoom)
        window.preview_canvas.bind('<Control-Button-5>', self._preview_zoom)

        # middle mouse drag = pan
        window.preview_canvas.bind('<Button-2>', self._preview_pan_start)
        window.preview_canvas.bind('<B2-Motion>', self._preview_pan_drag)
        window.preview_canvas.bind('<ButtonRelease-2>', self._preview_pan_end)
        
        window.preview_canvas.bind('<Configure>', lambda e: self._refresh_export_preview(window))
        
        window.preview_canvas.pack(fill=tk.BOTH, expand=True)
        window.preview_canvas.bind(
            '<Button-1>',
            lambda e: self._on_preview_text_click(e, window, window.preview_canvas),
        )
        bg_combo.bind('<<ComboboxSelected>>', lambda e: self._refresh_export_preview(window))

        window.status_label = ttk.Label(main_frame, text="", font=('', 9), foreground="#0066cc")
        window.status_label.pack(anchor=tk.W, pady=(6, 0))

        def initial_render():
            if not self.preserve_text.get():
                window.status_label.config(
                    text="Text is exported as paths — enable 'Preserve text' to edit text here.",
                    foreground="#cc6600",
                )
            self._refresh_export_preview(window)

        window.after(100, initial_render)

    def preview_selection_as_svg(self):
        if not self.doc:
            messagebox.showwarning("Preview", "Open a PDF first.")
            return
        sel = self._get_selection_rect_image_coords()
        if not sel:
            messagebox.showinfo("Preview Full Page", "No selection found. Previewing the entire page.")
        try:
            svg = self._svg_from_selection()
        except Exception as e:
            messagebox.showwarning("Preview", str(e))
            return
        self.open_export_preview(svg)

    def _export_from_preview(self, window):
        path = filedialog.asksaveasfilename(
            title="Save SVG",
            defaultextension=".svg",
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
            parent=window,
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(window.current_svg)
            self._set_status(f"✓ Saved: {Path(path).name}")
            window.status_label.config(text=f"Saved to {Path(path).name}")
        except Exception as e:
            messagebox.showerror("Export SVG", f"Failed to save SVG:\n{e}", parent=window)

    def _copy_from_preview(self, window):
        try:
            self.clipboard_clear()
            self.clipboard_append(window.current_svg)
            self.update()
            self._set_status("✓ SVG code copied to clipboard")
            window.status_label.config(text="SVG copied to clipboard")
        except Exception as e:
            messagebox.showerror("Copy SVG", f"Failed to copy SVG:\n{e}", parent=window)

    def export_selection_as_svg(self):
        # Check if there is a selection to inform the user
        sel = self._get_selection_rect_image_coords()
        if not sel:
            messagebox.showinfo("Exporting Full Page", "No selection found. Exporting the entire page.")
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
            self._set_status(f"✓ Saved: {Path(path).name}")
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
            self._set_status("✓ SVG code copied to clipboard")
        except Exception as e:
            messagebox.showerror("Copy SVG", f"Failed to copy SVG:\n{e}")

    def _create_tooltip(self, widget, text):
        """Create a tooltip for a widget"""
        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")
            label = ttk.Label(tooltip, text=text, background="#ffffe0", relief=tk.SOLID, borderwidth=1, padding=2)
            label.pack()
            widget.tooltip = tooltip
        
        def on_leave(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()
                del widget.tooltip
        
        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)


def main():
    app = PdfToSvgCropper()
    app.mainloop()


if __name__ == "__main__":
    main()
