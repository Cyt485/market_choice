"""Server 酱推送：支持 Markdown 格式，优化显示效果"""

import requests
import json
from typing import List, Dict
from datetime import datetime
from config import SERVERCHAN_SENDKEY, CONFIG

class ServerChanNotifier:
    """Server 酱推送器"""
    
    def __init__(self, sendkey: str = SERVERCHAN_SENDKEY):
        self.sendkey = sendkey
        self.url = CONFIG.SERVERCHAN_URL.format(sendkey=sendkey)
    
    def format_message(self, picks: List[Dict], date_str: str) -> tuple:
        """
        格式化推送消息
        返回: (title, desp)
        """
        title = f"📊 {date_str} 价值投资潜力股"
        
        # 构建 Markdown 表格
        lines = [
            f"**⏰ 推送时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "**🎯 今日精选 10 只价值股（A股+港股）**",
            "",
            "| 排名 | 代码 | 名称 | 市场 | 行业 | 信心分 | 核心逻辑 |",
            "| :---: | :--- | :--- | :---: | :--- | :---: | :--- |",
        ]
        
        for i, pick in enumerate(picks, 1):
            market_emoji = "🇨🇳" if pick.get('market') == 'a' else "🇭🇰"
            lines.append(
                f"| {i} | **{pick['code']}** | {pick['name']} | {market_emoji} | "
                f"{pick.get('industry', '-')} | {pick.get('confidence', '-')} | "
                f"{pick.get('reason', '-')} |"
            )
        
        lines.extend([
            "",
            "---",
            "**📋 筛选标准：**",
            "• 热度不过热：换手率<15%，量比<3",
            "• 基本面优秀：ROE>10%，负债率<60%，毛利率>20%",
            "• 现金流健康：经营现金流为正",
            "• 估值合理：PE<30，营收正增长",
            "",
            "⚠️ *本推送由 AI 自动生成，不构成投资建议*"
        ])
        
        desp = "\n".join(lines)
        return title, desp
    
    def send(self, picks: List[Dict]) -> bool:
        """发送推送"""
        if not self.sendkey:
            print("❌ Server 酱 SendKey 未配置")
            return False
        
        date_str = datetime.now().strftime('%m/%d')
        title, desp = self.format_message(picks, date_str)
        
        try:
            response = requests.post(
                self.url,
                data={
                    "title": title,
                    "desp": desp,
                    "channel": "9"  # 微信通道
                },
                timeout=30
            )
            
            result = response.json()
            if result.get('code') == 0:
                print(f"✅ 推送成功: {result.get('data', {})}")
                return True
            else:
                print(f"❌ 推送失败: {result}")
                return False
                
        except Exception as e:
            print(f"❌ 推送异常: {e}")
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