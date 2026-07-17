# Several ways to run this script:

python deep_symbol_llm_analyzer.py \
  --symbols HDB \
  --heuristic_outputs ./outputs/trade_pipeline_integrate_llm \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --financial_cache_path ./data/financial_statements \
  --news_cache_path ./data/news_cache \
  --outputs ./outputs/deep_symbol_llm \
  --results ./results/deep_symbol_llm_report_{date}.txt \
  --news_config ./configs/news_deep_symbol.json \
  --force_refresh_news \
  --force_refresh_financial


# ./data/financial_statements/
# └── quarter_2/
#     ├── TCB_Techcombank_2026_Q2.pdf
#     ├── TCB_Techcombank_2026_Q2.md
#     ├── TCB_Techcombank_2026_Q2_pdf_extract.md
#     ├── TCB_Techcombank_2026_Q2_filing_row.json
#     ├── TCB_Techcombank_2026_Q2_income_statement_quarter.csv
#     ├── TCB_Techcombank_2026_Q2_balance_sheet_quarter.csv
#     ├── TCB_Techcombank_2026_Q2_cash_flow_quarter.csv
#     └── ...

# ./data/news_cache/
# ├── raw/
# │   └── raw_news_20260716_20260716_113000.csv
# └── symbols/
#     ├── TCB_news_20260716.csv
#     ├── FPT_news_20260716.csv
#     └── MSB_news_20260716.csv

# ./outputs/deep_symbol_llm/
# ├── prompts/
# │   ├── TCB_deep_prompt_20260716_113000.md
# │   └── FPT_deep_prompt_20260716_113010.md
# ├── json/
# │   ├── TCB_deep_decision_20260716_113000.json
# │   └── FPT_deep_decision_20260716_113010.json
# ├── markdown/
# │   ├── TCB_deep_analysis_20260716_113000.md
# │   └── FPT_deep_analysis_20260716_113010.md
# └── deep_symbol_manifest_20260716_113020.json