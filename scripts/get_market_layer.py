import os
import sys
import json
from datetime import datetime, timedelta
import pandas as pd
# import polars as pl # computer is freezing when importing this lib !!!
import requests
from scripts.layer_utils import convert_to_millions, format_financial_numbers

from vnstock_data import Market, Reference, Insights, Listing, TopStock, show_api, show_doc, Fundamental, Analytics
# from vnstock_data.ui import Insights, Macro
# from vnstock_news import BatchCrawler

# Market layer Để liên kết dữ liệu vĩ mô với thị trường chứng khoán

def market_layer(market_config):

    symbol = market_config.symbol
    symbol_compare = market_config.symbol_compare
    index_symbol = market_config.index_symbol
    length = market_config.length

    print(f"Get market information for {symbol} and {index_symbol}...\n")
    print("=" * 80)

    market = Market()
    equity = market.equity(symbol)
    idx = market.index(index_symbol)
    
    results = {'Equity': {}, 'Index': {}, 'Compare_with': {}}
    
    # Gom nhóm các phương thức để chạy vòng lặp cho gọn
    test_groups = [
        (f"Equity: {symbol}", {
            'foreign_flow': lambda: equity.foreign_flow(),
            'history': lambda: equity.history(length=length),
            'intraday': lambda: equity.intraday(),
            'matched_by_price': lambda: equity.matched_by_price(),
            'odd_lot': lambda: equity.odd_lot(),
            'ohlcv': lambda: equity.ohlcv(length=length),
            'order_book': lambda: equity.order_book(),
            'price_board': lambda: equity.price_board(),
            'price_depth': lambda: equity.price_depth(),
            'proprietary_flow': lambda: equity.proprietary_flow(),
            'quote': lambda: equity.quote(),
            'session_stats': lambda: equity.session_stats(),
            'summary': lambda: equity.summary(),
            'trade_history': lambda: equity.trade_history(),
            'trades': lambda: equity.trades(),
            'trading_stats': lambda: equity.trading_stats(),
            'volume_profile': lambda: equity.volume_profile()
        }),
        (f"Index: {index_symbol}", {
            'ohlcv': lambda: idx.ohlcv(length=length),
            'stock_influence': lambda: idx.stock_influence(),
            'trade_history': lambda: idx.trade_history()
        }),
        (f"Compare_with: ['{symbol}', '{symbol_compare}']", {
            'odd_lot': lambda: market.odd_lot([symbol, symbol_compare]),
            'price_board': lambda: market.price_board([symbol, symbol_compare]),
            'quote': lambda: market.quote([symbol, symbol_compare])
        })
    ]

    for group_name, methods in test_groups:
        print(f"\n--- {group_name} ---")
        current_group = group_name.split(':')[0].strip() 

        for name, func in methods.items():
            print(f"[*] Getting data: {name}() ... ", end="")
            try:
                # Gọi API lấy dữ liệu
                raw_data = func()
                
                # Áp dụng hàm quy đổi tiền tệ
                # processed_data = convert_to_millions(raw_data)
                results[current_group][name] = raw_data
                
                # print("Successed")
                # # Chỉ in 3 dòng đầu để xem trước (Preview)
                # if isinstance(processed_data, pd.DataFrame):
                #     print(processed_data.head(3).to_string())
                # else:
                #     print(processed_data) # Dành cho trường hợp dữ liệu không phải DataFrame
                # print("-" * 40)
                
            except Exception as e:
                print(f" Error: {e}\n" + "-" * 40)
    
    return results