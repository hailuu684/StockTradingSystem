#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# run_market_research_to_deep_analysis.sh
# End-to-end runner:
#   1) Run market-wide heuristic research pipeline.
#   2) Extract filtered BUY_CANDIDATE/WATCHLIST symbols from output CSVs.
#   3) Run deep LLM analysis for selected symbols using heuristic output, structured BCTC cache, and news cache.
#
# Put this file at the root of your Stocks repo, then run:
#   chmod +x run_market_research_to_deep_analysis.sh
#   ./run_market_research_to_deep_analysis.sh

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

# -----------------------------
# Defaults
# -----------------------------
if [[ -f "$SCRIPT_DIR/full_trade_pipeline_integrate_llm.py" ]]; then
  REPO_ROOT="$SCRIPT_DIR"
elif [[ -d "$SCRIPT_DIR/Stocks" && -f "$SCRIPT_DIR/Stocks/full_trade_pipeline_integrate_llm.py" ]]; then
  REPO_ROOT="$SCRIPT_DIR/Stocks"
else
  REPO_ROOT="$(pwd)"
fi

VENV_PATH="${VENV_PATH:-/home/luutunghai@gmail.com/.venv}"
PYTHON_BIN="python"

STAGE="all"                         # all | market | deep
PIPELINE_CONFIG="./configs/trade_pipeline_integrate_llm.json"
NEWS_CONFIG="./configs/news_deep_symbol.json"
MARKET_SCRIPT="./full_trade_pipeline_integrate_llm.py"
DEEP_SCRIPT="./deep_symbol_llm_analyzer.py"

MARKET_OUTPUTS="./outputs/trade_pipeline_integrate_llm"
DEEP_OUTPUTS="./outputs/deep_symbol_llm"
FINANCIAL_CACHE_PATH="./data/financial_statements"
NEWS_CACHE_PATH="./data/news_cache"
RESULTS_DIR="./results"
LOG_DIR="./logs"

MARKET_AGENT_MODE="heuristic"        # heuristic avoids LLM calls in the wide scan
TOP_N="10"
ACTIONS="BUY_CANDIDATE,WATCHLIST"
MIN_SCORE=""
SYMBOLS=""
SYMBOLS_FILE=""
DRY_RUN_DEEP="0"
FORCE_REFRESH_NEWS="0"
FORCE_REFRESH_FINANCIAL="0"
NEWS_TTL_DAYS="10"
LOG_LEVEL="INFO"
SKIP_NEWS="0"

