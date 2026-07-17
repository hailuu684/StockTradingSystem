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

def format_financial_numbers(df):
    """
    Hàm dùng chung tự động nhận diện và quy đổi mọi chỉ số tiền tệ sang đơn vị phù hợp.
    Sửa lỗi bỏ sót cột do đổi tên giữa chừng (safe rename) và loại trừ các cột năm.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    
    df = df.copy()
    new_columns = {} # Dùng để lưu danh sách các cột cần đổi tên sau khi lặp xong
    
    # Danh sách các cột chứa thông tin thời gian cần bỏ qua hoàn toàn, không chia
    exclude_time_cols = ['year', 'period', 'year_period', 'month', 'quarter']
    
    for col in df.columns:
        # Loại trừ các cột thời gian đã định nghĩa ở trên
        if any(time_keyword in str(col).lower() for time_keyword in exclude_time_cols):
            continue
            
        # Chỉ xử lý các cột có kiểu dữ liệu là số
        if pd.api.types.is_numeric_dtype(df[col]):
            abs_mean = df[col].abs().mean()
            
            # Trường hợp 1: Dữ liệu tài chính rất lớn (> 100 Triệu VND) -> Đổi sang Tỷ
            if abs_mean > 100_000_000:
                df[col] = (df[col] / 1_000_000_000).round(2)
                new_columns[col] = f"{col}"
                
            # Trường hợp 2: Dữ liệu giao dịch thị trường (từ 10,000 đến 100 Triệu) -> Đổi sang Triệu
            elif 10_000 < abs_mean <= 100_000_000:
                df[col] = (df[col] / 1_000_000).round(2)
                new_columns[col] = f"{col}"
                
            # Các trường hợp chỉ số nhỏ (PE, ROE, EPS dưới 10,000) sẽ giữ nguyên
            
    # Tiến hành đổi tên hàng loạt một cách an toàn sau khi vòng lặp kết thúc
    if new_columns:
        df.rename(columns=new_columns, inplace=True)

    return df


# def is_data_valid(df):
#     """
#     Kiểm tra tính hợp lệ của dữ liệu trả về từ API.
#     Trả về: (bool, str) -> (Trạng thái hợp lệ, Lý do nếu không hợp lệ)
#     """
#     # 1. Kiểm tra nếu kết quả là None
#     if df is None:
#         return False, "Data is None"
    
#     # 2. Kiểm tra đúng kiểu DataFrame hoặc Series (phòng trường hợp API trả về dict/list lỗi)
#     if not isinstance(df, (pd.DataFrame, pd.Series)):
#         return False, f"Invalid type ({type(df).__name__})"
        
#     # 3. Kiểm tra DataFrame có bị rỗng (0 dòng) không
#     if df.empty:
#         return False, "Empty DataFrame (0 rows)"
        
#     # 4. Kiểm tra xem toàn bộ các cột có bị rỗng (toàn NaN/None) hay không
#     if df.isna().all().all():
#         return False, "All values are NaN/None"
        
#     return True, f"Success ({len(df)} rows)"

def is_data_valid(df_or_list):
    """
    Kiểm tra dữ liệu trả về (hỗ trợ cả DataFrame và List[Dict]).
    """
    if not df_or_list or len(df_or_list) == 0:
        return False, "Empty data returned"
    
    # 1. Hợp lệ nếu là DataFrame
    if isinstance(df_or_list, pd.DataFrame):
        if df_or_list.empty or df_or_list.isna().all().all():
            return False, "Empty or NaN DataFrame"
        return True, f"Success ({len(df_or_list)} rows)"
    
    # 2. Hợp lệ nếu là List (Đặc trưng của RSS)
    if isinstance(df_or_list, list):
        return True, f"Success ({len(df_or_list)} articles)"
        
    return False, f"Invalid type ({type(df_or_list).__name__})"