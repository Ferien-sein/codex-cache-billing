# Codex 缓存账单

> 由 Codex 智能体在 2026-10-06 一次性开发完成：全程约 124 次模型调用、2874 万 token，按本项目同一套价目表折合约 ¥15.0。详见[开发方式与成本](#开发方式与成本)。

给 Codex 用的会话账单技能：读会话日志里每次大模型调用的用量，按 DeepSeek 峰谷价目表折算成金额，随时告诉你当前步、当前轮、整条会话各自花了多少钱。

## 它算什么

```
缓存账单 · rollout-….jsonl
当前步               46.2K tok   ¥0.0260
  缓存命中         21.8K tok   ¥0.0004
  缓存未命中        24.1K tok   ¥0.0241
  输出             365 tok   ¥0.0015
当前轮               46.2K tok   ¥0.026
会话累计 · 4 步         130K tok   ¥0.08
谷价 · 按 DeepSeek-V4.1-Flash 估算
```

口径与 DSH 插件 [dsh-cache-billing](https://github.com/better-er/dsh-cache-billing) 同源：

- 一次 API 调用算一步，同一轮的步累加成轮，整条会话累加。
- 缓存命中读 `cached_input_tokens`，未命中输入 = `input_tokens` + `cache_write_input_tokens`，输出读 `output_tokens`。
- 每一步按它自己发生的时刻判峰谷，不按最新时刻统算。

## 安装

把这个仓库放进 Codex 的技能目录，文件夹名保持 `cache-billing`：

```bash
git clone <本仓库地址> "$HOME/.codex/skills/cache-billing"
```

Windows PowerShell：

```powershell
git clone <本仓库地址> "$env:USERPROFILE\.codex\skills\cache-billing"
```

新开一个会话即可用，说「账单」「这花了多少钱」就会触发。

## 用法

```bash
python scripts/bill.py                      # 最新会话，三块账
python scripts/bill.py --session <片段|路径>  # 指定会话
python scripts/bill.py --list               # 最近改动的会话
python scripts/bill.py --json               # 机器可读
python scripts/bill.py --line               # 一行摘要
```

## 每轮回复自动附一行

把 [AGENTS.example.md](AGENTS.example.md) 的内容放进 `~/.codex/AGENTS.md`（Codex 的全局指令文件，已存在就追加），每轮回复的最后一行就会自动带上账单。记得把里面的路径换成你自己的。

## 口径与调价

- **峰谷**：北京时间工作日 09:00–12:00、14:00–18:00 按峰价，其余时段、周六日与中国法定节假日全天谷价。
- **价目表**：低谷 缓存命中 0.02 / 未命中输入 1 / 输出 4 元每百万 token，高峰翻倍。
- 改价、补新一年的节假日，改 `scripts/bill.py` 顶部的 `FLASH_OFFPEAK`、`PEAK_MULTIPLIER`、`HOLIDAYS`。

## 来源与致谢

记账口径、价目表与峰谷政策沿用 [better-er/dsh-cache-billing](https://github.com/better-er/dsh-cache-billing)（MIT，© 2026 betterer）。本项目是给 Codex 写的同口径实现，不是它的分支，也没有打包它的代码；上游又注明参考 [Phant0Meow/dsh-meow-cachebilling](https://github.com/Phant0Meow/dsh-meow-cachebilling) 的思路重写。上游的 MIT 许可与版权声明见 [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md)。

## 开发方式与成本

本项目由 Codex 智能体协助完成：2026-10-06 的一次会话内读完上游源码、核对宿主接口、写出脚本并自测。该会话的实际用量约：

| 项目 | 数量 |
| --- | --- |
| 模型调用 | 124 次 |
| Token 合计 | 约 2874 万 |
| 其中缓存命中输入 | 约 1426 万 |
| 其中未命中输入 | 约 1441 万 |
| 其中输出 | 约 7.8 万 |
| 按本项目同一套价目表估算 | 约 ¥15.0 |

数字取自会话日志的实际记录，随会话继续会略微增长；折算口径与脚本一致。

## 免责与合规

- 非官方项目，与 DeepSeek、OpenAI 及其关联公司无关；「DeepSeek」「Codex」等名称与商标归各自所有者。
- 金额是按公开价目表做的本地估算，不是账户账单，也不构成任何费用依据，实际扣费以服务商账单为准。
- 价目表与节假日数据来自公开信息，可能滞后或有调整，以官方公告为准。

## License

本项目以 [MIT](LICENSE) 发布。
