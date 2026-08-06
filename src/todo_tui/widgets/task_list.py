"""タスク一覧ウィジェット"""

from __future__ import annotations

from datetime import date

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable

from ..models import Task, format_due, priority_label, priority_style


class TaskTable(DataTable):
    """タスクを一覧表示する DataTable

    タイトルは長さが読めないので最後の列に置き、状態・期限・優先度が
    横スクロールで隠れないようにしている。
    """

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
        self.add_column("", width=3)
        self.add_column("期限", width=9)
        self.add_column("優先", width=4)
        self.add_column("タスク")

    def update_tasks(self, tasks: list[Task], today: date) -> None:
        """一覧を作り直す (選択中だったタスクにカーソルを戻す)"""
        previous = self.selected_task
        self._tasks = list(tasks)
        self.clear()
        for task in tasks:
            self.add_row(*_row(task, today))

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


def _row(task: Task, today: date) -> tuple[Text, Text, Text, Text]:
    """タスク1件を行の内容にする"""
    check = Text("[x]" if task.done else "[ ]", style="green" if task.done else "")

    due = Text(format_due(task.due))
    if task.is_overdue(today):
        due.stylize("bold red")
    elif task.due == today and not task.done:
        due.stylize("bold yellow")

    priority = Text(priority_label(task.priority), style=priority_style(task.priority))

    title = Text(task.title, style="dim strike" if task.done else "")
    if task.memo:
        # メモがあることの印 (中身は一覧の下の行に出す)
        title.append(" ✎", style="dim")

    return check, due, priority, title
