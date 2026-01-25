"""Weekly report: collect bot stats for the past 7 days and post to #all-agikids."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from slack_sdk import WebClient

CHANNEL_ID = "C0AA2F5EQ5S"
BOT_USER_ID = "U0AAJUXE07M"
STATE_FILE = Path(__file__).parent.parent / "state" / "last_extraction.json"

slack = WebClient(token=os.environ["SLACK_BOT_TOKEN"])


def get_weekly_stats() -> dict[str, int]:
    """Count bot mentions, bot replies, and unique users in the past 7 days."""
    oldest = str(time.time() - 7 * 24 * 3600)
    result = slack.conversations_history(channel=CHANNEL_ID, oldest=oldest, limit=200)
    messages = result.get("messages", [])

    mentions = 0
    bot_replies = 0
    users: set[str] = set()

    for msg in messages:
        user = msg.get("user", "")
        text = msg.get("text", "")

        if user == BOT_USER_ID:
            bot_replies += 1
        elif f"<@{BOT_USER_ID}>" in text:
            mentions += 1
            users.add(user)
        elif user and user != "USLACKBOT":
            users.add(user)

        # Count thread replies too
        if msg.get("reply_count", 0) > 0:
            thread = slack.conversations_replies(channel=CHANNEL_ID, ts=msg["ts"], limit=50)
            for reply in thread.get("messages", [])[1:]:
                r_user = reply.get("user", "")
                if r_user == BOT_USER_ID:
                    bot_replies += 1
                elif r_user and r_user != "USLACKBOT":
                    users.add(r_user)

    return {"mentions": mentions, "bot_replies": bot_replies, "unique_users": len(users), "total_messages": len(messages)}


def get_extraction_stats() -> dict[str, str]:
    """Read last extraction state."""
    if not STATE_FILE.exists():
        return {"last_run": "never", "extracted_count": "0"}
    data = json.loads(STATE_FILE.read_text())
    return {"last_run": data.get("last_run", "unknown"), "extracted_count": str(data.get("extracted_count", 0))}


def format_report(stats: dict[str, int], extraction: dict[str, str]) -> str:
    """Format weekly report as Slack message."""
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    return (
        f":bar_chart: *AGI Kids 周报* ({today})\n\n"
        f"*社区活跃度*\n"
        f"- 活跃用户: {stats['unique_users']} 人\n"
        f"- 总消息数: {stats['total_messages']}\n"
        f"- Bot 被 @: {stats['mentions']} 次\n"
        f"- Bot 回复: {stats['bot_replies']} 条\n\n"
        f"*知识提取*\n"
        f"- 上次提取: {extraction['last_run']}\n"
        f"- 提取经验数: {extraction['extracted_count']}\n\n"
        f"_由 GitHub Actions 自动生成_"
    )


def main() -> None:
    print("=== AGI Kids Weekly Report ===")
    stats = get_weekly_stats()
    print(f"Stats: {stats}")
    extraction = get_extraction_stats()
    print(f"Extraction: {extraction}")
    report = format_report(stats, extraction)
    print(f"Report:\n{report}")
    slack.chat_postMessage(channel=CHANNEL_ID, text=report)
    print("Report posted to #all-agikids")


if __name__ == "__main__":
    main()
