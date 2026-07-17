# Vietnam Stock Research & LLM Trade Analyzer

A production-oriented Python research pipeline for the Vietnamese equity market. The project combines structured market data from `vnstock_data`, news data from `vnstock_news`, deterministic quant/technical screening, structured financial-statement readthroughs, and an optional LLM trade-analysis layer.

The intended workflow is simple:

```text
Market-wide heuristic scan
    -> rank and filter bank / technology symbols
    -> select BUY_CANDIDATE / WATCHLIST symbols
    -> run deep symbol analysis only on selected names
    -> cache structured financial statements and news
    -> generate prompts, Markdown reports, JSON decisions and text summaries
```

> **Disclaimer**: This project is a research and decision-support tool only. It does not provide investment advice, guarantee returns, or replace independent due diligence. You are responsible for all trading and investment decisions.

---

## Table of Contents

- [Key Features](#key-features)
- [Architecture](#architecture)
- [Repository Layout](#repository-layout)
- [Data Sources](#data-sources)
- [Installation](#installation)
- [Environment Variables](#environment-variables)
- [Quick Start](#quick-start)
- [End-to-End Runner](#end-to-end-runner)
- [Market-Wide Research Pipeline](#market-wide-research-pipeline)
- [Deep Symbol LLM Analyzer](#deep-symbol-llm-analyzer)
- [Financial Statement Processing](#financial-statement-processing)
- [News Processing](#news-processing)
- [LLM Integration](#llm-integration)
- [Configuration Reference](#configuration-reference)
- [Outputs](#outputs)
- [Recommended Operating Workflow](#recommended-operating-workflow)
- [Troubleshooting](#troubleshooting)
- [Security and Git Hygiene](#security-and-git-hygiene)
- [Limitations](#limitations)
- [Roadmap](#roadmap)

---

## Key Features

- **Market-wide research scan** across the configured universe.
- **Sector-focused screening** for Vietnamese bank and technology stocks by default.
- **Heuristic ranking engine** for trend, momentum, flow, valuation, liquidity, and risk/reward.
- **Morgan Stanley-style research framework**: bull/base/bear cases, probability-style reasoning, expected return, risk/reward, entry zone, stop loss, and position sizing.
- **Structured BCTC / financial-statement Markdown** generated from `Fundamental().equity(symbol)` tables.
- **Deep LLM analysis** only after heuristic filtering, reducing token usage and API calls.
- **News cache** with TTL so repeated analysis does not re-crawl news unnecessarily.
- **Prompt template** designed for institutional-style trade analysis.
- **Config-driven design**: most thresholds, paths, LLM settings, news crawler settings, and risk parameters are JSON-configurable.
- **GitHub-ready output artifacts**: reports, prompts, JSON decisions, Markdown analysis, CSV rankings, cache folders, and logs.
- **Telegram-ready extension point**: the JSON/Markdown output can be consumed by a notifier module later.

---

## Architecture

```text
+----------------------+       +----------------------+       +----------------------+
|  Vnstock Market      |       |  Vnstock Insights    |       |  Vnstock Analytics   |
|  OHLCV, flow, quote  |       |  screener, ranking   |       |  VNINDEX PE/PB       |
+----------+-----------+       +----------+-----------+       +----------+-----------+
           |                              |                              |
           +------------------------------+------------------------------+
                                          |
                                          v
                              +------------------------+
                              | Heuristic Market Scan  |
                              | full_trade_pipeline_*  |
                              +-----------+------------+
                                          |
                       candidates_ranked_latest.csv
                       watchlist_latest.csv
                                          |
                                          v
+----------------------+       +------------------------+       +----------------------+
| Fundamental Layer    |       | News Layer             |       | Optional User Inputs |
| BCTC structured MD   |       | cached symbol news     |       | insights / RAG       |
+----------+-----------+       +-----------+------------+       +----------+-----------+
           |                               |                               |
           +-------------------------------+-------------------------------+
                                           |
                                           v
                              +------------------------+
                              | Deep Symbol Analyzer   |
                              | deep_symbol_llm_*.py   |
                              +-----------+------------+
                                          |
           +------------------------------+------------------------------+
           |                              |                              |
           v                              v                              v
     Markdown reports               JSON decisions                 TXT summaries
```

The wide scan should normally run without LLM calls. The LLM is reserved for a small set of shortlisted symbols to save API quota and to keep the final reasoning focused.

---

## Repository Layout

Current working structure:

```text
Stocks/
├── configs/
│   ├── deep_symbol_trade_prompt_template.md
│   ├── llm.json
│   ├── market_config.json
│   ├── market_config.py
│   ├── news.json
│   ├── news_deep_symbol.json
│   ├── trade_pipeline_integrate_llm.json
│   └── trade_pipeline_integrate_llm_budget.json
│
├── scripts/
│   ├── get_fundamental_analysis_layer.py
│   ├── get_llm_layer.py
│   ├── get_llm_layer_budget.py
│   ├── get_market.py
│   ├── get_news_layer.py
│   └── market_schema.py
│
├── full_trade_pipeline_integrate_llm.py
├── full_trade_pipeline_integrate_llm_budget.py
├── deep_symbol_llm_analyzer.py
├── get_information.py
└── run_market_research_to_deep_analysis.sh
```

Generated runtime folders are usually:

```text
Stocks/
├── data/
│   ├── financial_statements/
│   └── news_cache/
├── outputs/
│   ├── trade_pipeline_integrate_llm/
│   └── deep_symbol_llm/
├── results/
└── logs/
```

---

## Data Sources

### 1. Market Data

The Market Layer supplies real-time and historical trading data such as OHLCV, quotes, order book snapshots, foreign flow, proprietary flow, session statistics and market-wide quotes.

Main syntax used by this project:

```python
from vnstock_data import Market

market = Market()
equity = market.equity("TCB")
idx = market.index("VNINDEX")

ohlcv = equity.ohlcv(length="1Y")
foreign = equity.foreign_flow()
proprietary = equity.proprietary_flow()
summary = equity.summary()
quote_many = market.quote(["TCB", "FPT", "MBS"])
index_ohlcv = idx.ohlcv(length="1Y")
```

### 2. Insights Data

The pipeline uses the Insights Layer for screener and market-ranking style data.

Correct screener syntax:

```python
from vnstock_data import Insights

ins = Insights()
filters = [
    {"name": "exchange", "conditionOptions": [{"type": "value", "value": "hsx"}]},
    {"name": "ttmRoe", "conditionOptions": [{"type": "range", "from": 15, "to": 100}]},
]

df = ins.screener.filter(filters=filters, limit=100)
```

Do **not** use deprecated or unsupported domains such as `Insights.sector("technology")` unless your local package explicitly exposes them.

### 3. Fundamental Data

The project reads financial statements from structured `vnstock_data` tables, not from OCR by default.

Main syntax:

```python
from vnstock_data import Fundamental

fun = Fundamental()
eq = fun.equity("TCB")

filings = eq.filing(doc_type="financial_report")  # or eq.filing()
income = eq.income_statement(period="quarter")
balance = eq.balance_sheet(period="quarter")
cash_flow = eq.cash_flow(period="quarter")
ratio = eq.ratio(period="quarter")
notes = eq.note(period="quarter", lang="vi")
health = eq.financial_health(scorecard="auto", limit=4)
```

The fundamental schema can be wide, sector-specific, and sparse. For example, securities-company financial statements may include many FVTPL, AFS, HTM, brokerage, margin-lending and customer-cash fields. The processing layer must treat `None` / empty / not-applicable values carefully and must not assume every line item applies to every sector.

### 4. News Data

The project uses `vnstock_news` for article crawling. Different crawlers return different shapes:

```text
Crawler.get_articles_from_feed()       -> List[Dict]
Crawler.get_articles()                 -> List[Dict]
BatchCrawler.fetch_articles()          -> pandas.DataFrame
AsyncBatchCrawler.fetch_articles_async -> pandas.DataFrame
```

For finance sites such as CafeF, prefer `BatchCrawler` with a sitemap URL when RSS is unavailable:

```python
from vnstock_news import BatchCrawler

crawler = BatchCrawler(site_name="cafef", request_delay=1.5, output_path="./data/news_cache/_tmp")
articles = crawler.fetch_articles(
    limit=100,
    sitemap_url="https://cafef.vn/latest-news-sitemap.xml",
)
```

---

## Installation

### 0. You need to subscribe vnstock (paid package)
This repo is built based on paid vnstock package (syntax is different compared to free-tier one)

### 1. Clone the repository

```bash
git clone <your-repo-url> Stocks
cd Stocks
```

### 2. Create and activate a Python environment

Python 3.10+ is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

### 3. Install common Python dependencies

```bash
pip install pandas numpy requests python-dateutil google-genai
```

Optional packages depending on your branch:

```bash
pip install pypdf beautifulsoup4 feedparser aiohttp
```

### 4. Install / activate Vnstock packages

This project expects the Vnstock sponsor/member ecosystem to be installed in your environment, especially:

```text
vnstock_data
vnstock_news
```

Follow your Vnstock onboarding/installer instructions. Do **not** commit installer files, API keys or account tokens to GitHub.

---

## Environment Variables

Set your LLM API key through environment variables, not in committed JSON files.

For Gemini:

```bash
export GEMINI_API_KEY="your_key_here"
```

Generic fallback used by some configs:

```bash
export TRADING_LLM_API_KEY="your_key_here"
```

Recommended local `.env` style file, not committed:

```bash
GEMINI_API_KEY=your_key_here
TRADING_LLM_API_KEY=your_key_here
```

---

## Quick Start

### Option A: Run the end-to-end shell script

```bash
chmod +x ./run_market_research_to_deep_analysis.sh

./run_market_research_to_deep_analysis.sh \
  --market-outputs ./outputs/trade_pipeline_integrate_llm \
  --deep-outputs ./outputs/deep_symbol_llm \
  --financial-cache-path ./data/financial_statements \
  --news-cache-path ./data/news_cache \
  --results-dir ./results
```

This performs:

```text
1. Market-wide heuristic scan
2. Auto-extract top BUY_CANDIDATE / WATCHLIST symbols
3. Deep LLM analysis for selected symbols
4. Save reports, logs, Markdown, JSON decisions and cache artifacts
```

### Option B: Run market research only

```bash
python full_trade_pipeline_integrate_llm.py \
  --mode initial \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --outputs ./outputs/trade_pipeline_integrate_llm \
  --results ./results/reports_trade_pipeline_integrate_llm_{date}.txt \
  --agent-mode heuristic
```

Use `--agent-mode heuristic` for the wide scan to avoid unnecessary LLM calls.

### Option C: Run deep analysis only for selected symbols

The current deep analyzer CLI uses `--financial_statement_path` as the cache root for financial-statement artifacts. Treat it as the structured financial cache path.

```bash
python deep_symbol_llm_analyzer.py \
  --symbols TCB,FPT,MBS \
  --heuristic_outputs ./outputs/trade_pipeline_integrate_llm \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --financial_statement_path ./data/financial_statements \
  --news_cache_path ./data/news_cache \
  --news_config ./configs/news_deep_symbol.json \
  --outputs ./outputs/deep_symbol_llm \
  --results ./results/deep_symbol_llm_report_{date}.txt
```

Dry-run mode prepares data and prompts without calling the LLM:

```bash
python deep_symbol_llm_analyzer.py \
  --symbols TCB,FPT \
  --heuristic_outputs ./outputs/trade_pipeline_integrate_llm \
  --financial_statement_path ./data/financial_statements \
  --outputs ./outputs/deep_symbol_llm \
  --results ./results/deep_symbol_llm_report_{date}.txt \
  --dry_run
```

---

## End-to-End Runner

The shell runner is designed for the normal research workflow.

```bash
./run_market_research_to_deep_analysis.sh [options]
```

Important options:

| Option | Description |
|---|---|
| `--stage all|market|deep` | Run the whole flow, market-only, or deep-only. |
| `--config PATH` | Main trade-pipeline config. |
| `--news-config PATH` | News config for deep analysis. |
| `--market-outputs PATH` | Output folder for market-wide scan. |
| `--deep-outputs PATH` | Output folder for deep analysis. |
| `--financial-cache-path PATH` | Financial-statement cache root used by the shell script. |
| `--news-cache-path PATH` | News cache root. |
| `--results-dir PATH` | Report directory. |
| `--symbols TCB,FPT` | Override auto-selected symbols. |
| `--symbols-file PATH` | Read symbols from CSV/TXT. |
| `--top-n N` | Maximum number of symbols for deep analysis. |
| `--actions CSV` | Actions selected from candidate CSVs; default `BUY_CANDIDATE,WATCHLIST`. |
| `--market-agent-mode heuristic` | Recommended for wide scan. |
| `--dry-run-deep` | Build deep prompts but do not call LLM. |
| `--force-refresh-news` | Ignore fresh news cache and crawl again. |

Examples:

```bash
# Full run with default settings
./run_market_research_to_deep_analysis.sh

# Free-tier friendly: only five deep symbols, no LLM in wide scan
./run_market_research_to_deep_analysis.sh \
  --top-n 5 \
  --market-agent-mode heuristic

# Deep analysis only for manual symbols
./run_market_research_to_deep_analysis.sh \
  --stage deep \
  --symbols TCB,FPT,MBS \
  --market-outputs ./outputs/trade_pipeline_integrate_llm
```

---

## Market-Wide Research Pipeline

Main file:

```text
full_trade_pipeline_integrate_llm.py
```

Main modes:

```bash
--mode initial
--mode daily_news
```

For the current workflow, use `initial` mode for broad market research.

```bash
python full_trade_pipeline_integrate_llm.py \
  --mode initial \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --outputs ./outputs/trade_pipeline_integrate_llm \
  --results ./results/reports_trade_pipeline_integrate_llm_{date}.txt \
  --agent-mode heuristic
```

Common agent modes:

| Mode | Meaning |
|---|---|
| `heuristic` / `off` | No LLM call; deterministic scoring only. Recommended for wide scans. |
| `llm` / `on` | Use LLM as final decision engine. Use only for small symbol sets. |
| `compare` / `both` | Save both heuristic and LLM decisions for comparison. |

The market scan focuses on configured sectors:

```json
"target_sectors": ["bank", "technology"]
```

The default config also includes fallback symbol lists for banks and technology names in case screener sector tagging is incomplete.

---

## Deep Symbol LLM Analyzer

Main file:

```text
deep_symbol_llm_analyzer.py
```

Use this after the market-wide scan has generated:

```text
outputs/trade_pipeline_integrate_llm/candidates_ranked_latest.csv
outputs/trade_pipeline_integrate_llm/watchlist_latest.csv
outputs/trade_pipeline_integrate_llm/markdown/*.md
outputs/trade_pipeline_integrate_llm/decisions/*.json
```

The deep analyzer builds a compact research pack:

```text
previous heuristic context
+ structured financial statement markdown
+ symbol-related news
+ optional user insights
+ optional RAG / playbook context
+ standardized institutional prompt
```

Then it calls:

```python
from scripts.get_llm_layer import ask_llm
```

The LLM response is normalized to a structured JSON action.

### Input symbol selection

Direct symbols:

```bash
--symbols TCB,FPT,MBS
```

File-based symbols:

```bash
--symbols_file ./outputs/trade_pipeline_integrate_llm/watchlist_latest.csv
```

The file parser accepts a CSV column named `symbol`, `ticker`, or `code`; for TXT files, use one symbol per line or comma-separated values.

---

## Financial Statement Processing

There are two financial-statement utilities in this repository:

1. The deep analyzer's built-in structured financial export.
2. `scripts/get_fundamental_analysis_layer.py`, a more detailed standalone financial-report generator.

The recommended input source is structured `vnstock_data` Fundamental data, not OCR.

### Standalone financial report generation

```bash
python scripts/get_fundamental_analysis_layer.py \
  --symbol TCB \
  --output_root ./data/financial_statements
```

Optional PDF archive mode, if your branch supports it:

```bash
python scripts/get_fundamental_analysis_layer.py \
  --symbol TCB \
  --output_root ./data/financial_statements \
  --download_pdf
```

The LLM should consume the structured Markdown report, not a raw PDF.

### Cache behavior

Financial statement artifacts are stored by quarter:

```text
data/financial_statements/
├── quarter_1/
│   ├── TCB_<company>_2026_Q1.md
│   └── TCB_<company>_2026_Q1_*.csv
├── quarter_2/
│   ├── TCB_<company>_2026_Q2.md
│   └── TCB_<company>_2026_Q2_*.csv
└── ...
```

If a structured Markdown file for the latest quarter already exists, the analyzer can reuse it. When a new quarter appears, it should add a new `quarter_N` folder rather than deleting the previous quarter.

### Null and not-applicable handling

Fundamental data is sector-dependent. Do not fill missing financial metrics with zero unless the metric explicitly represents a volume or count. For financial line items:

- all-null columns should be recorded as missing or not applicable,
- latest-quarter nulls should be reported as data gaps,
- ratios and valuation fields should not be imputed with zero,
- duplicate columns must be made unique before row-wise processing,
- pandas `Series` values should be scalarized before formatting.

---

## News Processing

Main files:

```text
scripts/get_news_layer.py
configs/news.json
configs/news_deep_symbol.json
```

Use `news_deep_symbol.json` for deep analysis. It is configured to prefer batch/sitemap collection for finance sites such as CafeF, avoiding errors like:

```text
No RSS URLs configured
```

News cache layout:

```text
data/news_cache/
├── raw/
│   └── raw_news_*.csv
└── symbols/
    ├── TCB_news_YYYYMMDD.csv
    ├── FPT_news_YYYYMMDD.csv
    └── MBS_news_YYYYMMDD.csv
```

By default, cached news can be reused for 10 days:

```bash
--news_ttl_days 10
```

Force a fresh crawl:

```bash
--force_refresh_news
```

Recommended crawler behavior:

| Use Case | Recommended Mode |
|---|---|
| Fast intraday monitoring | RSS where available |
| Deep symbol analysis | BatchCrawler + sitemap |
| Large NLP corpus | AsyncBatchCrawler or EnhancedNewsCrawler |
| Production / retry / validation | EnhancedNewsCrawler when available |

---

## LLM Integration

Main LLM wrapper:

```text
scripts/get_llm_layer.py
```

Default config:

```text
configs/llm.json
```

Prompt template:

```text
configs/deep_symbol_trade_prompt_template.md
```

### Recommended LLM usage

Use LLM only after the heuristic filter has reduced the universe.

```text
Bad:  1,600 symbols -> 1,600 LLM calls
Good: 1,600 symbols -> heuristic shortlist -> 5-10 LLM calls
```

The final prompt asks the LLM to return JSON only, with fields such as:

```json
{
  "final_action": "BUY_CANDIDATE | WATCHLIST | HOLD_MONITOR | REDUCE_OR_EXIT | IGNORE",
  "confidence": 0.0,
  "investment_horizon": "3M | 1Y | BOTH",
  "thesis_summary": "...",
  "financial_statement_readthrough": {},
  "technical_readthrough": {},
  "news_readthrough": {},
  "buy_plan": {},
  "sell_or_reduce_rules": [],
  "what_to_monitor_next_10_days": [],
  "data_gaps": []
}
```

### Free-tier friendly settings

For Gemini free tier or rate-limited models:

- run the wide scan with `--agent-mode heuristic`,
- use `--top-n 3` to `--top-n 10` in the shell runner,
- use `--dry_run` first to inspect prompts,
- lower `max_output_tokens` in `configs/llm.json`,
- add delay between deep symbol calls if needed.

---

## Configuration Reference

### `configs/trade_pipeline_integrate_llm.json`

Controls the market-wide research scan.

Important sections:

| Section | Purpose |
|---|---|
| `paths` | Output folders and optional RAG/user-insight paths. |
| `reports` | Report path and console printing. |
| `universe` | Target sectors, exchanges, liquidity filters, fallback symbols. |
| `market` | Market data collection windows and methods. |
| `insights` | Screener/ranking/sentiment settings. |
| `fundamental` | Fundamental collection settings. |
| `analytics` | VNINDEX valuation settings. |
| `technical_strategy` | RSI, ATR, MA windows and breakout settings. |
| `ms_style_scenario` | Bull/base/bear scenario thresholds. |
| `risk` | Portfolio value, risk per trade, max position and stop logic. |
| `agent` / `llm_config` | LLM provider and API configuration. |

### `configs/news_deep_symbol.json`

Controls the deep-analysis news crawler.

Important sections:

| Section | Purpose |
|---|---|
| `run_profile` | Usually `ml` for deep symbol analysis. |
| `run_mode` | Usually `batch`. |
| `target_sites` | News sites to crawl. |
| `site_registry` | Per-site RSS/sitemap settings. |
| `network_settings` | Request delay, retries, concurrency, 403/429 handling. |
| `preprocessing` | Normalize, clean HTML, deduplicate, parse times, build text column. |
| `output` | Where crawler outputs are saved. |

### `configs/deep_symbol_trade_prompt_template.md`

Controls the institutional-style prompt sent to the LLM. Keep it strict: JSON-only output, no markdown, no unsupported claims, no fabricated figures.

---

## Outputs

### Market-wide scan outputs

```text
outputs/trade_pipeline_integrate_llm/
├── candidates_ranked_latest.csv
├── watchlist_latest.csv
├── markdown/
│   └── <SYMBOL>_research_<timestamp>.md
├── decisions/
│   └── <SYMBOL>_decision_<timestamp>.json
├── prompts/
│   └── <SYMBOL>_prompt_<timestamp>.md
└── initial_manifest_<timestamp>.json
```

### Deep analysis outputs

```text
outputs/deep_symbol_llm/
├── prompts/
│   └── <SYMBOL>_deep_prompt_<timestamp>.md
├── json/
│   └── <SYMBOL>_deep_decision_<timestamp>.json
├── markdown/
│   └── <SYMBOL>_deep_analysis_<timestamp>.md
├── raw/
└── deep_symbol_manifest_<timestamp>.json
```

### Text reports

```text
results/
├── reports_market_research_<timestamp>.txt
└── reports_deep_symbol_analysis_<timestamp>.txt
```

### Logs

```text
logs/
└── run_market_research_to_deep_analysis_<timestamp>.log
```

---

## Recommended Operating Workflow

### Daily after market close

```bash
./run_market_research_to_deep_analysis.sh \
  --stage market \
  --market-agent-mode heuristic
```

Review:

```text
outputs/trade_pipeline_integrate_llm/candidates_ranked_latest.csv
outputs/trade_pipeline_integrate_llm/watchlist_latest.csv
results/reports_market_research_*.txt
```

### Deep analysis on shortlisted names

```bash
./run_market_research_to_deep_analysis.sh \
  --stage deep \
  --symbols TCB,FPT,MBS \
  --top-n 5
```

### Full workflow

```bash
./run_market_research_to_deep_analysis.sh \
  --stage all \
  --top-n 10 \
  --market-agent-mode heuristic
```

### News refresh

Run with cached news most days. Force refresh when needed:

```bash
./run_market_research_to_deep_analysis.sh \
  --stage deep \
  --symbols TCB,FPT \
  --force-refresh-news
```

---

## Trading Methodology

The pipeline is designed around a two-stage process.

### Stage 1: Quant / heuristic screen

The market-wide scan ranks stocks using deterministic signals, such as:

- trend and moving-average structure,
- 20-day and 60-day returns,
- RSI / MACD / ATR-derived risk,
- volume expansion,
- foreign and proprietary flow,
- relative strength versus VNINDEX,
- valuation sanity checks,
- liquidity and tradability,
- scenario-based risk/reward.

### Stage 2: Institutional-style deep analysis

The deep analyzer uses a research pack with:

- previous heuristic context,
- structured BCTC / financial-statement Markdown,
- news context,
- optional user insights,
- optional RAG/playbook context,
- bull/base/bear target context,
- entry/stop/target and position-sizing context.

The LLM should not calculate raw indicators or invent figures. It should synthesize the prepared evidence and produce a structured decision.

---

## Troubleshooting

### 1. `No RSS URLs configured`

Use `configs/news_deep_symbol.json` and prefer `BatchCrawler` with sitemap for CafeF:

```bash
--news_config ./configs/news_deep_symbol.json
```

### 2. Pandas warning: `Could not infer format`

Find unsafe datetime parsing:

```bash
grep -R "pd.to_datetime" -n ./Stocks | grep -v "format=" | grep -v "__pycache__"
```

Use explicit date formats instead of relying on Pandas dateutil inference.

### 3. `ValueError: The truth value of a Series is ambiguous`

This usually means a pandas `Series` was used in a boolean context, often from duplicate columns or row access. Fix by scalarizing values before formatting:

```python
# Bad
text = str(value or "").strip()

# Good
value = scalarize(value, default=None)
text = "" if value is None else str(value).strip()
```

Also ensure duplicate columns are renamed before row-wise processing.

### 4. HTTP 403 / 429 while crawling news

Use lower concurrency and higher delay:

```json
"network_settings": {
  "request_delay": 2.0,
  "max_concurrency": 2,
  "retry_attempts": 2
}
```

Wait before retrying if the site blocks requests.

### 5. LLM quota exceeded

Use:

```bash
--market-agent-mode heuristic
--top-n 3
```

Run `--dry_run` first to inspect prompts without API calls.

### 6. Missing Vnstock packages

Activate the correct environment and verify imports:

```bash
source .venv/bin/activate
python - <<'PY'
from vnstock_data import Market, Fundamental, Insights, Analytics
from vnstock_news import BatchCrawler
print("vnstock packages are importable")
PY
```

---

## Security and Git Hygiene

Do not commit:

```text
.env
*.key
*.pem
installer.run
outputs/
results/
logs/
data/news_cache/
data/financial_statements/
__pycache__/
*.pyc
```

Recommended `.gitignore` additions:

```gitignore
# Secrets
.env
*.key
*.pem
installer.run

# Runtime outputs
outputs/
results/
logs/
data/news_cache/
data/financial_statements/

# Python
__pycache__/
*.py[cod]
.venv/

# Local notebooks / scratch
.ipynb_checkpoints/
*.tmp
```

API keys should be injected through environment variables such as `GEMINI_API_KEY`.

---

## Legal and Ethical Notes

- Respect website terms of service, robots.txt and rate limits when crawling news.
- Do not republish copyrighted article content unless you have the right to do so.
- Use crawled news for internal research, feature extraction and analytics.
- Stop or slow down if you receive HTTP 403 or 429 responses.
- This repository is for research and educational workflows; it is not a licensed investment-advisory service.

---

## Limitations

- The pipeline depends on your local Vnstock package version and account permissions.
- Some data providers may delay, revise or temporarily fail to return data.
- `Insights` schemas can change; prefer `ins.screener.criteria()` when validating field names.
- Fundamental data schemas are sector-specific and can contain many sparse or not-applicable fields.
- News crawling can fail due to website layout changes, rate limits, robots policies or connectivity issues.
- LLM output is probabilistic; always validate decisions against numeric data and risk rules.

---

## Roadmap

Planned or natural next steps:

- Telegram notifier consuming deep-analysis JSON and Markdown outputs.
- Backtest module for factor score deciles and top-N portfolios.
- Walk-forward calibration of 1M / 3M / 1Y scoring thresholds.
- Richer RAG memory for trade journals and sector playbooks.
- Portfolio tracker with exposure, sector concentration and stop-loss monitoring.
- More granular bank and technology sector templates.
- Unit tests for date parsing, fundamental scalarization, news cache, symbol selection and JSON normalization.

---

## Maintainer Notes

Recommended broad workflow:

```bash
# 1. Activate environment
source .venv/bin/activate

# 2. Run market-wide scan without LLM
python full_trade_pipeline_integrate_llm.py \
  --mode initial \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --outputs ./outputs/trade_pipeline_integrate_llm \
  --results ./results/reports_trade_pipeline_integrate_llm_{date}.txt \
  --agent-mode heuristic

# 3. Run deep analysis only on shortlisted names
python deep_symbol_llm_analyzer.py \
  --symbols TCB,FPT,MBS \
  --heuristic_outputs ./outputs/trade_pipeline_integrate_llm \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --financial_statement_path ./data/financial_statements \
  --news_cache_path ./data/news_cache \
  --news_config ./configs/news_deep_symbol.json \
  --outputs ./outputs/deep_symbol_llm \
  --results ./results/deep_symbol_llm_report_{date}.txt
```

For one-command execution:

```bash
./run_market_research_to_deep_analysis.sh --stage all --top-n 10
```