usage() {
  cat <<'EOF'
Usage:
  ./run_market_research_to_deep_analysis.sh [options]

Main flow:
  all     : run market research scan, extract symbols, then run deep LLM analysis. Default.
  market  : only run market research scan and produce candidate/watchlist outputs.
  deep    : only run deep analysis. Use --symbols or --symbols-file, or existing candidate CSVs.

Options:
  --repo-root PATH             Root folder of Stocks repo. Default: auto-detect/current dir.
  --venv PATH                  Python venv path. Default: /home/luutunghai@gmail.com/.venv
  --stage all|market|deep      Which stage to run. Default: all.
  --config PATH                Full trade pipeline config. Default: ./configs/trade_pipeline_integrate_llm.json
  --news-config PATH           News config for deep analyzer. Default: ./configs/news_deep_symbol.json
  --market-script PATH         Market pipeline script. Default: ./full_trade_pipeline_integrate_llm.py
  --deep-script PATH           Deep analyzer script. Default: ./deep_symbol_llm_analyzer.py

Outputs and cache:
  --market-outputs PATH        Market scan output folder. Default: ./outputs/trade_pipeline_integrate_llm
  --deep-outputs PATH          Deep analysis output folder. Default: ./outputs/deep_symbol_llm
  --financial-cache-path PATH  Structured BCTC markdown/cache folder. Default: ./data/financial_statements
  --news-cache-path PATH       News cache folder. Default: ./data/news_cache
  --results-dir PATH           Report folder. Default: ./results
  --log-dir PATH               Log folder. Default: ./logs

Symbol selection:
  --symbols "TCB,FPT,MBS"      Override auto-extraction; deep analysis runs on these symbols.
  --symbols-file PATH          CSV/TXT with symbol/ticker/code column or one symbol per line.
  --top-n N                    Max symbols to deep analyze after filtering. Default: 10
  --actions CSV                Actions selected from candidate CSVs. Default: BUY_CANDIDATE,WATCHLIST
  --min-score VALUE            Optional minimum score filter. Example: 65 or 0.65

Runtime:
  --market-agent-mode MODE     heuristic|compare|llm|off|on|both. Default: heuristic.
  --force-refresh-news         Re-crawl news even if cache is fresh.
  --force-refresh-financial    Regenerate structured BCTC cache if deep analyzer supports it.
  --news-ttl-days N            News cache TTL in days. Default: 10
  --skip-news                  Pass --no_news if current deep analyzer supports it; otherwise ignored.
  --dry-run-deep               Build deep prompts/data but do not call LLM.
  --log-level LEVEL            INFO|DEBUG|WARNING|ERROR. Default: INFO

Examples:
  # Full run: heuristic market scan -> auto top symbols -> deep LLM analysis
  ./run_market_research_to_deep_analysis.sh

  # Full run with explicit output folders
  ./run_market_research_to_deep_analysis.sh \
    --market-outputs ./outputs/trade_pipeline_market_research \
    --deep-outputs ./outputs/deep_symbol_llm \
    --financial-cache-path ./data/financial_statements \
    --news-cache-path ./data/news_cache \
    --results-dir ./results

  # Run deep analysis only for manually selected symbols
  ./run_market_research_to_deep_analysis.sh \
    --stage deep \
    --symbols TCB,FPT,MBS \
    --market-outputs ./outputs/trade_pipeline_integrate_llm

  # Free-tier friendly: only 5 deep symbols, no LLM in wide market scan
  ./run_market_research_to_deep_analysis.sh --top-n 5 --market-agent-mode heuristic
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) REPO_ROOT="$2"; shift 2 ;;
    --venv) VENV_PATH="$2"; shift 2 ;;
    --stage) STAGE="$2"; shift 2 ;;
    --config) PIPELINE_CONFIG="$2"; shift 2 ;;
    --news-config) NEWS_CONFIG="$2"; shift 2 ;;
    --market-script) MARKET_SCRIPT="$2"; shift 2 ;;
    --deep-script) DEEP_SCRIPT="$2"; shift 2 ;;
    --market-outputs) MARKET_OUTPUTS="$2"; shift 2 ;;
    --deep-outputs) DEEP_OUTPUTS="$2"; shift 2 ;;
    --financial-cache-path|--financial_statement_path) FINANCIAL_CACHE_PATH="$2"; shift 2 ;;
    --news-cache-path) NEWS_CACHE_PATH="$2"; shift 2 ;;
    --results-dir) RESULTS_DIR="$2"; shift 2 ;;
    --log-dir) LOG_DIR="$2"; shift 2 ;;
    --market-agent-mode|--agent-mode) MARKET_AGENT_MODE="$2"; shift 2 ;;
    --symbols) SYMBOLS="$2"; shift 2 ;;
    --symbols-file) SYMBOLS_FILE="$2"; shift 2 ;;
    --top-n) TOP_N="$2"; shift 2 ;;
    --actions) ACTIONS="$2"; shift 2 ;;
    --min-score) MIN_SCORE="$2"; shift 2 ;;
    --news-ttl-days) NEWS_TTL_DAYS="$2"; shift 2 ;;
    --force-refresh-news) FORCE_REFRESH_NEWS="1"; shift ;;
    --force-refresh-financial) FORCE_REFRESH_FINANCIAL="1"; shift ;;
    --skip-news|--no-news|--no_news) SKIP_NEWS="1"; shift ;;
    --dry-run-deep|--dry-run) DRY_RUN_DEEP="1"; shift ;;
    --log-level) LOG_LEVEL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage; exit 2 ;;
  esac
done

if [[ "$STAGE" != "all" && "$STAGE" != "market" && "$STAGE" != "deep" ]]; then
  echo "Invalid --stage: $STAGE. Use all, market, or deep." >&2
  exit 2
