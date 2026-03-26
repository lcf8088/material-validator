"""
TIFF export functionality for archiving validated MTRs.

Converts PDFs to TIFF format with proper naming convention.
8-level posterized grayscale + deflate compression for readable small
text while keeping files compact (~900 KB for a typical 3-page MTR).
"""

import io
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

COMPRESSION_MAP = {
    'lzw': 'tiff_lzw',
    'jpeg': 'jpeg',
    'none': None,
    'deflate': 'tiff_deflate',
    'ccitt': 'group4',
}


def render_enhanced_pages(pdf_path: str, dpi: int = 300, posterize: bool = True) -> List[str]:
    """Render PDF pages as enhanced grayscale PNGs.

    When posterize=True: grayscale + posterize to 8 levels (for TIFF output).
    When posterize=False: full grayscale (for Claude vision — max detail).

    Args:
        pdf_path: Path to the input PDF.
        dpi: Resolution (default 300).
        posterize: Whether to posterize to 8 levels (default True).

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

    suffix = '_enhanced' if posterize else '_raw'
    output_dir = Path(tempfile.gettempdir()) / 'mtr_enhanced'
    output_dir.mkdir(exist_ok=True)

    scale = dpi / 72.0
    base_mat = fitz.Matrix(scale, scale)
    image_paths = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        # Apply page rotation so text renders horizontally
        mat = fitz.Matrix(scale, scale)
        if page.rotation:
            mat = mat.prerotate(page.rotation)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)
        img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
        if posterize:
            # Posterize to 8 gray levels — compact TIFF output
            img = img.point(lambda x: (x >> 5) << 5)

        out_path = output_dir / f"{pdf_path.stem}{suffix}_p{page_num + 1}.png"
        img.save(str(out_path))
        image_paths.append(str(out_path))
        logger.debug("Rendered page %d (%s): %dx%d", page_num + 1,
                      'posterized' if posterize else 'raw', pix.width, pix.height)

    doc.close()
    return image_paths


def enhanced_images_to_tiff(
    image_paths: List[str],
    output_path: str,
    dpi: int = 300,
) -> Tuple[bool, str]:
    """Assemble pre-rendered enhanced PNGs into a multi-page TIFF.

    Uses the same deflate compression as pdf_to_tiff. Since the images
    are already posterized grayscale, no further processing is needed.

    Args:
        image_paths: List of enhanced PNG paths from render_enhanced_pages().
        output_path: Output TIFF file path.
        dpi: DPI metadata to embed (default 300).

    Returns:
        (success, message)
    """
    try:
        from PIL import Image

        if not image_paths:
            return False, "No images to convert"

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        images = []
        for p in image_paths:
            img = Image.open(p)
            # Already grayscale posterized — just load
            images.append(img)

        images[0].save(
            output_path,
            format='TIFF',
            compression='tiff_deflate',
            dpi=(dpi, dpi),
            save_all=True,
            append_images=images[1:],
        )

        return True, f"Saved {len(images)} page(s) to {output_path}"

    except Exception as e:
        return False, f"TIFF assembly failed: {e}"


def parse_input_filename(filename: str) -> dict:
    """Parse MTR input filename to extract PO#, LN#, and identifier (Heat#/Batch#).

    Expected patterns:
        PO#.LN#.HEAT#.pdf   → metals/elastomers (3 segments)
        PO#.LN#.pdf          → assemblies (2 segments)

    Returns dict with keys: po_number, line_item, identifier (None if assembly).
    """
    stem = Path(filename).stem
    # Split on '.' separator
    parts = [p.strip() for p in stem.split('.') if p.strip()]

    if len(parts) >= 3:
        # Metal/elastomer: PO#.LN#.ID (extra dots become part of ID)
        return {
            'po_number': parts[0],
            'line_item': parts[1],
            'identifier': '.'.join(parts[2:]),
        }
    elif len(parts) == 2:
        # Assembly: PO#.LN#
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
    # Replace common problematic characters
    text = re.sub(r'[<>:"/\\|?*]', '_', text)
    # Remove leading/trailing whitespace and dots
    text = text.strip('. ')
    # Collapse multiple underscores
    text = re.sub(r'_+', '_', text)
    return text


def generate_archive_filename(
    po_number: str,
    line_item: str,
    identifier: Optional[str] = None,
    extension: str = '.tiff'
) -> str:
    """
    Generate archive filename: YYYY.MM.PO#.LN#.ID.tiff

    Metals use heat number as ID, elastomers use batch number.
    Assemblies omit the ID segment.
    Duplicate handling (_1, _2 suffix) is done by the caller.
    """
    from datetime import datetime
    now = datetime.now()
    date_prefix = f"{now.year}.{now.month:02d}"

    po_raw = sanitize_filename(po_number or 'UNKNOWN')
    # Strip non-digit characters (e.g. "PO001934" -> "001934") and zero-pad to 6 digits
    po_digits = re.sub(r'\D', '', po_raw)
    po = po_digits.zfill(6) if po_digits else po_raw
    ln_raw = sanitize_filename(line_item or '00')
    # Zero-pad numeric line items to 3 digits
    ln = ln_raw.zfill(3) if ln_raw.isdigit() else ln_raw

    parts = [date_prefix, po, ln]
    if identifier:
        parts.append(sanitize_filename(identifier))

    return '.'.join(parts) + extension


def generate_assembly_archive_filename(
    po_number: str,
    line_item: str,
    extension: str = '.tiff'
) -> str:
    """
    Generate archive filename for assembly packets: YYYY.MM.PO#.LN#.tiff
    No material-specific identifier is appended for assemblies.
    """
    return generate_archive_filename(po_number, line_item, identifier=None, extension=extension)


def pdf_to_tiff(
    pdf_path: str,
    output_path: str,
    dpi: int = 300,
    compression: str = 'lzw'
) -> Tuple[bool, str]:
    """
    Convert PDF to multi-page TIFF.

    Renders pages as grayscale, posterizes to 8 levels, and saves
    with deflate compression.

    Args:
        pdf_path: Input PDF file path
        output_path: Output TIFF file path
        dpi: Resolution (default 300)
        compression: TIFF compression (lzw, jpeg, none, ccitt)

    Returns:
        (success, message)
    """
    try:
        import fitz  # pymupdf
        from PIL import Image

        pdf_path = Path(pdf_path)
        output_path = Path(output_path)

        if not pdf_path.exists():
            return False, f"PDF not found: {pdf_path}"

        # Open PDF
        doc = fitz.open(pdf_path)

        if len(doc) == 0:
            return False, "PDF has no pages"

        # Render each page as grayscale, posterize to 8 levels
        images = []
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)

        for page_num in range(len(doc)):
            page = doc[page_num]
            # Apply page rotation so text renders horizontally
            page_mat = mat
            if page.rotation:
                page_mat = fitz.Matrix(scale, scale).prerotate(page.rotation)
            pix = page.get_pixmap(matrix=page_mat, colorspace=fitz.csGRAY)

            img = Image.frombytes("L", [pix.width, pix.height], pix.samples)
            # Posterize: quantize to 8 gray levels (preserves text anti-aliasing)
            img = img.point(lambda x: (x >> 5) << 5)
            images.append(img)
            logger.debug("Rendered page %d: %dx%d", page_num + 1, pix.width, pix.height)

        doc.close()

        # Deflate for posterized grayscale — best size/quality for documents
        tiff_compression = 'tiff_deflate'

        # Save as multi-page TIFF
        output_path.parent.mkdir(parents=True, exist_ok=True)

        images[0].save(
            output_path,
            format='TIFF',
            compression=tiff_compression,
            dpi=(dpi, dpi),
            save_all=True,
            append_images=images[1:],
        )

        return True, f"Saved {len(images)} page(s) to {output_path}"

    except ImportError as e:
        return False, f"Missing dependency: {e}. Install with: pip install pymupdf pillow"
    except Exception as e:
        return False, f"Conversion failed: {e}"


def image_to_tiff(
    image_path: str,
    output_path: str,
    dpi: int = 300,
    compression: str = 'lzw'
) -> Tuple[bool, str]:
    """
    Convert image (PNG, JPG) to TIFF.
    """
    try:
        from PIL import Image
        
        image_path = Path(image_path)
        output_path = Path(output_path)
        
        if not image_path.exists():
            return False, f"Image not found: {image_path}"
        
        img = Image.open(image_path)
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        tiff_compression = COMPRESSION_MAP.get(compression.lower(), 'tiff_lzw')
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        img.save(
            output_path,
            format='TIFF',
            compression=tiff_compression,
            dpi=(dpi, dpi)
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

    Args:
        src_path: Original PDF file path.
        dst_path: Destination path for the compressed PDF.
        render_dpi: DPI for the rasterized variant (default 150).
        jpeg_quality: JPEG quality for the rasterized variant (default 35).

    Returns:
        True on success, False on failure.
    """
    try:
        import fitz
        from PIL import Image

        src_path = str(src_path)
        dst_path = str(dst_path)

        # --- Strategy 1: optimize original ---
        doc = fitz.open(src_path)
        opt_tmp = dst_path + '.opt.tmp'
        doc.save(opt_tmp, garbage=4, deflate=True, clean=True)
        doc.close()
        opt_size = os.path.getsize(opt_tmp)

        # --- Strategy 2: render to grayscale JPEG ---
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

        # --- Pick the smaller one ---
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
        # Clean up temp files on error
        for tmp in [dst_path + '.opt.tmp', dst_path + '.rnd.tmp']:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False


