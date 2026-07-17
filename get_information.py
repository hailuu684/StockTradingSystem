from scripts import get_market_layer, get_fundamental_layer, get_macro_layer, get_insights_layer, get_analytics_layer, get_news_layer
import json
from types import SimpleNamespace
from vnstock_news import Crawler
import pandas as pd 

def main():
    # # 1. Đọc dữ liệu từ file JSON
    # setting_market_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/markets.json"

    # with open(setting_market_path, 'r', encoding='utf-8') as f:
    #     config_dict = json.load(f)

    # # 2. Ép kiểu dictionary thành đối tượng để gọi dạng config.symbol
    # market_config = SimpleNamespace(**config_dict["market_config"])

    # # 3. Truyền vào hàm của bạn để chạy
    # results = get_market_layer.market_layer(market_config)

    # print("\n=== Kết quả ===")
    # print(results['Equity']['history'].sort_values(by='time', ascending=False).head())

    # --------------------------------------------------

    # # 1. Đọc file JSON
    # setting_fundamental_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/fundamentals.json"
    # with open(setting_fundamental_path, 'r', encoding='utf-8') as f:
    #     fundamental_config_raw = json.load(f)

    # fundamental_config = SimpleNamespace(**fundamental_config_raw["fundamental_config"])

    # # 3. Chạy hàm
    # fundamental_results = get_fundamental_layer.fundamental_layer(fundamental_config)

    # # Giờ bạn có thể in kết quả rất sạch sẽ bằng key gốc:
    # print(fundamental_results['note'].head())
    # print(fundamental_results['financial_health'].head())
    # print(fundamental_results['filing'].head())

    # --------------------------------------------------

    # # 1. Đọc file JSON cấu hình Macro
    # setting_macro_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/macro.json"
    # with open(setting_macro_path, 'r', encoding='utf-8') as f:
    #     macro_config_raw = json.load(f)

    # # Sử dụng SimpleNamespace 1 tầng duy nhất
    # macro_config = SimpleNamespace(**macro_config_raw["macro_config"])

    # # 3. Chạy hàm
    # macro_results = get_macro_layer.macro_layer(macro_config)

    # # Giờ bạn có thể in kết quả rất sạch sẽ bằng key gốc:
    # print("\n--- retail ---")
    # print(macro_results['retail'].head())
    
    # print("\n--- VÀNG TRONG NƯỚC ---")
    # print(macro_results['gold_vn'].head())

    # --------------------------------------------------

    # setting_insight_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/insights.json"
    # strategy_insight_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/insights_filter_strategy.json"

    # with open(setting_insight_path, 'r', encoding='utf-8') as f:
    #     insight_config_raw = json.load(f)
    
    # with open(strategy_insight_path, "r", encoding="utf-8") as f:
    #     all_strategies = json.load(f)

    # insight_config = SimpleNamespace(**insight_config_raw["insight_config"])
    # insight_results = get_insights_layer.insights_layer(insight_config, all_strategies)

    # print(insight_results['heatmap'])

    # --------------------------------------------------

    # # 1. Đọc file JSON cấu hình Analytics
    # setting_analytics_path = "./configs/analytics.json"
    # # index co the chon "VNINDEX", "HNX", "VN30"

    # with open(setting_analytics_path, 'r', encoding='utf-8') as f:
    #     analytics_config_raw = json.load(f)

    # # Khởi tạo SimpleNamespace 1 tầng duy nhất đúng thiết kế đồng bộ
    # analytics_config = SimpleNamespace(**analytics_config_raw["analytics_config"])

    # # 2. Thực thi gọi hàm xử lý từ Layer
    # analytics_results = get_analytics_layer.analytics_layer(analytics_config)

    # # 3. In kiểm tra dữ liệu kết quả (Giữ nguyên tên cột gốc reportDate, pe, pb từ Schema)
    # print("\n=== KẾT QUẢ ĐÁNH GIÁ TỔNG HỢP (EVALUATION) ===")
    # if analytics_results['evaluation'] is not None:
    #     print(analytics_results['evaluation'].head())
    # else:
    #     print("Không có dữ liệu Evaluation.")

    # --------------------------------------------------
    # --------------------------------------------------

    # # RSS Parser - Lấy từ RSS Feed
    # crawler = Crawler(site_name="vnexpress")
    # articles = crawler.get_articles_from_feed(limit_per_feed=3)  # Returns List[Dict]

    # # Convert to DataFrame nếu cần
    # df = pd.DataFrame(articles)
    # print(df.head())

    news_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/news.json"
    news_web_path = "/home/luutunghai@gmail.com/projects/Forex/Stocks/configs/news_websites.json"

    with open(news_path, 'r', encoding='utf-8') as f:
        news = json.load(f)
    
    with open(news_web_path, "r", encoding="utf-8") as f:
        news_websites = json.load(f)

    # Chạy hàm lấy tin tức
    news_data_dict = get_news_layer.news_layer(news)
    
    df = news_data_dict["data"]
    files = news_data_dict["files"]
    errors = news_data_dict["errors"]

    print(df.head())
    print(files)
    print(errors)


if __name__== "__main__":
    main()


    