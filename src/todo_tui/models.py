"""タスクとその設定項目 (ステータス・タグ) のデータモデル"""

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

# ステータス・タグに使える色 (値, 表示名)
# 端末のANSI 16色だけを使い、ターミナルの配色設定に追従させる。"" は端末の既定色
COLORS: list[tuple[str, str]] = [
    ("", "既定"),
    ("red", "赤"),
    ("green", "緑"),
    ("yellow", "黄"),
    ("blue", "青"),
    ("magenta", "紫"),
    ("cyan", "水"),
    ("white", "白"),
    ("bright_black", "灰"),
    ("bright_red", "明るい赤"),
    ("bright_green", "明るい緑"),
    ("bright_yellow", "明るい黄"),
    ("bright_blue", "明るい青"),
    ("bright_magenta", "明るい紫"),
    ("bright_cyan", "明るい水"),
    ("bright_white", "明るい白"),
]

_COLOR_LABELS = dict(COLORS)


def color_label(color: str) -> str:
    """色の表示名"""
    return _COLOR_LABELS.get(color, color)


def valid_color(color: object) -> str:
    """未知の色は既定色に落とす"""
    return color if isinstance(color, str) and color in _COLOR_LABELS else ""


def textual_color(color: str) -> str:
    """Textual のウィジェット (Select / SelectionList など) で使う色名

    Rich では "blue" が端末のANSI色を指すが、Textual では CSS の色として
    #0000ff に解釈されてしまう。端末の配色に追従させるため ansi_ を付ける。
    """
    return f"ansi_{color}" if color else ""


def new_id() -> str:
    """設定項目の識別子

    名前を変えてもタスク側の参照が壊れないよう、ステータス・タグはIDで参照する。
    """
    return uuid.uuid4().hex[:8]


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


def priority_rank(priority: str) -> int:
    """並び替え用の順位"""
    return _PRIORITY_RANK.get(priority, 1)


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


def _name_of(data: dict) -> str:
    """設定項目の名前を取り出す (空なら壊れているとみなす)"""
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name が空です")
    return name.strip()


@dataclass
class Status:
    """タスクのステータス (設定画面で追加・編集する)"""

    id: str
    name: str
    color: str = ""
    done: bool = False  # このステータスを「完了扱い」にするか

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color, "done": self.done}

    @classmethod
    def from_dict(cls, data: dict) -> Status:
        """保存された辞書から復元する (名前が無ければ ValueError)"""
        return cls(
            id=str(data.get("id") or new_id()),
            name=_name_of(data),
            color=valid_color(data.get("color")),
            done=bool(data.get("done", False)),
        )


@dataclass
class Tag:
    """タスクのタグ (設定画面で追加・編集する)"""

    id: str
    name: str
    color: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "color": self.color}

    @classmethod
    def from_dict(cls, data: dict) -> Tag:
        """保存された辞書から復元する (名前が無ければ ValueError)"""
        return cls(
            id=str(data.get("id") or new_id()),
            name=_name_of(data),
            color=valid_color(data.get("color")),
        )


@dataclass
class Task:
    """1件のタスク

    ステータスとタグは設定側の項目を ID で参照する。完了かどうかは
    ステータスの ``done`` で決まるため、タスク自身は持たない。
    """

    title: str
    due: date | None = None
    priority: str = DEFAULT_PRIORITY
    memo: str = ""
    status: str = ""  # Status.id (空・未知なら既定ステータス扱い)
    tags: list[str] = field(default_factory=list)  # Tag.id のリスト
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def to_dict(self) -> dict:
        """保存用の辞書にする"""
        return {
            "id": self.id,
            "title": self.title,
            "due": self.due.isoformat() if self.due else None,
            "priority": self.priority,
            "memo": self.memo,
            "status": self.status,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        """保存された辞書から復元する

        タイトルと期限が壊れている場合だけ ValueError を投げ (呼び出し側でその
        1件を飛ばす)、優先度など復帰できる項目は既定値に落とす。
        ステータス・タグが今の設定に無い場合の始末は Config 側で行う。
        """
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title が空です")

        due_raw = data.get("due")
        due = date.fromisoformat(due_raw) if due_raw else None

        priority = data.get("priority", DEFAULT_PRIORITY)
        if priority not in PRIORITIES:
            priority = DEFAULT_PRIORITY

        raw_tags = data.get("tags")
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []

        return cls(
            title=title,
            due=due,
            priority=priority,
            memo=str(data.get("memo") or ""),
            status=str(data.get("status") or ""),
            tags=tags,
            id=str(data.get("id") or uuid.uuid4().hex),
        )
