"""タスク一覧ウィジェット"""

from __future__ import annotations

from datetime import date

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable

from ..config import Config
from ..models import Task, format_due, priority_label, priority_style, subtask_progress

# 列幅 (タイトルは長さが読めないので最後に置き、残りの幅を与える)
_STATUS_WIDTH = 10
_DUE_WIDTH = 9
_PRIORITY_WIDTH = 4
_TAGS_WIDTH = 9

# 列幅に収まらない分は折り返さず「…」で切る
_CLIP = {"no_wrap": True, "overflow": "ellipsis"}


class TaskTable(DataTable):
    """タスクを一覧表示する DataTable

    タイトルは長さが読めないので最後の列に置き、ステータス・期限・優先度・
    タグが横スクロールで隠れないようにしている。
    """

    BINDING_GROUP_TITLE = "TODOリスト"

    # 矢印キー (DataTable標準) に加えて vim 風の jk でも動かせるようにする
    BINDINGS = [
        Binding("k", "cursor_up", "上へ", show=False),
        Binding("j", "cursor_down", "下へ", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tasks: list[Task] = []
        self.cursor_type = "row"
        self.zebra_stripes = True

    def on_mount(self) -> None:
        self.add_column("ステータス", width=_STATUS_WIDTH)
        self.add_column("期限", width=_DUE_WIDTH)
        self.add_column("優先", width=_PRIORITY_WIDTH)
        self.add_column("タグ", width=_TAGS_WIDTH)
        self.add_column("タスク")

    def update_tasks(self, tasks: list[Task], today: date, config: Config) -> None:
        """一覧を作り直す (選択中だったタスクにカーソルを戻す)"""
        previous = self.selected_task
        self._tasks = list(tasks)
        self.clear()
        for task in tasks:
            self.add_row(*_row(task, today, config))

        if previous is not None:
            for i, task in enumerate(tasks):
                if task.id == previous.id:
                    self.move_cursor(row=i)
                    break

    @property
    def selected_task(self) -> Task | None:
        """カーソル行のタスク (無ければ None)"""
        row = self.cursor_row
        if row is not None and 0 <= row < len(self._tasks):
            return self._tasks[row]
        return None


def _row(task: Task, today: date, config: Config) -> tuple[Text, ...]:
    """タスク1件を行の内容にする"""
    status = config.status_of(task)
    done = status.done

    status_cell = Text(status.name, style=status.color, **_CLIP)

    due = Text(format_due(task.due))
    if config.is_overdue(task, today):
        due.stylize("bold red")
    elif task.due == today and not done:
        due.stylize("bold yellow")

    priority = Text(priority_label(task.priority), style=priority_style(task.priority))

    tags = Text(**_CLIP)
    for i, tag in enumerate(config.tags_of(task)):
        if i:
            tags.append(",", style="dim")
        tags.append(tag.name, style=tag.color)

    title = Text(task.title, style="dim strike" if done else "")
    if task.memo:
        # メモがあることの印 (中身は一覧の下の行に出す)
        title.append(" ✎", style="dim")
    if task.links:
        # リンクがあることの印 (o キーで開ける)
        title.append(" ↗", style="dim")
    if task.subtasks:
        # チェックリストの進み具合 (中身は c キーで開ける)
        checked, total = subtask_progress(task.subtasks)
        title.append(f" {checked}/{total}", style="dim")

    return status_cell, due, priority, tags, title
