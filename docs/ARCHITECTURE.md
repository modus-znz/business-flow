# Architecture

bizflow is a chain of small stages, each of which consumes a file the previous
one wrote. The important structural decision is that the split happens at the
CSV: everything upstream of `items.csv` is about reading a PDF, and everything
downstream is arithmetic on tabular data that could have arrived from anywhere.

## The shape, in one paragraph

`process` runs two independent extractions over the same PDF. The header goes to
invoice2data, which matches labelled fields by regex. The line items go to a
geometry harvest: pdfplumber gives every word an x/y position, the layout YAML
names the column headers as they are printed, and a column is the set of words
near the x-centre of its header. Both write into `out/`, and `analyze` and
`optimize` then read only the CSV.

```
                     ┌── invoice2data + templates/<vendor>.yml ──► header JSON
  PDF ──► ocrmypdf ──┤
         (optional)  └── pdfplumber words(x,y) + layouts/<vendor>.yml
                                    │
                                    ▼
                            line items CSV
                                    │
                    ┌───────────────┴───────────────┐
                    ▼                               ▼
             analyze (DuckDB)              optimize (stockpyl, ortools)
             printed vs full-precision       EOQ per SKU, CP-SAT pallet plan
             brand mix, top items
                    │                               │
                    └──────────► Parquet ◄──────────┘
```

## Why two extraction strategies

invoice2data matches a labelled field anywhere on the page. That is exactly
right for a header: `N° Documento` is a string that appears once and carries
its own value, so position is irrelevant and a regex is sufficient.

A line item has no such anchor. Nothing in a row says "I am the price"; a row is
a row because of where it sits relative to the header row above it. The same
regex that finds `Prezzo` cannot say which of the four numbers in a row is the
unit price, because the answer is the one under that column heading on that page.

So the two halves of an invoice get two different mechanisms, and the layout
file is the interface between them. The cost is that a vendor needs two files
rather than one, and that a supplier who reflows their template requires a
template edit. The alternative — one heuristic for both — is what makes most
extraction tools quietly wrong, and a wrong price column is worse than an
error.

## Modules

| Module | Responsibility | Knows about |
|---|---|---|
| `__main__.py` | CLI surface, argument parsing, output formatting | Every stage, none of their internals |
| `extract.py` | invoice2data header extraction; the geometry harvest | pdfplumber geometry, layout schema |
| `analyze.py` | DuckDB reconciliation, brand mix, Parquet export | A CSV on disk |
| `optimize.py` | Weight parsing, EOQ, pallet packing | A list of dicts |
| `convert.py` | Markdown conversion, OCR wrapper | External tools (`markitdown`, `ocrmypdf`) |
| `install.py` | Layered install, venv healing, smoke test | apt, venv, the import graph |

`extract.py` is the only module that knows how a PDF becomes a row. `analyze`
and `optimize` never see a PDF, which is what lets them run against a CSV that
came from a different tool.

## The harvest, in detail

`harvest_items(pdf_path, layout)` is the core. Per page:

1. `page.extract_words()` yields every word with `x0`, `x1`, `top`, `text`.
2. For each column in the layout, `_header_center(words, header)` locates the
   header. A compound header is a word *sequence*: the x-centre of the **last**
   word is the anchor.
3. `_rows(words)` clusters words into visual rows by `top` with a 3-point band.
4. For each row whose first token matches `code_regex`, each column is filled by
   `_pick`, which takes the numeric word whose own centre is closest to the
   column's centre, within `tol`.
5. The description is everything between the code and the first numeric column,
   minus the numeric tokens themselves.

### Three details that are load-bearing

**The last word anchors a compound header.** A right-aligned total column is
labelled `P.zo Totale` on the left and the numbers sit on the right. The label's
*first* word is the wrong anchor by a wide margin; the last word is adjacent to
the figures. Getting this backwards produces a column of plausible-looking
numbers in the wrong place.

**`round(top)` splits a line.** Words on one printed line routinely differ in
`top` by a fraction of a point. Rounding to an integer can put two words from
one line in different clusters, and a row then loses a column. The 3-point band
in `_rows` exists for that reason, and the comment in the code says so.

**`tol` is a half-width, not a match distance.** `_pick` finds the *nearest*
numeric word to the column centre and then rejects it if it is further than
`tol`. So a wide `tol` lets a neighbouring column bleed in, and a narrow one
drops values that are slightly offset. 30 points is a reasonable start for a
crowded Italian wholesale invoice; it is not a constant.

## Weight parsing

`optimize.attach_weights` looks for `GR|KG|ML|LT|CL` followed by a number in the
description, and converts to kilograms (`KG`/`LT` ×1000, `ML` ×1, `CL` ×10,
`GR` ×1), then multiplies by a 1.05 packaging factor.

Rows with no parseable weight get the **median** piece weight from the rows
that did parse. This is an estimate, and on the reference document 29 of 270 rows
needed it. The count is printed (`weights: 241/270 parsed from descriptions`) but
the estimated rows are not distinguished in the output, which is a known gap.

## Reconciliation

`analyze.summarize` prints two sums and the difference:

- `printed_sum` — the sum of the line totals as printed.
- `full_precision_sum` — the sum of `qty * mpl * piece_price`.

Suppliers round each line to cents for display, so these differ by a small
amount even when every row was harvested correctly. Printing only the declared
total would hide that, and a rounding artefact would be indistinguishable from a
missing row. The second sum is only computed when the layout actually carries
all three of `qty`, `mpl` and `piece_price`.

`has_precision` is computed with a `DESCRIBE` rather than a `try`, because a
`SELECT` against absent columns fails at query time and a `try` around the query
would swallow real errors too.

## Error handling

`process` exits with a message rather than writing an empty CSV when the harvest
returns nothing. The message names the likely cause (`check the layout spec`),
because the overwhelmingly common cause is a `code_regex` that does not match
the first token of a row, not an empty document.

`extract_header` silences the `invoice2data` logger to `CRITICAL`. Its text
backend cascade logs partial-match noise at WARNING and ERROR even when a later
backend succeeds, so an unmatched template produced a wall of alarming output
for a clean no-match. A real no-match surfaces as the function's own `None`.

## State

There is none. No database, no cache, no config file, no environment variable.
Each command reads files and prints. The only outputs are `out/` and whatever
`install.py` creates in a venv.

## Known weaknesses

- **Nothing is tested.** The geometry harvest is the product and no test pins
  its behaviour against a known PDF.
- **Headers must repeat per page.** Each page is processed independently against
  the same layout; a page with a different header row yields mis-anchored
  columns rather than an error.
- **Description truncation is positional.** A description that runs under a
  numeric column loses its tail, because the cut is an x-threshold rather than a
  column boundary.
- **The median weight fallback is silent per row.** Counted, not marked.
- **SQL is built by f-string interpolation** of the CSV path. Acceptable for a
  local tool invoked by the file's owner; not safe if the path ever comes from
  an untrusted source.
- **`analyze` guesses brand from the first word** of the description
  (`split_part(descrizione,' ',1)`), which is a heuristic and will mislabel any
  item whose description does not lead with the brand.
