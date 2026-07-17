import os
import sys
import json
from datetime import datetime, timedelta
import pandas as pd
# import polars as pl # computer is freezing when importing this lib !!!
import requests
from scripts.layer_utils import convert_to_millions, format_financial_numbers

from vnstock_data import Market, Reference, Insights, Listing, TopStock, show_api, show_doc, Fundamental, Analytics

# Fundamental Để phân tích tác động của kinh tế đến các công ty

def fundamental_layer(fundamental_configs):
    # 1. Đọc thông tin từ cấu trúc JSON đã gom nhóm
    symbol = fundamental_configs.symbol
    scorecard_mode = fundamental_configs.scorecard_mode
    
    # Phân rã nhóm periods
    periods = fundamental_configs.periods
    income_statement_period = periods.get('income_statement', 'yearly')
    balance_sheet_period = periods.get('balance_sheet', 'quarterly')
    cash_flow_period = periods.get('cash_flow', 'yearly')
    ratio_period = periods.get('ratio', 'quarterly')
    
    # Phân rã nhóm note_config
    note_cfg = fundamental_configs.note_config
    note = note_cfg.get('period', 'yearly')
    note_language = note_cfg.get('language', 'vi')
    
    print(f"Bắt đầu thu thập dữ liệu Fundamental cho mã: {symbol}...\n")
    print("=" * 80)
    
    # Khởi tạo đối tượng từ thư viện
    fun = Fundamental()
    equity = fun.equity(symbol)
    
    results = {}

    # Định nghĩa các hàm với key sạch để sau này dễ truy cập trong results
    methods = {
        'income_statement': lambda: equity.income_statement(period=income_statement_period),
        'balance_sheet': lambda: equity.balance_sheet(period=balance_sheet_period),
        'cash_flow': lambda: equity.cash_flow(period=cash_flow_period),
        'ratio': lambda: equity.ratio(period=ratio_period),
        'note': lambda: equity.note(period=note, lang=note_language),
        'filing': lambda: equity.filing(),
        'financial_health': lambda: equity.financial_health(scorecard=scorecard_mode, limit=4)
    }

    for name, func in methods.items():
        print(f"[*] Getting data: {name} ... ", end="")
        try:
            raw_data = func()
            
            # Định dạng lại hiển thị số liệu tài chính
            # processed_data = format_financial_numbers(raw_data)
            results[name] = raw_data
            print("Thành công")
            
        except Exception as e:
            print(f"Error: {e}")
            print("-" * 60)
            
    return results