fi

cd "$REPO_ROOT"

if [[ -d "$VENV_PATH" && -f "$VENV_PATH/bin/activate" ]]; then
  # shellcheck disable=SC1090
  source "$VENV_PATH/bin/activate"
  PYTHON_BIN="$VENV_PATH/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
fi

mkdir -p "$MARKET_OUTPUTS" "$DEEP_OUTPUTS" "$FINANCIAL_CACHE_PATH" "$NEWS_CACHE_PATH" "$RESULTS_DIR" "$LOG_DIR"
STAMP="$(date '+%Y%m%d_%H%M%S')"
MARKET_RESULTS="${RESULTS_DIR}/reports_market_research_${STAMP}.txt"
DEEP_RESULTS="${RESULTS_DIR}/reports_deep_symbol_analysis_${STAMP}.txt"
LOG_FILE="${LOG_DIR}/run_market_research_to_deep_analysis_${STAMP}.log"
GENERATED_SYMBOLS_FILE="${MARKET_OUTPUTS}/selected_symbols_${STAMP}.txt"

exec > >(tee -a "$LOG_FILE") 2>&1

echo "================================================================================"
echo "Market research -> Deep symbol LLM analysis"
echo "================================================================================"
echo "Repo root              : $(pwd)"
echo "Python                 : $PYTHON_BIN"
echo "Stage                  : $STAGE"
echo "Config                 : $PIPELINE_CONFIG"
echo "Market outputs          : $MARKET_OUTPUTS"
echo "Deep outputs            : $DEEP_OUTPUTS"
echo "Financial cache         : $FINANCIAL_CACHE_PATH"
echo "News cache              : $NEWS_CACHE_PATH"
echo "Market report           : $MARKET_RESULTS"
echo "Deep report             : $DEEP_RESULTS"
echo "Log                     : $LOG_FILE"
echo "================================================================================"

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "Missing $label: $path" >&2
    exit 10
  fi
}

run_cmd() {
  echo
  echo ">> $*"
  "$@"
}

require_file "$PIPELINE_CONFIG" "pipeline config"
require_file "$MARKET_SCRIPT" "market pipeline script"
require_file "$DEEP_SCRIPT" "deep analyzer script"
if [[ -n "$NEWS_CONFIG" && ! -f "$NEWS_CONFIG" ]]; then
  echo "Warning: news config not found, deep analyzer will use its default: $NEWS_CONFIG"
  NEWS_CONFIG=""
fi

if [[ "$STAGE" == "all" || "$STAGE" == "market" ]]; then
  echo
  echo "[1/3] Running market-wide research scan"
  run_cmd "$PYTHON_BIN" "$MARKET_SCRIPT" \
    --mode initial \
    --config "$PIPELINE_CONFIG" \
    --outputs "$MARKET_OUTPUTS" \
    --results "$MARKET_RESULTS" \
    --agent-mode "$MARKET_AGENT_MODE"
else
  echo
  echo "[1/3] Skipping market-wide scan because --stage=$STAGE"
fi

if [[ "$STAGE" == "market" ]]; then
  echo
  echo "Market-only stage completed."
  echo "Candidate CSV : ${MARKET_OUTPUTS}/candidates_ranked_latest.csv"
  echo "Watchlist CSV : ${MARKET_OUTPUTS}/watchlist_latest.csv"
  echo "Report        : $MARKET_RESULTS"
  exit 0
fi

# -----------------------------
# Select symbols for deep analysis
# -----------------------------
echo
if [[ -n "$SYMBOLS" ]]; then
  echo "[2/3] Using user-specified symbols: $SYMBOLS"
  printf '%s\n' "$SYMBOLS" | tr ',; ' '\n' | awk 'NF {print toupper($1)}' | awk '!seen[$0]++' > "$GENERATED_SYMBOLS_FILE"
elif [[ -n "$SYMBOLS_FILE" ]]; then
  echo "[2/3] Using user-specified symbols file: $SYMBOLS_FILE"
  require_file "$SYMBOLS_FILE" "symbols file"
  "$PYTHON_BIN" - "$SYMBOLS_FILE" "$GENERATED_SYMBOLS_FILE" <<'PY'
