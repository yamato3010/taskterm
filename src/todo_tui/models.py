"""タスクのデータモデル"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date

# 優先度: キー -> (表示名, Richのスタイル)
# 色は端末のANSIパレットに追従する色名 (red/yellow/blue) を使う
PRIORITIES: dict[str, tuple[str, str]] = {
    "high": ("高", "bold red"),
    "mid": ("中", "yellow"),
    "low": ("低", "blue"),
}

DEFAULT_PRIORITY = "mid"

# 一覧の並び順 (数値が小さいほど先)
_PRIORITY_RANK = {"high": 0, "mid": 1, "low": 2}

# p キーで切り替える順序
_PRIORITY_CYCLE = ["high", "mid", "low"]

# 曜日名 (date.weekday() の 0=月曜 に合わせた並び)
WEEKDAYS = "月火水木金土日"


def priority_label(priority: str) -> str:
    """優先度の表示名"""
    return PRIORITIES.get(priority, PRIORITIES[DEFAULT_PRIORITY])[0]


def priority_style(priority: str) -> str:
    """優先度の表示スタイル"""
    return PRIORITIES.get(priority, PRIORITIES[DEFAULT_PRIORITY])[1]


def next_priority(priority: str) -> str:
    """次の優先度 (高 → 中 → 低 → 高)"""
    if priority not in _PRIORITY_CYCLE:
        return DEFAULT_PRIORITY
    return _PRIORITY_CYCLE[(_PRIORITY_CYCLE.index(priority) + 1) % len(_PRIORITY_CYCLE)]


def format_due(due: date | None) -> str:
    """期限を「8/6(木)」の形にする (期限なしは空文字)"""
    if due is None:
        return ""
    return f"{due.month}/{due.day}({WEEKDAYS[due.weekday()]})"


def parse_due(text: str, *, today: date | None = None) -> date | None:
    """入力された期限を date にする

    受け付ける形式は ``2026-08-06`` ``2026/8/6`` ``8/6`` ``8-6``。
    月日だけの場合は今年として扱う。空文字は「期限なし」で None を返す。
    形式が不正なら ValueError を投げる。
    """
    text = text.strip()
    if not text:
        return None

    parts = re.split(r"[-/.]", text)
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        raise ValueError(f"期限の形式が不正です: {text}") from None

    if len(numbers) == 2:
        numbers.insert(0, (today or date.today()).year)
    if len(numbers) != 3:
        raise ValueError(f"期限の形式が不正です: {text}")

    try:
        return date(*numbers)
    except ValueError:
        raise ValueError(f"存在しない日付です: {text}") from None


@dataclass
class Task:
    """1件のタスク"""

    title: str
    due: date | None = None
    priority: str = DEFAULT_PRIORITY
    memo: str = ""
    done: bool = False
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def is_overdue(self, today: date) -> bool:
        """期限を過ぎた未完了タスクか"""
        return not self.done and self.due is not None and self.due < today

    def to_dict(self) -> dict:
        """保存用の辞書にする"""
        return {
            "id": self.id,
            "title": self.title,
            "due": self.due.isoformat() if self.due else None,
            "priority": self.priority,
            "memo": self.memo,
            "done": self.done,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        """保存された辞書から復元する

        タイトルと期限が壊れている場合だけ ValueError を投げ (呼び出し側でその
        1件を飛ばす)、優先度など復帰できる項目は既定値に落とす。
        """
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title が空です")

        due_raw = data.get("due")
        due = date.fromisoformat(due_raw) if due_raw else None

        priority = data.get("priority", DEFAULT_PRIORITY)
        if priority not in PRIORITIES:
            priority = DEFAULT_PRIORITY

        return cls(
            title=title,
            due=due,
            priority=priority,
            memo=str(data.get("memo") or ""),
            done=bool(data.get("done", False)),
            id=str(data.get("id") or uuid.uuid4().hex),
        )


def sort_tasks(tasks: list[Task]) -> list[Task]:
    """未完了 → 期限が近い順 (期限なしは最後) → 優先度 → タイトル で並べる"""
    return sorted(
        tasks,
        key=lambda t: (
            t.done,
            t.due is None,
            t.due or date.max,
            _PRIORITY_RANK.get(t.priority, 1),
            t.title,
        ),
    )
