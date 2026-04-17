"""
Image export for archiving validated MTRs.

Each page is written as a separate grayscale JPG with a ``_page_NN`` suffix.
"""

import io
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

PAGE_SUFFIX_FMT = "_page_{:02d}"


def _page_path(output_dir: Path, base_name: str, page_num: int) -> Path:
    return output_dir / f"{base_name}{PAGE_SUFFIX_FMT.format(page_num)}.jpg"


def render_enhanced_pages(pdf_path: str, dpi: int = 300) -> List[str]:
    """Render PDF pages as grayscale PNGs in a temp directory.

    Used by the pipeline as an intermediate format for Claude vision and
    JPG archival export.

    Args:
        pdf_path: Path to the input PDF.
        dpi: Render resolution (default 300).

    Returns:
        List of PNG file paths (one per page).
    """
    import fitz  # pymupdf
    from PIL import Image

    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    if len(doc) == 0:
        doc.close()
        return []

    output_dir = Path(tempfile.gettempdir()) / 'mtr_enhanced'
    output_dir.mkdir(exist_ok=True)

    scale = dpi / 72.0
    image_paths = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        mat = fitz.Matrix(scale, scale)
        if page.rotation:
            mat = mat.prerotate(page.rotation)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
        out_path = output_dir / f"{pdf_path.stem}_raw_p{page_num + 1}.png"
        img.save(str(out_path))
        image_paths.append(str(out_path))
        logger.debug("Rendered page %d: %dx%d", page_num + 1, pix.width, pix.height)

    doc.close()
    return image_paths


def enhanced_images_to_jpgs(
    image_paths: List[str],
    output_dir: str,
    base_name: str,
    dpi: int = 300,
    quality: int = 75,
) -> Tuple[bool, str, List[str]]:
    """Save pre-rendered page images as per-page grayscale JPGs for archival.

    Outputs ``{base_name}_page_01.jpg``, ``{base_name}_page_02.jpg``, ...

    Pages are forced to 8-bit grayscale (``L`` mode) and saved with
    progressive + optimized JPEG encoding — smallest file size that still
    preserves text legibility at print resolution.

    Args:
        image_paths: Ordered list of page images (e.g. from render_enhanced_pages).
        output_dir: Destination directory (created if missing).
        base_name: Filename prefix (no extension, no page suffix).
        dpi: DPI metadata to embed (default 300).
        quality: JPEG quality 1-95 (default 75 — archival-friendly for text).

    Returns:
        (success, message, list_of_written_paths)
    """
    try:
        from PIL import Image

        if not image_paths:
            return False, "No images to convert", []

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        written: List[str] = []
        for idx, p in enumerate(image_paths, start=1):
            img = Image.open(p)
            if img.mode != 'L':
                img = img.convert('L')
            page_path = _page_path(out_dir, base_name, idx)
            img.save(
                str(page_path), format='JPEG', quality=quality,
                dpi=(dpi, dpi), optimize=True, progressive=True,
            )
            written.append(str(page_path))

        return True, f"Saved {len(written)} page(s) to {out_dir}", written

    except Exception as e:
        return False, f"JPG assembly failed: {e}", []


def parse_input_filename(filename: str) -> dict:
    """Parse MTR input filename to extract PO#, LN#, and identifier (Heat#/Batch#).

    Expected patterns:
        PO#.LN#.HEAT#.pdf   → metals/elastomers (3 segments)
        PO#.LN#.pdf          → assemblies (2 segments)

    Returns dict with keys: po_number, line_item, identifier (None if assembly).
    """
    stem = Path(filename).stem
    parts = [p.strip() for p in stem.split('.') if p.strip()]

    if len(parts) >= 3:
        return {
            'po_number': parts[0],
            'line_item': parts[1],
            'identifier': '.'.join(parts[2:]),
        }
    elif len(parts) == 2:
        return {
            'po_number': parts[0],
            'line_item': parts[1],
            'identifier': None,
        }
    elif len(parts) == 1:
        return {
            'po_number': parts[0],
            'line_item': None,
            'identifier': None,
        }
    else:
        return {
            'po_number': None,
            'line_item': None,
            'identifier': None,
        }


def sanitize_filename(text: str) -> str:
    """Remove/replace characters that are invalid in filenames."""
    text = re.sub(r'[<>:"/\\|?*]', '_', text)
    text = text.strip('. ')
    text = re.sub(r'_+', '_', text)
    return text