import sys, re
from pathlib import Path
import pandas as pd
src = Path(sys.argv[1])
out = Path(sys.argv[2])
symbols = []
if src.suffix.lower() == ".csv":
    df = pd.read_csv(src)
    col = None
    for c in ["symbol", "ticker", "code"]:
        if c in df.columns:
            col = c
            break
    if col is None:
        raise SystemExit(f"No symbol/ticker/code column in {src}")
    symbols = df[col].dropna().astype(str).tolist()
else:
    symbols = re.split(r"[,;\s]+", src.read_text(encoding="utf-8", errors="ignore"))
cleaned = []
seen = set()
for s in symbols:
    x = re.sub(r"[^A-Za-z0-9]", "", str(s)).upper()
    if x and x not in seen:
        seen.add(x)
        cleaned.append(x)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(cleaned) + ("\n" if cleaned else ""), encoding="utf-8")
print(f"Selected {len(cleaned)} symbols from {src}: {', '.join(cleaned)}")
PY
else
  echo "[2/3] Extracting top symbols from heuristic market outputs"
  "$PYTHON_BIN" - "$MARKET_OUTPUTS" "$GENERATED_SYMBOLS_FILE" "$TOP_N" "$ACTIONS" "$MIN_SCORE" <<'PY'
import sys
from pathlib import Path
import pandas as pd

out_dir = Path(sys.argv[1])
symbol_file = Path(sys.argv[2])
top_n = int(sys.argv[3])
actions = {a.strip().upper() for a in sys.argv[4].split(",") if a.strip()}
min_score_raw = sys.argv[5].strip()
min_score = float(min_score_raw) if min_score_raw else None

csvs = []
for name in ["watchlist_latest.csv", "candidates_ranked_latest.csv"]:
    p = out_dir / name
    if p.exists():
        try:
            df = pd.read_csv(p)
            if not df.empty:
                df["__source_file"] = name
                csvs.append(df)
        except Exception as exc:
            print(f"Warning: cannot read {p}: {exc}")

if not csvs:
    raise SystemExit(f"No candidate/watchlist CSV found in {out_dir}")

df = pd.concat(csvs, ignore_index=True, sort=False)

def first_existing(cols):
    for c in cols:
        if c in df.columns:
            return c
    return None

symbol_col = first_existing(["symbol", "ticker", "code"])
if not symbol_col:
    raise SystemExit("No symbol/ticker/code column found in candidate CSVs")

action_cols = [c for c in ["action", "final_action", "heuristic_action", "llm_action", "status"] if c in df.columns]
score_cols = [c for c in ["composite_score", "composite", "score", "score_3m", "score_1m", "score_1y", "expected_return", "risk_reward"] if c in df.columns]

for c in score_cols:
    df[c] = pd.to_numeric(df[c], errors="coerce")

if score_cols:
    score_col = score_cols[0]
    df["__score"] = df[score_col]
else:
    score_col = None
    df["__score"] = 0.0

# Clean symbols.
df["__symbol"] = df[symbol_col].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)
df = df[df["__symbol"].astype(bool)].copy()

filtered = df.copy()
if actions and action_cols:
    action_mask = pd.Series(False, index=filtered.index)
    for c in action_cols:
        action_mask |= filtered[c].astype(str).str.upper().isin(actions)
    filtered = filtered[action_mask].copy()

if min_score is not None and score_col is not None:
    filtered = filtered[filtered["__score"].fillna(-10**18) >= min_score].copy()

# Fallback: if no BUY/WATCH symbols, use top score from all candidates.
if filtered.empty:
    print("No symbols matched requested actions/min-score. Falling back to top symbols by score.")
    filtered = df.copy()

filtered = filtered.sort_values("__score", ascending=False, na_position="last")
filtered = filtered.drop_duplicates("__symbol", keep="first").head(top_n)
symbols = filtered["__symbol"].tolist()

symbol_file.parent.mkdir(parents=True, exist_ok=True)
symbol_file.write_text("\n".join(symbols) + ("\n" if symbols else ""), encoding="utf-8")

