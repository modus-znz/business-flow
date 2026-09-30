# Operations

Installing, running, and onboarding a supplier. The short version: no
configuration file, no environment variable, no credential, and no network call
at runtime.

## Install

### Normal

```bash
python3 install.py --check        # dry run — print the plan, change nothing
python3 install.py                # do it
```

Five phases, each skippable:

| Phase | What it does | Needs root? |
|---|---|---|
| `apt` | System CLI layer: `ocrmypdf`, `poppler-utils`, `tesseract-ocr*`, `pandoc`, `qpdf`, `entr`, … | prints the command and continues |
| `venv` | `~/.local/share/bizvenv` with `--system-site-packages`, then `pip install -e .` | no |
| `bin` | Static `duckdb` CLI into `~/.local/bin` | no |
| `data` | Vendor templates into `~/.local/share/invoice2data-templates` | no |
| `smoke` | Imports every dependency **from inside the venv** and runs the CLI | no |

Without root it prints the single `apt-get` line an admin needs and completes
every user-space phase. That is deliberate: on a host where the operator has no
sudo, "install the parts you can and tell me the rest" beats refusing to start.

### Idempotence and the venv healer

Re-running is safe and is the expected way to repair a broken install.

The venv is created with `--system-site-packages`, which has a specific failure
mode worth knowing: **if the system already provides a package, `pip install`
into the venv silently does nothing for it.** And the reverse also happens — a
newer system package can break an import inside a venv that holds an older
dependency. Both directions produce an import error that looks like a corrupt
install.

So every failed import is retried with `--upgrade --ignore-installed`, which
forces the venv's copy to win. This is the rule the installer encodes, and it is
why `--smoke-only` is more than a formality: an install marker file can say the
install succeeded while the venv is still broken.

```bash
python3 install.py --smoke-only   # verify without touching apt or binaries
```

### Slow or absent egress

`install.py` is written for hosts where PyPI crawls. Build the wheelhouse
somewhere fast, ship the directory, install offline:

```bash
# on a fast machine, matching OS/arch/python
pip download -r requirements.txt -d wheelhouse/
pip download setuptools wheel -d wheelhouse/
```

Verify the wheelhouse is actually complete by installing into a **bare** venv
with no index. A wheelhouse that only works on the machine that built it is not
a wheelhouse:

```bash
python3 -m venv /tmp/t
/tmp/t/bin/pip install --no-index --find-links wheelhouse/ -e .
```

Then on the target host:

```bash
python3 install.py --no-apt --no-bin --wheelhouse ~/wheelhouse
sudo apt-get install -y ~/debs/*.deb     # the one root step
```

Let the target host compute its own missing-package closure rather than shipping
a pre-built list, so a version bump on the mirror does not leave the list stale:

```bash
ssh HOST 'apt-get install --print-uris -y PKGS' | grep "^.http" | cut -d"'" -f2 > uris.txt
xargs -P 8 -n 1 curl -fsSO < uris.txt
for f in debs/*.deb; do dpkg-deb -I "$f" >/dev/null || echo "BAD: $f"; done
```

`curl -f` matters: without it a 404 body is saved as a `.deb` and fails later,
somewhere unrelated.

Two traps that cost real time:

- **`apt-get install` with local `.deb` arguments can still re-download
  same-version, same-hash packages from the archive.** Observed on 6 of 30
  locally; suspected `%`-encoded filenames and epoch mapping. Pre-fetching by
  decoded name avoids most of it.
- **A Cloudflare-fronted Debian mirror is dramatically faster than the canonical
  pool** on some hosts — measured 6.9 MB/s against 20 KB/s. If a fetch crawls,
  try the CDN before assuming the link is broken.

If the transfer itself is the bottleneck rather than the mirror, ship a tarball
over HTTP **with Range support** and pull it with `aria2c`, which needs 206
responses to split:

```bash
tar cf payload.tar.gz payload/ && sha256sum payload.tar.gz > SHA256SUMS
python3 -m http.server 8000 &        # note: stdlib http.server answers 200-only
aria2c -c -x 8 -s 8 -k 4M http://HOST:8000/payload.tar.gz
sha256sum -c SHA256SUMS && tar xf payload.tar.gz
```

## Usage

```bash
bizflow process invoice.pdf --out out/
bizflow analyze out/invoice-items.csv
bizflow optimize out/invoice-items.csv --pallet-cap 450
bizflow convert order.pdf -o order.md
bizflow ocr scan.pdf clean.pdf
scripts/watch.sh ~/inbox ~/out
```

### Hot folder

`scripts/watch.sh` uses `entr` in oneshot mode: a new PDF appears in `~/inbox`,
it is processed, and it moves to `~/out/processed`. Files are moved rather than
deleted so a failed run leaves its input recoverable.

## Onboarding a supplier

This is the part that takes judgement, and the part this repository cannot do
for you. The bundled layout and template are **synthetic examples** — a real
supplier's specifications do not belong in a public repository.

### 1. Find the header fields

```bash
pdftotext -layout supplier.pdf - | less
```