def generate_archive_filename(
    po_number: str,
    line_item: str,
    identifier: Optional[str] = None,
    extension: str = '.jpg',
) -> str:
    """
    Generate archive filename: YYYY.MM.PO#.LN#.ID.jpg

    Metals use heat number as ID, elastomers use batch number.
    Assemblies omit the ID segment.

    For multi-page outputs, callers should strip the extension and append
    ``_page_NN`` suffixes per page — use ``build_page_paths``.
    """
    from datetime import datetime
    now = datetime.now()
    date_prefix = f"{now.year}.{now.month:02d}"

    po_raw = sanitize_filename(po_number or 'UNKNOWN')
    po_digits = re.sub(r'\D', '', po_raw)
    po = po_digits.zfill(6) if po_digits else po_raw
    ln_raw = sanitize_filename(line_item or '00')
    ln = ln_raw.zfill(3) if ln_raw.isdigit() else ln_raw

    parts = [date_prefix, po, ln]
    if identifier:
        parts.append(sanitize_filename(identifier))

    return '.'.join(parts) + extension


def generate_assembly_archive_filename(
    po_number: str,
    line_item: str,
    extension: str = '.jpg',
) -> str:
    """Archive filename for assembly packets: YYYY.MM.PO#.LN#.jpg (no ID)."""
    return generate_archive_filename(po_number, line_item, identifier=None, extension=extension)


def build_page_paths(
    output_dir: str,
    base_name: str,
    page_count: int,
    extension: str = '.jpg',
) -> List[Path]:
    """Build a list of per-page archive paths: base_page_01.jpg, base_page_02.jpg, ..."""
    out = Path(output_dir)
    return [out / f"{base_name}{PAGE_SUFFIX_FMT.format(i)}{extension}"
            for i in range(1, page_count + 1)]


def pdf_to_jpgs(
    pdf_path: str,
    output_dir: str,
    base_name: str,
    dpi: int = 300,
    quality: int = 75,
) -> Tuple[bool, str, List[str]]:
    """Render each PDF page directly to a grayscale JPG with _page_NN suffix.

    Output uses 8-bit grayscale with progressive + optimized JPEG — compact
    for archival while staying legible when printed.

    Args:
        pdf_path: Input PDF file path.
        output_dir: Destination directory for per-page JPGs.
        base_name: Filename prefix (no extension, no page suffix).
        dpi: Render resolution (default 300).
        quality: JPEG quality 1-95 (default 75 — archival-friendly for text).

    Returns:
        (success, message, list_of_written_paths)
    """
    try:
        import fitz  # pymupdf
        from PIL import Image

        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            return False, f"PDF not found: {pdf_path}", []

        doc = fitz.open(pdf_path)
        if len(doc) == 0:
            doc.close()
            return False, "PDF has no pages", []

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        scale = dpi / 72.0
        written: List[str] = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            page_mat = fitz.Matrix(scale, scale)
            if page.rotation:
                page_mat = page_mat.prerotate(page.rotation)
            pix = page.get_pixmap(matrix=page_mat, colorspace=fitz.csGRAY)
            img = Image.frombytes("L", [pix.width, pix.height], pix.samples)

            page_path = _page_path(out_dir, base_name, page_num + 1)
            img.save(
                str(page_path), format='JPEG', quality=quality,
                dpi=(dpi, dpi), optimize=True, progressive=True,
            )
            written.append(str(page_path))
            logger.debug("Rendered page %d: %dx%d", page_num + 1, pix.width, pix.height)

        doc.close()
        return True, f"Saved {len(written)} page(s) to {out_dir}", written

    except ImportError as e:
        return False, f"Missing dependency: {e}. Install with: pip install pymupdf pillow", []
    except Exception as e:
        return False, f"Conversion failed: {e}", []


def image_to_jpg(
    image_path: str,
    output_path: str,
    dpi: int = 300,
    quality: int = 75,
) -> Tuple[bool, str]:
    """Convert a single image (PNG, JPG, TIFF, ...) to a grayscale archival JPG."""
    try:
        from PIL import Image

        image_path = Path(image_path)
        output_path = Path(output_path)

        if not image_path.exists():
            return False, f"Image not found: {image_path}"

        img = Image.open(image_path)
        if img.mode != 'L':
            img = img.convert('L')

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(
            str(output_path), format='JPEG', quality=quality,
            dpi=(dpi, dpi), optimize=True, progressive=True,
        )
        return True, f"Saved to {output_path}"

    except ImportError:
        return False, "Missing dependency: pillow. Install with: pip install pillow"
    except Exception as e:
        return False, f"Conversion failed: {e}"


