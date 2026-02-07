#!/usr/bin/env python3
"""
Launcher script for Material Cert Validator GUI.

Run this to start the desktop application.
"""

import sys
from pathlib import Path

# Ensure we can import from the package
sys.path.insert(0, str(Path(__file__).parent))

def check_dependencies():
    """Check if required dependencies are installed."""
    import importlib

    # (import_name, pip_name)
    deps = [
        ('customtkinter', 'customtkinter'),
        ('tkinterdnd2', 'tkinterdnd2'),
        ('httpx', 'httpx'),
        ('yaml', 'pyyaml'),
        ('fitz', 'pymupdf'),
        ('PIL', 'pillow'),
    ]

    missing = []
    for import_name, pip_name in deps:
        try:
            importlib.import_module(import_name)
        except ImportError:
            missing.append(pip_name)
    
    if missing:
        print("Missing dependencies:")
        for dep in missing:
            print(f"  - {dep}")
        print("\nInstall with:")
        print(f"  pip install {' '.join(missing)}")
        print("\nOr install all requirements:")
        print("  pip install -r requirements.txt")
        return False
    
    return True


def main():
    if not check_dependencies():
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    from gui.app import main as run_app
    run_app()


if __name__ == '__main__':
    main()
