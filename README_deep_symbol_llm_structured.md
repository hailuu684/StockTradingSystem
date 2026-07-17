# Deep Symbol LLM Analyzer - Structured BCTC

This add-on replaces the OCR/manual-PDF flow. It uses structured vnstock Fundamental data to build a quarterly BCTC Markdown report, caches it by `symbol + year + quarter`, and feeds it with previous heuristic results, optional user insights, optional news, and optional RAG context into the LLM.

## Main command

```bash
python deep_symbol_llm_analyzer.py \
  --symbols TCB,FPT,MBS \
  --heuristic_outputs ./outputs/trade_pipeline_integrate_llm \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --financial_cache_path ./data/financial_statements \
  --news_cache_path ./data/news_cache \
  --outputs ./outputs/deep_symbol_llm \
  --results ./results/deep_symbol_llm_report_{date}.txt
```

## Dry-run without LLM

```bash
python deep_symbol_llm_analyzer.py \
  --symbols TCB \
  --heuristic_outputs ./outputs/trade_pipeline_integrate_llm \
  --financial_cache_path ./data/financial_statements \
  --outputs ./outputs/deep_symbol_llm \
  --results ./results/deep_symbol_llm_report_{date}.txt \
  --dry_run
```

## Incremental BCTC cache behavior

Default behavior:

1. Call `Fundamental().equity(symbol).filing(doc_type="financial_report")` only to detect the latest available quarter.
2. If `./data/financial_statements/quarter_<n>/<SYMBOL>_*_<YEAR>_Q<n>_structured_financial_report.md` already exists, reuse it.
3. If a newer quarter exists, generate a new report in `quarter_<new_q>`.
4. Do not delete older quarter folders/reports.

To skip the filing check and reuse the latest local Markdown:

```bash
--skip_filing_check
```

To force regeneration:

```bash
--force_refresh_financial
```

## Optional inputs

Disable news:

```bash
--no_news
```

Provide user-fed insights:

```bash
--insights_path ./configs/user_insights/{symbol}.md
```

Use a custom prompt template:

```bash
--prompt_template ./configs/deep_symbol_trade_prompt_template.md
```

The default prompt template is stored at:

```text
./configs/deep_symbol_trade_prompt_template.md
```

Run with specific path:

```bash
./run_market_research_to_deep_analysis.sh \
  --market-outputs ./outputs/trade_pipeline_market_research \
  --deep-outputs ./outputs/deep_symbol_llm \
  --financial-cache-path ./data/financial_statements \
  --news-cache-path ./data/news_cache \
  --results-dir ./results
```

Analyze specific symbols

```bash
./run_market_research_to_deep_analysis.sh \
  --stage deep \
  --symbols TCB,FPT,MBS \
  --market-outputs ./outputs/trade_pipeline_integrate_llm \
  --financial-cache-path ./data/financial_statements \
  --news-cache-path ./data/news_cache
```

Run with API free tier:

```bash
./run_market_research_to_deep_analysis.sh \
  --top-n 5 \
  --market-agent-mode heuristic
```

Scan market

```bash
./run_market_research_to_deep_analysis.sh \
  --stage market
```

Run dry-run deep analyzer to build prompt/data but have not called LLM yet

```bash
./run_market_research_to_deep_analysis.sh \
  --stage deep \
  --symbols TCB,FPT \
  --dry-run-deep
```

Script will create the main following outputs:

```
./outputs/trade_pipeline_integrate_llm/
  candidates_ranked_latest.csv
  watchlist_latest.csv
  selected_symbols_YYYYMMDD_HHMMSS.txt

./outputs/deep_symbol_llm/
  prompts/
  json/
  markdown/
  deep_symbol_manifest_*.json

./data/financial_statements/
  structured BCTC markdown/cache theo quý

./data/news_cache/
  raw news + symbol-filtered news cache

./results/
  reports_market_research_YYYYMMDD_HHMMSS.txt
  reports_deep_symbol_analysis_YYYYMMDD_HHMMSS.txt

./logs/
  run_market_research_to_deep_analysis_YYYYMMDD_HHMMSS.log
```

