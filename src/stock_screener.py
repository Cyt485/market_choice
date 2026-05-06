"""量化初筛：评分制 + 纯行情降级"""

import pandas as pd
import numpy as np
from typing import List, Dict
from config import CONFIG, ValueInvestConfig
from src.data_fetcher import DataFetcher


class StockScreener:
    def __init__(self, config: ValueInvestConfig = CONFIG):
        self.config = config
        self.fetcher = DataFetcher()

    def screen_a_shares(self) -> pd.DataFrame:
        print("🔍 开始 A 股初筛...")
        df = self.fetcher.get_a_share_list()
        if df.empty:
            print("  ❌ A股数据获取失败")
            return df

        print(f"  获取到 {len(df)} 只 A 股原始数据")

        # 数值转换（fillna 防止 NaN 导致过滤失败）
        df['market_cap'] = pd.to_numeric(df['market_cap'], errors='coerce').fillna(0)
        df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce').fillna(-1)
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce').fillna(0)
        df['volume_ratio'] = pd.to_numeric(df['volume_ratio'], errors='coerce').fillna(1.0)

        # 调试输出
        print(f"  [调试] 市值范围: {df['market_cap'].min()/1e8:.2f}亿 ~ {df['market_cap'].max()/1e8:.2f}亿")
        print(f"  [调试] PE范围: {df['pe_ttm'].min():.2f} ~ {df['pe_ttm'].max():.2f}")
        print(f"  [调试] 换手范围: {df['turnover'].min():.2f}% ~ {df['turnover'].max():.2f}%")
        print(f"  [调试] 量比范围: {df['volume_ratio'].min():.2f} ~ {df['volume_ratio'].max():.2f}")

        initial = len(df)

        # 1. 市值过滤（>=20亿），市值为0的跳过此条件（靠评分处理）
        mask_cap = (df['market_cap'] >= self.config.MIN_MARKET_CAP_A) | (df['market_cap'] == 0)
        df = df[mask_cap]

        # 2. PE过滤：允许 -1（无数据），允许 0-50，排除 >50 和 <0（除-1外）
        mask_pe = (df['pe_ttm'] == -1) | ((df['pe_ttm'] > 0) & (df['pe_ttm'] <= self.config.MAX_PE_TTM))
        df = df[mask_pe]

        # 3. 热度过滤
        df = df[df['turnover'] <= self.config.MAX_TURNOVER_RATIO]

        # 4. 量比过滤
        df = df[df['volume_ratio'] <= self.config.MAX_VOLUME_RATIO]

        print(f"  过滤后: {initial} -> {len(df)} 只")
        if len(df) == 0:
            print("  ⚠️ A股过滤后为空，请检查上述调试数据")
        return df

    def screen_hk_shares(self) -> pd.DataFrame:
        print("🔍 开始港股初筛...")
        df = self.fetcher.get_hk_share_list()
        if df.empty:
            print("  ❌ 港股数据获取失败")
            return df

        print(f"  获取到 {len(df)} 只港股原始数据")

        df['market_cap'] = pd.to_numeric(df['market_cap'], errors='coerce').fillna(0)
        df['pe_ttm'] = pd.to_numeric(df['pe_ttm'], errors='coerce').fillna(-1)
        df['turnover'] = pd.to_numeric(df['turnover'], errors='coerce').fillna(0)
        df['volume_ratio'] = pd.to_numeric(df['volume_ratio'], errors='coerce').fillna(1.0)

        print(f"  [调试] 市值范围: {df['market_cap'].min()/1e8:.2f}亿 ~ {df['market_cap'].max()/1e8:.2f}亿")
        print(f"  [调试] PE范围: {df['pe_ttm'].min():.2f} ~ {df['pe_ttm'].max():.2f}")

        initial = len(df)

        # 市值过滤（>=10亿港币），市值为0的跳过
        mask_cap = (df['market_cap'] >= self.config.MIN_MARKET_CAP_HK) | (df['market_cap'] == 0)
        df = df[mask_cap]

        mask_pe = (df['pe_ttm'] == -1) | ((df['pe_ttm'] > 0) & (df['pe_ttm'] <= self.config.MAX_PE_TTM))
        df = df[mask_pe]

        df = df[df['turnover'] <= self.config.MAX_TURNOVER_RATIO]

        print(f"  港股过滤后: {initial} -> {len(df)} 只")
        if len(df) == 0:
            print("  ⚠️ 港股过滤后为空")
        return df

    def enrich_financials(self, df: pd.DataFrame, market: str = 'a') -> pd.DataFrame:
        print(f"📊 获取 {market.upper()} 财务数据并评分...")
        results = []
        success_count = 0
        fail_count = 0

        for idx, row in df.iterrows():
            code = row['代码'] if '代码' in row else row['code']
            name = row['名称'] if '名称' in row else row['name']

            try:
                fin = self.fetcher.get_financial_data(code, market)
                cf = self.fetcher.get_cash_flow(code, market)

                if fin:
                    success_count += 1
                else:
                    fail_count += 1

                score = self._calculate_score(fin, cf, row)

                # 只排除极端差的情况（综合评分<25）
                if score < 25:
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
                    'roe': fin.get('roe', 0) if fin else 0,
                    'debt_ratio': fin.get('debt_ratio', 0) if fin else 0,
                    'gross_margin': fin.get('gross_margin', 0) if fin else 0,
                    'revenue_growth': fin.get('revenue_growth', 0) if fin else 0,
                    'profit_growth': fin.get('profit_growth', 0) if fin else 0,
                    'operating_cf': cf.get('operating_cf', 0) if cf else 0,
                    'has_financial': bool(fin),
                    'score': score,
                }
                results.append(result)

            except Exception as e:
                continue

            if len(results) % 50 == 0 and len(results) > 0:
                print(f"    已处理 {len(results)} 只合格股票...")

        result_df = pd.DataFrame(results)
        print(f"  财务获取成功: {success_count}, 失败: {fail_count}")
        if result_df.empty:
            print(f"  ⚠️ 财务评分后无股票通过")
            return result_df

        print(f"  评分后: {len(result_df)} 只（平均分{result_df['score'].mean():.1f}）")
        return result_df.sort_values('score', ascending=False)

    def _calculate_score(self, fin: Dict, cf: Dict, row: pd.Series) -> float:
        """综合评分（0-100分）"""
        score = 0

        # 1. 估值评分（0-25分）
        pe = row.get('pe_ttm', 50)
        if pe <= 0:
            pe = 50
        if pe <= 10:
            score += 25
        elif pe <= 15:
            score += 22
        elif pe <= 20:
            score += 18
        elif pe <= 30:
            score += 12
        elif pe <= 50:
            score += 6
        else:
            score += 2

        # 2. 市值评分（0-10分）
        cap = row.get('market_cap', 0)
        if cap >= 500e8:
            score += 10
        elif cap >= 100e8:
            score += 8
        elif cap >= 50e8:
            score += 6
        elif cap >= 20e8:
            score += 4
        else:
            score += 2

        # 3. 热度评分（0-10分）
        turnover = row.get('turnover', 0)
        if turnover <= 3:
            score += 10
        elif turnover <= 5:
            score += 8
        elif turnover <= 10:
            score += 5
        elif turnover <= 15:
            score += 3
        else:
            score += 1

        # 4. 量价评分（0-5分）
        vr = row.get('volume_ratio', 1)
        if 0.8 <= vr <= 1.5:
            score += 5
        elif 0.5 <= vr <= 2:
            score += 3
        else:
            score += 1

        # 无财务数据时给保底分
        if not fin:
            score += 25
            return round(min(score, 100), 2)

        # 5. ROE评分（0-20分）
        roe = fin.get('roe', 0)
        if roe >= 20:
            score += 20
        elif roe >= 15:
            score += 16
        elif roe >= 10:
            score += 12
        elif roe >= 5:
            score += 8
        elif roe > 0:
            score += 4

        # 6. 负债评分（0-10分）
        debt = fin.get('debt_ratio', 50)
        if debt <= 30:
            score += 10
        elif debt <= 50:
            score += 8
        elif debt <= 70:
            score += 5
        elif debt <= 80:
            score += 2

        # 7. 成长性评分（0-10分）
        growth = fin.get('revenue_growth', -100)
        if growth >= 30:
            score += 10
        elif growth >= 15:
            score += 8
        elif growth >= 0:
            score += 5
        elif growth >= -10:
            score += 3
        elif growth >= -20:
            score += 1

        # 8. 现金流评分（0-10分）
        if cf and cf.get('operating_cf', 0) > 0:
            score += 10
        elif cf and cf.get('operating_cf', 0) > -1e8:
            score += 5

        return round(min(score, 100), 2)

    def diversify_by_industry(self, df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
        selected = []
        industries = {}

        for _, row in df.iterrows():
            industry = row['industry']
            if industries.get(industry, 0) >= 2:
                continue
            selected.append(row)
            industries[industry] = industries.get(industry, 0) + 1
            if len(selected) >= top_n:
                break

        return pd.DataFrame(selected)

    def run_screening(self) -> pd.DataFrame:
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
            print("\n⚠️ 所有市场均无候选股票")
            return pd.DataFrame()

        combined = pd.concat(all_candidates, ignore_index=True)
        combined = combined.sort_values('score', ascending=False)

        print(f"\n📊 综合评分分布:")
        print(f"   最高分: {combined['score'].max():.1f}")
        print(f"   平均分: {combined['score'].mean():.1f}")
        print(f"   最低分: {combined['score'].min():.1f}")

        final = self.diversify_by_industry(combined, self.config.TARGET_INDUSTRY_COUNT)

        print(f"\n✅ 初筛完成，选出 {len(final)} 只候选股票")
        if not final.empty:
            print(final[['code', 'name', 'market', 'industry', 'score', 'has_financial']].head(10).to_string())

        return final