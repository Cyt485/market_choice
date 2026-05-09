"""Server 酱推送 + PushPlus兜底：支持 Markdown 格式，动态消息"""

import requests
import json
import os
from typing import List, Dict
from datetime import datetime
from config import SERVERCHAN_SENDKEY, CONFIG


class ServerChanNotifier:
    """Server 酱推送器 + PushPlus备用"""

    def __init__(self, sendkey: str = SERVERCHAN_SENDKEY):
        self.sendkey = sendkey
        self.url = CONFIG.SERVERCHAN_URL.format(sendkey=sendkey) if sendkey else ""
        # PushPlus 作为备用
        self.pushplus_token = os.getenv("PUSHPLUS_TOKEN", "")

    def format_message(self, picks: List[Dict], date_str: str) -> tuple:
        """
        格式化推送消息
        返回: (title, desp)
        """
        count = len(picks)
        title = f"📊 {date_str} 价值投资潜力股（{count}只）"

        lines = [
            f"**⏰ 推送时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            f"**🎯 今日精选 {count} 只价值股（A股+港股）**",
            "",
            "| 排名 | 代码 | 名称 | 市场 | 行业 | 信心分 | 核心逻辑 |",
            "| :---: | :--- | :--- | :---: | :--- | :---: | :--- |",
        ]

        for i, pick in enumerate(picks, 1):
            market_emoji = "🇨🇳" if pick.get('market') == 'a' else "🇭🇰"
            reason = pick.get('reason', '-')
            # 截断过长的理由
            if len(reason) > 40:
                reason = reason[:37] + "..."
            lines.append(
                f"| {i} | **{pick['code']}** | {pick['name']} | {market_emoji} | "
                f"{pick.get('industry', '-')} | {pick.get('confidence', '-')} | "
                f"{reason} |"
            )

        lines.extend([
            "",
            "---",
            "**📋 筛选标准：**",
            "• 综合评分制（估值+ROE+现金流+成长性+安全性）",
            "• 市值>20亿(A股)/10亿(港股)，换手率适中",
            "• 行业分散，A股港股均衡配置",
            f"• 今日共筛选出 **{count}** 只",
            "",
            "⚠️ *本推送由 AI 自动生成，不构成投资建议*"
        ])

        desp = "\n".join(lines)
        return title, desp

    def send(self, picks: List[Dict]) -> bool:
        """发送推送（主通道 + 备用通道）"""
        date_str = datetime.now().strftime('%m/%d')
        title, desp = self.format_message(picks, date_str)

        # 尝试 Server 酱
        if self.sendkey:
            try:
                response = requests.post(
                    self.url,
                    data={
                        "title": title,
                        "desp": desp,
                        "channel": "9"
                    },
                    timeout=30
                )
                result = response.json()
                if result.get('code') == 0:
                    print(f"✅ Server酱推送成功: {result.get('data', {})}")
                    return True
                else:
                    print(f"⚠️ Server酱推送失败: {result}，尝试备用通道...")
            except Exception as e:
                print(f"⚠️ Server酱异常: {e}，尝试备用通道...")

        # 备用：PushPlus
        if self.pushplus_token:
            try:
                resp = requests.post(
                    "https://www.pushplus.plus/send",
                    json={
                        "token": self.pushplus_token,
                        "title": title,
                        "content": desp.replace("\n", "<br>"),
                        "template": "html"
                    },
                    timeout=30
                )
                data = resp.json()
                if data.get('code') == 200:
                    print(f"✅ PushPlus备用推送成功")
                    return True
                else:
                    print(f"❌ PushPlus推送失败: {data}")
            except Exception as e:
                print(f"❌ PushPlus异常: {e}")

        # 最后：打印到控制台（作为最后兜底）
        if not self.sendkey and not self.pushplus_token:
            print("\n" + "=" * 60)
            print(title)
            print(desp)
            print("=" * 60)
            print("⚠️ 未配置推送通道，以上仅打印到控制台")
            return True

        return False

    def send_test(self) -> bool:
        """发送测试消息"""
        test_picks = [{
            'code': '000001',
            'name': '测试股票',
            'market': 'a',
            'industry': '金融',
            'confidence': 8,
            'reason': '测试推送功能'
        }]
        return self.send(test_picks)
