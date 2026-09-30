# Contributing

## The one rule

**Do not add a real supplier to this repository.** Not in a template, not in a
layout filename, not in a docstring, not in a test fixture, not in an issue.

An earlier version of this repository named a real supplier in a header
template, in a layout *filename*, in a module docstring and in the README. The
repository had to be made private by hand and its history rewritten. The
filename matters as much as the contents, because the filename is in the URL.

Use the synthetic sample in `templates/it.sample-vendor.yml` and
`bizflow/layouts/it.sample-vendor.yml`, and say in your PR that you did. CI
checks that the bundled template still names the synthetic sample and that
layout filenames still look like generic slugs.

If you need to discuss a real supplier's layout, describe the *shape* — "the
total column is labelled with two words and the numbers are right-aligned" — not
the name.

## Getting set up

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

If you change the harvest, the layout, or the header template, add a test that
fails without your change. The suite runs against
`invoices/sample-invoice.pdf`, a generated synthetic invoice; regenerate it with
`tools/make_sample_invoice.py` when you need a new shape (multi-page, wrapped
descriptions, a different column order are all missing and would be welcome).

The most valuable contribution is still a harder sample. The current one is
tidy: one header row, no wrapped descriptions, no continuation lines.

## Making a change

1. **Open an issue first** for anything larger than a bug fix, and for any
   change to a layout or template.
2. **A layout or template change needs the `--layout` default updated in the same
   commit** if it renames a bundled file, or `process` will point at a missing
   path. CI checks this.
3. **Keep assumptions in the flags.** `pallet_cap`, `order_cost`, `holding` and
   `cycles` are parameters because the right value is a business decision, not a
   default. If you find yourself hardcoding one, it belongs on the command line.
4. **Print both reconciliation sums.** A single declared total hides per-line
   rounding drift, and that drift is usually what someone is looking for.
5. **New behaviour needs a test.** The first contribution that adds a test suite
   beats every other item on the list.
6. **Match the existing comment discipline.** The comments in `extract.py` exist
   to record *why* something is done a particular non-obvious way — the
   compound-header anchor, the `round(top)` trap, the `tol` semantics. If you
   change one of those behaviours, the comment explaining it has to change too.

## What will be rejected

- A real supplier's name or invoice number anywhere in the tree.
- A hardcoded column offset, header string or layout default in the Python
  source. Layouts are files; that is the design.
- A change that makes the harvest silently tolerant of a bad layout. Failing
  loudly is correct — a wrong price column is worse than an error.
- A dependency added without saying so in the PR. The install path is already the
  hardest part of this project on a slow host, and `install.py` has to know about
  every new package in `VENV_IMPORTS`.
- Scope creep. A bug fix is a bug fix.

## Commit messages

Plain sentences describing what changed and why. The history is squashed to a
single commit on `main`, so individual messages matter mainly for review.

## Licence

Contributions are MIT, matching the repository.
