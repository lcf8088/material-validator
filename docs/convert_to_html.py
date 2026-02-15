"""Convert all markdown docs to print-friendly HTML."""
import markdown
from pathlib import Path

CSS = """
<style>
  @media print {
    body { margin: 0.5in; }
    h1 { page-break-before: avoid; }
    table, pre, blockquote { page-break-inside: avoid; }
  }
  body {
    font-family: "Segoe UI", Arial, Helvetica, sans-serif;
    font-size: 11pt;
    line-height: 1.5;
    color: #000;
    background: #fff;
    max-width: 8.5in;
    margin: 0 auto;
    padding: 0.5in;
  }
  h1 { font-size: 18pt; border-bottom: 2px solid #000; padding-bottom: 4pt; margin-top: 24pt; }
  h2 { font-size: 14pt; border-bottom: 1px solid #000; padding-bottom: 3pt; margin-top: 20pt; }
  h3 { font-size: 12pt; margin-top: 16pt; }
  h4 { font-size: 11pt; margin-top: 12pt; }
  table {
    border-collapse: collapse;
    width: 100%;
    margin: 12pt 0;
    font-size: 10pt;
  }
  th, td {
    border: 1px solid #000;
    padding: 4pt 6pt;
    text-align: left;
    vertical-align: top;
  }
  th {
    background: #e0e0e0;
    font-weight: bold;
  }
  tr:nth-child(even) td {
    background: #f5f5f5;
  }
  code {
    font-family: Consolas, "Courier New", monospace;
    font-size: 10pt;
    background: #f0f0f0;
    padding: 1pt 3pt;
    border: 1px solid #ccc;
  }
  pre {
    background: #f0f0f0;
    border: 1px solid #ccc;
    padding: 8pt;
    overflow-x: auto;
    font-size: 9pt;
    line-height: 1.4;
  }
  pre code {
    background: none;
    border: none;
    padding: 0;
  }
  blockquote {
    border-left: 3px solid #000;
    margin: 12pt 0;
    padding: 4pt 12pt;
    color: #333;
    background: #f9f9f9;
  }
  hr {
    border: none;
    border-top: 1px solid #000;
    margin: 20pt 0;
  }
  strong { font-weight: bold; }
  ul, ol { margin: 6pt 0; padding-left: 24pt; }
  li { margin: 3pt 0; }
  a { color: #000; text-decoration: underline; }
</style>
"""

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
{css}
</head>
<body>
{body}
</body>
</html>
"""

def convert_file(md_path: Path):
    text = md_path.read_text(encoding="utf-8")
    # Extract title from first heading
    title = md_path.stem
    for line in text.splitlines():
        if line.startswith("# "):
            title = line.lstrip("# ").strip()
            break

    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "codehilite", "toc"],
        extension_configs={"codehilite": {"use_pygments": False}},
    )
    html = TEMPLATE.format(title=title, css=CSS, body=body)
    out = md_path.with_suffix(".html")
    out.write_text(html, encoding="utf-8")
    print(f"  {md_path.name} -> {out.name}")

def main():
    docs = Path(__file__).parent
    md_files = sorted(docs.glob("*.md"))
    if not md_files:
        print("No .md files found.")
        return
    print(f"Converting {len(md_files)} files:")
    for f in md_files:
        convert_file(f)
    print("Done.")

if __name__ == "__main__":
    main()
