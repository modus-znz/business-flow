# syntax=docker/dockerfile:1
#
# A container for the bizflow CLI. This is not a demo: there is no server, no
# port, and nothing to curl. It exists because the PDF path needs a real system
# toolchain (ocrmypdf, tesseract, poppler) and installing that on a host is
# exactly the friction a container removes.
#
#   docker build -t bizflow .
#   docker run --rm -v "$PWD:/data" -v "$PWD/out:/out" bizflow \
#       process /data/invoice.pdf --out /out
FROM python:3.12-slim

# The OCR and PDF layer. tesseract-ocr-ita matches the bundled sample layout;
# add -eng and -swa if you process documents in those languages.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ocrmypdf \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies before the source, so editing bizflow/ does not bust the layer
# cache. Copied from pyproject.toml by hand to keep the two in step: the list
# below is exactly the [project.dependencies] array.
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir \
        pdfplumber invoice2data duckdb "markitdown[pdf]" stockpyl ortools pyyaml

COPY bizflow/ bizflow/
COPY templates/ templates/
RUN pip install --no-cache-dir --no-deps -e .

# There is no configuration environment variable to set, by design. Output
# paths and business assumptions (--pallet-cap, --order-cost, --holding) are
# command-line arguments, so the same image runs any workflow without rebuilds.
#
# HOME is redirected to a writable tmp so invoice2data's template lookup
# (~/.local/share/invoice2data-templates) does not fail as root in a throwaway
# layer. The bundled sample template is inside the package and needs no mount.
ENV HOME=/tmp

# A CLI has no port to expose and no long-running process to keep alive, so
# there is no HEALTHCHECK: the meaningful check is that the CLI starts, which
# is what `docker run --rm bizflow --help` does.
ENTRYPOINT ["bizflow"]
CMD ["--help"]
