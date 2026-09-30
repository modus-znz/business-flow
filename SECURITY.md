# Security policy

## Reporting a vulnerability

Open a **private** security advisory on this repository rather than a public
issue. Include the input that triggers it and what you expected instead. If you
would rather not use GitHub's advisory flow, open an issue that says only "security
report, please open a private channel" and nothing technical.

There is no guaranteed response time — this is a single-maintainer project. What
is guaranteed is that a valid report is fixed or explained.

## Threat model

bizflow is a **command-line tool that reads local files**. That is the whole
attack surface, and it is worth stating precisely because the honest answer is
unusually small:

| Property | Reality |
|---|---|
| Network calls at runtime | **None.** No telemetry, no update check, no phone-home. |
| Credentials | **None exist.** There is no config file, no environment variable, no token. |
| Authentication | Not applicable. There is no server, no port, no listener. |
| Privileges | Runs as the invoking user. It needs write access to `--out` and nothing else. |
| Untrusted input | Yes — the PDF you point it at, and any layout YAML you pass with `--layout`. |
| Data it produces | Your supplier's commercial data, written as CSV and Parquet. |

The two real risks are the last two rows.

### 1. A malicious or crafted PDF

The PDF is parsed by `pdfplumber`, `pypdf` (via `invoice2data`) and
`ocrmypdf`/`tesseract`. These are C and C++ codebases with a long history of
parsing bugs. Treat any PDF from an untrusted source as untrusted input, and run
the tool inside a container or a throwaway VM if the source is genuinely
hostile.

pdfplumber's word extraction also builds an in-memory representation of every
page, so a PDF with an extreme page count or a pathological word count can
consume a lot of RAM. There is no page limit in this tool.

### 2. A layout YAML you did not write

`--layout` takes a path to a YAML file and reads `code_regex` as a regular
expression, which is compiled and matched against every row token. A pathological
pattern — nested quantifiers over a long string — is a CPU denial of service on
your own machine. Only load layouts you wrote or trust.

## Data handling

`out/*.csv` and `out/*.parquet` contain whatever was on the invoice: article
codes, quantities, unit prices and totals. Depending on the supplier and the
jurisdiction that can be commercially sensitive.

- `.gitignore` covers the default `bizflow-out/` directory.
- **A CSV written anywhere else inside a git working tree will be committed by
  `git add .`.** Write real data outside the repository.
- Nothing is uploaded, because nothing uploads. Deleting the output files
  deletes the data.
- The repository itself contains no real invoice, no supplier name and no real
  figures. The bundled layout and template are synthetic, and CI fails the build
  if the bundled template stops naming the synthetic sample.

## Explicitly not a service

Do not wrap this in a web service, expose it to an untrusted network, or point
it at a directory another user can write to. It was designed to be run by the
person who owns the invoices, on their own machine, and the `analyze` module
builds SQL by interpolating the CSV path — fine for a local tool invoked by the
file's owner, not safe if that path ever comes from somewhere else.

## Supported versions

| Version | Supported |
|---|---|
| `main` | yes |
| anything older | no |

No LTS track. Fixes land on `main`.
