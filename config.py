"""配置文件：价值投资筛选参数（优化版 v2）—— 多数据源兜底 + 自适应阈值"""

import os
from dataclasses import dataclass, field

@dataclass
class ValueInvestConfig:
    """价值投资筛选配置 —— 优化版，避免过度筛选"""
    
    # === 市场范围 ===
    A_SHARE_ENABLED: bool = True
    HK_SHARE_ENABLED: bool = True
    
    # === 市值要求（降低门槛，增加小盘价值股）===
    MIN_MARKET_CAP_A: float = 20e8      # A股最小市值 20亿（原50亿）
    MIN_MARKET_CAP_HK: float = 10e8     # 港股最小市值 10亿港币（原30亿）
    
    # === 估值指标（放宽PE限制，价值股不一定低PE）===
    MAX_PE_TTM: float = 50              # 市盈率上限 50（原30，允许合理溢价）
    MIN_PE_TTM: float = 0               # 允许低PE（如银行、能源）
    
    # === 盈利能力（分级制，不一刀切）===
    MIN_ROE_TTM: float = 5              # ROE下限 5%（原10%，经济下行周期放宽）
    PREFERRED_ROE: float = 10           # 优先ROE（高于此加分）
    
    # === 财务安全（行业差异化）===
    MAX_DEBT_RATIO: float = 80          # 资产负债率上限 80%（原60%，银行/地产可达90%）
    PREFERRED_DEBT_RATIO: float = 50    # 理想负债率（低于此加分）
    
    # === 成长性（允许负增长，看相对改善）===
    MIN_REVENUE_GROWTH: float = -20     # 营收增长率下限 -20%（原0%，允许周期低谷）
    MIN_PROFIT_GROWTH: float = -30      # 净利润增长率下限 -30%（允许一次性亏损）
    
    # === 现金流（核心指标，保持严格但允许例外）===
    MIN_CASH_FLOW_RATIO: float = 0.3    # 经营现金流/净利润 下限 0.3（原0.5）
    STRICT_CASH_FLOW: bool = False      # 是否强制现金流为正（改为False，评分制）
    
    # === 热度控制 ===
    MAX_TURNOVER_RATIO: float = 20      # 换手率上限 20%（原15%，放宽）
    MAX_VOLUME_RATIO: float = 5.0       # 量比上限 5（原3.0，放宽）
    
    # === 行业配置 ===
    TARGET_INDUSTRY_COUNT: int = 10     # 目标行业数量
    MAX_PER_INDUSTRY: int = 2           # 每行业最多选2只（放宽，避免过度集中）
    
    # === 🆕 自适应阈值（解决推送股票过少问题）===
    MIN_FINAL_PICKS: int = 5            # 最少推送股票数，不足时自动降级
    MIN_SCORE_THRESHOLD: float = 15.0   # 最低评分门槛（原25，降低到15）
    AUTO_RELAX_FILTERS: bool = True     # 候选不足时自动放宽过滤条件
    
    # === 评分权重 ===
    SCORE_WEIGHT_ROE: float = 20        # ROE权重
    SCORE_WEIGHT_VALUATION: float = 20  # 估值权重
    SCORE_WEIGHT_GROWTH: float = 15     # 成长性权重
    SCORE_WEIGHT_CASHFLOW: float = 20   # 现金流权重
    SCORE_WEIGHT_SAFETY: float = 15     # 财务安全权重
    SCORE_WEIGHT_QUALITY: float = 10    # 盈利质量权重
    
    # === 🆕 多数据源配置 ===
    DATA_SOURCE_ORDER: list = field(default_factory=lambda: [
        "akshare_eastmoney",    # 东财（主）
        "akshare_sina",         # 新浪
        "tencent_qt",           # 腾讯行情
        "local_fallback",       # 本地硬编码兜底
    ])
    REQUEST_TIMEOUT: int = 20          # 单次请求超时（秒）
    MAX_RETRIES: int = 2               # 每个数据源最大重试次数
    
    # === DeepSeek ===
    DEEPSEEK_MODEL: str = "deepseek-chat"
    MAX_TOKENS_PER_ANALYSIS: int = 1200  # 增加token预算
    AI_MAX_RETRIES: int = 2              # AI API重试次数
    
    # === Server酱 ===
    SERVERCHAN_URL: str = "https://sctapi.ftqq.com/{sendkey}.send"

CONFIG = ValueInvestConfig()

# 环境变量
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
SERVERCHAN_SENDKEY = os.getenv("SERVERCHAN_SENDKEY")
