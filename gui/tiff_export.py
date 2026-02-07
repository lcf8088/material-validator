"""
TIFF export functionality for archiving validated MTRs.

Converts PDFs to TIFF format with proper naming convention.
"""

import re
from pathlib import Path
from typing import Optional, Tuple


COMPRESSION_MAP = {
    'lzw': 'tiff_lzw',
    'jpeg': 'jpeg',
    'none': None,
    'deflate': 'tiff_deflate',
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


def pdf_to_tiff(
    pdf_path: str,
    output_path: str,
    dpi: int = 300,
    compression: str = 'lzw'
) -> Tuple[bool, str]:
    """
    Convert PDF to multi-page TIFF.
    
    Args:
        pdf_path: Input PDF file path
        output_path: Output TIFF file path
        dpi: Resolution (default 300)
        compression: TIFF compression (lzw, jpeg, none)
    
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
        
        # Convert each page to PIL Image
        images = []
        scale = dpi / 72.0  # PDF default is 72 DPI
        mat = fitz.Matrix(scale, scale)
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            pix = page.get_pixmap(matrix=mat)
            
            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            images.append(img)
        
        doc.close()
        
        # Determine compression
        tiff_compression = COMPRESSION_MAP.get(compression.lower(), 'tiff_lzw')
        
        # Save as multi-page TIFF
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        if len(images) == 1:
            images[0].save(
                output_path,
                format='TIFF',
                compression=tiff_compression,
                dpi=(dpi, dpi)
            )
        else:
            # Multi-page TIFF
            images[0].save(
                output_path,
                format='TIFF',
                compression=tiff_compression,
                dpi=(dpi, dpi),
                save_all=True,
                append_images=images[1:]
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
