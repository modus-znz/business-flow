#!/usr/bin/env python3
"""bizflow toolkit installer — workstation or server, idempotent, stdlib-only.

Phases:
  apt    system CLI layer (needs root; prints the command and continues if not)
  venv   ~/.local/share/bizvenv (--system-site-packages) + bizflow -e install
  bin    duckdb CLI static binary -> ~/.local/bin (optional, --no-bin to skip)
  data   invoice2data vendor templates -> ~/.local/share/invoice2data-templates
  smoke  verify EVERYTHING actually imports and runs (markers lie; tests don't)

Rules baked in, each from a failure that cost a deploy:
  * a --system-site-packages venv silently no-ops pip installs when a system
    copy exists, and system packages can break INSIDE the venv when the venv
    holds a newer dependency -> every failed import is retried with
    --upgrade --ignore-installed
  * never trust an install marker; smoke-test imports from inside the venv

Usage: python3 install.py [--check] [--no-apt] [--no-bin] [--smoke-only]
                          [--wheelhouse DIR]

--wheelhouse DIR: install python deps offline from a directory of wheels
(pip gets --no-index --find-links DIR). For servers with crawling PyPI
egress: build it on a fast machine with
  pip download -r requirements.txt -d wheelhouse/ && \
  pip download setuptools wheel -d wheelhouse/
then rsync the directory over and pass it here.
"""
import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

HOME = Path.home()
VENV = HOME / ".local/share/bizvenv"
VPIP = VENV / "bin/pip"
VPY = VENV / "bin/python"
BIN = HOME / ".local/bin"
TPL_DST = HOME / ".local/share/invoice2data-templates"
REPO = Path(__file__).resolve().parent

APT_PKGS = [
    # pipeline core
    "pandoc", "qpdf", "ocrmypdf", "tesseract-ocr-eng", "tesseract-ocr-ita",
    "tesseract-ocr-swa", "poppler-utils", "python3-venv", "python3-pip",
    # analysis companions (tested toolkit)
    "hledger", "miller", "entr", "fzf",
]
VENV_IMPORTS = ["pdfplumber", "invoice2data", "duckdb", "markitdown",
                "stockpyl", "ortools", "yaml"]
CLI_TOOLS = ["pandoc", "qpdf", "ocrmypdf", "pdftotext", "tesseract",
             "hledger", "mlr", "entr", "fzf"]
DUCKDB_URL = ("https://github.com/duckdb/duckdb/releases/latest/download/"
              "duckdb_cli-linux-amd64.zip")


def run(cmd, **kw):
    print(f"  $ {' '.join(map(str, cmd))}")
    return subprocess.run([str(c) for c in cmd], **kw)


def phase_apt(check):
    missing = [p for p in APT_PKGS if run(
        ["dpkg", "-s", p], capture_output=True).returncode != 0]
    if not missing:
        print("apt: all present")
        return True
    cmd = ["apt-get", "install", "-y"] + missing
    if check:
        print(f"apt: WOULD install {missing}")
        return True
    if os.geteuid() == 0:
        return run(cmd, env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
                   ).returncode == 0
    if run(["sudo", "-n", "true"], capture_output=True).returncode == 0:
        return run(["sudo", "-n"] + cmd).returncode == 0
    print(f"apt: NO ROOT - run manually:\n  sudo apt-get install -y {' '.join(missing)}")
    return False


def phase_venv(check, wheelhouse=None):
    if check:
        print(f"venv: {'exists' if VPY.exists() else 'WOULD create'} {VENV}")
        return True
    if not VPY.exists():
        run([sys.executable, "-m", "venv", "--system-site-packages", VENV])
    offline = ["--no-index", "--find-links", str(wheelhouse)] if wheelhouse else []
    if not offline:
        run([VPIP, "install", "-q", "--upgrade", "pip"], capture_output=True)
    r = run([VPIP, "install", "-q"] + offline + ["-e", REPO])
    if r.returncode != 0:
        return False
    # gotcha guard: verify every import INSIDE the venv, heal with --ignore-installed
    for mod in VENV_IMPORTS:
        if run([VPY, "-c", f"import {mod}"], capture_output=True).returncode != 0:
            pkg = {"yaml": "pyyaml"}.get(mod, mod)
            print(f"venv: {mod} broken (system-shadow gotcha) -> reinstalling")
            run([VPIP, "install", "-q", "--upgrade", "--ignore-installed"]
                + offline + [pkg])
    BIN.mkdir(parents=True, exist_ok=True)
    link = BIN / "bizflow"
    if not link.exists():
        link.symlink_to(VENV / "bin/bizflow")
    return True


