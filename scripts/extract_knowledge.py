"""每日知识提取: Slack 消息 → Claude 提取 → 写入 knowledge/ 目录"""
# TODO Phase 2 实现:
# 1. slack_sdk 获取过去 24h 的 #all-agikids 消息
# 2. 过滤噪音 (短消息/emoji/闲聊)
# 3. 调用 Claude API 评估价值 (阈值 0.7)
# 4. 结构化提取 (类别/标题/内容/置信度)
# 5. 写入 knowledge/ 对应目录
print("Knowledge extraction - TODO Phase 2")
