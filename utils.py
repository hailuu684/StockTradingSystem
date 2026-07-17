import pandas as pd

def convert_to_millions(df):
    """
    Hàm tự động tìm các cột giá trị tiền tệ và quy đổi sang đơn vị Triệu VND.
    Giữ nguyên tối đa 2 chữ số thập phân cho dễ nhìn.
    """
    if not isinstance(df, pd.DataFrame):
        return df
    
    df = df.copy() # Tránh cảnh báo SettingWithCopyWarning của Pandas
    
    # Tìm các cột có chứa 'val', 'value' (như buy_val, total_value) hoặc 'market_cap'
    money_columns = [col for col in df.columns if 'val' in col.lower() or 'market_cap' in col.lower()]
    
    for col in money_columns:
        # Đảm bảo chỉ chia nếu cột đó thực sự chứa dữ liệu dạng số
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = (df[col] / 1_000_000).round(2)
            # Đổi tên cột để ghi chú rõ đơn vị
            df.rename(columns={col: f"{col}_(Triệu)"}, inplace=True)
            
    return df

def format_financial_numbers(df, divider=1_000_000_000, unit_name="Tỷ"):
    """
    Hàm tự động nhận diện các cột chứa số tiền lớn (BCTC) 
    và quy đổi sang đơn vị Tỷ VNĐ / Triệu VNĐ.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    
    df = df.copy()
    
    for col in df.columns:
        # Chỉ xử lý các cột có kiểu dữ liệu là số (float/int)
        if pd.api.types.is_numeric_dtype(df[col]):
            # Kiểm tra: Nếu giá trị trung bình tuyệt đối của cột > 10,000 
            # (để tránh vô tình chia các cột tỷ số ratio như PE, ROE, Beta...)
            if df[col].abs().mean() > 10000:
                df[col] = (df[col] / divider).round(2)
                df.rename(columns={col: f"{col} ({unit_name})"}, inplace=True)
                
    return df


def _run_and_print_test(name, func, results_dict):
    """Hàm phụ trợ để thực thi và in kết quả"""
    print(f"[*] Đang lấy dữ liệu: {name} ... ", end="")
    try:
        data = func()
        results_dict[name] = data
        print("✅ Thành công")
        
        if isinstance(data, pd.DataFrame):
            print(data.head(3).to_string())
        else:
            print(data)
        print("-" * 60)
    except Exception as e:
        print(f"❌ Lỗi: {e}")
        print("-" * 60)