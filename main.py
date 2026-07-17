# source /home/luutunghai@gmail.com/.venv/bin/activate
# deactivate
# ./installer.run -- --non-interactive --api-key "vnstock_aa7b4b1f5b7ddd27be0eb4ac24e57241" --venv-path "/home/luutunghai@gmail.com/.venv"

import os
import sys
import json
from datetime import datetime, timedelta
import pandas as pd
# import polars as pl # computer is freezing when importing this lib !!!
import requests
from utils import convert_to_millions, format_financial_numbers, _run_and_print_test
# Khai báo các module chuẩn từ Hệ sinh thái Vnstock 2026
from vnstock_data import Market, Reference, Insights, Listing, TopStock, show_api, show_doc, Fundamental, Analytics
from vnstock_data.ui import Insights, Macro
from vnstock_news import BatchCrawler
# from vnstock_ta import Indicator


def test_vnstock_reference():
    company = "TCB"

    ref = Reference()

    # Thông tin tổng quan công ty
    df_profile = ref.company(f"{company}").info()

    # Danh sách cổ đông lớn
    df_shareholders = ref.company(f"{company}").shareholders()

    # Quản lý cấp cao
    df_officers = ref.company(f"{company}").officers()

    # Công ty con
    df_subs = ref.company(f"{company}").subsidiaries()

    # Tin tức & sự kiện
    df_news = ref.company(f"{company}").news()
    df_events = ref.company(f"{company}").events()

    # Tỷ lệ ký quỹ
    # df_margin = ref.company(f"{company}").margin_ratio()

    # df_profile_pl = pl.from_pandas(df_profile)
    # df_shareholders_pl = pl.from_pandas(df_shareholders)
    # df_officers_pl = pl.from_pandas(df_officers)
    # df_subs_pl = pl.from_pandas(df_subs)
    # df_news_pl = pl.from_pandas(df_news)
    # df_events_pl = pl.from_pandas(df_events)
    # df_margin_pl = pl.from_pandas(df_margin)

    # 2. Hàm in nhanh cấu trúc và dữ liệu mẫu bằng Polars
    def print_pandas_summary(name, df):
        print("=" * 60)
        print(f"📊 Pandas SUMMARY: {name}")
        print("=" * 60)
        
        if df is None or df.empty:
            print("❌ Dữ liệu trống.\n")
            return
            
        print(f"Kích thước: {df.shape} dòng, {df.shape} cột")
        print("-" * 60)
        
        # NẾU LÀ TIN TỨC: In theo từng dòng, bóc tách Title rõ ràng để dễ đọc
        if 'title' in df.columns:
            # Thay thế các giá trị None thành chuỗi trống để giao diện sạch hơn
            df_filled = df.fillna(" (Không có nội dung) ")
            
            for idx, row in df_filled.head(3).iterrows():
                print(f"[{idx+1}] Tiêu đề: {row['title']}")
                print(f"    Tóm tắt: {row['summary']}")
                if 'publish_date' in df.columns: # Nếu có cột ngày đăng
                    print(f"    Ngày đăng: {row['publish_date']}")
                print("-" * 40)
        else:
            # Đối với các dữ liệu dạng bảng khác (Cổ đông, Lãnh đạo...)
            # Cấu hình Pandas hiển thị tối đa cột để không bị ẩn dấu ba chấm `...`
            with pd.option_context('display.max_columns', None, 'display.width', 1000):
                print(df.head(3))
        
        print("\n")

    # 3. Gọi hàm in tóm tắt
    print_pandas_summary("Tổng quan công ty", df_profile)
    print_pandas_summary("Cổ đông lớn", df_shareholders)
    print_pandas_summary("Quản lý cấp cao", df_officers)
    print_pandas_summary("Công ty con", df_subs)
    print_pandas_summary("Tin tức", df_news)


