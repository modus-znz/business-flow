"""Document conversion: anything -> Markdown (markitdown), scan -> text (ocrmypdf)."""
import subprocess


def to_markdown(src, out=None):
    """LLM-readable Markdown. Content survives; table STRUCTURE flattens -
    use extract.harvest_items for structured line items."""
    from markitdown import MarkItDown

    md = MarkItDown().convert(str(src)).text_content
    if out:
        with open(out, "w") as f:
            f.write(md)
    return md


def ocr(src, dst, lang="ita+eng", skip_text=True):
    """OCR to searchable PDF/A. skip_text handles mixed/already-texted PDFs."""
    cmd = ["ocrmypdf", "-l", lang]
    if skip_text:
        cmd.append("--skip-text")
    cmd += [str(src), str(dst)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return dst