print(f"Selected {len(symbols)} symbols for deep analysis: {', '.join(symbols)}")
cols = ["__symbol"] + action_cols[:2] + ([score_col] if score_col else []) + ["__source_file"]
cols = [c for c in cols if c in filtered.columns]
if cols:
    print(filtered[cols].to_string(index=False))
PY
fi

if [[ ! -s "$GENERATED_SYMBOLS_FILE" ]]; then
  echo "No symbols selected for deep analysis. Stop." >&2
  exit 20
fi

SELECTED_SYMBOLS="$(paste -sd, "$GENERATED_SYMBOLS_FILE")"
echo "Selected symbols file : $GENERATED_SYMBOLS_FILE"
echo "Selected symbols      : $SELECTED_SYMBOLS"

# -----------------------------
# Run deep symbol analysis
# -----------------------------
echo
echo "[3/3] Running deep symbol LLM analysis"

DEEP_HELP="$($PYTHON_BIN "$DEEP_SCRIPT" --help 2>&1 || true)"
DEEP_ARGS=(
  "$PYTHON_BIN" "$DEEP_SCRIPT"
  --symbols "$SELECTED_SYMBOLS"
  --heuristic_outputs "$MARKET_OUTPUTS"
  --config "$PIPELINE_CONFIG"
  --repo_root "."
  --news_cache_path "$NEWS_CACHE_PATH"
  --news_ttl_days "$NEWS_TTL_DAYS"
  --outputs "$DEEP_OUTPUTS"
  --results "$DEEP_RESULTS"
  --log_level "$LOG_LEVEL"
)

if grep -q -- "--financial_cache_path" <<< "$DEEP_HELP"; then
  DEEP_ARGS+=(--financial_cache_path "$FINANCIAL_CACHE_PATH")
else
  # Backward compatibility with current deep_symbol_llm_analyzer.py in your repo.
  DEEP_ARGS+=(--financial_statement_path "$FINANCIAL_CACHE_PATH")
fi

if [[ -n "$NEWS_CONFIG" ]]; then
  DEEP_ARGS+=(--news_config "$NEWS_CONFIG")
fi
if [[ "$FORCE_REFRESH_NEWS" == "1" ]]; then
  DEEP_ARGS+=(--force_refresh_news)
fi
if [[ "$FORCE_REFRESH_FINANCIAL" == "1" ]]; then
  if grep -q -- "--force_refresh_financial" <<< "$DEEP_HELP"; then
    DEEP_ARGS+=(--force_refresh_financial)
  else
    echo "Warning: deep analyzer does not support --force_refresh_financial; ignored."
  fi
fi
if [[ "$SKIP_NEWS" == "1" ]]; then
  if grep -q -- "--no_news" <<< "$DEEP_HELP"; then
    DEEP_ARGS+=(--no_news)
  elif grep -q -- "--skip_news" <<< "$DEEP_HELP"; then
    DEEP_ARGS+=(--skip_news)
  else
    echo "Warning: deep analyzer does not support --no_news/--skip_news; ignored."
  fi
fi
if [[ "$DRY_RUN_DEEP" == "1" ]]; then
  DEEP_ARGS+=(--dry_run)
fi

if [[ "$DRY_RUN_DEEP" != "1" && -z "${GEMINI_API_KEY:-}" && -z "${TRADING_LLM_API_KEY:-}" ]]; then
  echo "Warning: no GEMINI_API_KEY/TRADING_LLM_API_KEY found in environment. Deep LLM call may fail depending on your config."
fi

run_cmd "${DEEP_ARGS[@]}"

echo
echo "================================================================================"
echo "DONE"
echo "================================================================================"
echo "Market report         : $MARKET_RESULTS"
echo "Deep report           : $DEEP_RESULTS"
echo "Selected symbols file : $GENERATED_SYMBOLS_FILE"
echo "Market outputs        : $MARKET_OUTPUTS"
echo "Deep outputs          : $DEEP_OUTPUTS"
echo "Financial cache       : $FINANCIAL_CACHE_PATH"
echo "News cache            : $NEWS_CACHE_PATH"
echo "Log                   : $LOG_FILE"
echo "================================================================================"
