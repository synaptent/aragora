#!/usr/bin/env bash
# EU AI Act Compliance Demo
#
# Shows the full Aragora compliance workflow end-to-end in under 2 minutes:
#
#   1. Classify a use case by EU AI Act risk tier
#   2. Export a compliance bundle with per-article artifacts
#   3. Review the machine-readable bundle and human summary
#
# No API keys or running server required. Uses synthetic demo data.
#
# Usage:
#   ./scripts/demo_compliance.sh              # Full demo
#   ./scripts/demo_compliance.sh --classify   # Classification only
#   ./scripts/demo_compliance.sh --export     # Bundle export only
#   ./scripts/demo_compliance.sh --clean      # Remove generated output
#
# Output: ./demo-compliance-pack/
#   README.md                  Manifest with compliance score
#   bundle.json                Full machine-readable bundle
#   receipt.md                 Art. 9 -- Risk assessment
#   audit_trail.md             Art. 12 -- Event log / provenance
#   transparency_report.md     Art. 13 -- Agent participation & reasoning
#   human_oversight.md         Art. 14 -- Override capability & voting record
#   accuracy_report.md         Art. 15 -- Confidence & robustness metrics

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTPUT_DIR="${DEMO_OUTPUT_DIR:-$ROOT/demo-compliance-pack}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BOLD="\033[1m"
GREEN="\033[32m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"

step() { printf "\n${BOLD}%s${RESET}\n%s\n" "$1" "$(printf '=%.0s' $(seq 1 ${#1}))"; }
log()  { printf "${CYAN}[compliance-demo]${RESET} %s\n" "$*"; }
ok()   { printf "${GREEN}[compliance-demo]${RESET} %s\n" "$*"; }

require_python() {
    if ! command -v python3 >/dev/null 2>&1; then
        printf "Error: python3 not found. Install Python 3.11+.\n" >&2
        exit 1
    fi
    if ! python3 -c "import aragora" 2>/dev/null; then
        printf "Error: aragora not installed. Run: pip install -e .\n" >&2
        exit 1
    fi
}

clean() {
    if [[ -d "$OUTPUT_DIR" ]]; then
        rm -rf "$OUTPUT_DIR"
        ok "Removed $OUTPUT_DIR"
    else
        log "Nothing to clean."
    fi
    exit 0
}

# ---------------------------------------------------------------------------
# Parse args
# ---------------------------------------------------------------------------

DO_CLASSIFY=true
DO_EXPORT=true

for arg in "$@"; do
    case "$arg" in
        --classify) DO_CLASSIFY=true;  DO_EXPORT=false ;;
        --export)   DO_CLASSIFY=false; DO_EXPORT=true  ;;
        --clean)    clean ;;
        --help|-h)
            sed -n '2,22p' "$0" | sed 's/^# //'
            exit 0
            ;;
        *)
            printf "Unknown argument: %s\n" "$arg" >&2
            exit 1
            ;;
    esac
done

require_python

# ---------------------------------------------------------------------------
# Step 1: Classify a use case
# ---------------------------------------------------------------------------

if $DO_CLASSIFY; then
    step "Step 1 -- Classify your AI use case"
    log "Running: aragora compliance classify"
    echo ""

    DESCRIPTION="AI-powered recruitment and CV screening system for automated candidate filtering in hiring decisions"
    log "Use case: \"$DESCRIPTION\""
    echo ""

    python3 -m aragora.cli.main compliance classify "$DESCRIPTION"

    echo ""
    log "The classifier maps free-text to Annex III categories and lists all obligations."
    log "Unacceptable-risk use cases (Art. 5) are flagged and cannot be deployed in the EU."
fi

# ---------------------------------------------------------------------------
# Step 2: Export compliance bundle
# ---------------------------------------------------------------------------

if $DO_EXPORT; then
    step "Step 2 -- Export EU AI Act compliance bundle"
    log "Running: aragora compliance export --demo"
    echo ""

    python3 -m aragora.cli.main compliance export \
        --demo \
        --format markdown \
        --output-dir "$OUTPUT_DIR"

    echo ""
    ok "Bundle written to: $OUTPUT_DIR/"
    echo ""

    step "Step 3 -- Review the bundle"
    log "Files generated:"
    for f in README.md bundle.json receipt.md audit_trail.md transparency_report.md human_oversight.md accuracy_report.md; do
        if [[ -f "$OUTPUT_DIR/$f" ]]; then
            size=$(wc -c < "$OUTPUT_DIR/$f" | tr -d ' ')
            printf "  %-35s  (%s bytes)\n" "$f" "$size"
        fi
    done

    echo ""
    log "Quick look at the manifest (README.md):"
    echo ""
    /usr/bin/head -60 "$OUTPUT_DIR/README.md" 2>/dev/null || head -60 "$OUTPUT_DIR/README.md"

    echo ""
    step "Next steps"
    printf "  1. Replace demo data with a real receipt:\n"
    printf "       aragora compliance export --receipt-file /path/to/receipt.json \\\\\n"
    printf "           --output-dir ./compliance-pack\n\n"
    printf "  2. Or generate the full artifact bundle (Art. 12/13/14 JSON artifacts):\n"
    printf "       aragora compliance eu-ai-act generate --output ./compliance-bundle/\n\n"
    printf "  3. Integrate into CI to generate compliance artifacts on every debate:\n"
    printf "       aragora compliance export --debate-id <id> --output-dir ./ci-compliance/\n\n"
    printf "  4. Review the full guide:\n"
    printf "       docs/compliance/EU_AI_ACT_GUIDE.md\n\n"

    ok "Demo complete. August 2, 2026 enforcement deadline -- get compliant today."
fi
