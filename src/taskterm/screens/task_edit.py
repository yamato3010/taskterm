"""タスクの追加・編集フォーム"""

from __future__ import annotations

from datetime import date
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from rich.text import Text
from textual.widgets import Button, Input, Label, Select, SelectionList, Static
from textual.widgets.selection_list import Selection

from ..config import Config
from ..models import DEFAULT_PRIORITY, PRIORITIES, Task, parse_due, textual_color
from .memo import MemoEditScreen


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
        Binding("ctrl+o", "edit_memo", "メモを編集"),
    ]

    def __init__(
        self,
        config: Config,
        task: Task | None = None,
        *,
        default_due: date | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._target = task
        # 追加のときは、カレンダーで選んでいる日を期限の初期値にする
        self._due = task.due if task else default_due
        # メモは別画面で編集するため、保存までここで持つ
        self._memo = task.memo if task else ""

    def compose(self) -> ComposeResult:
        task = self._target
        config = self._config

        with Vertical(id="edit-dialog") as dialog:
            dialog.border_title = "タスクを編集" if task else "タスクを追加"

            yield Label("タイトル")
            yield Input(
                value=task.title if task else "",
                placeholder="やること",
                compact=True,
                id="title",
            )

            yield Label("期限 (空欄で期限なし / 例: 2026-08-06、8/6)")
            yield Input(
                value=self._due.isoformat() if self._due else "",
                placeholder="YYYY-MM-DD",
                compact=True,
                id="due",
            )

            with Horizontal(id="edit-selects"):
                with Vertical():
                    yield Label("優先度")
                    yield Select(
                        [(label, key) for key, (label, _) in PRIORITIES.items()],
                        value=task.priority if task else DEFAULT_PRIORITY,
                        allow_blank=False,
                        compact=True,
                        id="priority",
                    )
                with Vertical():
                    yield Label("ステータス")
                    yield Select(
                        [
                            (Content.styled(s.name, textual_color(s.color)), s.id)
                            for s in config.statuses
                        ],
                        value=config.status_of(task).id if task else config.default_status().id,
                        allow_blank=False,
                        compact=True,
                        id="status",
                    )

            yield Label("タグ (space で選択)")
            if config.tags:
                yield SelectionList[str](
                    *[
                        Selection(
                            Content.styled(tag.name, textual_color(tag.color)),
                            tag.id,
                            task is not None and tag.id in task.tags,
                        )
                        for tag in config.tags
                    ],
                    compact=True,
                    id="tags",
                )
            else:
                yield Label("タグは設定画面 (, キー) で追加できます", id="no-tags")

            yield Label("メモ (複数行。Ctrl+O で全画面編集)")
            with Horizontal(id="memo-row"):
                yield Static(id="memo-preview")
                yield Button("編集 (^O)", compact=True, id="edit-memo")

            with Horizontal(id="edit-buttons"):
                yield Button("保存", variant="primary", compact=True, id="save")
                yield Button("取消", compact=True, id="cancel")

    def on_mount(self) -> None:
        self._show_memo_preview()
        self.query_one("#title", Input).focus()

    def on_input_submitted(self) -> None:
        """入力欄で Enter を押したら保存する"""
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        elif event.button.id == "edit-memo":
            self.action_edit_memo()
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._save()

    def action_edit_memo(self) -> None:
        """メモを全画面で編集する"""
        title = self.query_one("#title", Input).value.strip() or "タスク"
        self.app.push_screen(MemoEditScreen(title, self._memo), self._on_memo_edited)

    def _on_memo_edited(self, memo: Optional[str]) -> None:
        """編集から戻ったら控えを更新する (保存はフォームの保存時)"""
        if memo is not None:
            self._memo = memo
            self._show_memo_preview()

    def _show_memo_preview(self) -> None:
        """メモの1行目だけをフォームに出す"""
        preview = self.query_one("#memo-preview", Static)
        lines = self._memo.splitlines()
        if not lines:
            preview.update(Text("(なし)", style="dim"))
            return
        text = Text(lines[0], no_wrap=True, overflow="ellipsis")
        if len(lines) > 1:
            text.append(f"  … 全{len(lines)}行", style="dim")
        preview.update(text)

    def _selected_tags(self) -> list[str]:
        """選択されているタグのID (設定の並び順で返す)"""
        if not self._config.tags:
            return []
        selected = set(self.query_one("#tags", SelectionList).selected)
        return [tag.id for tag in self._config.tags if tag.id in selected]

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
        status = str(self.query_one("#status", Select).value)
        tags = self._selected_tags()
        memo = self._memo

        task = self._target
        if task is None:
            self.dismiss(
                Task(
                    title=title,
                    due=due,
                    priority=priority,
                    memo=memo,
                    status=status,
                    tags=tags,
                )
            )
            return

        task.title = title
        task.due = due
        task.priority = priority
        task.memo = memo
        task.status = status
        task.tags = tags
        self.dismiss(task)
