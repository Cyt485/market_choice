"""DeepSeek AI 分析：极简 Prompt 设计，控制 Token 消耗"""

import os
import json
import requests
from typing import List, Dict
from config import DEEPSEEK_API_KEY, CONFIG

class DeepSeekAnalyzer:
    """DeepSeek 价值投资分析师"""
    
    API_URL = "https://api.deepseek.com/chat/completions"
    
    def __init__(self, api_key: str = DEEPSEEK_API_KEY):
        self.api_key = api_key
        self.model = CONFIG.DEEPSEEK_MODEL
        
    def analyze_stocks(self, stocks_df) -> List[Dict]:
        """
        批量分析股票，使用极简 Prompt 减少 Token
        一次性分析所有候选股票，而非逐个调用
        """
        if stocks_df.empty:
            return []
        
        # 构建极简数据摘要
        stock_summaries = []
        for _, row in stocks_df.iterrows():
            summary = (f"{row['code']}({row['name']})|{row['market']}|{row['industry']}|"
                      f"PE{row['pe_ttm']:.1f}|ROE{row['roe']:.1f}%|"
                      f"负债{row['debt_ratio']:.1f}%|营收增{row['revenue_growth']:.1f}%|"
                      f"经营现金流{row['operating_cf']/1e8:.1f}亿")
            stock_summaries.append(summary)
        
        stocks_text = "\n".join(stock_summaries)
        
        # 极简 System Prompt + User Prompt
        system_prompt = """你是价值投资专家。基于给定财务数据，从10只候选股中选出最具价值的10只（可少于10只）。
规则：
1. 优先：低PE(<20)+高ROE(>15%)+低负债(<50%)+正现金流+营收正增长
2. 排除：PE>25或负债>55%或现金流为负或营收下滑>5%
3. 行业分散，A股港股均衡
4. 输出JSON数组：[{code, name, market, industry, reason, confidence(1-10)}]"""

        user_prompt = f"候选股票（代码|名称|市场|行业|PE|ROE|负债率|营收增长|经营现金流）：\n{stocks_text}\n\n请严格按JSON格式输出结果，不要其他内容。"
        
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
                    "temperature": 0.1,  # 低温度确保稳定输出
                    "max_tokens": CONFIG.MAX_TOKENS_PER_ANALYSIS,
                    "response_format": {"type": "json_object"}
                },
                timeout=60
            )
            
            if response.status_code != 200:
                print(f"DeepSeek API 错误: {response.status_code} - {response.text}")
                return self._fallback_ranking(stocks_df)
            
            result = response.json()
            content = result['choices'][0]['message']['content']
            
            # 解析 JSON
            try:
                data = json.loads(content)
                picks = data.get('stocks', data) if isinstance(data, dict) else data
                return picks[:10] if isinstance(picks, list) else self._fallback_ranking(stocks_df)
            except:
                return self._fallback_ranking(stocks_df)
                
        except Exception as e:
            print(f"DeepSeek 分析失败: {e}")
            return self._fallback_ranking(stocks_df)
    
    def _fallback_ranking(self, stocks_df) -> List[Dict]:
        """API 失败时的降级方案：按量化评分排序"""
        print("⚠️ 使用降级方案：按量化评分排序")
        results = []
        for _, row in stocks_df.head(10).iterrows():
            results.append({
                'code': row['code'],
                'name': row['name'],
                'market': row['market'],
                'industry': row['industry'],
                'reason': f"量化评分{row['score']}分，PE{row['pe_ttm']:.1f}，ROE{row['roe']:.1f}%",
                'confidence': min(int(row['score'] / 10), 10)
            })
        return results