def tiff_to_pdf(tiff_path: str, pdf_path: str, quality: int = 40) -> bool:
    """Convert a multi-page TIFF to a compact JPEG-compressed PDF.

    Uses PyMuPDF (fitz) to embed JPEG-compressed images into a PDF,
    producing files significantly smaller than the source TIFF.

    Args:
        tiff_path: Path to the input TIFF file.
        pdf_path: Path for the output PDF file.
        quality: JPEG quality (1-95, default 40 — readable text, compact file).

    Returns:
        True on success, False on failure.
    """
    try:
        import io
        import fitz  # pymupdf
        from PIL import Image

        tiff_path = Path(tiff_path)
        pdf_path = Path(pdf_path)

        if not tiff_path.exists():
            logger.error("TIFF not found for PDF conversion: %s", tiff_path)
            return False

        img = Image.open(tiff_path)
        pdf_doc = fitz.open()

        page_idx = 0
        try:
            while True:
                img.seek(page_idx)
                page_img = img.copy()

                # Encode as JPEG in memory
                buf = io.BytesIO()
                if page_img.mode == 'L':
                    # Grayscale — convert to RGB for JPEG
                    page_img = page_img.convert('RGB')
                elif page_img.mode not in ('RGB',):
                    page_img = page_img.convert('RGB')
                page_img.save(buf, format='JPEG', quality=quality)
                buf.seek(0)

                # Insert JPEG as a full-page image in the PDF
                w, h = page_img.size
                # Scale to points (72 dpi reference)
                dpi = img.info.get('dpi', (300, 300))
                dpi_x = dpi[0] if isinstance(dpi, (tuple, list)) else dpi
                dpi_y = dpi[1] if isinstance(dpi, (tuple, list)) else dpi
                pt_w = w * 72.0 / dpi_x
                pt_h = h * 72.0 / dpi_y

                pdf_page = pdf_doc.new_page(width=pt_w, height=pt_h)
                pdf_page.insert_image(
                    fitz.Rect(0, 0, pt_w, pt_h),
                    stream=buf.getvalue(),
                )

                page_idx += 1
        except EOFError:
            pass

        if page_idx == 0:
            logger.error("No pages found in TIFF: %s", tiff_path)
            pdf_doc.close()
            return False

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        pdf_doc.save(str(pdf_path), deflate=True, garbage=4)
        pdf_doc.close()

        logger.info("PDF created: %s (%d pages)", pdf_path, page_idx)
        return True

    except Exception as e:
        logger.error("TIFF-to-PDF conversion failed: %s", e)
        return False


