"""
TIFF export functionality for archiving validated MTRs.

Converts PDFs to TIFF format with proper naming convention.
8-level posterized grayscale + deflate compression for readable small
text while keeping files compact (~900 KB for a typical 3-page MTR).
"""

import logging
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
    mat = fitz.Matrix(scale, scale)
    image_paths = []

    for page_num in range(len(doc)):
        page = doc[page_num]
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
    heat_number: str,
    po_number: Optional[str] = None,
    extension: str = '.tiff'
) -> str:
    """
    Generate archive filename per convention: HEAT_NUMBER-PO_NUMBER.tiff
    
    If no PO number, just uses heat number.
    """
    heat = sanitize_filename(heat_number or 'UNKNOWN')
    
    if po_number:
        po = sanitize_filename(po_number)
        return f"{heat}-{po}{extension}"
    else:
        return f"{heat}{extension}"


def generate_assembly_archive_filename(
    po_number: str,
    customer_part_number: str,
    extension: str = '.tiff'
) -> str:
    """
    Generate archive filename for assembly packets: PO_CustomerPartNumber.tiff
    """
    po = sanitize_filename(po_number or 'UNKNOWN-PO')
    part = sanitize_filename(customer_part_number or 'UNKNOWN-PART')
    return f"{po}_{part}{extension}"


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
            pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY)

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
    
    # Generate filename
    filename = generate_archive_filename(heat_number, po_number, '.tiff')
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
    print(generate_archive_filename("D2213660", "PO-12345"))
    print(generate_archive_filename("Y75T", None))
    print(generate_archive_filename("ABC/123", "PO:456"))
