"""配置文件：价值投资筛选参数"""

import os
from dataclasses import dataclass

@dataclass
class ValueInvestConfig:
    """价值投资筛选配置"""
    
    # === 市场范围 ===
    A_SHARE_ENABLED: bool = True
    HK_SHARE_ENABLED: bool = True
    
    # === 基本面筛选阈值 ===
    MIN_MARKET_CAP_A: float = 50e8      # A股最小市值 50亿
    MIN_MARKET_CAP_HK: float = 30e8     # 港股最小市值 30亿港币
    MAX_PE_TTM: float = 30              # 市盈率上限
    MIN_ROE_TTM: float = 10             # ROE下限 (%)
    MIN_ROE_3Y_AVG: float = 8           # 3年平均ROE下限
    MAX_DEBT_RATIO: float = 60            # 资产负债率上限 (%)
    MIN_CASH_FLOW_RATIO: float = 0.5    # 经营现金流/净利润 下限
    
    # === 热度控制 ===
    MAX_TURNOVER_RATIO: float = 15      # 换手率上限 (%)
    MAX_VOLUME_RATIO: float = 3.0       # 量比上限 (避免过热)
    
    # === 财务质量 ===
    MIN_REVENUE_GROWTH: float = 0       # 营收增长率下限
    MIN_PROFIT_GROWTH: float = -10      # 净利润增长率下限 (允许小幅下滑)
    MIN_GROSS_MARGIN: float = 20        # 毛利率下限 (%)
    
    # === 行业配置 ===
    TARGET_INDUSTRY_COUNT: int = 10     # 目标行业数量
    MAX_PER_INDUSTRY: int = 1           # 每行业最多选1只
    
    # === DeepSeek ===
    DEEPSEEK_MODEL: str = "deepseek-chat"
    MAX_TOKENS_PER_ANALYSIS: int = 800  # 控制token消耗
    
    # === Server酱 ===
    SERVERCHAN_URL: str = "https://sctapi.ftqq.com/{sendkey}.send"

CONFIG = ValueInvestConfig()

# 环境变量
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY")