import pandas as pd
from vnstock_data import Insights
import json
from scripts.layer_utils import is_data_valid


def insights_layer(insights_config, all_strategies):
    """
    Hàm xử lý Insights Layer bao phủ 6 domain.
    Đã sửa cú pháp gọi dạng thuộc tính (ví dụ: ins.ranking.gainer) đúng chuẩn Vnstock v3.
    """
    print("🚀 BẮT ĐẦU THU THẬP DỮ LIỆU INSIGHTS LAYER...\n")
    print("=" * 80)
    
    ins = Insights()
    results = {}
    
    # -------------------------------------------------------------------------
    # 1. RANKING DOMAIN (Xếp hạng & Top)
    # -------------------------------------------------------------------------
    rk_cfg = getattr(insights_config, 'ranking', {})
    idx = rk_cfg.get('index', 'VNINDEX')
    lmt = rk_cfg.get('limit', 10)
    dt = rk_cfg.get('date') # YYYY-MM-DD

    rk = ins.ranking 
    ranking_methods = {
        'gainer': lambda: rk.gainer(index=idx, limit=lmt),
        'loser': lambda: rk.loser(index=idx, limit=lmt),
        'value': lambda: rk.value(index=idx, limit=lmt),
        'volume': lambda: rk.volume(index=idx, limit=lmt),
        'deal': lambda: rk.deal(index=idx, limit=lmt),
        'foreign_buy': lambda: rk.foreign_buy(date=dt, limit=lmt) if dt else rk.foreign_buy(limit=lmt),
        'foreign_sell': lambda: rk.foreign_sell(date=dt, limit=lmt) if dt else rk.foreign_sell(limit=lmt)
    }

    print("\n--- 1. RANKING DOMAIN ---")
    for name, func in ranking_methods.items():
        print(f"[*] Getting data: ranking.{name}() ... ", end="", flush=True)
        try:
            raw_data = func()
            is_valid, message = is_data_valid(raw_data)
            if is_valid:
                results[f"ranking_{name}"] = raw_data
                print(f"✅ {message}")
            else:
                results[f"ranking_{name}"] = None 
                print(f"⚠️ Warning: {message}")
        except Exception as e:
            print(f"❌ API Error: {e}")
            results[f"ranking_{name}"] = None

    # -------------------------------------------------------------------------
    # 2. SCREENER DOMAIN (Bộ Lọc Chứng Khoán)
    # -------------------------------------------------------------------------
    # Dùng để lọc những mã cổ phiếu phù hợp với tiêu chí/chỉ báo kĩ thuật đề ra
            
    scr_cfg = getattr(insights_config, 'screener', {})
    scr_strategy = scr_cfg.get('strategy', 'growth_strategy')
    selected_filter = all_strategies[scr_strategy]
    scr_limit = scr_cfg.get('limit', 2000)
    scr_lang = scr_cfg.get('lang', 'en')
    
    # SỬA TẠI ĐÂY: scr là thuộc tính ins.screener (không có dấu ngoặc)
    scr = ins.screener
    screener_methods = {
        'criteria': lambda: scr.criteria(lang=scr_lang),
        'filter': lambda: scr.filter(filters=selected_filter, limit=scr_limit)
    }

    print("\n--- 2. SCREENER DOMAIN ---")
    for name, func in screener_methods.items():
        print(f"[*] Getting data: screener.{name}() ... ", end="", flush=True)
        try:
            raw_data = func()
            is_valid, message = is_data_valid(raw_data)
            if is_valid:
                results[f"screener_{name}"] = raw_data
                print(f"✅ {message}")
            else:
                results[f"screener_{name}"] = None 
                print(f"⚠️ Warning: {message}")
        except Exception as e:
            print(f"❌ API Error: {e}")
            results[f"screener_{name}"] = None

    # -------------------------------------------------------------------------
    # 3. EQUITY DOMAIN (Theo Mã Cổ Phiếu)
    # -------------------------------------------------------------------------
    eq_cfg = getattr(insights_config, 'equity', {})
    symbol = eq_cfg.get('symbol')
    
    if symbol:
        print(f"\n--- 3. EQUITY DOMAIN ({symbol}) ---")
        # equity nhận tham số đầu vào nên bắt buộc giữ nguyên dấu ngoặc ins.equity(symbol)
        eq = ins.equity(symbol) 
        equity_methods = {
            'order_flow': lambda: eq.order_flow(),
            'order_flow_history': lambda: eq.order_flow_history(),
            'peer_compare': lambda: eq.peer_compare(),
            'rrg': lambda: eq.rrg()
        }
        for name, func in equity_methods.items():
            print(f"[*] Getting data: equity('{symbol}').{name}() ... ", end="", flush=True)
            try:
                raw_data = func()
                is_valid, message = is_data_valid(raw_data)
                if is_valid:
                    results[f"equity_{name}"] = raw_data
                    print(f"✅ {message}")
                else:
                    results[f"equity_{name}"] = None 
                    print(f"⚠️ Warning: {message}")
            except Exception as e:
                print(f"❌ API Error: {e}")
                results[f"equity_{name}"] = None

    # -------------------------------------------------------------------------
    # 4. FLOW DOMAIN (Dòng Tiền)
    # -------------------------------------------------------------------------
    flow_cfg = getattr(insights_config, 'flow', {})
    if flow_cfg.get('enabled'):
        print("\n--- 4. FLOW DOMAIN ---")
        try:
            # GIỮ NGUYÊN: ins.flow là thuộc tính (không có dấu ngoặc)
            flow = ins.flow
            flow_methods = {
                'active': lambda: flow.active(),
                'foreign': lambda: flow.foreign(),
                'proprietary': lambda: flow.proprietary()
            }
            for name, func in flow_methods.items():
                print(f"[*] Getting data: flow.{name}() ... ", end="", flush=True)
                try:
                    raw_data = func()
                    is_valid, message = is_data_valid(raw_data)
                    if is_valid:
                        results[f"flow_{name}"] = raw_data
                        print(f"✅ {message}")
                    else:
                        results[f"flow_{name}"] = None 
                        print(f"⚠️ Warning: {message}")
                except Exception as e:
                    print(f"❌ API Error: {e}")
                    results[f"flow_{name}"] = None
        except Exception as e:
            print(f"❌ Flow Domain Init Error: {e}")

    # -------------------------------------------------------------------------
    # 5. SECTOR DOMAIN (Theo Ngành)
    # -------------------------------------------------------------------------
    sector_cfg = getattr(insights_config, 'sector', {})
    sec_name = sector_cfg.get('name')
    if sec_name:
        print(f"\n--- 5. SECTOR DOMAIN ({sec_name}) ---")
        try:
            # sector nhận tham số tên ngành nên bắt buộc giữ nguyên dấu ngoặc ins.sector(sec_name)
            sec = ins.sector(sec_name)
            sector_methods = {
                'flow_intraday': lambda: sec.flow_intraday(),
                'index_intraday': lambda: sec.index_intraday(),
                'members': lambda: sec.members(),
                'rrg': lambda: sec.rrg()
            }
            for name, func in sector_methods.items():
                print(f"[*] Getting data: sector('{sec_name}').{name}() ... ", end="", flush=True)
                try:
                    raw_data = func()
                    is_valid, message = is_data_valid(raw_data)
                    if is_valid:
                        results[f"sector_{name}"] = raw_data
                        print(f"✅ {message}")
                    else:
                        results[f"sector_{name}"] = None 
                        print(f"⚠️ Warning: {message}")
                except Exception as e:
                    print(f"❌ API Error: {e}")
                    results[f"sector_{name}"] = None
        except Exception as e:
            print(f"❌ Sector Domain Init Error: {e}")

    # -------------------------------------------------------------------------
    # 6. SENTIMENT DOMAIN (Tâm Lý Thị Trường)
    # -------------------------------------------------------------------------
    sentiment_cfg = getattr(insights_config, 'sentiment', {})
    if sentiment_cfg.get('enabled'):
        print("\n--- 6. SENTIMENT DOMAIN ---")
        try:
            # GIỮ NGUYÊN: ins.sentiment là thuộc tính (không có dấu ngoặc)
            stm = ins.sentiment
            sentiment_methods = {
                'breadth': lambda: stm.breadth(),
                'contribution': lambda: stm.contribution(),
                'heatmap': lambda: stm.heatmap()
            }
            for name, func in sentiment_methods.items():
                print(f"[*] Getting data: sentiment.{name}() ... ", end="", flush=True)
                try:
                    raw_data = func()
                    is_valid, message = is_data_valid(raw_data)
                    if is_valid:
                        results[f"sentiment_{name}"] = raw_data
                        print(f"✅ {message}")
                    else:
                        results[f"sentiment_{name}"] = None 
                        print(f"⚠️ Warning: {message}")
                except Exception as e:
                    print(f"❌ API Error: {e}")
                    results[f"sentiment_{name}"] = None
        except Exception as e:
            print(f"❌ Sentiment Domain Init Error: {e}")

    print("\n🎉 HOÀN THÀNH QUÁ TRÌNH THU THẬP INSIGHTS LAYER!")
    return results

# Đoạn code dùng để test nhanh file
if __name__ == "__main__":
    # Nạp cấu hình từ file json
    with open('insights_config.json', 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Chạy hàm
    data_dict = insights_layer(config)