"""数据获取：多数据源容错 + 本地缓存 + 纯行情降级"""

import akshare as ak
import pandas as pd
import numpy as np
import requests
import json
import os
import time
import random
from typing import List, Dict, Optional
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)


def get_cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def load_cache(key: str, max_age_hours: int = 24) -> Optional[Dict]:
    path = get_cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        if datetime.now().timestamp() - mtime > max_age_hours * 3600:
            return None
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None


def save_cache(key: str, data: Dict):
    try:
        with open(get_cache_path(key), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass


def safe_float(val, default: float = 0.0) -> float:
    try:
        if val is None or val == '' or val == '-' or str(val).lower() == 'nan':
            return default
        return float(val)
    except (ValueError, TypeError):
        return default


class DataFetcher:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        })

    def _random_delay(self, base: float = 0.5):
        time.sleep(base + random.uniform(0, 0.5))

    # ==================== A股行情 ====================

    def get_a_share_list(self) -> pd.DataFrame:
        try:
            df = ak.stock_zh_a_spot_em()
            if not df.empty and len(df) > 3000:
                return self._clean_a_df(df)
        except Exception as e:
            print(f"  ⚠️ 东财接口失败: {str(e)[:60]}")

        print("  🔄 启用本地成分股兜底...")
        return self._get_local_a_shares()

    def _clean_a_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df[~df['名称'].astype(str).str.contains('ST|退|摘牌|\\*', na=False, regex=True)]
        df = df[~df['代码'].astype(str).str.startswith(('8', '4', '9'))]
        df = df.rename(columns={
            '最新价': 'price', '涨跌幅': 'change_pct', '换手率': 'turnover',
            '市盈率-动态': 'pe_ttm', '总市值': 'market_cap',
            '所属行业': 'industry', '量比': 'volume_ratio', '振幅': 'amplitude'
        })
        for col in ['price', 'turnover', 'pe_ttm', 'market_cap', 'volume_ratio']:
            if col not in df.columns:
                df[col] = 0
        df['market'] = 'a'
        return df[['代码', '名称', 'price', 'change_pct', 'turnover', 'pe_ttm',
                   'market_cap', 'industry', 'volume_ratio', 'amplitude', 'market']].copy()

    def _get_local_a_shares(self) -> pd.DataFrame:
        """本地成分股兜底（腾讯实时行情）"""
        codes = [
            '600000', '600016', '600036', '601398', '601939', '601288', '601988', '601318', '601628', '600030',
            '000001', '000776', '002142', '002948', '600919', '601166', '601229', '601997', '600837', '601211',
            '600519', '000858', '000568', '000596', '600809', '603288', '600887', '002714', '300498', '002507',
            '600276', '000538', '600436', '603259', '300760', '600763', '300015', '002001', '000963', '601933',
            '000063', '002415', '002230', '600570', '300033', '603501', '002371', '300782', '688981', '688012',
            '600584', '002049', '603893', '300408', '002236', '002410', '300124', '002594', '601127', '600660',
            '000333', '000651', '600690', '002032', '002508', '002242', '603195', '603486', '688169', '605117',
            '600031', '601100', '601012', '600438', '002129', '601615', '601727', '600089', '600900',
            '601857', '600028', '600938', '601088', '601899', '600547', '603993', '600362', '601600',
            '600585', '000877', '002271', '601636', '603737', '600309', '002601', '002460', '603799', '300014',
            '600009', '600115', '601111', '600029', '601006', '600377', '600018', '600026', '601919', '601866',
            '600011', '600023', '600795', '600886', '600674', '601985', '003816', '600905', '600032',
            '600637', '600088', '300413', '002027', '300251', '002739', '300133', '300418', '002624', '002555',
            '603444', '300315', '002602', '002517', '300031', '300113',
        ]
        codes = list(dict.fromkeys(codes))

        results = []
        for i in range(0, len(codes), 60):
            batch = codes[i:i + 60]
            tencent_codes = [f"sh{c}" if c.startswith('6') else f"sz{c}" for c in batch]
            url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"
            try:
                resp = self._session.get(url, timeout=15)
                text = resp.text
                for line in text.split('";'):
                    if 'v_sh' not in line and 'v_sz' not in line:
                        continue
                    try:
                        prefix, data = line.split('="', 1)
                        code = prefix.replace('v_sh', '').replace('v_sz', '').strip()
                        parts = data.split('~')
                        if len(parts) < 50:
                            continue
                        
                        # 腾讯字段索引（经日志验证）：
                        # 0=市场 1=名称 2=代码 3=现价 4=昨收 5=今开 ...
                        # 28=换手率% 29=市盈率(TTM) 32=涨跌幅% 33=振幅
                        # 44=流通市值(亿) 45=总市值(亿) 49=量比
                        
                        price = safe_float(parts[3])
                        change_pct = safe_float(parts[32])
                        turnover = safe_float(parts[28])
                        pe = safe_float(parts[29], -1)
                        
                        # 市值：优先总市值(parts[45])，为空则用流通市值(parts[44])，单位亿→元
                        market_cap_total = safe_float(parts[45])   # 总市值（亿）
                        market_cap_circ = safe_float(parts[44])    # 流通市值（亿）
                        market_cap = market_cap_total if market_cap_total > 0 else market_cap_circ
                        market_cap = market_cap * 1e8            # 亿 → 元
                        
                        volume_ratio = safe_float(parts[49], 1.0)  # 量比
                        amplitude = safe_float(parts[33])
                        
                        # 只打印一次调试
                        if len(results) == 0:
                            print(f"    [调试] {code} {parts[1]}: 价{price} PE{pe} 市值{market_cap/1e8:.1f}亿 换手{turnover}% 量比{volume_ratio}")
                        
                        results.append({
                            '代码': code,
                            '名称': parts[1],
                            'price': price,
                            'change_pct': change_pct,
                            'turnover': turnover,
                            'pe_ttm': pe if pe > 0 else -1,
                            'market_cap': market_cap,
                            'industry': '未知',
                            'volume_ratio': volume_ratio,
                            'amplitude': amplitude,
                            'market': 'a'
                        })
                    except Exception:
                        continue
            except Exception as e:
                print(f"    腾讯批量请求失败: {e}")

        df = pd.DataFrame(results)
        print(f"  本地兜底获取到 {len(df)} 只 A 股")
        return df

    # ==================== 港股行情 ====================

    def get_hk_share_list(self) -> pd.DataFrame:
        """获取港股列表"""
        try:
            print("  🔄 尝试新浪港股接口...")
            df = ak.stock_hk_spot()
            if not df.empty and len(df) > 100:
                print(f"    新浪港股获取到 {len(df)} 只（无市值PE数据）")
                return self._get_hk_with_tencent_supplement(df)
        except Exception as e:
            print(f"  ⚠️ 新浪港股接口失败: {str(e)[:60]}")

        print("  🔄 使用腾讯财经港股接口...")
        return self._get_hk_from_tencent()

    def _get_hk_with_tencent_supplement(self, df: pd.DataFrame) -> pd.DataFrame:
        """新浪港股 + 腾讯补充市值PE"""
        df = df.rename(columns={
            '代码': 'code', '中文名称': 'name', '最新价': 'price',
            '涨跌幅': 'change_pct', '成交量': 'volume', '成交额': 'amount',
        })
        
        # 从腾讯获取市值和PE（批量）
        codes = df['code'].astype(str).str.strip().tolist()
        tencent_data = {}
        
        for i in range(0, len(codes), 60):
            batch = codes[i:i + 60]
            codes_str = ','.join([f"hk{c}" for c in batch])
            url = f"http://qt.gtimg.cn/q={codes_str}"
            try:
                resp = self._session.get(url, timeout=15)
                text = resp.text
                for line in text.split('";'):
                    if 'v_hk' not in line:
                        continue
                    try:
                        prefix, data = line.split('="', 1)
                        code = prefix.replace('v_hk', '').strip()
                        parts = data.split('~')
                        if len(parts) < 50:
                            continue
                        
                        pe = safe_float(parts[29], -1)
                        # 港股市值：优先总市值(parts[45])，为空则用流通市值(parts[44])，单位亿→元
                        market_cap_total = safe_float(parts[45])
                        market_cap_circ = safe_float(parts[44])
                        market_cap = market_cap_total if market_cap_total > 0 else market_cap_circ
                        market_cap = market_cap * 1e8
                        
                        turnover = safe_float(parts[28])
                        volume_ratio = safe_float(parts[49], 1.0)
                        
                        tencent_data[code] = {
                            'pe_ttm': pe if pe > 0 else -1,
                            'market_cap': market_cap,
                            'turnover': turnover,
                            'volume_ratio': volume_ratio,
                        }
                    except:
                        continue
            except:
                continue
        
        # 合并数据
        df['pe_ttm'] = df['code'].map(lambda x: tencent_data.get(str(x), {}).get('pe_ttm', -1))
        df['market_cap'] = df['code'].map(lambda x: tencent_data.get(str(x), {}).get('market_cap', 0))
        df['turnover'] = df['code'].map(lambda x: tencent_data.get(str(x), {}).get('turnover', 0))
        df['volume_ratio'] = df['code'].map(lambda x: tencent_data.get(str(x), {}).get('volume_ratio', 1.0))
        
        df['industry'] = '港股通'
        df['amplitude'] = 0
        df['market'] = 'hk'
        
        # 调试
        print(f"    [调试] 港股样本: {df[['code','name','price','pe_ttm','market_cap']].head(3).to_dict('records')}")
        
        return df[['code', 'name', 'price', 'change_pct', 'turnover', 'pe_ttm',
                   'market_cap', 'industry', 'volume_ratio', 'amplitude', 'market']].copy()

    def _get_hk_from_tencent(self) -> pd.DataFrame:
        """纯腾讯财经获取港股"""
        hk_codes = [
            '00700', '03690', '09988', '09618', '09999', '01810', '02015', '02269',
            '02359', '01024', '06060', '09633', '02400', '09868', '09866', '09626',
            '01211', '02018', '09698', '09888', '06690', '06098', '06969', '09923',
            '09636', '09877', '09961', '01898', '00883', '00005', '02318', '01299',
            '03988', '01398', '02328', '06818', '06030', '03968', '03328', '06138',
            '06066', '06837', '06099', '06186', '06049', '06886', '06881', '03908',
            '03347', '06110', '06823', '06862', '01109', '00688', '01113', '01997',
            '02007', '02238', '01238', '06808', '01918', '01929', '01972', '01928',
            '03333', '03380', '03377', '00683', '01038', '00817', '00884', '00960',
            '00914', '01186', '00175', '00836', '00857', '00881', '00992', '01044',
            '01913', '09869', '09658', '09660', '06908', '09956', '09995', '01093',
            '01177', '01548', '01801', '06185', '09688', '02162', '01873', '01521',
            '02157', '02170', '02252', '02256', '02315', '02367', '01193', '01208',
            '02382', '02899', '00998', '01088', '00902', '00762', '00728', '00941',
            '00788', '00852', '00002', '00003', '00006', '00008', '00012', '00014',
            '00016', '00017', '00019', '00066', '00101', '00144', '00151', '00270',
            '00288', '00371', '00386', '00522', '00662', '00669', '00708', '00751',
            '00753', '00823', '00864', '00880', '00908', '00939', '00966', '00981',
            '00995', '01055', '01065', '01071', '01083', '01128', '01138', '01171',
            '01258', '01288', '01313', '01336', '01339', '01347', '01359', '01378',
            '01382', '01478', '01585', '01618', '01635', '01658', '01691', '01766',
            '01772', '01787', '01797', '01800', '01812', '01813', '01816', '01821',
            '01833', '01848', '01876', '01877', '01880', '01882', '01888', '01890',
            '01896', '01897', '01910', '01919', '01951', '01958', '01963', '01988',
            '01997', '02005', '02009', '02038', '02057', '02096', '02098', '02121',
            '02137', '02282', '02318', '02331', '02338', '02382', '02500', '02600',
            '02601', '02607', '02628', '02688', '02689', '02727', '02768', '02800',
            '02822', '02823', '02828', '02911', '03360', '03383', '03606', '03618',
            '03638', '03800', '03808', '03888', '03898', '03900', '03993', '03996',
            '06088', '06158', '06160', '06169', '06178', '06198', '06806', '06808',
            '06865', '06868', '06928', '06993', '09626', '09658', '09660', '09698',
            '09877', '09923', '09992',
        ]
        hk_codes = list(dict.fromkeys(hk_codes))

        results = []
        for i in range(0, len(hk_codes), 60):
            batch = hk_codes[i:i + 60]
            codes_str = ','.join([f"hk{c}" for c in batch])
            url = f"http://qt.gtimg.cn/q={codes_str}"

            try:
                resp = self._session.get(url, timeout=15)
                text = resp.text

                for line in text.split('";'):
                    if 'v_hk' not in line:
                        continue
                    try:
                        prefix, data = line.split('="', 1)
                        code = prefix.replace('v_hk', '').strip()
                        parts = data.split('~')
                        if len(parts) < 50:
                            continue

                        price = safe_float(parts[3])
                        change_pct = safe_float(parts[32])
                        turnover = safe_float(parts[28])
                        pe = safe_float(parts[29], -1)
                        
                        # 港股市值：优先总市值(parts[45])，为空则用流通市值(parts[44])，单位亿→元
                        market_cap_total = safe_float(parts[45])
                        market_cap_circ = safe_float(parts[44])
                        market_cap = market_cap_total if market_cap_total > 0 else market_cap_circ
                        market_cap = market_cap * 1e8
                        
                        volume_ratio = safe_float(parts[49], 1.0)
                        amplitude = safe_float(parts[33])

                        results.append({
                            'code': code,
                            'name': parts[1],
                            'price': price,
                            'change_pct': change_pct,
                            'turnover': turnover,
                            'pe_ttm': pe if pe > 0 else -1,
                            'market_cap': market_cap,
                            'industry': '港股通',
                            'volume_ratio': volume_ratio,
                            'amplitude': amplitude,
                            'market': 'hk'
                        })
                    except Exception:
                        continue

            except Exception as e:
                print(f"    腾讯港股请求失败: {e}")
                continue

        df = pd.DataFrame(results)
        print(f"  腾讯港股接口获取到 {len(df)} 只")
        return df

    # ==================== 财务数据 ====================

    def get_financial_data(self, code: str, market: str = 'a') -> Dict:
        cache_key = f"fin_{market}_{code}"
        cached = load_cache(cache_key, max_age_hours=48)
        if cached:
            return cached

        result = {}
        if market == 'a':
            baostock_code = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
            result = self._get_a_financial_from_baostock(baostock_code)
            if not result:
                result = self._get_a_financial_from_eastmoney(code)

        if result:
            save_cache(cache_key, result)
        return result

    def _get_a_financial_from_baostock(self, code: str) -> Dict:
        """Baostock 获取 A 股财务（code格式: sh.600000）"""
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code != '0':
                return {}

            rs = bs.query_dupont_data(code=code, year=2024, quarter=4)
            if rs.error_code != '0':
                bs.logout()
                return {}

            dupont_list = []
            while (rs.error_code == '0') & rs.next():
                dupont_list.append(rs.get_row_data())

            if not dupont_list:
                bs.logout()
                return {}

            latest = dupont_list[-1]
            roe = safe_float(latest[3] if len(latest) > 3 else 0)

            rs2 = bs.query_balance_data(code=code, year=2024, quarter=4)
            balance_list = []
            while (rs2.error_code == '0') & rs2.next():
                balance_list.append(rs2.get_row_data())

            debt_ratio = 0
            if balance_list:
                bal = balance_list[-1]
                liability = safe_float(bal[13] if len(bal) > 13 else 0)
                asset = safe_float(bal[7] if len(bal) > 7 else 1)
                debt_ratio = liability / asset * 100 if asset > 0 else 0

            rs3 = bs.query_profit_data(code=code, year=2024, quarter=4)
            profit_list = []
            while (rs3.error_code == '0') & rs3.next():
                profit_list.append(rs3.get_row_data())

            gross_margin = 0
            revenue_growth = 0
            profit_growth = 0
            eps = 0

            if profit_list:
                prof = profit_list[-1]
                gross_margin = safe_float(prof[7] if len(prof) > 7 else 0)
                revenue_growth = safe_float(prof[8] if len(prof) > 8 else 0)
                profit_growth = safe_float(prof[9] if len(prof) > 9 else 0)
                eps = safe_float(prof[5] if len(prof) > 5 else 0)

            bs.logout()

            return {
                'roe': roe,
                'debt_ratio': debt_ratio,
                'gross_margin': gross_margin,
                'revenue_growth': revenue_growth,
                'profit_growth': profit_growth,
                'eps': eps,
                'source': 'baostock'
            }

        except Exception:
            try:
                import baostock as bs
                bs.logout()
            except:
                pass
            return {}

    def _get_a_financial_from_eastmoney(self, code: str) -> Dict:
        try:
            indicator = ak.stock_financial_analysis_indicator(symbol=code)
            if indicator.empty:
                return {}
            latest = indicator.iloc[0]
            return {
                'roe': safe_float(latest.get('净资产收益率', 0)),
                'debt_ratio': safe_float(latest.get('资产负债率', 100)),
                'gross_margin': safe_float(latest.get('销售毛利率', 0)),
                'revenue_growth': safe_float(latest.get('营业收入同比增长率', 0)),
                'profit_growth': safe_float(latest.get('净利润同比增长率', 0)),
                'eps': safe_float(latest.get('基本每股收益', 0)),
                'source': 'eastmoney'
            }
        except:
            return {}

    def get_cash_flow(self, code: str, market: str = 'a') -> Dict:
        cache_key = f"cf_{market}_{code}"
        cached = load_cache(cache_key, max_age_hours=48)
        if cached:
            return cached

        result = {}
        if market == 'a':
            baostock_code = f"sh.{code}" if code.startswith('6') else f"sz.{code}"
            result = self._get_a_cf_from_baostock(baostock_code)
            if not result:
                result = self._get_a_cf_from_eastmoney(code)

        if result:
            save_cache(cache_key, result)
        return result

    def _get_a_cf_from_baostock(self, code: str) -> Dict:
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code != '0':
                return {}

            rs = bs.query_cash_flow_data(code=code, year=2024, quarter=4)
            cf_list = []
            while (rs.error_code == '0') & rs.next():
                cf_list.append(rs.get_row_data())

            bs.logout()

            if not cf_list:
                return {}

            latest = cf_list[-1]
            op_cf = safe_float(latest[8] if len(latest) > 8 else 0)

            return {
                'operating_cf': op_cf,
                'investing_cf': 0,
                'financing_cf': 0,
                'free_cf_approx': op_cf,
                'source': 'baostock'
            }
        except:
            try:
                import baostock as bs
                bs.logout()
            except:
                pass
            return {}

    def _get_a_cf_from_eastmoney(self, code: str) -> Dict:
        try:
            cf = ak.stock_cash_flow_sheet_by_report_em(symbol=code)
            if cf.empty:
                return {}
            latest = cf.iloc[0]
            op_cf = safe_float(latest.get('经营活动产生的现金流量净额', 0))
            return {
                'operating_cf': op_cf,
                'investing_cf': safe_float(latest.get('投资活动产生的现金流量净额', 0)),
                'financing_cf': safe_float(latest.get('筹资活动产生的现金流量净额', 0)),
                'free_cf_approx': op_cf - abs(safe_float(latest.get('购建固定资产、无形资产和其他长期资产支付的现金', 0))),
                'source': 'eastmoney'
            }
        except:
            return {}

    def get_industry_ranking(self) -> pd.DataFrame:
        try:
            df = ak.stock_board_industry_name_em()
            return df[['板块名称', '涨跌幅', '主力净流入', '换手率']].copy()
        except:
            return pd.DataFrame()