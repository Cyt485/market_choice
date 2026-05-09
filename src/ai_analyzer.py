"""DeepSeek AI 分析：优化 Prompt 设计 + 重试机制 + 充分降级"""

import os
import json
import requests
import time
from typing import List, Dict
from config import DEEPSEEK_API_KEY, CONFIG


class DeepSeekAnalyzer:
    """DeepSeek 价值投资分析师"""

    API_URL = "https://api.deepseek.com/chat/completions"

    def __init__(self, api_key: str = DEEPSEEK_API_KEY):
        self.api_key = api_key
        self.model = CONFIG.DEEPSEEK_MODEL

    def analyze_stocks(self, stocks_df) -> List[Dict]:
        if stocks_df.empty:
            return []

        stock_summaries = []
        for _, row in stocks_df.iterrows():
            summary = (f"{row['code']}({row['name']})|{row['market']}|{row['industry']}|"
                      f"PE{row['pe_ttm']:.1f}|ROE{row['roe']:.1f}%|"
                      f"负债{row['debt_ratio']:.1f}%|营收增{row['revenue_growth']:.1f}%|"
                      f"经营现金流{row['operating_cf']/1e8:.1f}亿|评分{row['score']:.1f}")
            stock_summaries.append(summary)

        stocks_text = "\n".join(stock_summaries)

        system_prompt = """你是资深价值投资分析师。请基于候选股票的财务数据，选出最优的8-10只股票。

分析框架（权重从高到低）：
1. 安全边际（估值）：PE越低越好，但也考虑行业特性
2. 盈利质量（ROE+毛利率）：ROE>10%优先，但周期股低谷可容忍
3. 财务健康（负债率）：负债率<50%优先，金融行业可放宽到80%
4. 现金流：经营现金流为正优先，但成长型公司可容忍短期为负
5. 成长性：营收正增长优先，但周期底部可容忍负增长
6. 行业分散：尽量避免同一行业超过2只
7. A股和港股尽量均衡

⚠️ 重要：目标是选出8-10只，至少选出5只。不要因为单一指标就排除股票。
如果候选本身少于8只，就全部分析后择优输出。

请严格按JSON数组格式输出：
[{"code":"000001","name":"平安银行","market":"a","industry":"银行","reason":"低估值+高ROE+稳定分红","confidence":9}]"""

        user_prompt = f"候选股票（代码|名称|市场|行业|PE|ROE|负债率|营收增长|经营现金流|量化评分）：\n{stocks_text}\n\n请选出最优的8-10只（至少5只），输出JSON数组。"

        # 重试逻辑
        last_error = None
        for attempt in range(CONFIG.AI_MAX_RETRIES + 1):
            try:
                response = requests.post(
                    self.API_URL,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.1,
                        "max_tokens": CONFIG.MAX_TOKENS_PER_ANALYSIS,
                    },
                    timeout=90
                )

                if response.status_code == 429:
                    wait = 2 ** attempt
                    print(f"  ⚠️ API限流，{wait}秒后重试...")
                    time.sleep(wait)
                    continue

                if response.status_code != 200:
                    print(f"  ❌ DeepSeek API 错误: {response.status_code} - {response.text[:200]}")
                    if attempt < CONFIG.AI_MAX_RETRIES:
                        time.sleep(2)
                        continue
                    return self._fallback_ranking(stocks_df)

                result = response.json()
                content = result['choices'][0]['message']['content']

                # 解析 JSON
                try:
                    content = content.strip()
                    if content.startswith("```json"):
                        content = content[len("```json"):].strip()
                    if content.startswith("```"):
                        content = content[3:].strip()
                    if content.endswith("```"):
                        content = content[:-3].strip()

                    data = json.loads(content)

                    if isinstance(data, dict):
                        picks = data.get('stocks', data.get('picks', data.get('results', [])))
                        if not picks:
                            # maybe the dict IS the stock mapping
                            picks = list(data.values()) if all(isinstance(v, dict) for v in data.values()) else []
                    elif isinstance(data, list):
                        picks = data
                    else:
                        picks = []

                    picks = [p for p in picks if isinstance(p, dict) and 'code' in p]

                    if picks:
                        print(f"  ✅ AI分析返回 {len(picks)} 只")
                        return picks[:12]  # 多留一些给后续处理

                except json.JSONDecodeError as je:
                    print(f"  ⚠️ JSON解析失败: {je}，原始内容: {content[:200]}...")
                    if attempt < CONFIG.AI_MAX_RETRIES:
                        continue

            except requests.Timeout:
                print(f"  ⚠️ API超时 (尝试 {attempt+1}/{CONFIG.AI_MAX_RETRIES+1})")
                if attempt < CONFIG.AI_MAX_RETRIES:
                    time.sleep(3)
            except Exception as e:
                last_error = e
                print(f"  ❌ DeepSeek 异常: {e}")
                if attempt < CONFIG.AI_MAX_RETRIES:
                    time.sleep(2)

        print(f"  🚨 AI分析最终失败: {last_error}")
        return self._fallback_ranking(stocks_df)

    def _fallback_ranking(self, stocks_df) -> List[Dict]:
        """API 失败时的降级方案：最大化利用量化评分"""
        print("⚠️ 使用降级方案：按量化评分排序")
        results = []
        # 取全部候选，不限制head(10)
        max_picks = min(len(stocks_df), CONFIG.TARGET_INDUSTRY_COUNT)
        for _, row in stocks_df.head(max_picks).iterrows():
            results.append({
                'code': row['code'],
                'name': row['name'],
                'market': row['market'],
                'industry': row['industry'],
                'reason': f"量化评分{row['score']:.1f}分，PE{row['pe_ttm']:.1f}，ROE{row['roe']:.1f}%",
                'confidence': min(int(row['score'] / 10) + 1, 10)
            })
        return results
