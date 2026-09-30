"""Header extraction (invoice2data) + geometry line-item harvest (pdfplumber).

The harvest is layout-driven: a YAML spec names the column headers as they
appear in the PDF, and words are picked by x-distance to each header center.
See layouts/it.sample-vendor.yml, which is a synthetic example layout.
"""
import re

import pdfplumber
import yaml

NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*,\d{2,4}$")
INT = re.compile(r"^\d{1,3}$")


def to_f(s):
    return float(s.replace(".", "").replace(",", "."))


def load_layout(path):
    with open(path) as f:
        return yaml.safe_load(f)


def extract_header(pdf_path, template_dir):
    """Vendor header fields via invoice2data custom templates. None if no match."""
    import logging

    from invoice2data import extract_data
    from invoice2data.extract.loader import read_templates

    # extract_data cascades text backends; a failing backend logs partial-match
    # noise at WARNING and ERROR even when a later backend succeeds. Silence the
    # lib entirely -- a real no-match surfaces as our None return.
    logging.getLogger("invoice2data").setLevel(logging.CRITICAL)
    templates = read_templates(str(template_dir))
    result = extract_data(str(pdf_path), templates=templates)
    return result or None


def _header_center(words, seq, gap=15):
    """x-center of the last word of a consecutive header word sequence."""
    if isinstance(seq, str):
        seq = [seq]
    for w in words:
        if w["text"] != seq[-1]:
            continue
        ok, prev = True, w
        for want in reversed(seq[:-1]):
            cand = [v for v in words if v["text"] == want
                    and abs(v["top"] - prev["top"]) < 2
                    and 0 < prev["x0"] - v["x1"] < gap]
            if not cand:
                ok = False
                break
            prev = cand[0]
        if ok:
            return (w["x0"] + w["x1"]) / 2
    return None


def _rows(words, tol=3):
    """Cluster words into visual rows. round(top) grouping splits lines - don't."""
    out = []
    for w in sorted(words, key=lambda w: w["top"]):
        if out and abs(w["top"] - out[-1][0]) < tol:
            out[-1][1].append(w)
        else:
            out.append([w["top"], [w]])
    return [sorted(ws, key=lambda w: w["x0"]) for _, ws in out]


def _pick(ws, cx, pattern=NUM, tol=40, cast=to_f):
    if cx is None:
        return None
    hits = [w for w in ws if pattern.match(w["text"])]
    if not hits:
        return None
    best = min(hits, key=lambda w: abs((w["x0"] + w["x1"]) / 2 - cx))
    if abs((best["x0"] + best["x1"]) / 2 - cx) < tol:
        return cast(best["text"])
    return None


def harvest_items(pdf_path, layout):
    """All line-item rows across pages, per the layout spec."""
    code_re = re.compile(layout["code_regex"])
    cols = layout["columns"]
    items = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            words = page.extract_words()
            centers = {}
            for name, spec in cols.items():
                spec = {"header": spec} if isinstance(spec, (str, list)) else spec
                centers[name] = (spec, _header_center(words, spec["header"]))
            if all(c is None for _, c in centers.values()):
                continue
            for ws in _rows(words):
                if not code_re.match(ws[0]["text"]):
                    continue
                row = {"page": pno, "code": ws[0]["text"]}
                for name, (spec, cx) in centers.items():
                    if spec.get("type") == "int":
                        row[name] = _pick(ws, cx, INT, spec.get("tol", 20), int)
                    else:
                        row[name] = _pick(ws, cx, NUM, spec.get("tol", 40))
                desc_limit = next((c for _, c in centers.values() if c), 400)
                row["descrizione"] = " ".join(
                    w["text"] for w in ws[1:]
                    if w["x0"] < desc_limit - 60 and not NUM.match(w["text"]))
                items.append(row)
    return items
