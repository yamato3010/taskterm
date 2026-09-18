"""タスクとその設定項目 (ステータス・タグ) のデータモデル"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

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

# 年度の開始月の既定 (4月始まり = 1Q が4〜6月)
FISCAL_START_MONTH = 4

# URLのスキーム (https: や msteams: など。無ければ https を補う)
_URL_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

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
    """日付を「8/6(木)」の形にする (None は空文字)"""
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


@dataclass(frozen=True)
class Quarter:
    """年度の開始月を起点に数えた四半期"""

    fiscal_year: int  # 年度 (開始月を含むほうの暦年)
    number: int  # 1〜4
    start: date
    end: date

    @property
    def days(self) -> int:
        """四半期の日数"""
        return (self.end - self.start).days + 1

    def remaining(self, day: date) -> int:
        """その日から終了までの残り日数 (その日は含まない。最終日なら0)"""
        return (self.end - day).days


def quarter_of(day: date, start_month: int) -> Quarter:
    """その日が属する四半期 (``start_month`` を年度の開始月として数える)"""
    number = ((day.month - start_month) % 12) // 3 + 1
    # 開始月より前の月は前の年度に属する
    fiscal_year = day.year - (1 if day.month < start_month else 0)
    start = _add_months(date(fiscal_year, start_month, 1), (number - 1) * 3)
    return Quarter(fiscal_year, number, start, _add_months(start, 3) - timedelta(days=1))


def _add_months(first_day: date, months: int) -> date:
    """月初の日付を月単位で進める"""
    year, month = divmod(first_day.year * 12 + first_day.month - 1 + months, 12)
    return date(year, month + 1, 1)


def normalize_url(url: str) -> str:
    """入力されたURLを開ける形にする

    ``example.com/x`` のようにスキームを省いて貼られた場合は ``https://`` を補う。
    ``msteams:`` のようなアプリのスキームはそのまま通す。
    """
    url = url.strip()
    if url and not _URL_SCHEME.match(url):
        return f"https://{url}"
    return url


def memo_heading(day: date) -> str:
    """メモの追記に使う日付見出し (全画面表示では markdown の見出しとして描かれる)"""
    return f"## {day.isoformat()}"


def append_memo_heading(memo: str, day: date) -> str:
    """メモの末尾に追記用の日付見出しを足した本文を返す

    末尾から遡って最初に見つかる見出しがその日のものなら、同じ日の欄に
    書き足すため見出しは足さない。戻り値は末尾にカーソルを置けばそのまま
    続きが書ける形 (最後が改行) にする。
    """
    heading = memo_heading(day)
    body = memo.rstrip()
    if not body:
        return f"{heading}\n"

    for line in reversed(body.splitlines()):
        if line.startswith("#"):
            # 同じ日の欄が開いていれば、そこに続けて書く
            return f"{body}\n" if line.strip() == heading else f"{body}\n\n{heading}\n"
    return f"{body}\n\n{heading}\n"


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
class Link:
    """タスクに紐づくリンク

    Teams のスレッドや Backlog のチケットなど、そのタスクの背景を辿るための
    参照先を、それが何かを示すタイトル付きで持つ。
    """

    title: str
    url: str

    def label(self) -> str:
        """一覧に出す表示名 (タイトルが空ならURLで代用する)"""
        return self.title or self.url

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url}

    @classmethod
    def from_dict(cls, data: dict) -> Link:
        """保存された辞書から復元する (URLが無ければ ValueError)"""
        url = data.get("url")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url が空です")
        title = data.get("title")
        return cls(
            title=title.strip() if isinstance(title, str) else "",
            url=url.strip(),
        )


@dataclass
class Subtask:
    """タスクを分解したチェックリストの1項目

    期限・ステータス・優先度は持たない (1つの作業の手順を並べるためのもの)。
    個別に日付で管理したくなった項目は、独立したタスクにする。
    """

    title: str
    done: bool = False

    def to_dict(self) -> dict:
        return {"title": self.title, "done": self.done}

    @classmethod
    def from_dict(cls, data: dict) -> Subtask:
        """保存された辞書から復元する (タイトルが無ければ ValueError)"""
        title = data.get("title")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title が空です")
        return cls(title=title.strip(), done=bool(data.get("done", False)))


def subtask_progress(subtasks: list[Subtask]) -> tuple[int, int]:
    """チェックリストの (完了数, 総数)"""
    return sum(1 for s in subtasks if s.done), len(subtasks)


@dataclass
class Task:
    """1件のタスク

    ステータスとタグは設定側の項目を ID で参照する。完了かどうかは
    ステータスの ``done`` で決まるため、タスク自身は持たない (持つのは
    「いつ完了にしたか」だけ)。
    """

    title: str
    due: date | None = None
    priority: str = DEFAULT_PRIORITY
    memo: str = ""
    status: str = ""  # Status.id (空・未知なら既定ステータス扱い)
    done_at: date | None = None  # 完了にした日 (未完了なら None。旧データは None のまま)
    tags: list[str] = field(default_factory=list)  # Tag.id のリスト
    links: list[Link] = field(default_factory=list)
    subtasks: list[Subtask] = field(default_factory=list)
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
            "done_at": self.done_at.isoformat() if self.done_at else None,
            "tags": list(self.tags),
            "links": [link.to_dict() for link in self.links],
            "subtasks": [item.to_dict() for item in self.subtasks],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Task:
        """保存された辞書から復元する

        タイトルと期限が壊れている場合だけ ValueError を投げ (呼び出し側でその
        1件を飛ばす)、優先度など復帰できる項目は既定値に落とす (壊れたリンク・
        チェックリストの項目はその1件だけ飛ばす)。
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

        # 完了日は無くても困らないので、壊れていればタスクごと飛ばさず捨てる
        done_at_raw = data.get("done_at")
        try:
            done_at = date.fromisoformat(done_at_raw) if done_at_raw else None
        except (TypeError, ValueError):
            done_at = None

        raw_tags = data.get("tags")
        tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []

        raw_links = data.get("links")
        links = []
        for entry in raw_links if isinstance(raw_links, list) else []:
            try:
                links.append(Link.from_dict(entry))
            except (AttributeError, TypeError, ValueError):
                continue

        raw_subtasks = data.get("subtasks")
        subtasks = []
        for entry in raw_subtasks if isinstance(raw_subtasks, list) else []:
            try:
                subtasks.append(Subtask.from_dict(entry))
            except (AttributeError, TypeError, ValueError):
                continue

        return cls(
            title=title,
            due=due,
            priority=priority,
            memo=str(data.get("memo") or ""),
            status=str(data.get("status") or ""),
            done_at=done_at,
            tags=tags,
            links=links,
            subtasks=subtasks,
            id=str(data.get("id") or uuid.uuid4().hex),
        )


@dataclass
class Filter:
    """一覧の絞り込み条件 (f キーの絞り込み画面で決める)

    ステータス・タグとも ID の集合で持ち、空の場合はその項目では絞らない。
    タグを複数選んだときは「いずれかを含む」(OR) で判定する。
    アプリを閉じるまでの一時的な状態なので、設定ファイルには保存しない。
    """

    statuses: set[str] = field(default_factory=set)
    tags: set[str] = field(default_factory=set)

    @property
    def is_active(self) -> bool:
        """何かで絞り込んでいるか"""
        return bool(self.statuses or self.tags)

    def matches_tags(self, task: Task) -> bool:
        """タグの条件だけで判定する (ステータス別の件数を数えるとき用)"""
        return not self.tags or bool(self.tags.intersection(task.tags))

    def matches(self, task: Task, status_id: str) -> bool:
        """タスクが条件に合うか

        ``status_id`` は、設定に無いIDを既定へ寄せた後の表示上のステータス。
        """
        if self.statuses and status_id not in self.statuses:
            return False
        return self.matches_tags(task)
