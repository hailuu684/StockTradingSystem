from vnstock_data import Analytics
from scripts.layer_utils import is_data_valid  # Import hàm validate chung từ dự án của bạn

def analytics_layer(analytics_config):
    """
    Hàm xử lý Analytics Layer (Phân tích định giá vĩ mô).
    Hỗ trợ nạp tham số linh hoạt từ SimpleNamespace 1 tầng và gọi API theo Keyword Arguments.
    """
    print("📊 BẮT ĐẦU THU THẬP DỮ LIỆU ANALYTICS LAYER...\n")
    print("=" * 80)
    
    ana = Analytics()
    results = {}
    
    # 1. Bóc tách cấu hình tầng cha 'valuation' từ SimpleNamespace an toàn
    val_cfg = getattr(analytics_config, 'valuation', {})
    
    # Lấy chỉ số mục tiêu (Mặc định: VNINDEX nếu JSON không khai báo)
    target_index = val_cfg.get('index', 'VNINDEX')
    
    # 2. Bóc tách khoảng thời gian duration cho từng phương thức con
    pe_duration = val_cfg.get('pe', {}).get('duration', '1Y')
    pb_duration = val_cfg.get('pb', {}).get('duration', '1Y')
    eval_duration = val_cfg.get('evaluation', {}).get('duration', '5Y')
    
    print(f"[*] Khởi tạo Valuation Domain cho rổ chỉ số: {target_index}")
    print("-" * 60)
    
    # Khởi tạo miền đối tượng định giá theo index mục tiêu
    val = ana.valuation(target_index)
    
    # Định nghĩa danh sách các phương thức chạy với Keyword Arguments chuẩn v3
    analytics_methods = {
        'pe': lambda: val.pe(duration=pe_duration),
        'pb': lambda: val.pb(duration=pb_duration),
        'evaluation': lambda: val.evaluation(duration=eval_duration)
    }
    
    # 3. Vòng lặp thực thi tự động và kiểm tra tính hợp lệ của DataFrame
    for name, func in analytics_methods.items():
        print(f"[*] Getting data: valuation('{target_index}').{name}() ... ", end="", flush=True)
        try:
            raw_data = func()
            
            # Kiểm thử cấu trúc và số lượng dòng trả về của DataFrame
            is_valid, message = is_data_valid(raw_data)
            if is_valid:
                results[name] = raw_data
                print(f"✅ {message}")
            else:
                results[name] = None
                print(f"⚠️ Warning: {message}")
                
        except Exception as e:
            print(f"❌ API Error: {e}")
            results[name] = None
            
    print("\n🎉 HOÀN THÀNH QUÁ TRÌNH THU THẬP ANALYTICS LAYER!")
    return results
