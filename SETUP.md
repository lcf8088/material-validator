# First-Time Setup

## 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `paddlepaddle-gpu` requires a CUDA-capable GPU. If you don't have one, replace it with `paddlepaddle` (CPU-only) in `requirements.txt`, or skip it entirely — OCR extraction will be unavailable but the rest of the app works fine.

## 2. Launch the App

```bash
python run_gui.py
```

## 3. Configure Settings

Click **Settings** in the sidebar.

### Pipeline tab
- **Anthropic API Key** — Required. Get one at [console.anthropic.com](https://console.anthropic.com). Click "Test Connection" to verify.
- **Watch Folder** — Optional. Directory to monitor for incoming MTR files.
- **Auto-process watched files** — When checked, files dropped in the watch folder are automatically run through the full pipeline.

### Archive tab
- **Archive Folder** — Where TIFF archives are stored.
- **Output Folder** — Overrides Archive Folder if set. Use this to separate working output from long-term archives.
- **Auto-archive TIFF after validation** — Automatically converts and saves a TIFF after each successful extraction. No manual "Archive" click needed.
- **Create PO# subfolders** — Organizes output as `[Output Folder]/[PO#]/[Heat-PO].tiff`.
- **TIFF DPI / Compression** — Archive quality settings (300 DPI + LZW is a good default).

### General tab
- **Specs Folder** — Point to a custom specs directory if you have specs outside the project.
- **Auto-detect Spec** — Let the matcher pick the right spec based on material grade and UNS.

Click **Save**.

## 4. Validate Your First MTR

1. Drag a PDF or image onto the drop zone (or click to browse).
2. Set the **Spec** dropdown (or leave on Auto-detect).
3. Enter a **PO#** if applicable (it stays filled between validations).
4. Click **Extract & Validate**.
5. Results appear in the two cards: extracted data on the left, validation on the right.

If auto-archive is on, the TIFF is saved automatically and the status bar shows the filename.

## 5. Batch Processing

1. Click the **Batch** button next to Archive.
2. Select a folder containing MTR PDFs/images.
3. A progress panel shows per-file results with pass/fail badges.
4. Cancel anytime. Click **Done** when finished.

## 6. Watch Folder (Hands-Free)

1. Set a watch folder in Settings and enable "Auto-process watched files".
2. Click **Watch: OFF** at the bottom of the sidebar to turn it on.
3. Drop PDFs into the watch folder — they process automatically.
4. The watcher waits for file copies to finish before processing.

## File Naming Convention

Output TIFFs are named: `[Heat#]-[PO#].tiff`

- Elastomers use Batch# instead of Heat#.
- Duplicate filenames get a `_1`, `_2` suffix.
- If "Create PO# subfolders" is on: `[Output]/[PO#]/[Heat-PO].tiff`.