def convert_to_archive(
    input_path: str,
    archive_folder: str,
    heat_number: str,
    po_number: Optional[str] = None,
    dpi: int = 300,
    compression: str = 'lzw'
) -> Tuple[bool, str, str]:
    """
    Convert input file to TIFF and save to archive folder with proper naming.
    
    Returns:
        (success, message, output_path)
    """
    input_path = Path(input_path)
    archive_folder = Path(archive_folder)
    
    # Generate filename (legacy: no line_item, use heat as identifier)
    filename = generate_archive_filename(po_number or 'UNKNOWN', '00', heat_number)
    output_path = archive_folder / filename
    
    # Check for existing file
    if output_path.exists():
        # Add suffix to avoid overwrite
        base = output_path.stem
        counter = 1
        while output_path.exists():
            output_path = archive_folder / f"{base}_{counter}.tiff"
            counter += 1
    
    # Convert based on input type
    suffix = input_path.suffix.lower()
    
    if suffix == '.pdf':
        success, message = pdf_to_tiff(str(input_path), str(output_path), dpi, compression)
    elif suffix in ('.png', '.jpg', '.jpeg', '.gif', '.bmp'):
        success, message = image_to_tiff(str(input_path), str(output_path), dpi, compression)
    elif suffix in ('.tif', '.tiff'):
        # Already TIFF, just copy with new name
        try:
            import shutil
            shutil.copy2(input_path, output_path)
            success, message = True, f"Copied to {output_path}"
        except Exception as e:
            success, message = False, f"Copy failed: {e}"
    else:
        return False, f"Unsupported file type: {suffix}", ""
    
    return success, message, str(output_path) if success else ""


if __name__ == '__main__':
    # Quick test
    print(generate_archive_filename("PO-12345", "01", "D2213660"))
    print(generate_archive_filename("PO-12345", "01"))
    print(parse_input_filename("000254.01.A1B2C3.pdf"))
    print(parse_input_filename("000254.03.pdf"))
