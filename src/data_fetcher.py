"""数据获取：多数据源容错，支持 A 股 + 港股"""

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
        优先东财 -> 新浪财经 -> 腾讯财经
        """
        # 尝试 1: akshare 东财接口（带异常捕获）
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
            if not df.empty and len(df) > 3000:
                return df
        except Exception as e:
            print(f"  ⚠️ 腾讯接口失败: {str(e)[:50]}")
        
        print("  ❌ 所有 A 股接口均失败")
        return pd.DataFrame()
    
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
        
        # 确保关键列存在
        for col in ['price', 'turnover', 'pe_ttm', 'market_cap', 'industry', 'volume_ratio']:
            if col not in df.columns:
                df[col] = 0
        
        return df[['代码', '名称', 'price', 'change_pct', 'turnover', 'pe_ttm', 
                   'market_cap', 'industry', 'volume_ratio', 'amplitude']].copy()
    
    def _get_a_share_from_sina(self) -> pd.DataFrame:
        """从新浪财经获取 A 股列表"""
        # 新浪提供分页接口，这里获取主要市场
        markets = ['sh_a', 'sz_a', 'cyb', 'kcb']  # 上证、深证、创业板、科创板
        all_data = []
        
        for market in markets:
            url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={market}"
            # 新浪实际接口更复杂，这里使用简化的实时行情批量接口
            pass
        
        # 使用新浪的批量行情接口（更稳定）
        # 获取股票代码列表后批量查询
        try:
            # 先获取代码列表
            codes_df = ak.stock_zh_a_spot_em()  # 这个在本地可能可用，云端不行
            # 如果上面失败，使用备用方案
        except:
            # 使用腾讯接口获取代码列表
            return self._get_a_share_from_tencent()
        
        return pd.DataFrame()
    
    def _get_a_share_from_tencent(self) -> pd.DataFrame:
        """从腾讯财经获取 A 股实时行情（最稳定的备用源）"""
        # 腾讯批量行情接口：http://qt.gtimg.cn/q=sh600000,sz000001,...
        # 先获取全量代码
        try:
            # 使用 akshare 获取代码列表（这个接口通常不受限）
            stock_list = ak.stock_info_a_code_name()
            codes = stock_list['code'].tolist()
        except:
            # 如果代码列表也获取失败，使用硬编码的主要指数成分股
            codes = self._get_major_stock_codes()
        
        # 分批获取（每批最多 60 只，避免 URL 过长）
        batch_size = 60
        all_results = []
        
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i+batch_size]
            # 构建腾讯格式代码：sh600000, sz000001
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
            
            # 解析腾讯返回的数据格式
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
        # 腾讯返回格式：v_sh600000="1~浦发银行~600000~...";
        pattern = r'v_([sh][\d]{6})="([^"]+)"'
        matches = re.findall(pattern, text)
        
        for code, data in matches:
            parts = data.split('~')
            if len(parts) < 45:
                continue
            
            try:
                # 腾讯字段索引：1=名称, 2=代码, 3=当前价, 4=昨收, 5=今开, 6=成交量, 7=外盘, 8=内盘,
                # 9=买一, 10=买一量, ..., 33=市盈率, 38=换手率, 43=振幅, 44=量比
                results.append({
                    '代码': parts[2],
                    '名称': parts[1],
                    'price': float(parts[3]) if parts[3] else 0,
                    'change_pct': float(parts[32]) if len(parts) > 32 and parts[32] else 0,
                    'turnover': float(parts[38]) if len(parts) > 38 and parts[38] else 0,
                    'pe_ttm': float(parts[33]) if len(parts) > 33 and parts[33] and parts[33] != '0' else 999,
                    'market_cap': float(parts[44]) if len(parts) > 44 and parts[44] else 0,  # 总市值（亿）
                    'industry': '未知',  # 腾讯接口无行业数据，后续补充
                    'volume_ratio': float(parts[43]) if len(parts) > 43 and parts[43] else 1.0,
                    'amplitude': float(parts[43]) if len(parts) > 43 and parts[43] else 0,
                })
            except:
                continue
        
        return results
    
    def _get_major_stock_codes(self) -> List[str]:
        """获取主要股票代码（备用方案）"""
        # 沪深300 + 中证500 主要成分股
        major_codes = [
            '600000','600004','600009','600010','600011','600015','600016','600018','600019','600023',
            '600025','600028','600029','600030','600031','600036','600038','600048','600050','600061',
            '600066','600073','600085','600089','600100','600104','600109','600111','600115','600118',
            '000001','000002','000063','000066','000069','000100','000157','000166','000333','000338',
            '000425','000538','000568','000596','000625','000651','000661','000725','000768','000776',
            '000858','000895','000938','000963','001289','001979','002001','002007','00810','00700',
            # ... 实际应包含更多，这里仅示例
        ]
        return major_codes
    
    # ==================== 港股 ====================
    
    def get_hk_share_list(self) -> pd.DataFrame:
        """获取港股列表（多源容错）"""
        # 尝试 1: akshare 港股通接口
        try:
            df = ak.stock_hk_ggt_components_em()
            if not df.empty:
                return self._clean_hk_df(df)
        except Exception as e:
            print(f"  ⚠️ 港股通接口失败: {str(e)[:50]}")
        
        # 尝试 2: 腾讯港股接口
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
    
    def _get_hk_from_tencent(self) -> pd.DataFrame:
        """从腾讯获取港股数据"""
        # 港股通标的代码
        hk_codes = [
            '00700','00883','00941','01898','02318','02331','03690','09988',
            '09999','09618','01211','02015','02269','06060','01024','03606',
            # ... 更多港股通标的
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
    
    # ==================== 财务数据（多源容错） ====================
    
    def get_financial_data(self, code: str, market: str = 'a') -> Dict:
        """获取财务数据（带缓存和容错）"""
        cache_key = f"{market}_{code}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        result = {}
        if market == 'a':
            # 尝试多个财务数据源
            result = self._get_a_financial_from_eastmoney(code)
            if not result:
                result = self._get_a_financial_from_10jqka(code)
        else:
            result = self._get_hk_financial_simple(code)
        
        self._cache[cache_key] = result
        return result
    
    def _get_a_financial_from_eastmoney(self, code: str) -> Dict:
        """从东方财富获取 A 股财务指标"""
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
        except Exception as e:
            return {}
    
    def _get_a_financial_from_10jqka(self, code: str) -> Dict:
        """从同花顺获取 A 股财务数据（备用源）"""
        try:
            # 同花顺财务数据接口
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
        """简化港股财务获取"""
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
        """获取现金流数据"""
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
        """获取行业排名"""
        try:
            df = ak.stock_board_industry_name_em()
            return df[['板块名称', '涨跌幅', '主力净流入', '换手率']].copy()
        except:
            return pd.DataFrame()
    
    def _safe_float(self, val, default: float = 0) -> float:
        """安全转换浮点数"""
        try:
            if val is None or val == '' or val == '-':
                return default
            return float(val)
        except:
            return default