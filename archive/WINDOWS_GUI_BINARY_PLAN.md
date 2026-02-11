# Windows GUI Binary Plan for yoto-up

## Current State

yoto-up is a ~25K-line Python 3.13 application with three interfaces:

- **CLI** (`yoto.py`) — Typer-based command-line tool
- **TUI** (`tui.py`) — Textual-based terminal UI for card editing
- **GUI** (`gui.py`) — Flet-based desktop GUI (the target for a Windows binary)

The project already has two GitHub Actions workflows that produce Windows artifacts:

| Workflow | Tool | Output |
|---|---|---|
| `build-cross.yml` | PyInstaller `--onefile --windowed` | `yoto-up.exe` (single file) |
| `build-cross-flet.yml` | `flet build windows` | Flet-packaged app directory |

### External services the binary must be able to reach ([docs](https://xkjq.github.io/yoto-up/external%20services/))

| Service | URL | Purpose |
|---|---|---|
| **Yoto API** | `api.yotoplay.com` | Card CRUD, media upload/transcode, icons |
| **Yoto OAuth** | `login.yotoplay.com` | Device-flow authentication (device code + token polling) |
| **YotoIcons** | `yotoicons.com` | Community icon scraping (optional) |
| **iTunes Search** | `itunes.apple.com/search` | Cover art lookup (no key needed) |
| **NLTK data** | NLTK servers | punkt / stopwords download (has local fallback) |

### Key dependencies that affect packaging

- **FFmpeg** — needed for audio normalization/transcoding (`ffmpeg-normalize`, `ffmpeg-binaries`)
- **numpy / matplotlib / librosa / pyloudnorm** — heavy native/scientific libs for audio analysis
- **Flet** — Flutter-based Python UI framework (ships its own Flutter runtime)
- **Pillow** — image processing for 16×16 pixel art icons
- **NLTK** — NLP for keyword extraction (optional, has fallback)

---

## Approach Options

Below are four viable approaches, ordered from least effort to most ambitious. They are not mutually exclusive — you could ship Option A quickly and evolve toward Option C or D.

---

### Option A: Improve the Existing PyInstaller Build (Recommended starting point)

**What it is:** The repo already has `build-cross.yml` using PyInstaller. This option focuses on hardening that pipeline to produce a polished, reliable single `.exe`.

**What to do:**

1. **Create a PyInstaller `.spec` file** instead of relying on bare CLI flags. This gives fine-grained control over:
   - Hidden imports (Flet, matplotlib backends, pydantic, etc.)
   - Data files to bundle (stamps, TUI CSS, NLTK data, Flet Flutter client)
   - FFmpeg binary inclusion via `ffmpeg-binaries`
   - Icon/splash for the `.exe`

2. **Bundle FFmpeg** — the `ffmpeg-binaries` package provides platform binaries. Add the FFmpeg executable path as a PyInstaller data file so it's extracted at runtime.

3. **Bundle NLTK data** — download `punkt_tab` and `stopwords` at build time and include them as data files. Set `NLTK_DATA` env var at startup to point to the extracted location.

4. **Add a Windows application manifest** — embed a manifest for DPI awareness, UAC level (asInvoker), and a proper application name.

5. **Add an `.ico` icon** for the executable.

6. **Code-sign the binary** (optional but reduces SmartScreen warnings) — use a self-signed or purchased code-signing certificate with `signtool`.

**Pros:**
- Minimal code changes; the existing GUI already works
- Single `yoto-up.exe` file — easiest distribution
- PyInstaller is mature and well-documented for Windows
- Fast iteration — just run `pyinstaller yoto-up.spec`

**Cons:**
- Startup can be slow (PyInstaller `--onefile` extracts to a temp dir)
- Antivirus false positives are common with PyInstaller executables
- Large binary size (~150-300 MB due to numpy/matplotlib/librosa)

**Estimated binary size:** 150–300 MB (single file) or 80–200 MB (one-dir mode, zipped)

---

### Option B: Use `flet build` (Flutter-native packaging)

**What it is:** Flet has its own `flet build windows` command that compiles the Python app into a Flutter-wrapped native Windows application. The repo already has `build-cross-flet.yml` for this.

**What to do:**

1. **Fix the existing `build-cross-flet.yml` workflow** — it currently produces a directory, not an installer. Add an NSIS or WiX step to create a proper `.msi` or setup `.exe`.

2. **Configure `flet build`** — use the `[tool.flet]` section in `pyproject.toml` (already partially configured: `app.module = "yoto_up.gui"`) to declare:
   - App name, version, description
   - Icon path
   - Additional Python packages to include
   - FFmpeg binary bundling

3. **Handle native dependencies** — `flet build` uses `serious_python` under the hood to bundle a Python runtime. Verify that numpy, matplotlib, librosa, and Pillow wheels are compatible. Some may need pre-built wheels or conditional imports.

4. **Bundle FFmpeg** — same as Option A, include the binary in the asset bundle.