def compress_pdf(src_path: str, dst_path: str, render_dpi: int = 150,
                  jpeg_quality: int = 35) -> bool:
    """Compress a PDF for archival storage.

    Tries two strategies and keeps the smaller result:
      1. Optimize the original (garbage-collect unused objects + deflate).
      2. Re-render every page as a grayscale JPEG at *render_dpi*.
    """
    try:
        import fitz
        from PIL import Image

        src_path = str(src_path)
        dst_path = str(dst_path)

        doc = fitz.open(src_path)
        opt_tmp = dst_path + '.opt.tmp'
        doc.save(opt_tmp, garbage=4, deflate=True, clean=True)
        doc.close()
        opt_size = os.path.getsize(opt_tmp)

        doc = fitz.open(src_path)
        rendered = fitz.open()
        scale = render_dpi / 72.0
        mat = fitz.Matrix(scale, scale)

        for page in doc:
            page_mat = mat
            if page.rotation:
                page_mat = fitz.Matrix(scale, scale).prerotate(page.rotation)
            pix = page.get_pixmap(matrix=page_mat, colorspace=fitz.csGRAY)
            img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
            img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=jpeg_quality)
            new_page = rendered.new_page(
                width=page.rect.width, height=page.rect.height
            )
            new_page.insert_image(
                fitz.Rect(0, 0, page.rect.width, page.rect.height),
                stream=buf.getvalue(),
            )
        doc.close()

        rnd_tmp = dst_path + '.rnd.tmp'
        rendered.save(rnd_tmp, deflate=True, garbage=4)
        rendered.close()
        rnd_size = os.path.getsize(rnd_tmp)

        if opt_size <= rnd_size:
            os.replace(opt_tmp, dst_path)
            os.remove(rnd_tmp)
            logger.info("Archive PDF (optimized original): %s (%d KB)",
                        dst_path, opt_size // 1024)
        else:
            os.replace(rnd_tmp, dst_path)
            os.remove(opt_tmp)
            logger.info("Archive PDF (rendered %d DPI): %s (%d KB)",
                        render_dpi, dst_path, rnd_size // 1024)
        return True

    except Exception as e:
        logger.error("compress_pdf failed: %s", e)
        for tmp in [dst_path + '.opt.tmp', dst_path + '.rnd.tmp']:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def jpgs_to_pdf(jpg_paths: List[str], pdf_path: str) -> bool:
    """Combine per-page JPGs into a single compact PDF.

    The JPGs are embedded directly (no re-encoding), so the resulting PDF
    matches the JPGs' visual quality while being a single file.
    """
    try:
        import fitz  # pymupdf
        from PIL import Image

        if not jpg_paths:
            return False

        pdf_path = Path(pdf_path)
        pdf_doc = fitz.open()

        for p in jpg_paths:
            img = Image.open(p)
            w, h = img.size
            dpi = img.info.get('dpi', (300, 300))
            dpi_x = dpi[0] if isinstance(dpi, (tuple, list)) else dpi
            dpi_y = dpi[1] if isinstance(dpi, (tuple, list)) else dpi
            pt_w = w * 72.0 / dpi_x
            pt_h = h * 72.0 / dpi_y

            with open(p, 'rb') as fh:
                jpg_bytes = fh.read()

            pdf_page = pdf_doc.new_page(width=pt_w, height=pt_h)
            pdf_page.insert_image(
                fitz.Rect(0, 0, pt_w, pt_h),
                stream=jpg_bytes,
            )

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_doc.save(str(pdf_path), deflate=True, garbage=4)
        pdf_doc.close()

        logger.info("PDF created: %s (%d pages)", pdf_path, len(jpg_paths))
        return True

    except Exception as e:
        logger.error("JPGs-to-PDF conversion failed: %s", e)
        return False


def convert_to_archive(
    input_path: str,
    archive_folder: str,
    heat_number: str,
    po_number: Optional[str] = None,
    dpi: int = 300,
    quality: int = 75,
) -> Tuple[bool, str, List[str]]:
    """
    Convert input file to per-page JPG archive files.

    Legacy single-identifier variant used by CLI: produces
    ``YYYY.MM.PO.000.HEAT_page_01.jpg`` etc.

    Returns:
        (success, message, list_of_output_paths)
    """
    input_path = Path(input_path)
    archive_folder = Path(archive_folder)

    base_filename = generate_archive_filename(po_number or 'UNKNOWN', '00', heat_number)
    base_name = Path(base_filename).stem

    suffix = input_path.suffix.lower()

    if suffix == '.pdf':
        return pdf_to_jpgs(str(input_path), str(archive_folder), base_name,
                            dpi=dpi, quality=quality)

    if suffix in ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tif', '.tiff'):
        out_path = archive_folder / f"{base_name}_page_01.jpg"
        success, message = image_to_jpg(str(input_path), str(out_path),
                                          dpi=dpi, quality=quality)
        return success, message, [str(out_path)] if success else []

    return False, f"Unsupported file type: {suffix}", []


if __name__ == '__main__':
    print(generate_archive_filename("PO-12345", "01", "D2213660"))
    print(generate_archive_filename("PO-12345", "01"))
    print(parse_input_filename("000254.01.A1B2C3.pdf"))
    print(parse_input_filename("000254.03.pdf"))
