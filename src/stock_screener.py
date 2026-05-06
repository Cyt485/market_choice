"""量化初筛：基于综合评分的价值投资筛选（避免过度过滤）"""

import pandas as pd
import numpy as np
from typing import List, Dict
from config import CONFIG, ValueInvestConfig
from src.data_fetcher import DataFetcher

class StockScreener:
    """价值股票初筛器（评分制版）"""
    
    def __init__(self, config: ValueInvestConfig = CONFIG):
        self.config = config
        self.fetcher = DataFetcher()
        
    def screen_a_shares(self) -> pd.DataFrame:
        """A股初筛（只过滤极端情况，保留评分空间）"""
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
        
        # === 只过滤极端垃圾股（非常宽松的硬门槛）===
        initial_count = len(df)
        
        # 1. 市值过滤：排除微型股（<20亿）
        df = df[df['market_cap'] >= self.config.MIN_MARKET_CAP_A]
        
        # 2. PE过滤：只排除亏损股（PE<0）和极端泡沫（PE>100）
        df = df[(df['pe_ttm'] > 0) | (df['pe_ttm'] == -1)]  # -1表示无PE数据
        df = df[(df['pe_ttm'] <= self.config.MAX_PE_TTM) | (df['pe_ttm'] == -1)]
        
        # 3. 热度过滤：只排除极度过热（换手率>20%）
        df = df[df['turnover'] <= self.config.MAX_TURNOVER_RATIO]
        
        # 4. 量比过滤：只排除异常放量（量比>5）
        df = df[df['volume_ratio'] <= self.config.MAX_VOLUME_RATIO]
        
        print(f"  宽松过滤后: {initial_count} -> {len(df)} 只（保留{(len(df)/initial_count*100):.1f}%）")
        return df
    
    def screen_hk_shares(self) -> pd.DataFrame:
        """港股初筛（同样宽松）"""
        print("🔍 开始港股初筛...")
        df = self.fetcher.get_hk_share_list()
        if df.empty:
            print("  ❌ 港股数据获取失败")
            return df
        
        print(f"  获取到 {len(df)} 只港股原始数据")
        
        df['market_cap'] = pd.to_numeric(df['market_cap'], errors='coerce')
        df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce')
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce')
        
        # 宽松过滤
        initial_count = len(df)
        df = df[df['market_cap'] >= self.config.MIN_MARKET_CAP_HK]
        df = df[(df['pe_ttm'] > 0) | (df['pe_ttm'] == -1)]
        df = df[df['pe_ttm'] <= self.config.MAX_PE_TTM]
        df = df[df['turnover'] <= self.config.MAX_TURNOVER_RATIO]
        
        print(f"  港股过滤后: {initial_count} -> {len(df)} 只")
        return df
    
    def enrich_financials(self, df: pd.DataFrame, market: str = 'a') -> pd.DataFrame:
        """增强财务数据 + 综合评分（替代硬门槛）"""
        print(f"📊 获取 {market.upper()} 财务数据并评分...")
        results = []
        
        for idx, row in df.iterrows():
            code = row['代码'] if '代码' in row else row['code']
            name = row['名称'] if '名称' in row else row['name']
            
            try:
                fin = self.fetcher.get_financial_data(code, market)
                if not fin:
                    continue  # 无财务数据跳过
                
                cf = self.fetcher.get_cash_flow(code, market)
                
                # === 计算综合评分（0-100分）===
                score = self._calculate_comprehensive_score(fin, cf, row)
                
                # === 只排除极端差的情况（综合评分<30）===
                if score < 30:
                    continue
                
                result = {
                    'code': code,
                    'name': name,
                    'market': market,
                    'industry': row.get('industry', row.get('所属行业', '未知')),
                    'price': row.get('price', 0),
                    'pe_ttm': row.get('pe_ttm', 0),
                    'market_cap': row.get('market_cap', 0),
                    'turnover': row.get('turnover', 0),
                    'volume_ratio': row.get('volume_ratio', 0),
                    # 原始财务数据
                    'roe': fin.get('roe', 0),
                    'roe_diluted': fin.get('roe_diluted', 0),
                    'debt_ratio': fin.get('debt_ratio', 0),
                    'gross_margin': fin.get('gross_margin', 0),
                    'revenue_growth': fin.get('revenue_growth', 0),
                    'profit_growth': fin.get('profit_growth', 0),
                    'eps': fin.get('eps', 0),
                    'operating_cf': cf.get('operating_cf', 0),
                    'free_cf': cf.get('free_cf_approx', 0),
                    'cf_to_profit': 0,  # 现金流/净利润比
                    # 评分
                    'score': score,
                    'score_breakdown': self._get_score_breakdown(fin, cf, row),
                }
                
                # 计算现金流覆盖比
                if fin.get('eps', 0) > 0 and result['operating_cf'] != 0:
                    # 近似：经营现金流 / (EPS * 股本)，简化用绝对值比较
                    result['cf_to_profit'] = result['operating_cf'] / (fin.get('eps', 1) * 1e8)
                
                results.append(result)
                
            except Exception as e:
                continue
            
            if len(results) % 100 == 0 and len(results) > 0:
                print(f"    已处理 {len(results)} 只合格股票...")
        
        result_df = pd.DataFrame(results)
        if result_df.empty:
            print(f"  ⚠️ 财务评分后无股票通过")
            return result_df
            
        print(f"  财务评分后: {len(result_df)} 只（平均分{result_df['score'].mean():.1f}）")
        return result_df.sort_values('score', ascending=False)
    
    def _calculate_comprehensive_score(self, fin: Dict, cf: Dict, row: pd.Series) -> float:
        """
        综合评分系统（0-100分）
        替代硬门槛，给每只股票的各个方面打分
        """
        score = 0
        weights = {
            'roe': self.config.SCORE_WEIGHT_ROE,
            'valuation': self.config.SCORE_WEIGHT_VALUATION,
            'growth': self.config.SCORE_WEIGHT_GROWTH,
            'cashflow': self.config.SCORE_WEIGHT_CASHFLOW,
            'safety': self.config.SCORE_WEIGHT_SAFETY,
            'quality': self.config.SCORE_WEIGHT_QUALITY,
        }
        
        # 1. ROE 评分（0-20分）
        roe = fin.get('roe', 0)
        if roe >= 20:
            score += weights['roe']
        elif roe >= 15:
            score += weights['roe'] * 0.8
        elif roe >= 10:
            score += weights['roe'] * 0.6
        elif roe >= 5:
            score += weights['roe'] * 0.3
        elif roe > 0:
            score += weights['roe'] * 0.1
        
        # 2. 估值评分（0-20分）—— 低PE得分高，但高PE不一定差
        pe = row.get('pe_ttm', 50)
        if pe <= 0:
            pe = 50  # 亏损股给中等估值
        if pe <= 10:
            score += weights['valuation']  # 极低估值，价值洼地
        elif pe <= 20:
            score += weights['valuation'] * 0.8
        elif pe <= 30:
            score += weights['valuation'] * 0.6
        elif pe <= 50:
            score += weights['valuation'] * 0.3
        else:
            score += weights['valuation'] * 0.1
        
        # 3. 成长性评分（0-15分）—— 允许负增长
        rev_growth = fin.get('revenue_growth', -100)
        profit_growth = fin.get('profit_growth', -100)
        avg_growth = (rev_growth + profit_growth) / 2 if profit_growth != -100 else rev_growth
        
        if avg_growth >= 30:
            score += weights['growth']
        elif avg_growth >= 15:
            score += weights['growth'] * 0.8
        elif avg_growth >= 0:
            score += weights['growth'] * 0.5
        elif avg_growth >= -10:
            score += weights['growth'] * 0.3  # 轻微下滑，可能是周期底部
        elif avg_growth >= -20:
            score += weights['growth'] * 0.1  # 明显下滑，但可能已price in
        
        # 4. 现金流评分（0-20分）—— 核心指标
        op_cf = cf.get('operating_cf', 0)
        if op_cf > 0:
            if op_cf > 1e9:  # 10亿以上
                score += weights['cashflow']
            elif op_cf > 5e8:
                score += weights['cashflow'] * 0.8
            elif op_cf > 1e8:
                score += weights['cashflow'] * 0.6
            else:
                score += weights['cashflow'] * 0.4
        else:
            # 现金流为负，但看是否因为扩张投资
            inv_cf = cf.get('investing_cf', 0)
            if inv_cf < 0 and op_cf > inv_cf * 0.5:  # 投资支出大但经营还能覆盖部分
                score += weights['cashflow'] * 0.2  # 扩张期，给予一定认可
        
        # 5. 财务安全评分（0-15分）
        debt = fin.get('debt_ratio', 50)
        if debt <= 30:
            score += weights['safety']
        elif debt <= 50:
            score += weights['safety'] * 0.8
        elif debt <= 70:
            score += weights['safety'] * 0.5
        elif debt <= 80:
            score += weights['safety'] * 0.2
        # >80% 不得分（但不过滤）
        
        # 6. 盈利质量评分（0-10分）
        gross = fin.get('gross_margin', 0)
        if gross >= 40:
            score += weights['quality']
        elif gross >= 30:
            score += weights['quality'] * 0.7
        elif gross >= 20:
            score += weights['quality'] * 0.4
        elif gross >= 10:
            score += weights['quality'] * 0.2
        # 低毛利行业（如零售）不得分但不扣分
        
        # 扣非ROE加分（说明利润真实）
        roe_diluted = fin.get('roe_diluted', 0)
        if roe_diluted >= roe * 0.9:  # 扣非ROE接近ROE
            score += 5  # 额外加分
        
        return round(min(score, 100), 2)
    
    def _get_score_breakdown(self, fin: Dict, cf: Dict, row: pd.Series) -> str:
        """获取评分明细（用于调试）"""
        parts = []
        roe = fin.get('roe', 0)
        pe = row.get('pe_ttm', 0)
        debt = fin.get('debt_ratio', 0)
        op_cf = cf.get('operating_cf', 0)
        
        parts.append(f"ROE{roe:.1f}%")
        parts.append(f"PE{pe:.1f}")
        parts.append(f"负债{debt:.1f}%")
        parts.append(f"经营现金流{op_cf/1e8:.1f}亿")
        
        return ", ".join(parts)
    
    def diversify_by_industry(self, df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
        """按行业分散，但允许同一行业多选如果评分差距大"""
        selected = []
        industries = {}
        
        for _, row in df.iterrows():
            industry = row['industry']
            
            # 行业配额：最多2只（放宽）
            if industries.get(industry, 0) >= 2:
                continue
            
            selected.append(row)
            industries[industry] = industries.get(industry, 0) + 1
            
            if len(selected) >= top_n:
                break
        
        return pd.DataFrame(selected)
    
    def run_screening(self) -> pd.DataFrame:
        """执行完整初筛（优化版）"""
        all_candidates = []
        
        if self.config.A_SHARE_ENABLED:
            a_df = self.screen_a_shares()
            if not a_df.empty:
                a_enriched = self.enrich_financials(a_df, 'a')
                if not a_enriched.empty:
                    all_candidates.append(a_enriched)
        
        if self.config.HK_SHARE_ENABLED:
            hk_df = self.screen_hk_shares()
            if not hk_df.empty:
                hk_enriched = self.enrich_financials(hk_df, 'hk')
                if not hk_enriched.empty:
                    all_candidates.append(hk_enriched)
        
        if not all_candidates:
            print("\n⚠️ 所有市场均无候选股票，请检查数据源")
            return pd.DataFrame()
        
        combined = pd.concat(all_candidates, ignore_index=True)
        combined = combined.sort_values('score', ascending=False)
        
        print(f"\n📊 综合评分分布:")
        print(f"   最高分: {combined['score'].max():.1f}")
        print(f"   平均分: {combined['score'].mean():.1f}")
        print(f"   中位数: {combined['score'].median():.1f}")
        print(f"   最低分: {combined['score'].min():.1f}")
        
        final = self.diversify_by_industry(combined, self.config.TARGET_INDUSTRY_COUNT)
        
        print(f"\n✅ 初筛完成，选出 {len(final)} 只候选股票")
        if not final.empty:
            print(f"\n🏆  top 10 股票:")
            print(final[['code', 'name', 'market', 'industry', 'score']].head(10).to_string())
        
        return final