**Pros:**
- Uses the framework's own packaging, so Flet-specific assets (Flutter client) are handled automatically
- Produces a native Windows app feel (Flutter rendering engine)
- Better than PyInstaller for Flet apps specifically

**Cons:**
- `flet build` is less mature than PyInstaller — can be finicky with complex dependency trees
- The macOS build is already commented out in the workflow (suggests issues)
- Heavy scientific deps (librosa, matplotlib) may cause build failures
- Less community documentation for troubleshooting

**Estimated binary size:** 100–250 MB

---

### Option C: Nuitka Compilation

**What it is:** [Nuitka](https://nuitka.net/) compiles Python to C and then to a native binary. This produces a genuine compiled executable rather than a bundled interpreter.

**What to do:**

1. **Install Nuitka** and a C compiler (MSVC or MinGW on Windows).

2. **Compile with:**
   ```
   nuitka --standalone --onefile --windows-console-mode=disable \
          --enable-plugin=numpy --enable-plugin=tk-inter \
          --include-data-dir=<stamps_dir>=yoto_up/stamps \
          --include-data-files=<ffmpeg_binary>=ffmpeg.exe \
          --windows-icon-from-ico=icon.ico \
          --company-name="yoto-up" --product-name="Yoto Up" \
          src/yoto_up/gui.py
   ```

3. **Handle Flet** — Nuitka has a Flet plugin or you may need to manually include the Flutter client files.

4. **Iterate on hidden imports** — Nuitka is generally better at auto-detecting imports than PyInstaller but may still need hints for dynamic imports (e.g., Flet's module loading).

**Pros:**
- Faster startup than PyInstaller (compiled, not interpreted)
- Smaller binaries (C compilation strips unused code)
- Fewer antivirus false positives
- Commercial license available for additional optimizations

**Cons:**
- Longer build times (C compilation)
- More complex to set up and debug
- Some packages with C extensions can be tricky
- Less widely used than PyInstaller (smaller community)

**Estimated binary size:** 80–200 MB

---

### Option D: Rewrite the GUI with a Different Framework

**What it is:** Replace the Flet GUI with a framework that has better native Windows packaging, while keeping the existing Python backend (`yoto_api.py`, `models.py`, audio utils, etc.) intact.

**Possible frameworks:**

| Framework | Language | Packaging | Notes |
|---|---|---|---|
| **Tauri + Python backend** | Rust + JS frontend, Python sidecar | `.msi` / `.exe` via Tauri bundler | Small binary (~10-30 MB + Python sidecar). Modern web UI. |
| **PySide6 / PyQt6** | Python | PyInstaller or `fbs` | Mature, well-tested packaging. Larger community. |
| **Dear PyGui** | Python | PyInstaller | Lightweight, GPU-accelerated. Good for custom UIs. |
| **Electron + Python** | JS + Python | electron-builder | Heavy but simple. Not recommended due to size. |

**The most practical rewrite target would be PySide6** because:
- It stays in Python (reuse all backend code as-is)
- Qt has excellent Windows packaging support
- PyInstaller + PySide6 is a well-trodden path
- Qt Designer provides visual layout tools

**However**, this is a significant effort (~3,250 lines of Flet GUI code to rewrite) and should only be considered if the Flet packaging options (A/B) prove unworkable.

---

## Recommendation

**Start with Option A (PyInstaller `.spec` hardening)** — it requires the least effort and the repo already has a working foundation. The concrete next steps would be:

1. Create a `yoto-up.spec` PyInstaller spec file with proper data bundling
2. Add an application icon (`.ico`)
3. Bundle FFmpeg and NLTK data
4. Add a Windows manifest for DPI awareness
5. Test on a clean Windows machine (no Python installed)
6. Set up the GitHub Actions workflow to produce both a single `.exe` and a `.zip` of the one-dir build
7. Optionally add an NSIS/Inno Setup installer script

If PyInstaller proves problematic (antivirus issues, startup speed), **Option C (Nuitka)** is the natural escalation path with the same codebase.

**Option B (`flet build`)** is worth exploring in parallel since it's already partially set up, but treat it as experimental given the maturity concerns.

**Option D (framework rewrite)** should only be considered as a last resort or a long-term goal.

---

## Dependency Size Reduction Tips (applicable to all options)

To reduce binary size regardless of which approach you choose:

1. **Make librosa optional** — it pulls in scipy, scikit-learn, etc. The GUI already has `[gui]` extras; consider a `[gui-lite]` without librosa.
2. **Replace matplotlib with a lighter plotting lib** — matplotlib adds ~30 MB. For simple waveform display, consider `plotille` (terminal) or render directly in Flet canvas.
3. **Lazy-import heavy modules** — defer `import numpy`, `import matplotlib`, etc. to the functions that actually use them. This doesn't reduce binary size but improves startup time.
4. **Strip NLTK** — only bundle the two corpora needed (punkt_tab, stopwords), not the full NLTK dataset.
5. **Use `--strip` and UPX** — PyInstaller and Nuitka both support stripping debug symbols and UPX compression.
