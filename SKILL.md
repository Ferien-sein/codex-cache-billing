---
name: cache-billing
description: 估算 Codex 会话花了多少钱——按 DeepSeek 峰谷价目表算当前步/当前轮/会话累计的缓存账单。用户问「这花了多少钱」「缓存账单」「token 成本」「缓存命中率这么高怎么还贵」「该不该换窗口」时使用。
---

# 缓存账单

Codex 每次大模型 API 调用的用量都在会话日志里：`~/.codex/sessions/**/*.jsonl` 的
`token_usage_record`，`usage.cached_input_tokens` 是缓存命中，`input_tokens` +
`cache_write_input_tokens` 是缓存未命中输入，`output_tokens` 是输出。别自己重算，
跑脚本，口径与 DSH 侧插件 `dsh-cache-billing` 一致。

## 跑账单

```bash
python scripts/bill.py                      # 最新会话
python scripts/bill.py --session <片段|路径>  # 指定会话
python scripts/bill.py --list               # 最近改动的会话
python scripts/bill.py --json               # 机器可读
python scripts/bill.py --line               # 一行摘要，每轮自动附账单用
```

`python` 不可用时试 `py`、`python3`，或用本机 Codex 运行时自带的解释器。

`--line` 输出形如 `账单：本轮 ¥0.026（1 步） · 会话 ¥0.15（6 步） · 谷价`。
用户要求「每轮回复自动附账单」时，靠的是全局指令 `~/.codex/AGENTS.md` 里那条规则，
每轮回复结束前跑一次 `--line` 并把这一行原样放在最后一行。

## 口径

- 三块账：**当前步**是最后一次 API 调用，**当前轮**是同一 `turn_id` 内多步累加，
  **会话累计**是整条会话，带步数与完全失效次数（有输入但缓存命中为 0 的步）。
- **峰谷**：北京时间工作日 09:00–12:00、14:00–18:00 按峰价，其余时段、周六日与
  中国法定节假日全天谷价。每一步按它自己发生的时刻计价，不按最新时刻统算。
- **价目表**：低谷 缓存命中 0.02 / 未命中输入 1 / 输出 4 元每百万 token，高峰翻倍。
  按 DeepSeek-V4.1-Flash 价估算，是本地估算不是官方账单；模型名不含 `flash` 时
  脚本会在末尾标注实际运行模型。
- 改价、改节假日表改 `scripts/bill.py` 顶部的 `FLASH_OFFPEAK`、`PEAK_MULTIPLIER`、
  `HOLIDAYS`。节假日只收到 2026 年，新年度安排公布后补日期即可。

## 回复用户

三块账各自给「总额 + 命中/未命中/输出三行」，再补一句峰谷与计价模型。用户问
「要不要换窗口」时，用会话累计的每步均价和缓存命中率说话，别只扔 token 数。
