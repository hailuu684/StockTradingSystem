import unittest
import pandas as pd
import numpy as np
import logging

# Bỏ qua cảnh báo deprecation của Pandas/Vnstock trong lúc chạy test
import warnings
warnings.filterwarnings("ignore")

# Import các Class từ file pipeline v2 của bạn
# Sửa tên module dưới đây nếu file của bạn tên khác
from data_pipeline import PipelineConfig, VnstockMasterMatrixPipeline

class TestVnstockDataPipeline(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        """Khởi tạo cấu hình và Pipeline một lần duy nhất cho toàn bộ test case."""
        print("🚀 Khởi tạo Test Suite cho Vnstock Master Matrix Pipeline...")
        cls.config = PipelineConfig(
            symbol="TCB",
            index_symbol="VNINDEX",
            length="1Y",         
            seq_length=5,        # Cửa sổ trượt 5 ngày
            log_level=logging.ERROR 
        )
        cls.pipeline = VnstockMasterMatrixPipeline(cls.config)

    # =====================================================================
    # PHẦN 1: INTEGRATION TESTS (KIỂM TRA DỮ LIỆU RAW TỪ API)
    # Kiểm tra xem API có trả về dữ liệu đúng chuẩn schema không
    # =====================================================================

    def test_01_market_raw_data(self):
        """Kiểm tra Raw Data của Market Layer (OHLCV)"""
        eq = self.pipeline.market.equity(self.config.symbol)
        df_ohlcv = eq.ohlcv(length="1M")
        
        self.assertIsInstance(df_ohlcv, pd.DataFrame)
        self.assertFalse(df_ohlcv.empty, "Dữ liệu OHLCV đang bị rỗng.")
        
        # Phải chứa các cột thiết yếu
        required_cols = ['time', 'open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            self.assertIn(col, df_ohlcv.columns, f"Thiếu cột '{col}' trong OHLCV")

    def test_02_fundamental_raw_data(self):
        """Kiểm tra Raw Data của Fundamental Layer (Balance Sheet)"""
        eq = self.pipeline.fundamental.equity(self.config.symbol)
        df_bs = eq.balance_sheet(period="quarter")
        
        self.assertIsInstance(df_bs, pd.DataFrame)
        if not df_bs.empty:
            # Chuyển tên cột về chữ thường để dễ test
            cols_lower = [str(c).lower() for c in df_bs.columns]
            self.assertTrue(
                any('assets' in c or 'tài sản' in c for c in cols_lower), 
                "Không tìm thấy cột dữ liệu Tài sản (Assets) trong Balance Sheet"
            )

    def test_03_macro_raw_data(self):
        """Kiểm tra Raw Data của Macro Layer"""
        if self.pipeline.macro is None:
            self.skipTest("Thư viện Macro chưa được cài đặt.")
            
        currency = self.pipeline.macro.currency()
        # Dùng interest_rate với kỳ hạn dài hơn (90 ngày) sẽ ổn định hơn exchange_rate
        df_ir = currency.interest_rate(period="day", length=90)
        
        self.assertIsInstance(df_ir, pd.DataFrame)
        if df_ir.empty:
            # API Vĩ mô thường xuyên bảo trì vào cuối tuần, không nên fail test vì lỗi mạng
            print("\n⚠️ API Macro trả về rỗng (Có thể do lỗi mạng từ nguồn cấp vnstock). Pass mềm.")
        else:
            self.assertTrue(len(df_ir.columns) > 0)


    def test_04_dynamic_feature_router(self):
        """Kiểm tra thuật toán tự động nhận diện và gán Prefix (Dynamic Router)"""
        dummy_df = pd.DataFrame({
            "time": ["2026-01-01", "2026-01-02"],
            "close": [30000, 31000],                # Thuộc MKT_
            "foreign_buy_volume": [1000, 2000],     # Thuộc FLOW_
            "rsi_14": [60, 65],                     # Thuộc INS_
            "pe": [8.5, 8.4],                       # Thuộc VAL_
            "total_assets": [1e12, 1e12],           # Thuộc FUN_
            "weird_column": [1, 2]                  # Cột lạ
        })

        # QUAN TRỌNG: Đổi source_type thành 'insights'
        # Vì 'insights' là domain duy nhất được phép chứa đủ 7 loại Prefix. 
        # Nếu để 'market', hệ thống sẽ cấm VAL_ và FUN_ lọt vào để bảo mật.
        routed_df = self.pipeline.auto_prefix_dataframe(
            dummy_df, source_type="insights", dataset_name="dummy", temporal_mode="daily"
        )

        # Kiểm tra xem có gán đúng Prefix theo bộ Mapping không
        self.assertIn("MKT_close", routed_df.columns)
        self.assertIn("FLOW_foreign_buy_volume", routed_df.columns)
        self.assertIn("INS_rsi_14", routed_df.columns)
        self.assertIn("VAL_pe", routed_df.columns)
        self.assertIn("FUN_total_assets", routed_df.columns)
        self.assertIn("INS_weird_column", routed_df.columns) # Prefix mặc định của insights là INS_

    def test_05_master_matrix_builder(self):
        """Kiểm thử hàm gộp ma trận Master_Matrix chạy end-to-end"""
        master = self.pipeline.build_master_matrix()
        
        self.assertIsInstance(master, pd.DataFrame)
        self.assertFalse(master.empty, "Master Matrix không được tạo ra.")
        self.assertIn("MKT_close", master.columns, "Mất cột MKT_close trọng yếu.")
        
        # Kiểm tra index có phải là Datetime không
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(master.index))
        
        # Đảm bảo không có cột nào lọt ra ngoài Prefix quy định
        allowed_prefixes = ("MKT_", "FLOW_", "INS_", "VAL_", "FUN_", "MAC_", "CMD_")
        for col in master.columns:
            self.assertTrue(
                col.startswith(allowed_prefixes), 
                f"Lỗi Router: Cột '{col}' không có Prefix hợp lệ."
            )

    def test_06_tensor_bundle_builder(self):
        """Kiểm thử việc cắt cửa sổ trượt (Sliding Window) cho Deep Learning"""
        # Lấy master matrix thực tế
        master = self.pipeline.build_master_matrix()
        
        # Tạo tensor với seq_length = 5
        bundle = self.pipeline.build_tensor_bundle(master, seq_length=5, train_ratio=0.8)
        
        # Kiểm tra số chiều (Dimensions) của ma trận
        # X_train phải là 3D: (số mẫu, số ngày, số features)
        self.assertEqual(bundle.X_train.ndim, 3, "X_train phải là ma trận 3D Tensor.")
        self.assertEqual(bundle.X_train.shape[1], 5, "Chiều thứ 2 của X_train phải bằng seq_length (5).")
        
        # y_train phải là 1D (Dự báo 1 giá trị)
        self.assertEqual(bundle.y_train.ndim, 1, "y_train phải là ma trận 1D.")
        
        # Kiểm tra Scale: Dữ liệu phải nằm trong khoảng [0, 1]
        self.assertTrue(np.min(bundle.X_train) >= 0.0, "Dữ liệu bị scale sai (nhỏ hơn 0).")
        self.assertTrue(np.max(bundle.X_train) <= 1.0 + 1e-6, "Dữ liệu bị scale sai (lớn hơn 1).")
        
        # Số lượng label y phải khớp với số lượng mẫu X
        self.assertEqual(bundle.X_train.shape[0], bundle.y_train.shape[0])
        self.assertEqual(bundle.X_valid.shape[0], bundle.y_valid.shape[0])

if __name__ == '__main__':
    # Verbosity=2 để in chi tiết từng bài test Pass/Fail
    unittest.main(verbosity=2)