def test_vnstock_market_methods(symbol='TCB', index_symbol='VNINDEX'):
    """
    Hàm kiểm thử các phương thức trong Market Layer, tự động quy đổi tiền 
    và in ra 3 dòng đầu tiên của mỗi DataFrame.
    """
    print(f"🚀 BẮT ĐẦU KIỂM THỬ VNSTOCK CHO MÃ {symbol} VÀ {index_symbol}...\n")
    print("=" * 80)
    
    market = Market()
    equity = market.equity(symbol)
    idx = market.index(index_symbol)
    
    results = {}
    
    # Gom nhóm các phương thức để chạy vòng lặp cho gọn
    test_groups = [
        (f"1. Cổ phiếu đơn lẻ: {symbol}", {
            'foreign_flow': lambda: equity.foreign_flow(),
            'history': lambda: equity.history(length='1Y'),
            'intraday': lambda: equity.intraday(),
            'matched_by_price': lambda: equity.matched_by_price(),
            'odd_lot': lambda: equity.odd_lot(),
            'ohlcv': lambda: equity.ohlcv(length='1Y'),
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
        (f"2. Chỉ số thị trường: {index_symbol}", {
            'ohlcv': lambda: idx.ohlcv(length='1Y'),
            'stock_influence': lambda: idx.stock_influence(),
            'trade_history': lambda: idx.trade_history()
        }),
        (f"3. Danh sách nhiều mã: ['{symbol}', 'SSI']", {
            'odd_lot': lambda: market.odd_lot([symbol, 'SSI']),
            'price_board': lambda: market.price_board([symbol, 'SSI']),
            'quote': lambda: market.quote([symbol, 'SSI'])
        })
    ]
    
    # Thực thi kiểm thử
    for group_name, methods in test_groups:
        print(f"\n--- {group_name} ---")
        for name, func in methods.items():
            print(f"[*] Đang lấy dữ liệu: {name}() ... ", end="")
            try:
                # Gọi API lấy dữ liệu
                raw_data = func()
                
                # Áp dụng hàm quy đổi tiền tệ
                processed_data = convert_to_millions(raw_data)
                results[f'{name}'] = processed_data
                
                print("✅ Thành công")
                # Chỉ in 3 dòng đầu để xem trước (Preview)
                if isinstance(processed_data, pd.DataFrame):
                    print(processed_data.head(3).to_string())
                else:
                    print(processed_data) # Dành cho trường hợp dữ liệu không phải DataFrame
                print("-" * 40)
                
            except Exception as e:
                print(f"❌ Lỗi: {e}\n" + "-" * 40)

    print("\n🎉 HOÀN THÀNH QUÁ TRÌNH KIỂM THỬ!")
    return results

def test_vnstock_news():
    print("Khởi động quy trình thu thập nội dung cấu trúc hóa...")
    
    # 1. Khởi tạo BatchCrawler (Hỗ trợ chạy đồng bộ 1 lần từ sitemap)
    crawler = BatchCrawler(
        site_name="cafef",
        request_delay=0.5,      # Đặt delay nhỏ để quét nhanh hơn
        output_path="./data",   # Thư mục lưu file tạm nếu cần
        debug=False
    )
    
    print("\n[1] Lấy danh mục tin từ hệ thống sitemap của CafeF...")
    
    # 2. Gọi hàm fetch_articles chuẩn đồng bộ theo tài liệu
    # Tham số 'limit' giúp khống chế số lượng bài viết cần lấy ngay từ đầu
    historical_corpus = crawler.fetch_articles(
        limit=50,
        sitemap_url="https://cafef.vn/latest-news-sitemap.xml"
    )
    
    # 3. Kiểm tra dữ liệu trả về (dạng pd.DataFrame) và lưu file
    if historical_corpus is not None and not historical_corpus.empty:
        print(f"Trích xuất thành công {len(historical_corpus)} bài viết chi tiết.")
        
        filename = "cafef_audit_latest.csv"
        historical_corpus.to_csv(filename, index=False)
        print(f"\nHoàn thành kết xuất dữ liệu về đường dẫn: {filename}")
    else:
        print("⚠️ Không lấy được dữ liệu hoặc sitemap trống.")

def test_vnstock_insights():
    ins = Insights()

    # top_insights = TopStock()

    # df = top_insights.gainer(limit=5)
    # print(df)
    # # ===== Top Gainer (Tăng Giá) =====
    # # Top gainer sàn VNINDEX
    # df_gainers_vn = ins.ranking.gainer(index='VNINDEX', limit=5)
    # print(df_gainers_vn)

    # # df_losers = ins.ranking().loser() print(df_losers)

    # # ===== Foreign Sell (Nước Ngoài Bán) =====
    # df_foreign_sell = ins.ranking.foreign_sell()
    # print(df_foreign_sell)

    # # ===== Top Deal (Giao Dịch Thỏa Thuận) =====
    # df_deals = ins.ranking.deal()
    # print(df_deals)

    # 1. Khai báo trực tiếp một List chứa các Dictionary điều kiện (List[Dict])
    custom_filter_list = [
        {'name': 'exchange', 'conditionOptions': [{'type': 'value', 'value': 'hsx'}]},
        {'name': 'ttmRoe', 'conditionOptions': [{'type': 'range', 'from': 15, 'to': 100}]},
        {'name': 'ttmPe', 'conditionOptions': [{'type': 'range', 'from': 0, 'to': 12}]},
        {'name': 'price_ema_20', 'conditionOptions': [{'type': 'range', 'from': 0, 'to': 10}]}
    ]

    # 2. Truyền vào biến `filters` thay vì `params`
    df_filtered = ins.screener.filter(filters=custom_filter_list, limit=5)
    print(f"Cổ phiếu HSX, P/E < 10, ROE > 15: {len(df_filtered)}")
    print(df_filtered.head())


def test_independent_screener():
    print("=" * 80)
    print("🧪 KIỂM THỬ ĐỘC LẬP: INSIGHTS SCREENER FILTER (NATIVE API)")
    print("=" * 80)
    
    json_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/insights.json"
    strategy_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/insights_filter_strategy.json"
    try:
        # 1. Đọc trực tiếp dữ liệu thô từ file JSON
        with open(json_path, 'r', encoding='utf-8') as f:
            config_raw = json.load(f)
        
        with open(strategy_path, "r", encoding="utf-8") as f:
            all_strategies = json.load(f)
            
        screener_cfg = config_raw.get("insight_config", {}).get("screener", {})
        
        selected_filter = all_strategies["growth_strategy"]  # Hoặc "value_strategy", "breakout_strategy"

        # Đảm bảo đây là một List các Dictionary nguyên bản
        native_filter_list = screener_cfg.get("filter", [])
        scr_limit = screener_cfg.get("limit", 10)
        scr_lang = screener_cfg.get("lang", "en")
        
        print(f"[*] Đang nạp {len(native_filter_list)} tiêu chí gốc từ file JSON...")
        print(f"[*] Gọi API: ins.screener.filter(filter=list_tho, limit={scr_limit}) ...")
        print("-" * 60)
        
        # 2. Thực thi gọi trực tiếp qua hệ thống Vnstock
        ins = Insights()
        scr = ins.screener
        
        df_result = scr.filter(filters=selected_filter, limit=scr_limit)
        
        # 3. Hiển thị kết quả kiểm tra bảng dữ liệu
        if isinstance(df_result, pd.DataFrame) and not df_result.empty:
            print(f"\n✔️ Thành công! Hệ thống trả về {len(df_result)} cổ phiếu.")
            print("-" * 80)
            
            # Chọn các cột đại diện có sẵn trong bảng để in ra xem trước
            preview_cols = ['symbol', 'exchange', 'price', 'market_cap', 'pe', 'roe', 'rsi', 'stock_trend']
            existing_cols = [col for col in preview_cols if col in df_result.columns]
            
            with pd.option_context('display.float_format', lambda x: f'{x:,.2f}', 
                                   'display.max_columns', None, 
                                   'display.width', 1000):
                print(df_result[existing_cols].to_string(index=False))
        else:
            print("\n⚠️ API trả về thành công nhưng DataFrame trống (0 rows).")
            print("💡 Giải thích: Không có mã nào trên thị trường đáp ứng đồng thời 17 tiêu chí khắt khe này.")
            
    except Exception as e:
        print(f"\n❌ Phát sinh lỗi hệ thống: {e}")
        print("💡 Gợi ý: Hãy kiểm tra xem file JSON có bị thừa dấu ngoặc hoặc sai định dạng chữ hoa/thường không.")
        
    print("=" * 80)

def test_vnstock_fundamental_methods(symbol='TCB'):
    """
    Hàm kiểm thử các phương thức trong Fundamental Layer theo chuẩn Object Oriented.
    """
    print(f"🚀 BẮT ĐẦU KIỂM THỬ FUNDAMENTAL LAYER CHO MÃ {symbol}...\n")
    print("=" * 80)
    
    # Khởi tạo đối tượng
    fun = Fundamental()
    equity = fun.equity(symbol)
    
    results = {}
    
    # Định nghĩa các hàm cần test cùng tham số đi kèm
    methods = {
        'income_statement (KQKD - Năm)': lambda: equity.income_statement(period='year'),
        'balance_sheet (CĐKT - Quý)': lambda: equity.balance_sheet(period='quarter'),
        'cash_flow (LCTT - Năm)': lambda: equity.cash_flow(period='year'),
        'ratio (Tỷ số TC - Quý)': lambda: equity.ratio(period='quarter'),
        'note (Thuyết minh - Năm)': lambda: equity.note(period='year', lang='vi'),
        'filing (Tài liệu PDF)': lambda: equity.filing(),
        'financial_health (Auto Scorecard - Gộp 4 báo cáo)': lambda: equity.financial_health(scorecard='auto', limit=4)
    }
    
    for name, func in methods.items():
        print(f"[*] Đang lấy dữ liệu: {name} ... ", end="")
        try:
            # Lấy dữ liệu thô
            raw_data = func()
            
            # Format số liệu cho dễ nhìn (áp dụng cho BCTC)
            processed_data = format_financial_numbers(raw_data)
            results[name] = processed_data
            
            print("✅ Thành công")
            
            # In 3 dòng đầu tiên
            if isinstance(processed_data, pd.DataFrame):
                print(processed_data.head(3).to_string())
            else:
                print(processed_data)
                
            print("-" * 60)
            
        except Exception as e:
            print(f"❌ Lỗi: {e}")
            print("-" * 60)
            
    print("\n🎉 HOÀN THÀNH QUÁ TRÌNH KIỂM THỬ FUNDAMENTAL!")
    return results


def test_vnstock_macro_layer():
    """
    Hàm kiểm thử toàn diện Macro Layer theo chuẩn Domain-Driven.
    Tuân thủ best practice, không sử dụng các hàm deprecated.
    """
    print("🚀 BẮT ĐẦU KIỂM THỬ MACRO LAYER...\n")
    print("=" * 80)
    
    mac = Macro()
    results = {}
    
    # 1. Economy Domain (Kinh tế Việt Nam)
    economy = mac.economy()
    eco_methods = {
        'gdp (Tăng trưởng GDP - Quý)': lambda: economy.gdp(period="quarter", length=4),
        'cpi (Chỉ số giá tiêu dùng - Tháng)': lambda: economy.cpi(period="month", length=12),
        'industry_prod (Sản xuất CN)': lambda: economy.industry_prod(period="month", length=3),
        'import_export (Xuất nhập khẩu)': lambda: economy.import_export(period="month", length=3),
        'retail (Bán lẻ)': lambda: economy.retail(period="month", length=3),
        'fdi (Đầu tư trực tiếp)': lambda: economy.fdi(period="month", length=3),
        'money_supply (Cung tiền)': lambda: economy.money_supply(period="month", length=3),
        'population_labor (Dân số & LĐ - Năm)': lambda: economy.population_labor(period="year", length=3)
    }
    
    print("\n--- 1. ECONOMY DOMAIN ---")
    for name, func in eco_methods.items():
        _run_and_print_test(name, func, results)

    # 2. Currency Domain (Tiền tệ & Lãi suất)
    currency = mac.currency()
    curr_methods = {
        'exchange_rate (Tỷ giá - Ngày)': lambda: currency.exchange_rate(period="day", length=5),
        'interest_rate (Lãi suất - Tháng - Long format)': lambda: currency.interest_rate(period="month", length=3, format="long")
    }
    
    print("\n--- 2. CURRENCY DOMAIN ---")
    for name, func in curr_methods.items():
        _run_and_print_test(name, func, results)

    # 3. Commodity Domain (Hàng hóa)
    commodity = mac.commodity()
    cmd_methods = {
        'gold (Vàng trong nước - VN)': lambda: commodity.gold(market="VN"),
        'gold (Vàng quốc tế - GLOBAL)': lambda: commodity.gold(market="GLOBAL"),
        'gas (Xăng dầu - VN)': lambda: commodity.gas(market="VN"),
        'oil_crude (Dầu thô WTI)': lambda: commodity.oil_crude(),
        'coke (Than cốc)': lambda: commodity.coke(),
        'steel (Thép - VN)': lambda: commodity.steel(market="VN"),
        'iron_ore (Quặng sắt)': lambda: commodity.iron_ore(),
        'fertilizer_ure (Phân URE)': lambda: commodity.fertilizer_ure(),
        'soybean (Đậu tương)': lambda: commodity.soybean(),
        'corn (Ngô)': lambda: commodity.corn(),
        'sugar (Đường)': lambda: commodity.sugar(),
        'pork (Thịt lợn - VN)': lambda: commodity.pork(market="VN")
    }
    
    print("\n--- 3. COMMODITY DOMAIN ---")
    for name, func in cmd_methods.items():
        _run_and_print_test(name, func, results)

    print("\n🎉 HOÀN THÀNH QUÁ TRÌNH KIỂM THỬ MACRO LAYER!")

    # Đang lấy dữ liệu: interest_rate (Lãi suất - Tháng - Long format) ... ❌ Lỗi: Unsupported report period type: month
    # [*] Đang lấy dữ liệu: fdi (Đầu tư trực tiếp) ... ❌ Lỗi: Failed to fetch data: 404 - Not Found
    # [*] Đang lấy dữ liệu: gdp (Tăng trưởng GDP - Quý) ... ❌ Lỗi: Failed to fetch data: 404 - Not Found
    return results

def test_vnstock_analytics_layer(index_symbol="VNINDEX"):
    """
    Hàm kiểm thử Analytics Layer chuyên về Định giá thị trường (Valuation).
    Tuân thủ best practice sử dụng Keyword Arguments và hướng đối tượng mới.
    """
    print(f"🚀 BẮT ĐẦU KIỂM THỬ ANALYTICS LAYER CHO CHỈ SỐ {index_symbol}...\n")
    print("=" * 80)
    
    # Khởi tạo đối tượng
    ana = Analytics()
    
    # Thiết lập domain valuation cho chỉ số cụ thể
    val = ana.valuation(index=index_symbol)
    
    results = {}
    
    # Định nghĩa các hàm cần test cùng tham số (Dùng Keyword Argument)
    methods = {
        'pe (P/E lịch sử - 1 Năm)': lambda: val.pe(duration="1Y"),
        'pb (P/B lịch sử - 3 Năm)': lambda: val.pb(duration="3Y"),
        'evaluation (Đánh giá tổng hợp - 5 Năm)': lambda: val.evaluation(duration="5Y")
    }
    
    for name, func in methods.items():
        print(f"[*] Đang lấy dữ liệu: {name} ... ", end="")
        try:
            # Lấy dữ liệu
            data = func()
            results[name] = data
            
            print("✅ Thành công")
            
            # In 3 dòng CUỐI CÙNG (dữ liệu mới nhất)
            if isinstance(data, pd.DataFrame):
                print(data.tail(3).to_string())
            else:
                print(data)
                
            print("-" * 60)
            
        except Exception as e:
            print(f"❌ Lỗi: {e}")
            print("-" * 60)
            
    print(f"\n🎉 HOÀN THÀNH QUÁ TRÌNH KIỂM THỬ ANALYTICS LAYER CHO {index_symbol}!")
    return results


def test_independent_macro():
    print("=" * 80)
    print("🧪 BẮT ĐẦU CHẠY THỬ NGHIỆM ĐỘC LẬP")
    print("=" * 80)
    
    mac = Macro()
    economy = mac.economy()
    
    # 1. Kiểm thử hàm Xuất Nhập Khẩu (import_export)
    print("\n[1] Thử nghiệm: economy.import_export() ...")
    try:
        # Chạy tham số mặc định theo tháng, lấy 6 tháng gần nhất
        df_trade = economy.import_export(period="month")
        print(f"✔️ Thành công! Trả về {len(df_trade)} dòng.")
        if isinstance(df_trade, pd.DataFrame) and not df_trade.empty:
            print(df_trade.head(2).to_string())
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        
    print("-" * 60)

    # 2. Kiểm thử hàm Cung tiền (money_supply)
    print("\n[2] Thử nghiệm: economy.money_supply() ...")
    try:
        # Chạy tham số mặc định theo tháng, lấy 6 tháng gần nhất
        df_money = economy.money_supply(period="month")
        print(f"✔️ Thành công! Trả về {len(df_money)} dòng.")
        if isinstance(df_money, pd.DataFrame) and not df_money.empty:
            print(df_money.head(2).to_string())
    except Exception as e:
        print(f"❌ Lỗi: {e}")

    print("-" * 60)

    # 3. Kiểm thử hàm Tổng vốn đầu tư (total_investment)
    print("\n[3] Thử nghiệm: economy.total_investment() ...")
    try:
        # Hàm này không có trong tài liệu API chính thức của Vnstock3
        df_invest = economy.total_investment(period="year", length=90)
        print(f"✔️ Thành công! Trả về {len(df_invest)} dòng.")
    except Exception as e:
        print(f"❌ Lỗi (Xác nhận lỗi API/Endpoint không tồn tại): {e}")
        print("💡 Khuyến nghị: Loại bỏ hoàn toàn total_investment khỏi code dự án chính thức.")

    print("=" * 80)


def export_column_report(dataframes_dict, output_path="./report/fundamental_layer_explore.txt"):
    # Tự động tạo thư mục ./report nếu chưa tồn tại
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("==================================================\n")
        f.write("      FUNDAMENTAL LAYER EXPLORATION REPORT        \n")
        f.write("==================================================\n\n")
        
        for name, df in dataframes_dict.items():
            f.write(f"=== METHOD: {name} ===\n")
            
            if df is None or df.empty:
                f.write("Status: Empty DataFrame or None\n")
                f.write("-" * 50 + "\n\n")
                continue
                
            # 1. Số lượng cột
            total_cols = len(df.columns)
            f.write(f"Total Columns: {total_cols}\n\n")
            
            # 2. Danh sách tất cả các cột
            f.write("All Columns:\n")
            for col in df.columns:
                f.write(f"  - {col}\n")
            f.write("\n")
            
            # 3. Kiểm tra cột trống (tất cả giá trị đều là NaN/None)
            empty_cols = df.columns[df.isna().all()].tolist()
            f.write(f"Empty Columns ({len(empty_cols)}):\n")
            if empty_cols:
                for col in empty_cols:
                    f.write(f"  - {col}\n")
            else:
                f.write("  (None - All columns contain data)\n")
                
            f.write("-" * 50 + "\n\n")
            
    print(f" Report successfully saved to: {output_path}")

def run_analysis():
    fun = Fundamental()
    mbs = fun.equity("MBS")

    # 1. Trích xuất danh sách tài liệu công bố
    filings = mbs.filing(doc_type="financial_report")
    print(filings.head())

    period = "quarter"
    
    # Gọi các phương thức và lưu vào dict để xử lý tập trung
    dfs = {
        "mbs.income_statement(period='quarter')": mbs.income_statement(period=period),
        "mbs.balance_sheet(period='quarter')": mbs.balance_sheet(period=period),
        "mbs.cash_flow(period='quarter')": mbs.cash_flow(period=period),
        "mbs.financial_health()": mbs.financial_health()
    }

    # Xuất báo cáo vào thư mục ./report
    export_column_report(dfs)

if __name__ == "__main__":
    # test_vnstock_reference()
    # test_vnstock_news()
    # test_vnstock_insights()
    # test_vnstock_market_methods()
    # test_vnstock_fundamental_methods()
    # test_vnstock_macro_layer()
    # test_vnstock_analytics_layer()

    # show_api(Insights())

    # # Xem sơ đồ vĩ mô và hàng hoá
    # show_api(Macro())

    # test_independent_macro()

    # test_independent_screener()

    run_analysis()




    


