"""Daily knowledge extraction: Slack conversations → Claude evaluation → knowledge files."""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from slack_sdk import WebClient

CHANNEL_ID = "C0AA2F5EQ5S"  # #all-agikids
BOT_USER_ID = "U0AAJUXE07M"
KNOWLEDGE_ROOT = Path(__file__).parent.parent
EXPERIENCES_DIR = KNOWLEDGE_ROOT / ".claude" / "skills" / "experiences"
CLAUDE_MD = KNOWLEDGE_ROOT / "CLAUDE.md"
STATE_FILE = KNOWLEDGE_ROOT / "state" / "last_extraction.json"

slack = WebClient(token=os.environ["SLACK_BOT_TOKEN"])
claude = anthropic.Anthropic()

EXTRACTION_PROMPT = """\
你是知识提取助手。分析以下 Slack 对话，提取有价值的 AI 儿童教育经验。

**只提取真实的家长经验分享**，忽略:
- Bot 回复 (user_id 为 {bot_id} 的消息)
- 纯问题（没有经验分享的提问）
- 闲聊、打招呼
- 少于 15 个中文字符的短消息

对每条有价值的经验，输出 JSON 数组，每个元素格式:
{{
  "topic": "工具或话题名称 (如 ScratchJr, Claude Code, Kimi)",
  "age_range": "适用年龄 (如 4-6岁)",
  "experience": "一句话总结经验 (具体可执行的发现)",
  "source_date": "消息日期 YYYY-MM-DD",
  "confidence": 0.0-1.0
}}

只输出 confidence >= 0.7 的经验。如果没有有价值的经验，输出空数组 []。
只输出 JSON，不要其他文字。

--- 对话内容 ---
{messages}
"""


def get_recent_messages(hours: int = 24) -> list[dict[str, str]]:
    """Fetch messages from #all-agikids in the last N hours, including thread replies."""
    oldest = str(time.time() - hours * 3600)
    result = slack.conversations_history(channel=CHANNEL_ID, oldest=oldest, limit=100)
    all_messages: list[dict[str, str]] = []

    for msg in result.get("messages", []):
        user = msg.get("user", "")
        text = msg.get("text", "").strip()
        ts = msg.get("ts", "")
        if not text or user == "USLACKBOT":
            continue
        all_messages.append({"user": user, "text": text, "ts": ts})

        # Fetch thread replies if thread exists
        if msg.get("reply_count", 0) > 0:
            thread = slack.conversations_replies(channel=CHANNEL_ID, ts=msg["ts"], limit=50)
            for reply in thread.get("messages", [])[1:]:  # skip parent (already added)
                r_user = reply.get("user", "")
                r_text = reply.get("text", "").strip()
                r_ts = reply.get("ts", "")
                if r_text and r_user != "USLACKBOT":
                    all_messages.append({"user": r_user, "text": r_text, "ts": r_ts})

    return all_messages


def format_messages_for_prompt(messages: list[dict[str, str]]) -> str:
    """Format messages for the extraction prompt."""
    lines: list[str] = []
    for msg in messages:
        role = "[BOT]" if msg["user"] == BOT_USER_ID else f"[USER:{msg['user'][:6]}]"
        lines.append(f"{role} {msg['text'][:500]}")
    return "\n".join(lines)


def extract_knowledge(messages: list[dict[str, str]]) -> list[dict[str, object]]:
    """Call Claude to extract knowledge from messages."""
    formatted = format_messages_for_prompt(messages)
    prompt = EXTRACTION_PROMPT.format(bot_id=BOT_USER_ID, messages=formatted)

    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    text = ""
    for block in response.content:
        if isinstance(block, anthropic.types.TextBlock):
            text = block.text
            break

    # Parse JSON from response (handle markdown code blocks)
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def write_experience(topic: str, experiences: list[dict[str, object]]) -> Path:
    """Write or append experiences to a topic file."""
    EXPERIENCES_DIR.mkdir(parents=True, exist_ok=True)
    slug = topic.lower().replace(" ", "-").replace("/", "-")
    filepath = EXPERIENCES_DIR / f"{slug}.md"

    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    if filepath.exists():
        content = filepath.read_text()
        # Find the metadata section and update
        count_line_idx = content.find("- 经验数:")
        if count_line_idx >= 0:
            old_count_line = content[count_line_idx:content.find("\n", count_line_idx)]
            old_count = int(old_count_line.split(":")[1].strip())
        else:
            old_count = 0
    else:
        old_count = 0
        age_ranges = {str(e.get("age_range", "未知")) for e in experiences}
        content = f"# {topic} 实践经验\n\n> 社区家长关于 {topic} 的真实使用经验汇总\n\n## 经验记录\n\n"
        content += f"## 元数据\n- 话题: {topic}\n- 适用年龄: {', '.join(age_ranges)}\n- 经验数: 0\n- 最后更新: {today}\n"

    # Add new experiences before metadata
    new_entries = ""
    for i, exp in enumerate(experiences):
        entry_num = old_count + i + 1
        source_date = exp.get("source_date", today)
        new_entries += f"### {entry_num}. {exp['experience'][:30]}... ({source_date})\n"
        new_entries += f"家长分享: {exp['experience']}\n"
        new_entries += f"适合: {exp.get('age_range', '未知')}\n\n"

    # Insert before metadata
    meta_idx = content.find("## 元数据")
    if meta_idx >= 0:
        content = content[:meta_idx] + new_entries + content[meta_idx:]
    else:
        content += "\n" + new_entries

    # Update metadata
    new_count = old_count + len(experiences)
    content = content.replace(f"- 经验数: {old_count}", f"- 经验数: {new_count}")
    content = content.replace(content[content.find("- 最后更新:"):content.find("\n", content.find("- 最后更新:"))], f"- 最后更新: {today}")

    filepath.write_text(content)
    return filepath


