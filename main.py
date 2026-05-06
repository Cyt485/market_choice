#!/usr/bin/env python3
"""每日价值投资选股主程序"""

import os
import sys
import json
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.stock_screener import StockScreener
from src.ai_analyzer import DeepSeekAnalyzer
from src.notifier import ServerChanNotifier
from config import DEEPSEEK_API_KEY, SERVERCHAN_SENDKEY

def main():
    print(f"\n{'='*60}")
    print(f"🚀 价值投资每日选股系统启动")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")
    
    # 检查环境变量
    if not DEEPSEEK_API_KEY:
        print("❌ 错误：未设置 DEEPSEEK_API_KEY")
        return 1
    if not SERVERCHAN_SENDKEY:
        print("❌ 错误：未设置 SERVERCHAN_SENDKEY")
        return 1
    
    # Step 1: 量化初筛
    screener = StockScreener()
    candidates = screener.run_screening()
    
    if candidates.empty:
        print("⚠️ 未找到符合条件的候选股票")
        # 发送空结果通知
        notifier = ServerChanNotifier()
        notifier.send([{
            'code': '-', 'name': '今日无符合标准股票', 'market': 'a',
            'industry': '-', 'confidence': 0, 'reason': '市场条件不满足筛选标准'
        }])
        return 0
    
    print(f"\n📋 候选股票列表:")
    print(candidates[['code', 'name', 'market', 'industry', 'pe_ttm', 'roe', 'score']].to_string())
    
    # Step 2: DeepSeek AI 深度分析
    print(f"\n{'='*60}")
    print("🤖 DeepSeek AI 分析中...")
    analyzer = DeepSeekAnalyzer()
    final_picks = analyzer.analyze_stocks(candidates)
    
    if not final_picks:
        print("⚠️ AI 分析未返回结果，使用量化评分排序")
        final_picks = analyzer._fallback_ranking(candidates)
    
    print(f"\n✅ 最终选出 {len(final_picks)} 只股票:")
    for i, pick in enumerate(final_picks, 1):
        print(f"  {i}. {pick['code']} {pick['name']} ({pick['market']}) - 信心{pick.get('confidence', '-')}")
    
    # Step 3: Server 酱推送
    print(f"\n{'='*60}")
    print("📲 推送结果到 Server 酱...")
    notifier = ServerChanNotifier()
    success = notifier.send(final_picks)
    
    # 保存结果到本地（用于调试和记录）
    result_file = f"results_{datetime.now().strftime('%Y%m%d')}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump({
            'date': datetime.now().isoformat(),
            'candidates_count': len(candidates),
            'final_picks': final_picks
        }, f, ensure_ascii=False, indent=2)
    print(f"💾 结果已保存到 {result_file}")
    
    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())