`-layout` preserves rough column positions but **scrambles the reading order**:
a value can appear on a *different* label's line than it belongs to. Verify every
zone you find against the rendered page, not against this dump.

### 2. Write the header template

```bash
cp templates/it.sample-vendor.yml ~/.local/share/invoice2data-templates/acme.yml
```

| Field | What to do |
|---|---|
| `issuer` | Their legal name |
| `keywords` | Strings that must appear for this template to apply |
| `invoice_number` | Regex for the document number |
| `date` | Regex, plus `date_formats` matching their layout |
| `amount` | Regex for the declared total |
| `options.decimal_separator` | `,` for EU suppliers — **this is the one most often missed** |
| `options.languages` | Drives invoice2data's backend selection |

For a label and its value that are far apart on the page, bridge them with a
bounded lazy match:

```yaml
amount: 'Totale Documento[\s\S]{0,400}?(\d{1,3}(?:\.\d{3})*,\d{2})'
```

The `400` is a safety bound. A generous window can match the wrong field on a
dense page, but an unbounded one will.

Test it alone before going further:

```bash
python3 -c "
from bizflow.extract import extract_header
print(extract_header('supplier.pdf', '$HOME/.local/share/invoice2data-templates'))
"
```

`None` means no template matched. The `invoice2data` logger is silenced to
`CRITICAL` by `extract_header`, so a no-match is quiet by design — check your
`keywords` first, then the regex.

### 3. Write the line-item layout

```bash
cp bizflow/layouts/it.sample-vendor.yml bizflow/layouts/acme.yml
```

| Key | Meaning |
|---|---|
| `code_regex` | Matches the **first token of the row** — EAN-13, or their article code |
| `columns.<name>` | The column header **exactly as printed** |
| `columns.<name>.header` | A string, or a list for a compound header |
| `columns.<name>.tol` | Half-width in points for column membership |

Rules that are not obvious from the code:

- **A compound header is anchored by its last word.** For
  `header: ["P.zo", "Totale"]` the column centre is the x-centre of `Totale`.
  Right-aligned columns are labelled to the left of their numbers, so the first
  word is the wrong anchor.
- **The header text must match the PDF's own text layer**, including accents and
  punctuation. `Q.tà` with the accent, not `Qta`.
- **Raise `tol` when columns bleed into each other; lower it when a value is
  dropped.** 30 is a starting point, not a constant.
- **`code_regex` is the row anchor.** If the harvest returns nothing, this is
  almost always why — check it before anything else.

### 4. Verify the row count

```bash
bizflow process supplier.pdf --layout bizflow/layouts/acme.yml --out /tmp/probe
```

Compare the row count against the invoice. A short harvest is nearly always a
narrow `tol` or a header that did not match; the columns that *are* populated
will look plausible, which is what makes a short harvest easy to miss.

Then look at the output:

```bash
head -3 /tmp/probe/supplier-items.csv
bizflow analyze /tmp/probe/supplier-items.csv
```

A large `rounding drift` is not a bug — it is per-line rounding by the supplier.
A `full-precision sum` far from `printed sum` means a column is being read from
the wrong place.

## Common failures

| Symptom | Likely cause | Action |
|---|---|---|
| `no line items found - check the layout spec` | `code_regex` does not match the row's first token | `pdftotext -layout` and look at what starts each row |
| Header returns `None`, silently | `keywords` do not appear, or the regex is wrong | Check `keywords` first; the logger is silenced on purpose |
| Amounts off by a factor of 1000 | `decimal_separator` left at `.` for an EU supplier | Set `options.decimal_separator: ','` |
| A column is populated with the neighbouring column's numbers | Wrong anchor, or `tol` too wide | Check whether a compound header is anchored on its last word; narrow `tol` |
| Only some rows harvested | A wrapped description moves the row's `top` | Increase row tolerance in `_rows`, or accept it |
| `ImportError` right after install | The `--system-site-packages` shadowing described above | Re-run `install.py`; the healer retries with `--upgrade --ignore-installed` |
| `duckdb` not found in a shell | The static binary is in `~/.local/bin`, not on `PATH` | `export PATH="$HOME/.local/bin:$PATH"` |
| OCR produces an empty text layer | Wrong language pack | `tesseract-ocr-ita` is installed by the `apt` phase; pass `--lang ita+eng` |
| A CSV written into the repo gets committed | `--out` defaulted inside the working tree | Write to a path outside the repo when the data is real |

## Handling the output

`out/*.csv` and `out/*.parquet` contain the supplier's commercial data: article
codes, quantities, prices and totals. `.gitignore` covers `bizflow-out/`, the
default output directory, but a CSV written anywhere else inside the working
tree will be picked up by `git add .`.

When the data is real, write outside the repository:

```bash
bizflow process supplier.pdf --out ~/work/invoices/2026-09/
```

There is no upload step and no database, so the only place this data can leak is
a commit. That is the whole threat model.

## Escalation

Bugs and template questions: open an issue with the `pdftotext -layout` excerpt
around the field that failed, with the counterparty removed. **Do not attach the
supplier's PDF, and do not paste their legal name into the issue** — a public
issue tracker is the wrong place for either.
