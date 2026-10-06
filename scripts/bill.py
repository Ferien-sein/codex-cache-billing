#!/usr/bin/env python3
"""Codex 缓存账单。

读 Codex 会话日志（~/.codex/sessions/**/*.jsonl）里每次大模型 API 调用的
用量，按 DeepSeek 峰谷价目表折算成金额，输出当前步 / 当前轮 / 会话累计三块账。

口径与 DSH 插件 dsh-cache-billing 一致：
- 一次 API 调用算一步；同一轮的步累加成轮；整条会话累加。
- 缓存命中读 cached_input_tokens，未命中输入 = input_tokens + cache_write_input_tokens，
  输出读 output_tokens。
- 每一步按该步发生的时刻判峰谷，跨轮不按最新时刻统算。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 价目表：CNY 元 / 百万 token，低谷基准价，高峰翻倍 ──
FLASH_OFFPEAK = {"hit": 0.02, "miss": 1.0, "out": 4.0}
PEAK_MULTIPLIER = 2
PRICING_LABEL = "DeepSeek-V4.1-Flash"

# 中国法定节假日（北京时间，只收放假日；周末本就全天谷价），2026 年国务院放假安排。
HOLIDAYS = {
    "2026-01-01", "2026-01-02", "2026-01-03",
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
    "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    "2026-04-04", "2026-04-05", "2026-04-06",
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05",
    "2026-06-19", "2026-06-20", "2026-06-21",
    "2026-09-25", "2026-09-26", "2026-09-27",
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05",
    "2026-10-06", "2026-10-07",
}

BEIJING = timezone(timedelta(hours=8))


def is_peak(at: datetime) -> bool:
    """北京工作日 09:00–12:00、14:00–18:00 为高峰；周末与法定节假日全天谷价。"""
    local = at.astimezone(BEIJING)
    if local.weekday() >= 5:
        return False
    if local.strftime("%Y-%m-%d") in HOLIDAYS:
        return False
    return 9 <= local.hour < 12 or 14 <= local.hour < 18


def rates(at: datetime) -> dict[str, float]:
    factor = PEAK_MULTIPLIER if is_peak(at) else 1
    return {key: value * factor for key, value in FLASH_OFFPEAK.items()}


@dataclass
class Step:
    """一次 API 调用的用量。"""

    at: datetime
    turn: str
    hit: int
    miss: int
    out: int
    model: str = ""

    @property
    def cost(self) -> tuple[float, float, float]:
        row = rates(self.at)
        return (
            self.hit * row["hit"] / 1e6,
            self.miss * row["miss"] / 1e6,
            self.out * row["out"] / 1e6,
        )

    @property
    def tier(self) -> str:
        return "peak" if is_peak(self.at) else "offPeak"


@dataclass
class Bucket:
    hit: int = 0
    miss: int = 0
    out: int = 0
    hit_cost: float = 0.0
    miss_cost: float = 0.0
    out_cost: float = 0.0
    steps: int = 0
    full_miss: int = 0

    def add(self, step: Step) -> None:
        hit_cost, miss_cost, out_cost = step.cost
        self.hit += step.hit
        self.miss += step.miss
        self.out += step.out
        self.hit_cost += hit_cost
        self.miss_cost += miss_cost
        self.out_cost += out_cost
        self.steps += 1
        if step.hit == 0 and (step.miss + step.out) > 0:
            self.full_miss += 1

    @property
    def cost(self) -> float:
        return self.hit_cost + self.miss_cost + self.out_cost

    @property
    def tokens(self) -> int:
        return self.hit + self.miss + self.out

    @property
    def input_tokens(self) -> int:
        return self.hit + self.miss


def sessions_root() -> Path:
    home = os.environ.get("CODEX_HOME")
    base = Path(home) if home else Path.home() / ".codex"
    return base / "sessions"


def list_sessions(limit: int) -> list[Path]:
    root = sessions_root()
    if not root.exists():
        return []
    files = sorted(root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def resolve_session(spec: str) -> Path:
    if spec and spec not in {"latest", "current"}:
        candidate = Path(spec)
        if candidate.exists():
            return candidate
        for found in list_sessions(500):
            if spec in found.name:
                return found
        raise SystemExit(f"找不到会话：{spec}")
    found = list_sessions(1)
    if not found:
        raise SystemExit(f"没有找到会话日志：{sessions_root()}")
    return found[0]


def parse_step(record: dict) -> Step | None:
    """一条 token_usage_record 就是一步。"""
    if record.get("type") != "token_usage_record":
        return None
    payload = record.get("payload") or {}
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    raw_time = record.get("timestamp") or payload.get("timestamp")
    try:
        at = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
    except ValueError:
        at = datetime.now(timezone.utc)
    return Step(
        at=at,
        turn=str(payload.get("turn_id") or ""),
        hit=int(usage.get("cached_input_tokens") or 0),
        miss=int(usage.get("input_tokens") or 0) + int(usage.get("cache_write_input_tokens") or 0),
        out=int(usage.get("output_tokens") or 0),
        model=str(payload.get("model") or ""),
    )


def read_steps(path: Path) -> list[Step]:
    """优先读 token_usage_record；老日志没有该类型时退化为 token_count 事件。"""
    steps: list[Step] = []
    fallback: list[Step] = []
    model = ""
    turn = ""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = record.get("payload") or {}
            kind = record.get("type")
            if kind == "turn_context":
                turn = str(payload.get("turn_id") or turn)
            elif kind == "session_meta":
                model = str(payload.get("model") or model)
            elif kind == "event_msg" and payload.get("type") == "thread_settings_applied":
                settings = payload.get("thread_settings") or {}
                model = str(settings.get("model") or model)
            elif kind == "world_state":
                state = payload.get("state") or {}
                mode = state.get("collaboration_mode") or {}
                model = str(mode.get("model") or model)
            step = parse_step(record)
            if step is not None:
                step.model = step.model or model
                steps.append(step)
                continue
            if record.get("type") != "event_msg":
                continue
            payload = record.get("payload") or {}
            if payload.get("type") != "token_count":
                continue
            usage = ((payload.get("info") or {}).get("last_token_usage")) or {}
            try:
                at = datetime.fromisoformat(str(record.get("timestamp")).replace("Z", "+00:00"))
            except ValueError:
                continue
            fallback.append(
                Step(
                    at=at,
                    turn=turn,
                    hit=int(usage.get("cached_input_tokens") or 0),
                    miss=int(usage.get("input_tokens") or 0)
                    + int(usage.get("cache_write_input_tokens") or 0),
                    out=int(usage.get("output_tokens") or 0),
                    model=model,
                )
            )
    return steps or fallback


def format_tokens(value: int) -> str:
    def scaled(number: float) -> str:
        return str(round(number)) if number >= 100 else str(round(number * 10) / 10)

    if value < 1000:
        return str(value)
    if value < 1_000_000:
        return f"{scaled(value / 1000)}K"
    return f"{scaled(value / 1_000_000)}M"


def format_amount(value: float, digits: int) -> str:
    if value <= 0:
        return "0"
    return f"{value:.{digits}f}"


def render(label: str, bucket: Bucket, digits: int) -> list[str]:
    lines = [f"{label:<14}{format_tokens(bucket.tokens):>9} tok   ¥{format_amount(bucket.cost, digits)}"]
    rows = [
        ("缓存命中", bucket.hit, bucket.hit_cost),
        ("缓存未命中", bucket.miss, bucket.miss_cost),
        ("输出", bucket.out, bucket.out_cost),
    ]
    for name, tokens, cost in rows:
        lines.append(f"  {name:<10}{format_tokens(tokens):>8} tok   ¥{format_amount(cost, digits)}")
    return lines


def build_bill(steps: list[Step]) -> dict:
    session = Bucket()
    for step in steps:
        session.add(step)
    last = steps[-1]
    current_turn = Bucket()
    for step in steps:
        if step.turn == last.turn:
            current_turn.add(step)
    return {"session": session, "turn": current_turn, "step": last}


def main() -> int:
    parser = argparse.ArgumentParser(description="Codex 缓存账单（按 DeepSeek 峰谷价估算）")
    parser.add_argument("--session", default="latest", help="会话文件路径、文件名片段，或 latest")
    parser.add_argument("--list", action="store_true", help="列出最近的会话日志")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--line", action="store_true", help="只输出一行摘要，供每轮自动附账单用")
    parser.add_argument("--limit", type=int, default=10, help="--list 显示条数")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    if args.list:
        for path in list_sessions(args.limit):
            stamp = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"{stamp}  {path.name}")
        return 0

    path = resolve_session(args.session)
    steps = read_steps(path)
    if not steps:
        if args.line:
            print("账单：本次会话暂无用量")
            return 0
        print(f"{path.name}：没有 Token 用量记录")
        return 0

    bill = build_bill(steps)
    session, turn, last = bill["session"], bill["turn"], bill["step"]

    if args.line:
        tier_text = "峰价" if last.tier == "peak" else "谷价"
        print(
            f"账单：本轮 ¥{format_amount(turn.cost, 3)}（{turn.steps} 步）"
            f" · 会话 ¥{format_amount(session.cost, 2)}（{session.steps} 步） · {tier_text}"
        )
        return 0

    if args.json:
        print(
            json.dumps(
                {
                    "session_file": str(path),
                    "model": last.model,
                    "tier": last.tier,
                    "currency": "CNY",
                    "step": {
                        "tokens": last.hit + last.miss + last.out,
                        "hit": last.hit,
                        "miss": last.miss,
                        "out": last.out,
                        "cost": sum(last.cost),
                    },
                    "turn": {
                        "steps": turn.steps,
                        "tokens": turn.tokens,
                        "hit": turn.hit,
                        "miss": turn.miss,
                        "out": turn.out,
                        "cost": turn.cost,
                    },
                    "session": {
                        "steps": session.steps,
                        "tokens": session.tokens,
                        "hit": session.hit,
                        "miss": session.miss,
                        "out": session.out,
                        "cost": session.cost,
                        "full_miss_steps": session.full_miss,
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"缓存账单 · {path.name}")
    step_bucket = Bucket()
    step_bucket.add(last)
    for line in render("当前步", step_bucket, 4):
        print(line)
    for line in render("当前轮", turn, 3):
        print(line)
    label = f"会话累计 · {session.steps} 步"
    for line in render(label, session, 2):
        print(line)
    if session.full_miss > 0:
        print(f"  {'完全失效':<10}{session.full_miss:>8} 次")
    tier_text = "峰价" if last.tier == "peak" else "谷价"
    model_note = ""
    if last.model and "flash" not in last.model.lower():
        model_note = f" · 实际运行 {last.model}"
    print(f"{tier_text} · 按 {PRICING_LABEL} 估算{model_note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
