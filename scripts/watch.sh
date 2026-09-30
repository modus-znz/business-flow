#!/bin/sh
# bizflow hot folder: drop PDFs into IN, structured output lands in OUT.
# Uses entr in oneshot mode. Processed PDFs move to OUT/processed.
IN="${1:-$HOME/bizflow-inbox}"
OUT="${2:-$HOME/bizflow-out}"
export IN OUT
mkdir -p "$IN" "$OUT/processed"
echo "watching $IN -> $OUT (ctrl-c to stop)"
while true; do
    ls "$IN"/*.pdf 2>/dev/null | entr -d -p sh -c '
        for f in "$IN"/*.pdf; do
            [ -e "$f" ] || continue
            bizflow process "$f" --out "$OUT" && mv "$f" "$OUT/processed/"
        done'
done
