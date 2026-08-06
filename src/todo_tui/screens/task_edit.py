"""タスクの追加・編集フォーム"""

from __future__ import annotations

from datetime import date
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select

from ..models import DEFAULT_PRIORITY, PRIORITIES, Task, parse_due


class TaskEditScreen(ModalScreen[Optional[Task]]):
    """タスクを追加・編集するモーダル

    保存すると Task を、取り消すと None を返す。編集の場合は渡された
    Task をそのまま書き換えて返す。
    """

    # 入力欄では Enter で保存できるが、優先度やボタンにフォーカスがあるときは
    # Enter がそちらに取られるため、どこからでも保存できるキーも用意する
    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("ctrl+s", "save", "保存"),
    ]

    def __init__(self, task: Task | None = None, *, default_due: date | None = None) -> None:
        super().__init__()
        self._target = task
        # 追加のときは、カレンダーで選んでいる日を期限の初期値にする
        self._due = task.due if task else default_due

    def compose(self) -> ComposeResult:
        task = self._target
        with Vertical(id="edit-dialog") as dialog:
            dialog.border_title = "タスクを編集" if task else "タスクを追加"

            yield Label("タイトル")
            yield Input(value=task.title if task else "", placeholder="やること", id="title")

            yield Label("期限 (空欄で期限なし / 例: 2026-08-06、8/6)")
            yield Input(
                value=self._due.isoformat() if self._due else "",
                placeholder="YYYY-MM-DD",
                id="due",
            )

            yield Label("優先度")
            yield Select(
                [(label, key) for key, (label, _) in PRIORITIES.items()],
                value=task.priority if task else DEFAULT_PRIORITY,
                allow_blank=False,
                id="priority",
            )

            yield Label("メモ")
            yield Input(value=task.memo if task else "", placeholder="任意", id="memo")

            with Horizontal(id="edit-buttons"):
                yield Button("保存", variant="primary", id="save")
                yield Button("取消", id="cancel")

    def on_mount(self) -> None:
        self.query_one("#title", Input).focus()

    def on_input_submitted(self) -> None:
        """入力欄で Enter を押したら保存する"""
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._save()

    def _save(self) -> None:
        title_input = self.query_one("#title", Input)
        title = title_input.value.strip()
        if not title:
            self.notify("タイトルを入力してください", severity="warning", timeout=4)
            title_input.focus()
            return

        due_input = self.query_one("#due", Input)
        try:
            due = parse_due(due_input.value)
        except ValueError as e:
            self.notify(str(e), severity="warning", timeout=4)
            due_input.focus()
            return

        priority = str(self.query_one("#priority", Select).value)
        memo = self.query_one("#memo", Input).value.strip()

        task = self._target
        if task is None:
            self.dismiss(Task(title=title, due=due, priority=priority, memo=memo))
            return

        task.title = title
        task.due = due
        task.priority = priority
        task.memo = memo
        self.dismiss(task)
