import json

def get_daily_quant_prompt(symbol, date_str, insight_data, news_list, tech_analysis):
    """
    Hàm tạo prompt cho LLM. 
    Chuyển đổi các dict/list thành chuỗi JSON đẹp mắt (indent=2) để LLM dễ đọc.
    """
    
    # Lấy 5 ngày giao dịch gần nhất để LLM thấy được xu hướng
    # Chuyển thành định dạng Markdown (Yêu cầu cài thư viện 'tabulate': pip install tabulate)
    df_recent = insight_data.tail(5)
    insight_markdown = df_recent.to_markdown()

    tech_str = json.dumps(tech_analysis, indent=2, ensure_ascii=False)
    
    # Format list tin tức thành các gạch đầu dòng
    news_str = "\n".join([f"- {news}" for news in news_list])
    
    prompt = f"""
            Bạn là một Giám đốc Phân tích Đầu tư (CIO) tại một quỹ Quant.
            Nhiệm vụ của bạn là tổng hợp và đưa ra quyết định giao dịch cho mã cổ phiếu {symbol} vào ngày {date_str}.

            Dưới đây là các dữ liệu được hệ thống tự động trích xuất:

            [1. DỮ LIỆU ĐỊNH LƯỢNG & VĨ MÔ (INSIGHT DATA)]
            {insight_markdown}

            [2. PHÂN TÍCH KỸ THUẬT (TECHNICAL ANALYSIS)]
            {tech_str}

            [3. TIN TỨC TRONG NGÀY (LATEST NEWS)]
            {news_str}

            === YÊU CẦU ===
            1. Hãy đối chiếu các chỉ báo Kỹ thuật (Technical) với Dòng tiền (trong Insight) xem chúng có đồng thuận không?
            2. Tin tức hiện tại đang hỗ trợ hay gây áp lực lên giá?
            3. Đưa ra Khuyến nghị Giao dịch (MUA/BÁN/NẮM GIỮ) ở giá nào và giải thích ngắn gọn lý do.
            """
    return prompt.strip()