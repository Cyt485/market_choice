"""量化初筛：基于财务指标和热度控制筛选候选股票"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from config import CONFIG, ValueInvestConfig
from src.data_fetcher import DataFetcher

class StockScreener:
    """价值股票初筛器"""
    
    def __init__(self, config: ValueInvestConfig = CONFIG):
        self.config = config
        self.fetcher = DataFetcher()
        
    def screen_a_shares(self) -> pd.DataFrame:
        """A股初筛"""
        print("🔍 开始 A 股初筛...")
        df = self.fetcher.get_a_share_list()
        if df.empty:
            return df
        
        # 基础过滤
        df['总市值'] = pd.to_numeric(df['总市值'], errors='coerce')
        df['市盈率-动态'] = pd.to_numeric(df['市盈率-动态'], errors='coerce')
        df['换手率'] = pd.to_numeric(df['换手率'], errors='coerce')
        df['量比'] = pd.to_numeric(df['量比'], errors='coerce')
        
        # 市值过滤
        df = df[df['总市值'] >= self.config.MIN_MARKET_CAP_A]
        # 市盈率过滤 (排除负值和过高估值)
        df = df[(df['市盈率-动态'] > 0) & (df['市盈率-动态'] <= self.config.MAX_PE_TTM)]
        # 热度过滤
        df = df[df['换手率'] <= self.config.MAX_TURNOVER_RATIO]
        df = df[df['量比'] <= self.config.MAX_VOLUME_RATIO]
        
        print(f"  A股基础过滤后: {len(df)} 只")
        return df
    
    def screen_hk_shares(self) -> pd.DataFrame:
        """港股初筛"""
        print("🔍 开始港股初筛...")
        df = self.fetcher.get_hk_share_list()
        if df.empty:
            return df
        
        df['总市值'] = pd.to_numeric(df['总市值'], errors='coerce')
        df['市盈率-动态'] = pd.to_numeric(df['市盈率-动态'], errors='coerce')
        df['换手率'] = pd.to_numeric(df['换手率'], errors='coerce')
        
        df = df[df['总市值'] >= self.config.MIN_MARKET_CAP_HK]
        df = df[(df['市盈率-动态'] > 0) & (df['市盈率-动态'] <= self.config.MAX_PE_TTM)]
        df = df[df['换手率'] <= self.config.MAX_TURNOVER_RATIO]
        
        print(f"  港股基础过滤后: {len(df)} 只")
        return df
    
    def enrich_financials(self, df: pd.DataFrame, market: str = 'a') -> pd.DataFrame:
        """增强财务数据"""
        print(f"📊 获取 {market.upper()} 财务数据...")
        results = []
        
        for _, row in df.iterrows():
            code = row['代码']
            try:
                fin = self.fetcher.get_financial_data(code, market)
                cf = self.fetcher.get_cash_flow(code, market)
                
                if not fin:
                    continue
                
                # 基本面过滤
                if fin.get('roe', 0) < self.config.MIN_ROE_TTM:
                    continue
                if fin.get('debt_ratio', 100) > self.config.MAX_DEBT_RATIO:
                    continue
                if fin.get('gross_margin', 0) < self.config.MIN_GROSS_MARGIN:
                    continue
                if fin.get('revenue_growth', -999) < self.config.MIN_REVENUE_GROWTH:
                    continue
                
                # 现金流质量检查
                op_cf = cf.get('operating_cf', 0)
                if op_cf <= 0:
                    continue
                
                # 计算综合评分
                score = self._calculate_score(fin, cf)
                
                result = {
                    'code': code,
                    'name': row['名称'],
                    'market': market,
                    'industry': row.get('所属行业', '未知'),
                    'price': row.get('最新价', 0),
                    'pe_ttm': row.get('市盈率-动态', 0),
                    'market_cap': row.get('总市值', 0),
                    'turnover': row.get('换手率', 0),
                    'roe': fin.get('roe', 0),
                    'debt_ratio': fin.get('debt_ratio', 0),
                    'gross_margin': fin.get('gross_margin', 0),
                    'revenue_growth': fin.get('revenue_growth', 0),
                    'profit_growth': fin.get('profit_growth', 0),
                    'operating_cf': op_cf,
                    'free_cf': cf.get('free_cf_approx', 0),
                    'score': score,
                }
                results.append(result)
                
            except Exception as e:
                continue
        
        result_df = pd.DataFrame(results)
        print(f"  财务过滤后: {len(result_df)} 只")
        return result_df.sort_values('score', ascending=False)
    
    def _calculate_score(self, fin: Dict, cf: Dict) -> float:
        """计算价值投资综合评分"""
        score = 0
        
        # ROE 权重 25%
        roe = fin.get('roe', 0)
        score += min(roe / 30 * 25, 25)  # ROE 30% 得满分
        
        # 低估值 权重 20%
        pe = fin.get('pe', 20)
        score += max(0, (30 - pe) / 30 * 20)
        
        # 成长性 权重 15%
        growth = fin.get('revenue_growth', 0)
        score += min(growth / 50 * 15, 15)
        
        # 现金流质量 权重 20%
        op_cf = cf.get('operating_cf', 0)
        if op_cf > 0:
            score += 20
        
        # 财务安全 权重 20%
        debt = fin.get('debt_ratio', 50)
        score += max(0, (60 - debt) / 60 * 20)
        
        return round(score, 2)
    
    def diversify_by_industry(self, df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
        """按行业分散，每行业最多选1只"""
        selected = []
        industries = set()
        
        for _, row in df.iterrows():
            industry = row['industry']
            if industry not in industries:
                selected.append(row)
                industries.add(industry)
            if len(selected) >= top_n:
                break
        
        return pd.DataFrame(selected)
    
    def run_screening(self) -> pd.DataFrame:
        """执行完整初筛流程"""
        all_candidates = []
        
        if self.config.A_SHARE_ENABLED:
            a_df = self.screen_a_shares()
            a_enriched = self.enrich_financials(a_df, 'a')
            all_candidates.append(a_enriched)
        
        if self.config.HK_SHARE_ENABLED:
            hk_df = self.screen_hk_shares()
            hk_enriched = self.enrich_financials(hk_df, 'hk')
            all_candidates.append(hk_enriched)
        
        if not all_candidates:
            return pd.DataFrame()
        
        combined = pd.concat(all_candidates, ignore_index=True)
        combined = combined.sort_values('score', ascending=False)
        
        # 行业分散
        final = self.diversify_by_industry(combined, self.config.TARGET_INDUSTRY_COUNT)
        
        print(f"\n✅ 初筛完成，选出 {len(final)} 只候选股票")
        return final