def update_claude_md(all_experiences: list[dict[str, object]]) -> None:
    """Regenerate CLAUDE.md knowledge section from experience files."""
    # Read base template (persona + rules)
    base = """\
# AGI Kids 知识库

你是 AGI Kids Bot, 帮助家长了解 AI 时代儿童教育的助手。
擅长: AI 工具推荐 (适合不同年龄段), 编程启蒙方案, AI 素养培养, 亲子 AI 实践活动设计。
回答要具体可执行, 给出年龄适配建议。用中文回答, 必要时中英混合。

## 社区知识

以下是社区家长的真实经验。回答相关问题时优先引用这些经验。

"""
    # Collect experiences from all skill files
    if EXPERIENCES_DIR.exists():
        for exp_file in sorted(EXPERIENCES_DIR.glob("*.md")):
            topic = exp_file.stem.replace("-", " ").title()
            lines = exp_file.read_text().splitlines()
            # Extract "家长分享:" lines as bullet points
            bullets: list[str] = []
            for line in lines:
                if line.startswith("家长分享:"):
                    bullets.append(f"- {line[5:]}")
            if bullets:
                base += f"### {topic}\n"
                base += "\n".join(bullets) + "\n\n"

    base += """\
## 回答规范

1. 如果有相关社区经验, 先引用再补充自己的建议
2. 引用格式: "社区家长反馈: ..."
3. 没有相关社区经验时, 正常回答即可
4. 回答保持具体可执行, 避免泛泛而谈
"""
    CLAUDE_MD.write_text(base)
    print(f"Updated CLAUDE.md: {len(base)} chars")


def save_state(extracted_count: int) -> None:
    """Save extraction state for dedup."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "last_run": datetime.now(tz=timezone.utc).isoformat(),
        "extracted_count": extracted_count,
    }
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n")


def main() -> None:
    print("=== AGI Kids Knowledge Extraction ===")

    # 1. Fetch recent messages
    hours = int(os.environ.get("EXTRACT_HOURS", "24"))
    messages = get_recent_messages(hours=hours)
    human_messages = [m for m in messages if m["user"] != BOT_USER_ID]
    print(f"Fetched {len(messages)} messages ({len(human_messages)} from humans)")

    if len(human_messages) < 2:
        print("Not enough human messages to extract. Skipping.")
        save_state(0)
        return

    # 2. Extract knowledge via Claude
    print("Calling Claude for knowledge extraction...")
    experiences = extract_knowledge(messages)
    print(f"Extracted {len(experiences)} experiences")

    if not experiences:
        print("No valuable experiences found. Skipping.")
        save_state(0)
        return

    # 3. Group by topic and write files
    by_topic: dict[str, list[dict[str, object]]] = {}
    for exp in experiences:
        topic = str(exp.get("topic", "general"))
        by_topic.setdefault(topic, []).append(exp)

    written_files: list[str] = []
    for topic, topic_exps in by_topic.items():
        filepath = write_experience(topic, topic_exps)
        written_files.append(str(filepath))
        print(f"  Wrote {len(topic_exps)} experiences to {filepath.name}")

    # 4. Regenerate CLAUDE.md
    update_claude_md(experiences)

    # 5. Save state
    save_state(len(experiences))
    print(f"\nDone. {len(experiences)} experiences extracted, {len(written_files)} files updated.")


if __name__ == "__main__":
    main()
