<div align="center">

# bizflow

**A command-line chain that turns a supplier PDF into reconciled line items, an EOQ table, and a pallet plan — with the layout described in YAML instead of hardcoded.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB.svg)](pyproject.toml)
[![Deps](https://img.shields.io/badge/dependencies-7%20packages-informational.svg)](requirements.txt)
[![Tests](https://img.shields.io/badge/tests-none%20yet-informational.svg)](#testing)

`modus-znz/bizflow` · Python · MIT

</div>

---

## Contents

- [The problem](#the-problem)
- [What it does](#what-it-does)
- [Quickstart](#quickstart)
- [Architecture](#architecture)
- [Usage](#usage)
- [Configuration](#configuration)
- [Testing](#testing)
- [Deployment and operations](#deployment-and-operations)
- [Design decisions and trade-offs](#design-decisions-and-trade-offs)
- [Limitations](#limitations)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

---

## The problem

A wholesale invoice is a table that only exists as a drawing. The quantities,
pack multiples, unit prices and line totals are all present, all precise, and
all laid out by a print shop rather than by a data format — so nothing reads
them without knowing where on the page each column starts.

The usual answers each fail differently:

- **A hand-maintained regex per supplier.** Works until the supplier changes
  their template, and there is no way to see *which* column a number came from
  when it goes wrong.
- **invoice2data alone.** It is good at the header — issuer, number, date,
  VAT, total — and does not attempt line items at all, because line items are
  positional rather than labelled.
- **A general table extractor.** Reliable on clean digital tables, and quietly
  wrong on a scanned or mixed-content PDF where the "table" is a text flow with
  a column ruler drawn through it.

bizflow splits the problem in two and gives each half the right tool. The
header goes to invoice2data, which is built for labelled fields. The line
items are harvested geometrically, with the column positions read off the
document's own header row.

The reconciliation it exposes is the part that matters commercially. Printed
line totals rarely equal quantity × multiple × piece price exactly, because the
supplier rounds each line to cents. `analyze` prints both sums and the drift
between them, so a rounding artefact is visibly a rounding artefact instead of
looking like a missing row.

## What it does

| Stage | Command | What happens |
|---|---|---|
| Fetch | `scripts/watch.sh` | Watches a folder, processes new PDFs, moves them to `processed/` |
| Convert | `bizflow convert` | Anything → Markdown, via markitdown |
| OCR | `bizflow ocr` | Scanned or mixed PDF → searchable PDF/A (`ita+eng` by default) |
| Extract | `bizflow process` | Header JSON via invoice2data; line items via pdfplumber geometry |
| Analyze | `bizflow analyze` | DuckDB: printed vs full-precision sums, brand mix, top items, Parquet |
| Optimize | `bizflow optimize` | stockpyl EOQ per SKU; ortools CP-SAT pallet packing |

The bundled layout and template are **synthetic examples**. They show the shape
of an Italian wholesale invoice without naming anybody. See
[Configuration](#configuration) for onboarding a real vendor.

## Quickstart

```bash
git clone https://github.com/modus-znz/business-flow.git
cd business-flow
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# The system tools the OCR and convert paths shell out to.
sudo apt-get install -y ocrmypdf poppler-utils tesseract-ocr tesseract-ocr-ita

# A synthetic invoice ships with the repo, so this works before you have one.
bizflow process invoices/sample-invoice.pdf --out out/
bizflow analyze out/sample-invoice-items.csv
```

Then point it at a real document:

```bash
bizflow process /path/to/supplier.pdf --out out/
```

No configuration, no credentials, no network calls at runtime. Or skip the venv
entirely — the system packages pull in `ocrmypdf`, `poppler-utils` and
`tesseract-ocr`, which the container image already has:

```bash
docker compose run --rm extract
```

`install.py` does all of the above plus an offline smoke test, and is designed
for hosts with no root: it prints the single `apt-get` line an admin needs and
completes every user-space step itself.

```bash
python3 install.py --check        # dry run, prints the plan
python3 install.py --smoke-only   # skip apt, verify the venv
python3 install.py                # full run
```

It is idempotent. Re-running repairs a venv that a `--system-site-packages`
experiment broke, in either direction.

## Architecture

```
  PDF ──► ocrmypdf ──► searchable PDF/A
            │
            ├──► invoice2data + templates/*.yml ──► header JSON
            │      (labelled fields: regex per field)
            │
            └──► pdfplumber ──► words with x/y geometry
                     │
                     └──► harvest_items() + layouts/*.yml
                            (positional columns: x-distance from
                             each header's centre)
                                   │
                                   ▼
                          line items CSV ──► DuckDB ──► Parquet
                                   │
                                   ├──► analyze  : reconciliation, brand mix
                                   └──► optimize : EOQ (stockpyl)
                                                  pallet packing (ortools CP-SAT)
```

### Modules

| Module | Lines | Responsibility |
|---|---|---|
| `bizflow/__main__.py` | 144 | CLI, argument parsing, output formatting |
| `bizflow/extract.py` | 113 | Header extraction and the geometry harvest |
| `bizflow/optimize.py` | 80 | Weight parsing, EOQ, pallet packing |
| `bizflow/analyze.py` | 47 | DuckDB reconciliation and brand mix |
| `bizflow/convert.py` | 24 | Markdown conversion and OCR wrappers |
| `install.py` | 204 | Layered installer, venv healer, smoke test |

Only `extract.py` knows how a PDF becomes a row. Everything downstream consumes
a CSV, which is why `analyze` and `optimize` can be run against a file that came
from somewhere else entirely.

## Usage

```bash
# Header + line items + summary, in one pass
bizflow process invoice.pdf --out out/
#   header : Sample Vendor S.r.l. n.000123 01/09/2026 12.480,00 EUR
#   items  : 270 rows -> out/invoice-items.csv
#   line items : 270
#   printed sum: 12.480,00
#   full-precision sum: 12.480,04 (rounding drift -0.04)
#   top brands : Sample 4.120,00 (33%), Other 3.900,00 (31%), ...
#   parquet    : out/invoice-items.parquet

# Reconciliation over any CSV, including one you built yourself
bizflow analyze out/invoice-items.csv

# Inventory economics and a packing plan
bizflow optimize out/invoice-items.csv --pallet-cap 450 --order-cost 450
#   weights: 241/270 parsed from descriptions; shipment ~1,880 kg
#   EOQ (K=450.00, holding=25%/yr, 12 cycles/yr):
#     Sample item one                        qty   120  EOQ   118.4  orders/yr  1.2
#     ...
#   pallets: 5 @ 450 kg [optimal] loads=47
```

Other subcommands:

```bash
bizflow convert order.pdf -o order.md    # LLM-readable Markdown
bizflow ocr scan.pdf clean.pdf           # searchable PDF/A
scripts/watch.sh ~/inbox ~/out           # hot folder
```

`process` accepts `--layout` and `--templates` to point at your own vendor
specs. It writes `<stem>-header.json`, `<stem>-items.csv`, and — when the
layout carries `qty`, `mpl` and `piece_price` — `<stem>-items.parquet`.

## Configuration

There is no configuration file, no environment variable, and no credential. The
whole surface is two YAML files and the CLI flags.

| Where | Holds | Default |
|---|---|---|
| `templates/<vendor>.yml` | invoice2data header fields | `~/.local/share/invoice2data-templates`, else `./templates` |
| `bizflow/layouts/<vendor>.yml` | line-item column geometry | the bundled `it.sample-vendor.yml` |
| `--out` | output directory | `bizflow-out/` |
| `--pallet-cap` | kg per pallet | `450` |
| `--order-cost` | EOQ order cost K | `450.0` |
| `--holding` | annual holding rate | `0.25` |
| `--cycles` | demand cycles per year | `12` |

The two YAML kinds are different animals, and the split is the main idea:

**A header template** names fields and matches them by regex anywhere on the
page. Order does not matter; the label is the anchor.

```yaml
issuer: Sample Vendor S.r.l.
fields:
  invoice_number: 'N° Documento\s+(\d+)'
  amount: 'Totale Documento[\s\S]{0,400}?(\d{1,3}(?:\.\d{3})*,\d{2})'
options:
  decimal_separator: ','
```

**A line-item layout** names the column headers *as they are printed* and lets
the harvester find each column's x-centre on the page. A compound header is a
word list, and the **last** word anchors the column.

```yaml
code_regex: '^\d{13}$'     # the row starts with an EAN-13
columns:
  qty: "Q.tà"
  total:
    header: ["P.zo", "Totale"]
  piece_price:
    header: ["P.zo", "Pz", "Imp."]
    tol: 30                # half-width in points for column membership
```

### Onboarding a real vendor

1. `pdftotext -layout invoice.pdf -` and find the label and value zones.
   `-layout` scrambles columns, so a value can appear on a *different* label's
   line — verify every zone against the rendered page, not the text dump.
2. Copy `templates/it.sample-vendor.yml`, set the issuer, and fit each regex.
   Use `[\s\S]{0,400}?` to bridge a label and its value when they are
   scattered. `decimal_separator: ','` for EU suppliers.
3. Copy the layout, set `code_regex` to whatever identifies a row, and list each
   printed column header. Pass with `--layout`.
4. Check the row count against the PDF. A harvest that returns nothing usually
   means `code_regex` does not match the first token of the row, not that the
   file has no items — `process` exits with that message rather than writing an
   empty CSV.

The full procedure, including the failure modes, is in
[docs/OPERATIONS.md](docs/OPERATIONS.md).

## Testing

```bash
python -m unittest discover -s tests -v
```

Eleven tests, run on Python 3.11–3.13 in CI, against
`invoices/sample-invoice.pdf` — a generated, entirely synthetic invoice that
ships with the repo. Regenerate it with `tools/make_sample_invoice.py`
(needs `reportlab`; the tool itself never needs it).

The tests exist for one reason: the fragile part of this project is geometry,
not regex. "Which number in this row is the unit price" depends on x-coordinates
that move whenever a layout changes, and when it breaks it produces a
plausible-looking wrong number rather than an exception. So the suite pins the
extracted values for every column of every row, asserts that the printed totals
reproduce the declared total, and asserts that the rounding drift is present but
small.

That last pair is worth spelling out. `analyze` printing a drift figure is the
point of the tool, so a sample where drift is zero proves nothing; and a drift
above 1% would mean a column is being read from the wrong place rather than that
a supplier rounded. The sample is built to land between the two.

To confirm the suite would catch a real regression, re-anchor the totals column
on the first word of its compound header instead of the last
(`header: ["P.zo"]` instead of `header: ["P.zo", "Totale"]`) and re-run. Four
tests fail. That is the exact mistake the layout documentation warns about, and
it is a silent one.

CI additionally checks that every module compiles, that both YAML files parse
and carry the keys `extract.py` reads by name, that the CLI wires up, that
`DEFAULT_LAYOUT` points at a file that exists, and that the bundled template
still names the synthetic sample while layout filenames still look like generic
slugs rather than company names.

The last check is not ceremony. An earlier version of this repository named a
real supplier in a template, in a layout *filename*, in a docstring and in its
README; the repository had to be made private. The filename matters as much as
the contents, because the filename is in the URL.

## Deployment and operations

This is a CLI, so "deployment" means installing it on the host that holds the
invoices.

| Concern | How it is handled |
|---|---|
| Install | `install.py` — apt layer, venv, templates, smoke test. Idempotent. |
| No root | Prints the one `apt-get` line for an admin, does the rest itself |
| Slow egress | `--no-apt --no-bin --wheelhouse DIR` consumes a pre-fetched wheelhouse |
| Configuration | None. Two YAML files and flags. No credential exists to rotate. |
| Network | None at runtime. It reads local PDFs and prints to stdout. |
| Sensitive data | Output CSVs and Parquet contain the supplier's commercial data. `.gitignore` covers `bizflow-out/`, but a CSV written *into* the repo will be committed by `git add .` — write to `--out` outside the working tree when the data is real. |
| Idempotence | `install.py` yes. `process` overwrites its outputs for a given stem. |

See [docs/OPERATIONS.md](docs/OPERATIONS.md) for the air-gapped install
procedure, which is the non-obvious case.

## Design decisions and trade-offs

| Decision | Chosen | Rejected | Cost accepted |
|---|---|---|---|
| Column detection by x-distance to a header centre | Anchoring on the document's own header row | Positional character offsets in the template | A header that moves between document versions needs the template re-read; that is a file edit, not a code change |
| Compound headers anchored by the last word | `"P.zo"` + `"Totale"` → the x-centre of `Totale` | Anchoring on the first word | For a right-aligned total column the *label* is usually left of the numbers, so the first word is the wrong anchor |
| Row start identified by a code regex | `^\d{13}$` on the row's first token | Inferring rows from y-coordinate clustering | Needs a per-vendor code format, but it makes row detection immune to a blank line inside a wrapped description |
| Weights parsed from the description, median fallback | `GR/KG/ML/LT/CL` regex, then a median piece weight | Requiring a weight column | 29 of 270 rows on the reference document had no parseable weight and were estimated. Flagged in the output rather than hidden |
| Row clustering on `top` with a tolerance, not `round(top)` | A 3-point band | Rounding the y-coordinate | `round()` splits a single visual line whose words differ by a fraction of a point |
| Both reconciliation sums always printed | Printed vs `qty*mpl*piece_price` | Reporting only the declared total | Two numbers where one would do, in exchange for making rounding drift visible rather than mysterious |
| Parameters as CLI flags, never config files | `--pallet-cap`, `--order-cost`, … | A YAML config | Nothing to version, nothing to migrate, but also no per-vendor defaults |
| A synthetic bundled layout | `it.sample-vendor.yml` | A real vendor's layout as the worked example | The example is less impressive, and it is the only version that can be public |
| `[\s\S]{0,400}?` bridges in header regexes | Bounded lazy match | Anchored exact matches | A generous window can match the wrong field on a dense page; the bound keeps it finite |

### Why the header and the line items use different strategies

invoice2data matches labelled fields, which is right for a header: `N° Documento`
is a string that appears exactly once and carries its own value. Line items have
no such anchor — a row is a row because of where it sits horizontally relative
to the header row above it. Forcing one strategy onto both is what makes most
extraction tools brittle, so bizflow uses each where it holds.

The cost is that a vendor needs two files, not one, and a column header that
moves is a template edit rather than something the tool can re-derive. That is
the trade, and it is deliberate: a re-derivable heuristic that silently picks
the wrong column is worse than a file a human has to look at.

## Limitations

- **One synthetic invoice, not a corpus.** The sample is generated, single-page
  and clean: one header row, no wrapped descriptions, no continuation lines, no
  merged cells. The harvest is exercised, but only against a layout as tidy as
  the one it is paired with. Real invoices are messier than the sample, and the
  per-vendor tuning in [docs/OPERATIONS.md](docs/OPERATIONS.md) is where that
  mess is actually handled.
- **No real invoice is included.** Deliberate, and the reason this is a public
  repository. The format in the usage examples is real; the values are invented.
- **Column tolerance still needs tuning per vendor.** `tol` is a half-width in
  points, and there is no way to choose it correctly without looking at the
  document. The `layout-probe` command below is the fix and does not exist yet.
- **Weights are often estimated.** Descriptions are parsed for `GR/KG/ML/LT/CL`;
  rows that do not parse get a median piece weight. The count of parsed vs
  total is printed, but the estimated rows are not distinguished in the output.
- **One language of layout.** The bundled sample is Italian. The header regexes
  are label-matched so they port, but the column harvesting assumes a
  left-to-right table with a single header row per page.
- **Multi-page tables assume a repeating header.** Each page is processed
  independently; a page whose header row differs from the first will produce
  mis-anchored columns rather than an error.
- **Descriptions are truncated by x-position, not by column.** A description
  that runs under a numeric column loses its tail.
- **`analyze` interpolates the CSV path into SQL.** Fine for a local tool
  invoked by the person who owns the file; not safe if the path ever comes from
  an untrusted source.
- **No multi-page header stitching.** `invoice2data` handles a header spanning
  pages; this tool does not, and will return `None` rather than a partial.

## Roadmap

- [ ] **Next** — a multi-page synthetic sample with a wrapped description and a
      continuation line, so the harvest is tested against a layout that is
      awkward rather than merely tidy.
- [ ] **Next** — a `bizflow layout-probe <pdf>` command that prints each
      detected header centre and the words falling inside each column, so
      tuning `tol` is a lookup rather than a guess.
- [ ] **Later** — mark estimated weights in the CSV with a `weight_source`
      column (`parsed` / `median`) instead of only counting them.
- [ ] **Later** — `--strict-count`: exit non-zero when the harvested row count
      disagrees with a declared count on the invoice.
- [ ] **Later** — a `templates/` schema validator callable locally, so a
      malformed template is caught before it is pointed at a supplier.
- [ ] **Probably not** — a hosted or multi-tenant version. The value here is
      that the layouts are files a person can read and edit; a service makes
      them somebody else's problem.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The short version:

1. **Do not add a real supplier to this repository.** Not in a template, not in
   a layout filename, not in a docstring, not in a test fixture. Use the
   synthetic sample, and say in the PR that you did. This has already caused one
   incident and the CI check exists because of it.
2. A layout or template change needs the matching `--layout` default updated in
   the same commit, or `process` will point at a missing file. CI checks this.
3. Keep the assumptions out of the code and in the flags. `pallet_cap`,
   `order_cost`, `holding` and `cycles` are parameters because the right value
   is a business decision, not a default.
4. If you add reconciliation, print both sums. A single number hides rounding
   drift, and the drift is usually the thing being looked for.
5. New behaviour needs a test. There is no suite yet; the first contribution
   that adds one is the most valuable thing in this list.

## License

MIT — see [LICENSE](LICENSE).
