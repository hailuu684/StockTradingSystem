python full_trade_pipeline.py \
  --mode initial \
  --config ./configs/trade_pipeline.json

# python full_trade_pipeline.py \
#   --mode daily_news \
#   --config ./configs/trade_pipeline.json \
#   --watchlist ./outputs/trade_pipeline/watchlist_latest.csv

# pipeline có LLM + heuristic comparison:
python full_trade_pipeline_integrate_llm.py \
  --mode initial \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --outputs ./outputs/trade_pipeline_integrate_llm \
  --results ./reports/reports_trade_pipeline_integrate_llm_{date}.txt \
  --agent-mode compare

# không LLM để so sánh baseline rule-based
python full_trade_pipeline_integrate_llm.py \
  --mode initial \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --outputs ./outputs/trade_pipeline_no_llm \
  --results ./reports/reports_trade_pipeline_no_llm_{date}.txt \
  --agent-mode heuristic

# chỉ dùng LLM final decision
python full_trade_pipeline_integrate_llm.py \
  --mode initial \
  --config ./configs/trade_pipeline_integrate_llm.json \
  --outputs ./outputs/trade_pipeline_integrate_llm \
  --results ./reports/reports_trade_pipeline_integrate_llm_{date}.txt \
  --agent-mode llm