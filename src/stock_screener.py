"""量化初筛：基于多源数据的价值投资筛选"""

import pandas as pd
import numpy as np
from typing import List, Dict
from config import CONFIG, ValueInvestConfig
from src.data_fetcher import DataFetcher

class StockScreener:
    """价值股票初筛器（多源容错版）"""
    
    def __init__(self, config: ValueInvestConfig = CONFIG):
        self.config = config
        self.fetcher = DataFetcher()
        
    def screen_a_shares(self) -> pd.DataFrame:
        """A股初筛"""
        print("🔍 开始 A 股初筛...")
        df = self.fetcher.get_a_share_list()
        if df.empty:
            print("  ❌ A股数据获取失败")
            return df
        
        print(f"  获取到 {len(df)} 只 A 股原始数据")
        
        # 数值转换
        df['market_cap'] = pd.to_numeric(df['market_cap'], errors='coerce')
        df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce')
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce')
        df['volume_ratio'] = pd.to_numeric(df['volume_ratio'], errors='coerce')
        
        # 基础过滤
        initial_count = len(df)
        df = df[df['market_cap'] >= self.config.MIN_MARKET_CAP_A]
        df = df[(df['pe_ttm'] > 0) & (df['pe_ttm'] <= self.config.MAX_PE_TTM)]
        df = df[df['turnover'] <= self.config.MAX_TURNOVER_RATIO]
        df = df[df['volume_ratio'] <= self.config.MAX_VOLUME_RATIO]
        
        print(f"  基础过滤: {initial_count} -> {len(df)} 只")
        return df
    
    def screen_hk_shares(self) -> pd.DataFrame:
        """港股初筛"""
        print("🔍 开始港股初筛...")
        df = self.fetcher.get_hk_share_list()
        if df.empty:
            print("  ❌ 港股数据获取失败")
            return df
        
        print(f"  获取到 {len(df)} 只港股原始数据")
        
        df['market_cap'] = pd.to_numeric(df['market_cap'], errors='coerce')
        df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce')
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce')
        
        df = df[df['market_cap'] >= self.config.MIN_MARKET_CAP_HK]
        df = df[(df['pe_ttm'] > 0) & (df['pe_ttm'] <= self.config.MAX_PE_TTM)]
        df = df[df['turnover'] <= self.config.MAX_TURNOVER_RATIO]
        
        print(f"  港股过滤后: {len(df)} 只")
        return df
    
    def enrich_financials(self, df: pd.DataFrame, market: str = 'a') -> pd.DataFrame:
        """增强财务数据（带容错）"""
        print(f"📊 获取 {market.upper()} 财务数据...")
        results = []
        
        for idx, row in df.iterrows():
            code = row['代码'] if '代码' in row else row['code']
            name = row['名称'] if '名称' in row else row['name']
            
            try:
                fin = self.fetcher.get_financial_data(code, market)
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
                
                # 现金流检查
                cf = self.fetcher.get_cash_flow(code, market)
                op_cf = cf.get('operating_cf', 0)
                if op_cf <= 0:
                    continue
                
                score = self._calculate_score(fin, cf)
                
                result = {
                    'code': code,
                    'name': name,
                    'market': market,
                    'industry': row.get('industry', row.get('所属行业', '未知')),
                    'price': row.get('price', 0),
                    'pe_ttm': row.get('pe_ttm', 0),
                    'market_cap': row.get('market_cap', 0),
                    'turnover': row.get('turnover', 0),
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
            
            # 每处理50只打印进度
            if len(results) % 50 == 0 and len(results) > 0:
                print(f"    已处理 {len(results)} 只合格股票...")
        
        result_df = pd.DataFrame(results)
        print(f"  财务过滤后: {len(result_df)} 只")
        return result_df.sort_values('score', ascending=False)
    
    def _calculate_score(self, fin: Dict, cf: Dict) -> float:
        """价值投资综合评分"""
        score = 0
        roe = fin.get('roe', 0)
        score += min(roe / 30 * 25, 25)
        
        pe = fin.get('pe', 20)
        score += max(0, (30 - pe) / 30 * 20)
        
        growth = fin.get('revenue_growth', 0)
        score += min(growth / 50 * 15, 15)
        
        op_cf = cf.get('operating_cf', 0)
        if op_cf > 0:
            score += 20
        
        debt = fin.get('debt_ratio', 50)
        score += max(0, (60 - debt) / 60 * 20)
        
        return round(score, 2)
    
    def diversify_by_industry(self, df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
        """按行业分散"""
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
        """执行完整初筛"""
        all_candidates = []
        
        if self.config.A_SHARE_ENABLED:
            a_df = self.screen_a_shares()
            if not a_df.empty:
                a_enriched = self.enrich_financials(a_df, 'a')
                all_candidates.append(a_enriched)
        
        if self.config.HK_SHARE_ENABLED:
            hk_df = self.screen_hk_shares()
            if not hk_df.empty:
                hk_enriched = self.enrich_financials(hk_df, 'hk')
                all_candidates.append(hk_enriched)
        
        if not all_candidates:
            return pd.DataFrame()
        
        combined = pd.concat(all_candidates, ignore_index=True)
        combined = combined.sort_values('score', ascending=False)
        final = self.diversify_by_industry(combined, self.config.TARGET_INDUSTRY_COUNT)
        
        print(f"\n✅ 初筛完成，选出 {len(final)} 只候选股票")
        return final