def phase_bin(check):
    if shutil.which("duckdb") or (BIN / "duckdb").exists():
        print("bin: duckdb present")
        return True
    if check:
        print("bin: WOULD download duckdb CLI")
        return True
    try:
        zpath = Path("/tmp/duckdb_cli.zip")
        urllib.request.urlretrieve(DUCKDB_URL, zpath)
        run(["unzip", "-o", "-q", zpath, "-d", BIN])
        (BIN / "duckdb").chmod(0o755)
        return True
    except Exception as e:
        print(f"bin: duckdb download failed ({e}) - python duckdb still works")
        return True  # non-fatal: the venv lib covers the pipeline


def phase_data(check):
    src = REPO / "templates"
    if check:
        print(f"data: WOULD copy {len(list(src.glob('*.yml')))} template(s)")
        return True
    TPL_DST.mkdir(parents=True, exist_ok=True)
    for t in src.glob("*.yml"):
        shutil.copy2(t, TPL_DST / t.name)
    print(f"data: templates -> {TPL_DST}")
    return True


def phase_smoke():
    ok = True
    for mod in VENV_IMPORTS:
        r = run([VPY, "-c", f"import {mod}"], capture_output=True)
        print(f"  import {mod:<14} {'OK' if r.returncode == 0 else 'FAIL'}")
        ok &= r.returncode == 0
    for t in CLI_TOOLS:
        found = shutil.which(t) is not None
        print(f"  cli    {t:<14} {'OK' if found else 'MISSING'}")
        ok &= found or t in ("hledger", "mlr", "entr", "fzf")  # companions
    r = run(["tesseract", "--list-langs"], capture_output=True, text=True)
    has_ita = "ita" in (r.stdout or "")
    print(f"  ocr    lang ita       {'OK' if has_ita else 'MISSING'}")
    ok &= has_ita
    r = run([VENV / "bin/bizflow", "--help"], capture_output=True)
    print(f"  cli    bizflow        {'OK' if r.returncode == 0 else 'FAIL'}")
    ok &= r.returncode == 0
    # micro end-to-end: synthetic items -> analyze -> optimize
    code = (
        "import csv,tempfile,os\n"
        "from bizflow import analyze, optimize\n"
        "rows=[{'page':1,'code':'1'*13,'descrizione':f'BRAND{i%3} PROD GR 200',"
        "'qty':2.0,'mpl':12,'price':10.0,'piece_price':0.8333,'total':20.0}"
        " for i in range(9)]\n"
        "f=tempfile.NamedTemporaryFile('w',suffix='.csv',delete=False,newline='')\n"
        "w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader()"
        ";w.writerows(rows);f.close()\n"
        "s=analyze.summarize(f.name); assert s['items']==9, s\n"
        "optimize.attach_weights(rows)\n"
        "n,loads,st=optimize.pack_pallets(rows,cap_kg=450)\n"
        "assert n>=1 and st in('OPTIMAL','FEASIBLE'),(n,st)\n"
        "os.unlink(f.name); print('  e2e    analyze+optimize  OK')\n")
    r = subprocess.run([str(VPY), "-c", code], capture_output=True, text=True)
    print(r.stdout.rstrip() or f"  e2e    FAIL\n{r.stderr[-400:]}")
    ok &= r.returncode == 0
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--no-apt", action="store_true")
    ap.add_argument("--no-bin", action="store_true")
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument("--wheelhouse", metavar="DIR",
                    help="offline pip installs from this wheel directory")
    a = ap.parse_args()

    if a.smoke_only:
        sys.exit(0 if phase_smoke() else 1)
    results = {}
    if not a.no_apt:
        results["apt"] = phase_apt(a.check)
    results["venv"] = phase_venv(a.check, a.wheelhouse)
    if not a.no_bin:
        results["bin"] = phase_bin(a.check)
    results["data"] = phase_data(a.check)
    if not a.check:
        results["smoke"] = phase_smoke()
    print("\n== " + "  ".join(f"{k}:{'OK' if v else 'PENDING/FAIL'}"
                              for k, v in results.items()))
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
