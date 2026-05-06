"""数据获取：akshare 封装，支持 A 股 + 港股"""

import akshare as ak
import pandas as pd
import numpy as np
from typing import List, Dict, Optional
import time
import warnings
warnings.filterwarnings('ignore')

class DataFetcher:
    """股票数据获取器"""
    
    def __init__(self):
        self._cache = {}
        
    def get_a_share_list(self) -> pd.DataFrame:
        """获取 A 股全量列表"""
        try:
            df = ak.stock_zh_a_spot_em()
            # 过滤 ST、退市、北交所
            df = df[~df['名称'].str.contains('ST|退|摘牌', na=False)]
            df = df[~df['代码'].str.startswith(('8', '4', '9'))]  # 排除北交所
            return df[['代码', '名称', '最新价', '涨跌幅', '换手率', '市盈率-动态', 
                       '总市值', '所属行业', '量比', '振幅']].copy()
        except Exception as e:
            print(f"获取A股列表失败: {e}")
            return pd.DataFrame()
    
    def get_hk_share_list(self) -> pd.DataFrame:
        """获取港股全量列表"""
        try:
            df = ak.stock_hk_ggt_components_em()
            # 补充基本信息
            spot = ak.stock_hk_spot_em()
            spot = spot[['代码', '名称', '最新价', '涨跌幅', '换手率', '市盈率', 
                        '总市值', '所属行业']].copy()
            spot.columns = ['代码', '名称', '最新价', '涨跌幅', '换手率', 
                          '市盈率-动态', '总市值', '所属行业']
            spot['量比'] = 1.0  # 港股量比数据需另外获取，简化处理
            spot['振幅'] = 0.0
            return spot
        except Exception as e:
            print(f"获取港股列表失败: {e}")
            return pd.DataFrame()
    
    def get_financial_data(self, code: str, market: str = 'a') -> Dict:
        """
        获取财务数据
        market: 'a' 或 'hk'
        """
        try:
            if market == 'a':
                # A股财务指标
                fin = ak.stock_financial_report_sina(stock=code, symbol="利润表")
                if fin.empty:
                    return {}
                
                # 获取关键指标
                indicator = ak.stock_financial_analysis_indicator(symbol=code)
                if indicator.empty:
                    return {}
                
                latest = indicator.iloc[0] if isinstance(indicator, pd.DataFrame) else indicator
                
                return {
                    'roe': float(latest.get('净资产收益率', 0)),
                    'roe_diluted': float(latest.get('净资产收益率(扣除非经常性损益)', 0)),
                    'debt_ratio': float(latest.get('资产负债率', 100)),
                    'gross_margin': float(latest.get('销售毛利率', 0)),
                    'revenue_growth': float(latest.get('营业收入同比增长率', 0)),
                    'profit_growth': float(latest.get('净利润同比增长率', 0)),
                    'eps': float(latest.get('基本每股收益', 0)),
                }
            else:
                # 港股财务数据（简化，实际需要更复杂的接口）
                return self._get_hk_financial_simple(code)
                
        except Exception as e:
            print(f"获取 {code} 财务数据失败: {e}")
            return {}
    
    def _get_hk_financial_simple(self, code: str) -> Dict:
        """简化港股财务获取（akshare港股财务接口有限）"""
        try:
            # 尝试获取港股财务摘要
            df = ak.stock_hk_financial_report_em(symbol=code, indicator="财务摘要")
            if df.empty:
                return {}
            latest = df.iloc[0]
            return {
                'roe': float(latest.get('净资产收益率', 0)),
                'debt_ratio': float(latest.get('资产负债比率', 100)),
                'gross_margin': float(latest.get('毛利率', 0)),
                'revenue_growth': float(latest.get('营业额同比增长', 0)),
                'profit_growth': float(latest.get('股东应占溢利同比增长', 0)),
                'eps': float(latest.get('每股盈利', 0)),
            }
        except:
            return {}
    
    def get_cash_flow(self, code: str, market: str = 'a') -> Dict:
        """获取现金流数据"""
        try:
            if market == 'a':
                cf = ak.stock_cash_flow_sheet_by_report_em(symbol=code)
                if cf.empty:
                    return {}
                latest = cf.iloc[0]
                return {
                    'operating_cf': float(latest.get('经营活动产生的现金流量净额', 0)),
                    'investing_cf': float(latest.get('投资活动产生的现金流量净额', 0)),
                    'financing_cf': float(latest.get('筹资活动产生的现金流量净额', 0)),
                    'free_cf_approx': float(latest.get('经营活动产生的现金流量净额', 0)) - 
                                     abs(float(latest.get('购建固定资产、无形资产和其他长期资产支付的现金', 0))),
                }
            return {}
        except:
            return {}
    
    def get_industry_ranking(self) -> pd.DataFrame:
        """获取行业涨跌幅排名，用于判断行业热度"""
        try:
            df = ak.stock_board_industry_name_em()
            df = df[['板块名称', '涨跌幅', '主力净流入', '换手率']].copy()
            df = df.sort_values('涨跌幅', ascending=False)
            return df
        except:
            return pd.DataFrame()