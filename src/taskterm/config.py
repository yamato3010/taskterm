"""設定 (ステータス・タグ) の読み書き

設定は JSON で ``~/.config/taskterm/config.json`` に保存する
(``XDG_CONFIG_HOME`` があればそれに従う)。ファイルが無い・壊れている場合は
既定値で動作し、アプリの起動を妨げない。

完了かどうか・並び順といった「ユーザーの定義に依存するタスクの意味付け」は
ここに集めている (タスク自身は ID を持つだけ)。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .models import FISCAL_START_MONTH, Status, Tag, Task, new_id, priority_rank

log = logging.getLogger(__name__)

APP_DIR_NAME = "taskterm"


def default_statuses() -> list[Status]:
    """初期のステータス (設定画面で自由に変えられる)"""
    return [
        Status(id="todo", name="未着手"),
        Status(id="doing", name="進行中", color="cyan"),
        Status(id="waiting", name="保留", color="yellow"),
        Status(id="done", name="完了", color="green", done=True),
    ]


def config_dir() -> Path:
    """設定ディレクトリ"""
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / APP_DIR_NAME


def config_path() -> Path:
    """設定ファイルのパス"""
    return config_dir() / "config.json"


@dataclass
class Config:
    """アプリ設定"""

    statuses: list[Status] = field(default_factory=default_statuses)
    tags: list[Tag] = field(default_factory=list)
    show_all: bool = False  # 一覧の表示範囲 (False: 選択日のみ / True: 全件)
    show_quarter: bool = False  # 四半期パネルを出すか
    fiscal_start_month: int = FISCAL_START_MONTH  # 年度の開始月 (1〜12)

    # ── ステータス・タグの参照 ────────────────

    def status_by_id(self, status_id: str) -> Status | None:
        return next((s for s in self.statuses if s.id == status_id), None)

    def tag_by_id(self, tag_id: str) -> Tag | None:
        return next((t for t in self.tags if t.id == tag_id), None)

    def default_status(self) -> Status:
        """新しいタスクのステータス (一覧の先頭)"""
        return self.statuses[0]

    def done_status(self) -> Status | None:
        """「完了」にするときのステータス (完了扱いの先頭。無ければ None)"""
        return next((s for s in self.statuses if s.done), None)

    def undone_status(self) -> Status:
        """「未完了」に戻すときのステータス (完了扱いでない先頭)"""
        return next((s for s in self.statuses if not s.done), self.default_status())

    def status_of(self, task: Task) -> Status:
        """タスクのステータス (未知なら既定)"""
        return self.status_by_id(task.status) or self.default_status()

    def tags_of(self, task: Task) -> list[Tag]:
        """タスクのタグ (設定の並び順で返す)"""
        return [t for t in self.tags if t.id in task.tags]

    # ── タスクの意味付け ──────────────────────

    def is_done(self, task: Task) -> bool:
        """完了扱いのステータスか"""
        return self.status_of(task).done

    def apply_status(self, task: Task, status_id: str, today: date) -> None:
        """タスクのステータスを変え、完了日を付け外しする

        ステータスを変える経路 (完了の切り替え・s キー・編集フォーム) は全て
        ここを通す。未完了から完了になったときだけ ``today`` を記録し、未完了に
        戻したら消す。完了のまま別の完了ステータスに移した場合は最初の日を残す。
        """
        was_done = self.is_done(task)
        task.status = status_id
        if self.is_done(task):
            if not was_done:
                task.done_at = today
        else:
            task.done_at = None

    def is_overdue(self, task: Task, today: date) -> bool:
        """期限を過ぎた未完了タスクか"""
        return not self.is_done(task) and task.due is not None and task.due < today

    def sort_tasks(self, tasks: list[Task]) -> list[Task]:
        """未完了 → 期限が近い順 (期限なしは最後) → 優先度 → タイトル で並べる"""
        return sorted(
            tasks,
            key=lambda t: (
                self.is_done(t),
                t.due is None,
                t.due or date.max,
                priority_rank(t.priority),
                t.title,
            ),
        )

    def sort_done_tasks(self, tasks: list[Task]) -> list[Task]:
        """完了タブ用に、完了日の新しい順で並べる

        完了日を持たない旧データは日付で比べられないので末尾にまとめる。
        """
        return sorted(
            tasks,
            # 新しい順にしたいので、日付そのものではなく通日の符号を反転して使う
            key=lambda t: (t.done_at is None, -(t.done_at or date.min).toordinal(), t.title),
        )

    def normalize_task(self, task: Task, *, legacy_done: bool = False) -> None:
        """ステータス・タグを今の設定に合わせて正す

        設定から消されたステータス・タグを参照しているタスクを救済する。
        ``legacy_done`` は、ステータスを持たない旧形式のタスクを読み込むときの
        完了フラグ (True なら完了扱いのステータスへ移す)。
        """
        if self.status_by_id(task.status) is None:
            fallback = (self.done_status() if legacy_done else None) or self.default_status()
            task.status = fallback.id
        # 完了ステータスを消したタスクに完了日が残らないようにする
        # (逆は補わない。完了日を持たない旧データはそのまま「完了日なし」で扱う)
        if not self.is_done(task):
            task.done_at = None
        known = {t.id for t in self.tags}
        task.tags = [t for t in task.tags if t in known]

    # ── 保存・読み込み ────────────────────────

    @classmethod
    def load(cls) -> Config:
        """設定を読み込む。読めなければ既定値を返す"""
        path = config_path()
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as e:
            log.warning("設定ファイルを読み込めないため既定値を使います (%s): %s", path, e)
            return cls()

        if not isinstance(data, dict):
            log.warning("設定ファイルの形式が不正なため既定値を使います: %s", path)
            return cls()

        statuses = _load_items(data.get("statuses"), Status)
        tags = _load_items(data.get("tags"), Tag)

        # ステータスが1つも無いと「既定のステータス」が決まらないため既定値に戻す
        if not statuses:
            log.warning("ステータスが空のため既定値を使います: %s", path)
            statuses = default_statuses()

        return cls(
            statuses=_dedupe_ids(statuses),
            tags=_dedupe_ids(tags),
            show_all=bool(data.get("show_all", False)),
            show_quarter=bool(data.get("show_quarter", False)),
            fiscal_start_month=_valid_month(data.get("fiscal_start_month")),
        )

    def save(self) -> None:
        """設定を保存する。失敗した場合は OSError を送出する"""
        path = config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / (path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(
                {
                    "statuses": [s.to_dict() for s in self.statuses],
                    "tags": [t.to_dict() for t in self.tags],
                    "show_all": self.show_all,
                    "show_quarter": self.show_quarter,
                    "fiscal_start_month": self.fiscal_start_month,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
            f.write("\n")
        os.replace(tmp, path)


def _load_items(raw: object, item_class: type) -> list:
    """設定項目のリストを読み込む (壊れている項目は飛ばす)"""
    if not isinstance(raw, list):
        return []
    items = []
    for entry in raw:
        try:
            items.append(item_class.from_dict(entry))
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            log.warning("読み込めない設定項目を飛ばします (%r): %s", entry, e)
    return items


def _valid_month(raw: object) -> int:
    """年度の開始月 (1〜12でなければ既定に落とす)"""
    return raw if isinstance(raw, int) and 1 <= raw <= 12 else FISCAL_START_MONTH


def _dedupe_ids(items: list) -> list:
    """IDの重複を解消する (手で編集して同じIDが並んだ場合の保険)"""
    seen: set[str] = set()
    for item in items:
        if item.id in seen:
            item.id = new_id()
        seen.add(item.id)
    return items
