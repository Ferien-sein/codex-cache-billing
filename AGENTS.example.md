# 会话账单

每轮回复的最后一行附上会话账单，跑这一条命令，把输出原样放在最后一行：

```
python "$env:USERPROFILE\.codex\skills\cache-billing\scripts\bill.py" --line
```

（cmd 里把路径写成 `%USERPROFILE%\.codex\skills\cache-billing\scripts\bill.py`。）

输出形如 `账单：本轮 ¥0.026（1 步） · 会话 ¥0.15（6 步） · 谷价`。

- 原样贴，不加标题、不复述、不在正文里再解释一遍。
- 脚本回「本次会话暂无用量」时省略这一行，也不要提这件事。
- 这次回复本身就在讲账单，或用户明说不要，就不必附。
- `python` 跑不通就试 `py`、`python3`；都跑不通就跳过这一行，并在末尾补一句脚本不可用。
