#!/usr/bin/env python3
"""每日价值投资选股主程序 —— 优化版"""

import os
import sys
import json
import traceback
from datetime import datetime

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.stock_screener import StockScreener
from src.ai_analyzer import DeepSeekAnalyzer
from src.notifier import ServerChanNotifier
from config import DEEPSEEK_API_KEY, SERVERCHAN_SENDKEY, CONFIG


def main():
    print(f"\n{'='*60}")
    print(f"🚀 价值投资每日选股系统启动 v2.0")
    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # 检查环境变量
    warnings = []
    if not DEEPSEEK_API_KEY:
        warnings.append("DEEPSEEK_API_KEY 未设置，将使用量化评分降级方案")
    if not SERVERCHAN_SENDKEY and not os.getenv("PUSHPLUS_TOKEN"):
        warnings.append("未配置推送通道（SERVERCHAN_SENDKEY/PUSHPLUS_TOKEN），结果仅打印到控制台")

    for w in warnings:
        print(f"⚠️ {w}")

    final_picks = []
    return_code = 0

    try:
        # Step 1: 量化初筛
        print(f"\n{'='*60}")
        print("📊 Step 1/3: 量化初筛")
        print(f"{'='*60}")
        screener = StockScreener()
        candidates = screener.run_screening()

        if candidates.empty:
            print("\n⚠️ 所有筛选条件均未产生候选股票")
            final_picks = [{
                'code': '-', 'name': '今日无符合标准股票', 'market': 'a',
                'industry': '-', 'confidence': 0,
                'reason': '市场条件不满足当前筛选标准，建议关注市场变化'
            }]
        else:
            print(f"\n📋 候选股票列表 ({len(candidates)} 只):")
            print(candidates[['code', 'name', 'market', 'industry', 'pe_ttm', 'roe', 'score']].to_string())

            # Step 2: DeepSeek AI 深度分析
            print(f"\n{'='*60}")
            print("🤖 Step 2/3: DeepSeek AI 深度分析")
            print(f"{'='*60}")
            analyzer = DeepSeekAnalyzer()
            final_picks = analyzer.analyze_stocks(candidates)

            if not final_picks:
                print("⚠️ AI 分析未返回结果，使用量化评分排序")
                final_picks = analyzer._fallback_ranking(candidates)

        # 确保至少有 MIN_FINAL_PICKS 只
        min_picks = CONFIG.MIN_FINAL_PICKS
        if len(final_picks) < min_picks and candidates is not None and not candidates.empty:
            print(f"\n⚠️ AI返回 {len(final_picks)} 只 < {min_picks}，补充量化高分股票...")
            existing_codes = {p['code'] for p in final_picks}
            for _, row in candidates.iterrows():
                if len(final_picks) >= min_picks:
                    break
                if row['code'] not in existing_codes:
                    final_picks.append({
                        'code': row['code'],
                        'name': row['name'],
                        'market': row['market'],
                        'industry': row['industry'],
                        'reason': f"补充推荐：量化评分{row['score']:.1f}分",
                        'confidence': min(int(row['score'] / 10) + 1, 10)
                    })

        print(f"\n✅ 最终选出 {len(final_picks)} 只股票:")
        for i, pick in enumerate(final_picks, 1):
            print(f"  {i}. {pick['code']} {pick['name']} ({pick['market']}) "
                  f"- {pick.get('industry','-')} - 信心{pick.get('confidence', '-')}")

    except Exception as e:
        print(f"\n❌ 选股流程异常: {e}")
        traceback.print_exc()
        return_code = 1
        final_picks = [{
            'code': '-', 'name': f'系统异常: {str(e)[:50]}', 'market': 'a',
            'industry': '-', 'confidence': 0, 'reason': '请检查日志'
        }]

    # Step 3: 推送
    print(f"\n{'='*60}")
    print("📲 Step 3/3: 推送结果")
    print(f"{'='*60}")
    notifier = ServerChanNotifier()
    success = notifier.send(final_picks)

    # 保存结果到本地
    try:
        result_file = f"results_{datetime.now().strftime('%Y%m%d')}.json"
        with open(result_file, 'w', encoding='utf-8') as f:
            json.dump({
                'date': datetime.now().isoformat(),
                'final_picks': final_picks,
                'count': len(final_picks)
            }, f, ensure_ascii=False, indent=2)
        print(f"💾 结果已保存到 {result_file}")
    except Exception as e:
        print(f"⚠️ 保存结果文件失败: {e}")

    if not success:
        return_code = 1 if return_code == 0 else return_code

    print(f"\n{'='*60}")
    print(f"🏁 选股系统运行完成 (退出码: {return_code})")
    print(f"{'='*60}\n")

    return return_code


if __name__ == "__main__":
    sys.exit(main())
