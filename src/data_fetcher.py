"""数据获取：多数据源容错 + 本地缓存 + 纯行情降级"""

import akshare as ak
import pandas as pd
import numpy as np
import requests
import json
import os
import time
import random
import yfinance as yf
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# 缓存目录
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cache')
os.makedirs(CACHE_DIR, exist_ok=True)

def get_cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")

def load_cache(key: str, max_age_hours: int = 24) -> Optional[Dict]:
    """加载缓存"""
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
    """保存缓存"""
    try:
        with open(get_cache_path(key), 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

class DataFetcher:
    """多数据源容错股票数据获取器（含缓存）"""
    
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Accept': 'application/json, text/plain, */*',
        })
    
    def _random_delay(self, base: float = 0.5):
        time.sleep(base + random.uniform(0, 0.5))
    
    # ==================== A股行情 ====================
    
    def get_a_share_list(self) -> pd.DataFrame:
        """获取 A 股全量列表"""
        # 尝试 akshare 东财
        try:
            df = ak.stock_zh_a_spot_em()
            if not df.empty and len(df) > 3000:
                return self._clean_a_df(df)
        except Exception as e:
            print(f"  ⚠️ 东财接口失败: {str(e)[:60]}")
        
        # 本地兜底：沪深300 + 中证500 + 主要指数成分股
        print("  🔄 启用本地成分股兜底...")
        return self._get_local_a_shares()
    
    def _clean_a_df(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df[~df['名称'].astype(str).str.contains('ST|退|摘牌|\*', na=False, regex=True)]
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
        """本地成分股兜底（基于腾讯实时行情）"""
        # 主要指数成分股 + 行业龙头
        codes = [
            # 金融
            '600000','600016','600036','601398','601939','601288','601988','601318','601628','600030',
            '000001','000776','002142','002948','600919','601166','601229','601997','600837','601211',
            # 消费
            '600519','000858','000568','000596','600809','603288','600887','002714','300498','002507',
            '600276','000538','600436','603259','300760','600763','300015','002001','000963','601933',
            # 科技
            '000063','002415','002230','600570','300033','603501','002371','300782','688981','688012',
            '600584','002049','603893','300408','002236','002410','300124','002594','601127','600660',
            # 制造
            '000333','000651','600690','002032','002508','002242','603195','603486','688169','605117',
            '600031','601100','300124','601012','600438','002129','601615','601727','600089','600900',
            # 能源/材料
            '601857','600028','600938','601088','601899','600547','601899','603993','600362','601600',
            '600585','000877','002271','601636','603737','600309','002601','002460','603799','300014',
            # 公用/交通
            '600009','600115','601111','600029','601006','600377','600018','600026','601919','601866',
            '600011','600023','600795','600886','600674','600900','601985','003816','600905','600032',
            # 传媒/互联网
            '600637','600088','300413','002027','300251','002739','300133','300418','002624','002555',
            '603444','300315','002602','002517','300031','300113','300418','002371','002236','002415',
        ]
        # 去重
        codes = list(dict.fromkeys(codes))
        
        # 批量获取腾讯行情
        results = []
        for i in range(0, len(codes), 60):
            batch = codes[i:i+60]
            tencent_codes = [f"sh{c}" if c.startswith('6') else f"sz{c}" for c in batch]
            url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"
            try:
                resp = self._session.get(url, timeout=10)
                text = resp.text
                for line in text.split('";'):
                    if not line or 'v_' not in line:
                        continue
                    try:
                        code_part = line.split('="')
                        if len(code_part) < 2:
                            continue
                        code = code_part[0].replace('v_sh', '').replace('v_sz', '')
                        data = code_part[1]
                        parts = data.split('~')
                        if len(parts) < 45:
                            continue
                        results.append({
                            '代码': code,
                            '名称': parts[1],
                            'price': float(parts[3]) if parts[3] else 0,
                            'change_pct': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                            'turnover': float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                            'pe_ttm': float(parts[33]) if len(parts) > 33 and parts[33] and parts[33] != '0' else -1,
                            'market_cap': float(parts[44]) if len(parts) > 44 and parts[44] else 0,
                            'industry': '未知',
                            'volume_ratio': float(parts[43]) if len(parts) > 43 and parts[43] else 1.0,
                            'amplitude': float(parts[43]) if len(parts) > 43 and parts[43] else 0,
                            'market': 'a'
                        })
                    except:
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
            df = ak.stock_hk_ggt_components_em()
            if not df.empty:
                return self._clean_hk_df(df)
        except Exception as e:
            print(f"  ⚠️ 港股通接口失败: {str(e)[:60]}")
        
        print("  🔄 启用 yfinance 港股兜底...")
        return self._get_hk_from_yfinance()
    
    def _clean_hk_df(self, df: pd.DataFrame) -> pd.DataFrame:
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
        df['volume_ratio'] = df.get('volume_ratio', 1.0)
        df['amplitude'] = 0
        return df[['code', 'name', 'price', 'change_pct', 'turnover', 'pe_ttm',
                   'market_cap', 'industry', 'volume_ratio', 'amplitude', 'market']].copy()
    
    def _get_hk_from_yfinance(self) -> pd.DataFrame:
        """yfinance 获取港股通主要标的"""
        hk_tickers = [
            '0700.HK','2318.HK','1299.HK','0005.HK','0939.HK','3988.HK','1398.HK',
            '2388.HK','0883.HK','0857.HK','1088.HK','0941.HK','2313.HK','1211.HK',
            '3690.HK','9988.HK','9618.HK','9999.HK','1810.HK','2015.HK','2269.HK',
            '2359.HK','6098.HK','1024.HK','6060.HK','0522.HK','0388.HK','0688.HK',
            '1109.HK','1997.HK','2007.HK','6099.HK','9633.HK','2400.HK','9868.HK',
            '9866.HK','2018.HK','2331.HK','0291.HK','1928.HK','0880.HK','1044.HK',
            '2319.HK','0027.HK','0001.HK','0002.HK','0003.HK','0006.HK','0011.HK',
            '0016.HK','0019.HK','0020.HK','0066.HK','0083.HK','0101.HK','0151.HK',
            '0175.HK','0267.HK','0288.HK','0316.HK','0322.HK','0386.HK','0669.HK',
            '0708.HK','0762.HK','0823.HK','0836.HK','0854.HK','0868.HK','0902.HK',
            '0916.HK','0960.HK','0968.HK','0981.HK','0988.HK','1038.HK','1093.HK',
            '1113.HK','1177.HK','1216.HK','1378.HK','1787.HK','1801.HK','1876.HK',
            '1880.HK','1898.HK','1918.HK','1929.HK','1958.HK','1963.HK','1972.HK',
            '1988.HK','2005.HK','2013.HK','2020.HK','2038.HK','2057.HK','2096.HK',
            '2098.HK','2121.HK','2162.HK','2202.HK','2238.HK','2282.HK','2314.HK',
            '2328.HK','2333.HK','2380.HK','2382.HK','2400.HK','2500.HK','2601.HK',
            '2628.HK','2688.HK','2689.HK','2727.HK','2768.HK','2777.HK','2800.HK',
            '2899.HK','2911.HK','2979.HK','2988.HK','3033.HK','3147.HK','3168.HK',
            '3222.HK','3323.HK','3328.HK','3333.HK','3339.HK','3360.HK','3380.HK',
            '3383.HK','3411.HK','3800.HK','3808.HK','3888.HK','3898.HK','3908.HK',
            '3968.HK','3983.HK','3990.HK','3993.HK','3996.HK','3998.HK','6030.HK',
            '6049.HK','6066.HK','6088.HK','6099.HK','6110.HK','6122.HK','6138.HK',
            '6158.HK','6160.HK','6185.HK','6186.HK','6198.HK','6808.HK','6818.HK',
            '6823.HK','6837.HK','6862.HK','6865.HK','6868.HK','6881.HK','6886.HK',
            '6898.HK','6908.HK','6963.HK','6988.HK','6993.HK','7200.HK','7225.HK',
            '7288.HK','7500.HK','7522.HK','7800.HK','8001.HK','8005.HK','8017.HK',
            '8028.HK','8032.HK','8033.HK','8047.HK','8057.HK','8111.HK','8128.HK',
            '8137.HK','8155.HK','8179.HK','8182.HK','8193.HK','8207.HK','8216.HK',
            '8225.HK','8231.HK','8236.HK','8243.HK','8247.HK','8250.HK','8260.HK',
            '8275.HK','8279.HK','8281.HK','8282.HK','8285.HK','8287.HK','8290.HK',
            '8291.HK','8293.HK','8295.HK','8300.HK','8305.HK','8308.HK','8310.HK',
            '8311.HK','8313.HK','8315.HK','8316.HK','8317.HK','8318.HK','8319.HK',
            '8320.HK','8321.HK','8322.HK','8325.HK','8326.HK','8328.HK','8331.HK',
            '8333.HK','8336.HK','8337.HK','8339.HK','8340.HK','8341.HK','8342.HK',
            '8343.HK','8345.HK','8346.HK','8347.HK','8348.HK','8349.HK','8350.HK',
            '8351.HK','8352.HK','8353.HK','8354.HK','8355.HK','8356.HK','8357.HK',
            '8358.HK','8359.HK','8360.HK','8361.HK','8362.HK','8363.HK','8364.HK',
            '8365.HK','8366.HK','8367.HK','8368.HK','8369.HK','8370.HK','8371.HK',
            '8372.HK','8373.HK','8375.HK','8376.HK','8377.HK','8378.HK','8379.HK',
            '8380.HK','8381.HK','8382.HK','8383.HK','8384.HK','8385.HK','8386.HK',
            '8387.HK','8388.HK','8389.HK','8390.HK','8391.HK','8392.HK','8393.HK',
            '8394.HK','8395.HK','8396.HK','8397.HK','8398.HK','8399.HK','8400.HK',
        ]
        # 去重
        hk_tickers = list(dict.fromkeys(hk_tickers))
        
        results = []
        for ticker in hk_tickers:
            try:
                self._random_delay(0.3)
                stock = yf.Ticker(ticker)
                info = stock.info
                
                # 只取有市值和PE的
                market_cap = info.get('marketCap', 0)
                pe = info.get('trailingPE', -1) or info.get('forwardPE', -1)
                
                if market_cap > 0:
                    results.append({
                        'code': ticker.replace('.HK', '').zfill(5),
                        'name': info.get('shortName', info.get('longName', ticker)),
                        'price': info.get('currentPrice', info.get('regularMarketPrice', 0)),
                        'change_pct': info.get('regularMarketChangePercent', 0) or 0,
                        'turnover': info.get('volume', 0) / info.get('sharesOutstanding', 1) * 100 if info.get('sharesOutstanding') else 0,
                        'pe_ttm': pe if pe and pe > 0 else -1,
                        'market_cap': market_cap,
                        'industry': info.get('industry', '未知'),
                        'volume_ratio': 1.0,
                        'amplitude': 0,
                        'market': 'hk'
                    })
            except Exception as e:
                continue
        
        df = pd.DataFrame(results)
        print(f"  yfinance 获取到 {len(df)} 只港股")
        return df
    
    # ==================== 财务数据（Baostock + yfinance + 缓存） ====================
    
    def get_financial_data(self, code: str, market: str = 'a') -> Dict:
        """获取财务数据（带缓存和多源容错）"""
        cache_key = f"fin_{market}_{code}"
        cached = load_cache(cache_key, max_age_hours=48)
        if cached:
            return cached
        
        result = {}
        if market == 'a':
            # 尝试 baostock（最稳定，无需注册）
            result = self._get_a_financial_from_baostock(code)
            if not result:
                result = self._get_a_financial_from_eastmoney(code)
        else:
            result = self._get_hk_financial_from_yfinance(code)
        
        if result:
            save_cache(cache_key, result)
        return result
    
    def _get_a_financial_from_baostock(self, code: str) -> Dict:
        """从 Baostock 获取 A 股财务数据（无需注册，稳定性高）"""
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code != '0':
                return {}
            
            # 获取杜邦分析指标（包含ROE等）
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
            
            # 取最新一期
            latest = dupont_list[-1]
            # 杜邦指标字段：code, pubDate, statDate, dupontROE, dupontAssetStoEquity, 
            # dupontAssetTurn, dupontProfitMargin, dupontROE, ...
            # 索引：0=code, 1=pubDate, 2=statDate, 3=dupontROE, ...
            
            roe = float(latest[3]) if len(latest) > 3 and latest[3] else 0
            
            # 获取资产负债数据
            rs2 = bs.query_balance_data(code=code, year=2024, quarter=4)
            balance_list = []
            while (rs2.error_code == '0') & rs2.next():
                balance_list.append(rs2.get_row_data())
            
            debt_ratio = 0
            if balance_list:
                bal = balance_list[-1]
                # 负债合计 / 资产总计
                try:
                    liability = float(bal[13]) if len(bal) > 13 and bal[13] else 0
                    asset = float(bal[7]) if len(bal) > 7 and bal[7] else 1
                    debt_ratio = liability / asset * 100 if asset > 0 else 0
                except:
                    pass
            
            # 获取利润数据
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
                try:
                    # 销售毛利率
                    gross_margin = float(prof[7]) if len(prof) > 7 and prof[7] else 0
                    # 营收同比增长率
                    revenue_growth = float(prof[8]) if len(prof) > 8 and prof[8] else 0
                    # 净利润同比增长率
                    profit_growth = float(prof[9]) if len(prof) > 9 and prof[9] else 0
                    # EPS
                    eps = float(prof[5]) if len(prof) > 5 and prof[5] else 0
                except:
                    pass
            
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
            
        except Exception as e:
            try:
                import baostock as bs
                bs.logout()
            except:
                pass
            return {}
    
    def _get_a_financial_from_eastmoney(self, code: str) -> Dict:
        """akshare 东财财务（备用）"""
        try:
            indicator = ak.stock_financial_analysis_indicator(symbol=code)
            if indicator.empty:
                return {}
            latest = indicator.iloc[0]
            return {
                'roe': float(latest.get('净资产收益率', 0)),
                'debt_ratio': float(latest.get('资产负债率', 100)),
                'gross_margin': float(latest.get('销售毛利率', 0)),
                'revenue_growth': float(latest.get('营业收入同比增长率', 0)),
                'profit_growth': float(latest.get('净利润同比增长率', 0)),
                'eps': float(latest.get('基本每股收益', 0)),
                'source': 'eastmoney'
            }
        except:
            return {}
    
    def _get_hk_financial_from_yfinance(self, code: str) -> Dict:
        """yfinance 获取港股财务"""
        try:
            ticker = f"{code}.HK"
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # 从 info 中提取财务指标
            return {
                'roe': info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else 0,
                'debt_ratio': info.get('debtToEquity', 0) / 100 if info.get('debtToEquity') else 0,
                'gross_margin': info.get('grossMargins', 0) * 100 if info.get('grossMargins') else 0,
                'revenue_growth': info.get('revenueGrowth', 0) * 100 if info.get('revenueGrowth') else 0,
                'profit_growth': info.get('earningsGrowth', 0) * 100 if info.get('earningsGrowth') else 0,
                'eps': info.get('trailingEps', 0),
                'source': 'yfinance'
            }
        except:
            return {}
    
    def get_cash_flow(self, code: str, market: str = 'a') -> Dict:
        """获取现金流（带缓存）"""
        cache_key = f"cf_{market}_{code}"
        cached = load_cache(cache_key, max_age_hours=48)
        if cached:
            return cached
        
        result = {}
        if market == 'a':
            result = self._get_a_cf_from_baostock(code)
            if not result:
                result = self._get_a_cf_from_eastmoney(code)
        else:
            result = self._get_hk_cf_from_yfinance(code)
        
        if result:
            save_cache(cache_key, result)
        return result
    
    def _get_a_cf_from_baostock(self, code: str) -> Dict:
        """Baostock 现金流"""
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
            # 字段：code, pubDate, statDate, CAToAsset, NCAToAsset, tangibleAssetToAsset,
            # ebitToInterest, CFOToOR, CFOToNP, CFOToGR
            
            # 经营现金流净额：需要查文档，这里用近似
            # baostock 的现金流表字段较复杂，简化处理
            try:
                op_cf = float(latest[8]) if len(latest) > 8 and latest[8] else 0  # 近似
            except:
                op_cf = 0
            
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
        """东财现金流"""
        try:
            cf = ak.stock_cash_flow_sheet_by_report_em(symbol=code)
            if cf.empty:
                return {}
            latest = cf.iloc[0]
            op_cf = float(latest.get('经营活动产生的现金流量净额', 0))
            return {
                'operating_cf': op_cf,
                'investing_cf': float(latest.get('投资活动产生的现金流量净额', 0)),
                'financing_cf': float(latest.get('筹资活动产生的现金流量净额', 0)),
                'free_cf_approx': op_cf - abs(float(latest.get('购建固定资产、无形资产和其他长期资产支付的现金', 0))),
                'source': 'eastmoney'
            }
        except:
            return {}
    
    def _get_hk_cf_from_yfinance(self, code: str) -> Dict:
        """yfinance 港股现金流"""
        try:
            ticker = f"{code}.HK"
            stock = yf.Ticker(ticker)
            cf = stock.cashflow
            if cf is None or cf.empty:
                return {}
            
            # 经营现金流
            op_cf = cf.loc['Operating Cash Flow'].iloc[0] if 'Operating Cash Flow' in cf.index else 0
            cap_ex = cf.loc['Capital Expenditure'].iloc[0] if 'Capital Expenditure' in cf.index else 0
            
            return {
                'operating_cf': op_cf,
                'investing_cf': 0,
                'financing_cf': 0,
                'free_cf_approx': op_cf + cap_ex if cap_ex < 0 else op_cf - cap_ex,
                'source': 'yfinance'
            }
        except:
            return {}
    
    def get_industry_ranking(self) -> pd.DataFrame:
        """行业排名"""
        try:
            df = ak.stock_board_industry_name_em()
            return df[['板块名称', '涨跌幅', '主力净流入', '换手率']].copy()
        except:
            return pd.DataFrame()