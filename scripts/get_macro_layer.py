from vnstock_data.ui import Insights, Macro
import pandas as pd
from scripts.layer_utils import is_data_valid


def macro_layer(macro_config):
    """
    Hàm xử lý Macro Layer nạp tham số từ SimpleNamespace 1 tầng.
    Tự động bóc tách các dictionary lồng nhau (economy, currency, commodity).
    """
    print("🚀 BẮT ĐẦU THU THẬP DỮ LIỆU MACRO LAYER...\n")
    print("=" * 80)
    
    mac = Macro()
    results = {}

    # -------------------------------------------------------------------------
    # 1. Economy Domain (Kinh tế Việt Nam)
    # -------------------------------------------------------------------------
    economy = mac.economy()
    # Lấy dict economy, nếu không có thì để dict rỗng
    eco_cfg = getattr(macro_config, 'economy', {})
    
    # Bóc tách cấu hình cụ thể từng chỉ số (mặc định nếu JSON thiếu trường)
    # gdp_p = eco_cfg.get('gdp', {}).get('period', 'quarter')
    # gdp_l = eco_cfg.get('gdp', {}).get('length', 4)
    
    cpi_p = eco_cfg.get('cpi', {}).get('period', 'month')
    cpi_l = eco_cfg.get('cpi', {}).get('length', 12)
    
    ip_p = eco_cfg.get('industry_prod', {}).get('period', 'month')
    ip_l = eco_cfg.get('industry_prod', {}).get('length', 3)
    
    ie_p = eco_cfg.get('import_export', {}).get('period', 'month')
    ie_l = eco_cfg.get('import_export', {}).get('length', 3)
    
    rt_p = eco_cfg.get('retail', {}).get('period', 'month')
    rt_l = eco_cfg.get('retail', {}).get('length', 3)
    
    # fdi_p = eco_cfg.get('fdi', {}).get('period', 'month')
    # fdi_l = eco_cfg.get('fdi', {}).get('length', 3)
    
    ms_p = eco_cfg.get('money_supply', {}).get('period', 'month')
    ms_l = eco_cfg.get('money_supply', {}).get('length', 3)
    
    pl_p = eco_cfg.get('population_labor', {}).get('period', 'year')
    pl_l = eco_cfg.get('population_labor', {}).get('length', 3)

    cre_p = eco_cfg.get('credit', {}).get('period', 'quarter')
    cre_l = eco_cfg.get('credit', {}).get('length', 4)

    eco_methods = {
        # 'gdp': lambda: economy.gdp(period=gdp_p, length=gdp_l), # Failed to fetch data: 404 - Not Found
        'cpi': lambda: economy.cpi(period=cpi_p, length=cpi_l), # can request but empty data
        'industry_prod': lambda: economy.industry_prod(period=ip_p, length=ip_l),
        'import_export': lambda: economy.import_export(period=ie_p, length=ie_l), # return 0 data
        'retail': lambda: economy.retail(period=rt_p, length=rt_l),
        # 'fdi': lambda: economy.fdi(period=fdi_p, length=fdi_l), # Failed to fetch data: 404 - Not Found
        'money_supply': lambda: economy.money_supply(period=ms_p, length=ms_l), # return 0 data
        'population_labor': lambda: economy.population_labor(period=pl_p, length=pl_l),
        'credit': lambda: economy.credit(period=cre_p, length=cre_l),
        # 'state_budget': lambda: economy.state_budget(period=sb_p, length=sb_l), # Failed to fetch data: 404 - Not Found
        # 'total_investment': lambda: economy.total_investment(period=ti_p, length=ti_l) # Failed to fetch data: 404 - Not Found
    }
    
    print("\n--- 1. ECONOMY DOMAIN ---")
    for name, func in eco_methods.items():
        print(f"[*] Getting data: {name}() ... ", end="")
        try:
            raw_data = func()
            is_valid, message = is_data_valid(raw_data)
            
            if is_valid:
                results[name] = raw_data
                print(f"{message}")
            else:
                # Gán None hoặc giữ DataFrame rỗng tùy kiến trúc downstream của bạn
                results[name] = None 
                print(f"Warning: {message}")
                
        except Exception as e:
            # Lỗi thực sự từ mạng hoặc API (như Timeout, 500 Server Error)
            print(f"API Error: {e}")
            results[name] = None

    # -------------------------------------------------------------------------
    # 2. Currency Domain (Tiền tệ & Lãi suất)
    # -------------------------------------------------------------------------
    currency = mac.currency()
    curr_cfg = getattr(macro_config, 'currency', {})
    
    ex_p = curr_cfg.get('exchange_rate', {}).get('period', 'day')
    ex_l = curr_cfg.get('exchange_rate', {}).get('length', 5)
    
    ir_l = curr_cfg.get('interest_rate', {}).get('length', 3)

    curr_methods = {
        'exchange_rate': lambda: currency.exchange_rate(period=ex_p, length=ex_l),
        'interest_rate': lambda: currency.interest_rate(length=ir_l)
    }
    
    print("\n--- 2. CURRENCY DOMAIN ---")
    for name, func in curr_methods.items():
        print(f"[*] Getting data: {name}() ... ", end="", flush=True)
        try:
            raw_data = func()
            is_valid, message = is_data_valid(raw_data)
            
            if is_valid:
                results[name] = raw_data
                print(f"{message}")
            else:
                results[name] = None 
                print(f"Warning: {message}")
                
        except Exception as e:
            print(f"API Error: {e}")
            results[name] = None

    # -------------------------------------------------------------------------
    # 3. Commodity Domain (Hàng hóa)
    # -------------------------------------------------------------------------
    commodity = mac.commodity()
    cmd_cfg = getattr(macro_config, 'commodity', {})
    
    g_vn = cmd_cfg.get('gold_vn', {}).get('market', 'VN') # VNĐ/lượng
    g_gb = cmd_cfg.get('gold_global', {}).get('market', 'GLOBAL')
    gas_m = cmd_cfg.get('gas', {}).get('market', 'VN') # USD/barrel hoặc USD/tấn
    st_m = cmd_cfg.get('steel', {}).get('market', 'VN')
    pk_m = cmd_cfg.get('pork', {}).get('market', 'VN')

    cmd_methods = {
        'gold_vn': lambda: commodity.gold(market=g_vn),
        'gold_global': lambda: commodity.gold(market=g_gb),
        'gas': lambda: commodity.gas(market=gas_m),
        'oil_crude': lambda: commodity.oil_crude(),
        'coke': lambda: commodity.coke(),
        'steel': lambda: commodity.steel(market=st_m),
        'iron_ore': lambda: commodity.iron_ore(),
        'fertilizer_ure': lambda: commodity.fertilizer_ure(),
        'soybean': lambda: commodity.soybean(),
        'corn': lambda: commodity.corn(),
        'sugar': lambda: commodity.sugar(),
        'pork': lambda: commodity.pork(market=pk_m)
    }
    
    
    print("\n--- 3. COMMODITY DOMAIN ---")
    for name, func in cmd_methods.items():
        print(f"[*] Getting data: {name}() ... ", end="", flush=True)
        try:
            raw_data = func()
            is_valid, message = is_data_valid(raw_data)
            
            if is_valid:
                results[name] = raw_data
                print(f"{message}")
            else:
                results[name] = None 
                print(f"Warning: {message}")
                
        except Exception as e:
            print(f"API Error: {e}")
            results[name] = None

    # print("\n🎉 HOÀN THÀNH QUÁ TRÌNH THU THẬP MACRO LAYER!")
    return results