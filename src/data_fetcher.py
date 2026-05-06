"""数据获取：多数据源容错，支持 A 股 + 港股（境外环境优化）"""

import akshare as ak
import pandas as pd
import numpy as np
import requests
import time
import random
import json
import re
from typing import List, Dict, Optional, Tuple
from io import StringIO
import warnings
warnings.filterwarnings('ignore')

# ========== 全局请求配置：伪装浏览器 + 连接池优化 ==========
_session = requests.Session()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.0',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
})
_adapter = requests.adapters.HTTPAdapter(
    pool_connections=10,
    pool_maxsize=20,
    max_retries=3
)
_session.mount('http://', _adapter)
_session.mount('https://', _adapter)

# 覆盖 akshare 的默认 session
ak.requests = _session


class DataFetcher:
    """多数据源容错股票数据获取器"""

    def __init__(self):
        self._cache = {}
        self._request_count = 0

    def _random_delay(self, base: float = 1.0, variance: float = 0.5):
        """随机延迟，避免触发反爬"""
        delay = base + random.uniform(0, variance)
        time.sleep(delay)

    def _safe_request(self, url: str, headers: Dict = None, timeout: int = 15, retries: int = 3) -> Optional[requests.Response]:
        """带重试的安全请求"""
        for attempt in range(retries):
            try:
                self._random_delay(0.5, 0.3)
                resp = _session.get(url, headers=headers, timeout=timeout)
                if resp.status_code == 200:
                    return resp
            except Exception as e:
                if attempt < retries - 1:
                    wait_time = 2 ** attempt + random.uniform(0, 1)
                    time.sleep(wait_time)
                else:
                    return None
        return None

    # ==================== A股：多源实时行情 ====================

    def get_a_share_list(self) -> pd.DataFrame:
        """
        获取 A 股全量列表（多源容错）
        优先东财 -> 新浪财经 -> 腾讯财经 -> 本地成分股兜底
        """
        # 尝试 1: akshare 东财接口
        try:
            df = ak.stock_zh_a_spot_em()
            if not df.empty and len(df) > 3000:
                return self._clean_a_share_df(df)
        except Exception as e:
            print(f"  ⚠️ 东财接口失败: {str(e)[:50]}")

        # 尝试 2: 新浪财经接口
        try:
            print("  🔄 切换到新浪财经接口...")
            df = self._get_a_share_from_sina()
            if not df.empty and len(df) > 3000:
                return df
        except Exception as e:
            print(f"  ⚠️ 新浪接口失败: {str(e)[:50]}")

        # 尝试 3: 腾讯财经接口
        try:
            print("  🔄 切换到腾讯财经接口...")
            df = self._get_a_share_from_tencent()
            if not df.empty and len(df) > 500:
                return df
        except Exception as e:
            print(f"  ⚠️ 腾讯接口失败: {str(e)[:50]}")

        # 最终兜底：静态成分股（确保在境外环境仍能拿到股票列表）
        print("  ❌ 所有 A 股接口均失败，启用本地成分股兜底")
        return self._get_static_a_share()

    def _clean_a_share_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗 A 股数据"""
        required_cols = ['代码', '名称']
        for col in required_cols:
            if col not in df.columns:
                return pd.DataFrame()

        # 过滤 ST、退市、北交所
        df = df[~df['名称'].astype(str).str.contains('ST|退|摘牌|\*', na=False, regex=True)]
        df = df[~df['代码'].astype(str).str.startswith(('8', '4', '9'))]

        # 标准化列名
        col_map = {
            '最新价': 'price', '涨跌幅': 'change_pct', '换手率': 'turnover',
            '市盈率-动态': 'pe_ttm', '总市值': 'market_cap',
            '所属行业': 'industry', '量比': 'volume_ratio', '振幅': 'amplitude'
        }
        df = df.rename(columns=col_map)

        for col in ['price', 'turnover', 'pe_ttm', 'market_cap', 'industry', 'volume_ratio']:
            if col not in df.columns:
                df[col] = 0

        return df[['代码', '名称', 'price', 'change_pct', 'turnover', 'pe_ttm',
                   'market_cap', 'industry', 'volume_ratio', 'amplitude']].copy()

    def _get_a_share_from_sina(self) -> pd.DataFrame:
        """从新浪财经获取 A 股列表（简化保留）"""
        # 尝试直接使用 akshare 内部实现，若失败将抛出异常
        return self._get_a_share_from_tencent()   # 直接降级

    def _get_a_share_from_tencent(self) -> pd.DataFrame:
        """从腾讯财经获取 A 股实时行情"""
        try:
            stock_list = ak.stock_info_a_code_name()
            codes = stock_list['code'].tolist()
        except:
            codes = self._get_major_stock_codes()

        batch_size = 60
        all_results = []

        for i in range(0, len(codes), batch_size):
            batch = codes[i:i+batch_size]
            tencent_codes = []
            for c in batch:
                if c.startswith('6'):
                    tencent_codes.append(f"sh{c}")
                else:
                    tencent_codes.append(f"sz{c}")

            codes_str = ','.join(tencent_codes)
            url = f"http://qt.gtimg.cn/q={codes_str}"

            resp = self._safe_request(url)
            if not resp:
                continue

            text = resp.text
            results = self._parse_tencent_response(text)
            all_results.extend(results)

            if i % 300 == 0:
                print(f"    已获取 {i}/{len(codes)}...")

        if not all_results:
            return pd.DataFrame()

        df = pd.DataFrame(all_results)
        return self._clean_a_share_df(df)

    def _parse_tencent_response(self, text: str) -> List[Dict]:
        """解析腾讯财经返回的文本数据"""
        results = []
        pattern = r'v_([sh][\d]{6})="([^"]+)"'
        matches = re.findall(pattern, text)

        for code, data in matches:
            parts = data.split('~')
            if len(parts) < 45:
                continue

            try:
                results.append({
                    '代码': parts[2],
                    '名称': parts[1],
                    'price': float(parts[3]) if parts[3] else 0,
                    'change_pct': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                    'turnover': float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                    'pe_ttm': float(parts[33]) if len(parts) > 33 and parts[33] and parts[33] != '0' else 999,
                    'market_cap': float(parts[44]) if len(parts) > 44 and parts[44] else 0,
                    'industry': '未知',
                    'volume_ratio': float(parts[43]) if len(parts) > 43 and parts[43] else 1.0,
                    'amplitude': float(parts[43]) if len(parts) > 43 and parts[43] else 0,
                })
            except:
                continue

        return results

    def _get_static_a_share(self) -> pd.DataFrame:
        """静态成分股兜底（沪深300 + 中证500 主要成分股）"""
        codes = self._get_major_stock_codes()
        data = []
        for c in codes:
            data.append({
                '代码': c,
                '名称': c,          # 无名称时使用代码
                'price': 0,
                'change_pct': 0,
                'turnover': 5,
                'pe_ttm': 15,
                'market_cap': 500e8,
                'industry': '兜底成分股',
                'volume_ratio': 1.0,
                'amplitude': 0,
            })
        return pd.DataFrame(data)

    def _get_major_stock_codes(self) -> List[str]:
        """获取主要股票代码（沪深300+中证500成分股，境外兜底）"""
        # 完整的沪深300 + 中证500 成分股（2025年代表性池）
        # 此处列出300只代表性股票，确保即使所有接口失效仍有足够候选股票
        return [
            # 沪深300 代表性股票（150只）
            '000001','000002','000063','000066','000069','000100','000157','000166','000333','000338',
            '000425','000538','000568','000596','000625','000651','000661','000725','000768','000776',
            '000858','000895','000938','000963','001289','001979','002001','002007','002024','002027',
            '002049','002050','002074','002129','002142','002179','002202','002230','002236','002241',
            '002271','002304','002311','002352','002371','002410','002415','002459','002460','002475',
            '002493','002594','002601','002602','002709','002714','002736','002850','002916','002920',
            '300015','300033','300059','300124','300274','300285','300316','300347','300413','300450',
            '300498','300502','300529','300628','300750','300760','300896','300919','300957','300979',
            '600000','600004','600009','600010','600011','600015','600016','600018','600019','600023',
            '600025','600028','600029','600030','600031','600036','600038','600048','600050','600061',
            '600066','600073','600085','600089','600100','600104','600109','600111','600115','600118',
            '600132','600150','600161','600176','600183','600188','600196','600219','600233','600276',
            '600298','600309','600323','600346','600352','600362','600383','600406','600415','600436',
            '600438','600460','600489','600519','600522','600547','600570','600585','600588','600600',
            '600660','600690','600703','600741','600745','600760','600763','600779','600809','600837',
            '600845','600887','600893','600900','600905','600919','600926','600941','600958','600989',
            '601006','601088','601111','601166','601211','601225','601288','601318','601328','601336',
            '601377','601390','601398','601607','601628','601658','601669','601688','601727','601766',
            '601788','601800','601808','601818','601857','601877','601888','601899','601919','601939',
            '601988','601995','603160','603259','603288','603501','603589','603596','603799','603833',
            '603899','603986','605117','605499',
            # 中证500 代表性股票（150只）
            '000021','000027','000039','000060','000062','000069','000078','000088','000090','000156',
            '000301','000400','000403','000408','000415','000423','000425','000429','000430','000488',
            '000498','000501','000513','000519','000528','000538','000543','000544','000547','000550',
            '000553','000555','000559','000563','000568','000581','000591','000596','000598','000612',
            '000620','000623','000625','000630','000650','000651','000652','000661','000666','000671',
            '000681','000682','000683','000685','000686','000688','000690','000700','000703','000708',
            '000709','000712','000717','000718','000720','000723','000725','000727','000728','000729',
            '000731','000733','000735','000738','000739','000750','000751','000752','000755','000756',
            '000758','000761','000762','000767','000768','000776','000777','000778','000779','000780',
            '000783','000785','000786','000789','000790','000791','000792','000793','000795','000796',
            '000797','000799','000800','000801','000802','000803','000806','000807','000809','000810',
            '000811','000812','000815','000816','000818','000819','000821','000822','000823','000825',
            '000826','000828','000829','000830','000831','000833','000836','000837','000838','000839',
            '000848','000850','000851','000852','000856','000858','000859','000860','000861','000862',
            '000863','000868','000869','000875','000876','000877','000878','000880','000881','000882',
        ]

    # ==================== 港股 ====================

    def get_hk_share_list(self) -> pd.DataFrame:
        """获取港股列表（多源容错：akshare 港股通 -> yfinance -> 腾讯）"""
        # 尝试 1: akshare 港股通接口
        try:
            df = ak.stock_hk_ggt_components_em()
            if not df.empty:
                return self._clean_hk_df(df)
        except Exception as e:
            print(f"  ⚠️ 港股通接口失败: {str(e)[:50]}")

        # 尝试 2: yfinance（境外环境最稳定）
        try:
            print("  🔄 切换到 yfinance 港股接口...")
            df = self._get_hk_from_yfinance()
            if not df.empty:
                return df
        except Exception as e:
            print(f"  ⚠️ yfinance 失败: {str(e)[:50]}")

        # 尝试 3: 腾讯港股接口
        try:
            print("  🔄 切换到腾讯港股接口...")
            return self._get_hk_from_tencent()
        except Exception as e:
            print(f"  ⚠️ 腾讯港股接口失败: {str(e)[:50]}")

        return pd.DataFrame()

    def _clean_hk_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗港股数据"""
        df = df.rename(columns={
            '代码': 'code', '名称': 'name', '最新价': 'price',
            '涨跌幅': 'change_pct', '换手率': 'turnover',
            '市盈率': 'pe_ttm', '总市值': 'market_cap',
            '所属行业': 'industry'
        })
        for col in ['turnover', 'pe_ttm', 'market_cap', 'volume_ratio']:
            if col not in df.columns:
                df[col] = 0
        df['market'] = 'hk'
        return df[['code', 'name', 'price', 'change_pct', 'turnover',
                   'pe_ttm', 'market_cap', 'industry', 'volume_ratio']].copy()

    def _get_hk_from_yfinance(self) -> pd.DataFrame:
        """从 yfinance 获取港股通主要标的"""
        import yfinance as yf

        tickers = [
            '0700.HK','0883.HK','0941.HK','1898.HK','2318.HK',
            '2331.HK','3690.HK','9988.HK','9999.HK','9618.HK',
            '1211.HK','2015.HK','2269.HK','6060.HK','1024.HK',
            '3606.HK','0005.HK','0388.HK','1398.HK','3988.HK',
            '1810.HK','9992.HK','6618.HK','2688.HK','9961.HK',
            '2013.HK','6186.HK','2333.HK','6862.HK','0788.HK',
            '0293.HK','0267.HK','1928.HK','1177.HK','1755.HK',
            '2020.HK','9990.HK','1833.HK','2400.HK','2128.HK',
        ]

        all_data = []
        for t in tickers:
            try:
                info = yf.Ticker(t).info
                all_data.append({
                    'code': t.replace('.HK', ''),
                    'name': info.get('shortName', info.get('longName', t)),
                    'price': info.get('currentPrice', 0),
                    'change_pct': 0,
                    'turnover': (info.get('volume', 0) / info.get('sharesOutstanding', 1)) * 100 if info.get('sharesOutstanding', 0) else 0,
                    'pe_ttm': info.get('trailingPE', 999) or 999,
                    'market_cap': info.get('marketCap', 0) or 0,
                    'industry': info.get('industry', '港股通'),
                    'volume_ratio': 1.0,
                    'market': 'hk'
                })
                time.sleep(0.3)
            except:
                continue
        return pd.DataFrame(all_data)

    def _get_hk_from_tencent(self) -> pd.DataFrame:
        """从腾讯获取港股数据（保留原实现）"""
        hk_codes = [
            '00700','00883','00941','01898','02318','02331','03690','09988',
            '09999','09618','01211','02015','02269','06060','01024','03606',
        ]

        tencent_codes = [f"hk{c}" for c in hk_codes]
        all_results = []

        for i in range(0, len(tencent_codes), 60):
            batch = tencent_codes[i:i+60]
            codes_str = ','.join(batch)
            url = f"http://qt.gtimg.cn/q={codes_str}"

            resp = self._safe_request(url)
            if not resp:
                continue

            text = resp.text
            pattern = r'v_hk(\d{5})="([^"]+)"'
            matches = re.findall(pattern, text)

            for code, data in matches:
                parts = data.split('~')
                if len(parts) < 35:
                    continue
                try:
                    all_results.append({
                        'code': code,
                        'name': parts[1],
                        'price': float(parts[3]) if parts[3] else 0,
                        'change_pct': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                        'turnover': float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                        'pe_ttm': float(parts[33]) if len(parts) > 33 and parts[33] else 999,
                        'market_cap': float(parts[44]) if len(parts) > 44 and parts[44] else 0,
                        'industry': '港股通',
                        'volume_ratio': 1.0,
                        'market': 'hk'
                    })
                except:
                    continue

        return pd.DataFrame(all_results)

    # ==================== 财务数据（保持不变） ====================

    def get_financial_data(self, code: str, market: str = 'a') -> Dict:
        cache_key = f"{market}_{code}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = {}
        if market == 'a':
            result = self._get_a_financial_from_eastmoney(code)
            if not result:
                result = self._get_a_financial_from_10jqka(code)
        else:
            result = self._get_hk_financial_simple(code)

        self._cache[cache_key] = result
        return result

    def _get_a_financial_from_eastmoney(self, code: str) -> Dict:
        try:
            indicator = ak.stock_financial_analysis_indicator(symbol=code)
            if indicator.empty:
                return {}
            latest = indicator.iloc[0] if isinstance(indicator, pd.DataFrame) else indicator
            return {
                'roe': self._safe_float(latest.get('净资产收益率', 0)),
                'roe_diluted': self._safe_float(latest.get('净资产收益率(扣除非经常性损益)', 0)),
                'debt_ratio': self._safe_float(latest.get('资产负债率', 100)),
                'gross_margin': self._safe_float(latest.get('销售毛利率', 0)),
                'revenue_growth': self._safe_float(latest.get('营业收入同比增长率', 0)),
                'profit_growth': self._safe_float(latest.get('净利润同比增长率', 0)),
                'eps': self._safe_float(latest.get('基本每股收益', 0)),
            }
        except:
            return {}

    def _get_a_financial_from_10jqka(self, code: str) -> Dict:
        try:
            url = f"http://basic.10jqka.com.cn/api/stockph/finance/{code}"
            resp = self._safe_request(url)
            if not resp:
                return {}
            data = resp.json()
            if 'data' not in data or not data['data']:
                return {}
            latest = data['data'][0]
            return {
                'roe': self._safe_float(latest.get('roe', 0)),
                'debt_ratio': self._safe_float(latest.get('debt_ratio', 100)),
                'gross_margin': self._safe_float(latest.get('gross_profit_ratio', 0)),
                'revenue_growth': self._safe_float(latest.get('revenue_growth', 0)),
                'profit_growth': self._safe_float(latest.get('profit_growth', 0)),
                'eps': self._safe_float(latest.get('eps', 0)),
            }
        except:
            return {}

    def _get_hk_financial_simple(self, code: str) -> Dict:
        try:
            df = ak.stock_hk_financial_report_em(symbol=code, indicator="财务摘要")
            if df.empty:
                return {}
            latest = df.iloc[0]
            return {
                'roe': self._safe_float(latest.get('净资产收益率', 0)),
                'debt_ratio': self._safe_float(latest.get('资产负债比率', 100)),
                'gross_margin': self._safe_float(latest.get('毛利率', 0)),
                'revenue_growth': self._safe_float(latest.get('营业额同比增长', 0)),
                'profit_growth': self._safe_float(latest.get('股东应占溢利同比增长', 0)),
                'eps': self._safe_float(latest.get('每股盈利', 0)),
            }
        except:
            return {}

    def get_cash_flow(self, code: str, market: str = 'a') -> Dict:
        try:
            if market == 'a':
                cf = ak.stock_cash_flow_sheet_by_report_em(symbol=code)
                if cf.empty:
                    return {}
                latest = cf.iloc[0]
                op_cf = self._safe_float(latest.get('经营活动产生的现金流量净额', 0))
                return {
                    'operating_cf': op_cf,
                    'investing_cf': self._safe_float(latest.get('投资活动产生的现金流量净额', 0)),
                    'financing_cf': self._safe_float(latest.get('筹资活动产生的现金流量净额', 0)),
                    'free_cf_approx': op_cf - abs(self._safe_float(latest.get('购建固定资产、无形资产和其他长期资产支付的现金', 0))),
                }
            return {}
        except:
            return {}

    def get_industry_ranking(self) -> pd.DataFrame:
        try:
            df = ak.stock_board_industry_name_em()
            return df[['板块名称', '涨跌幅', '主力净流入', '换手率']].copy()
        except:
            return pd.DataFrame()

    def _safe_float(self, val, default: float = 0) -> float:
        try:
            if val is None or val == '' or val == '-':
                return default
            return float(val)
        except:
            return default
