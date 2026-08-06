"""設定画面 (ステータス・タグの追加・編集)"""

from __future__ import annotations

import copy
from typing import Optional, Union

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, DataTable, Input, Label, Select, Static

from ..config import Config
from ..models import COLORS, Status, Tag, color_label, new_id, textual_color

Item = Union[Status, Tag]


class ItemTable(DataTable):
    """設定項目の一覧 (矢印キーに加えて jk でも動かせる)"""

    BINDINGS = [
        Binding("k", "cursor_up", "上へ", show=False),
        Binding("j", "cursor_down", "下へ", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cursor_type = "row"


class ItemEditScreen(ModalScreen[Optional[Item]]):
    """ステータス・タグ1件の追加・編集

    保存すると Status / Tag を、取り消すと None を返す。
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("ctrl+s", "save", "保存"),
    ]

    def __init__(self, kind: str, item: Item | None = None) -> None:
        super().__init__()
        self._kind = kind  # "status" または "tag"
        self._target = item

    def compose(self) -> ComposeResult:
        item = self._target
        label = "ステータス" if self._kind == "status" else "タグ"

        with Vertical(id="item-dialog") as dialog:
            dialog.border_title = f"{label}を{'編集' if item else '追加'}"

            yield Label("名前")
            yield Input(
                value=item.name if item else "",
                placeholder=label,
                compact=True,
                id="name",
            )

            yield Label("色 (端末の配色設定に追従します)")
            yield Select(
                [
                    (Content.styled(name, textual_color(value)), value)
                    for value, name in COLORS
                ],
                value=item.color if item else "",
                allow_blank=False,
                compact=True,
                id="color",
            )

            if self._kind == "status":
                yield Checkbox(
                    "完了扱いにする",
                    value=item.done if isinstance(item, Status) else False,
                    compact=True,
                    id="done",
                )

            with Horizontal(id="item-buttons"):
                yield Button("保存", variant="primary", compact=True, id="save")
                yield Button("取消", compact=True, id="cancel")

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_input_submitted(self) -> None:
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
        name_input = self.query_one("#name", Input)
        name = name_input.value.strip()
        if not name:
            self.notify("名前を入力してください", severity="warning", timeout=4)
            name_input.focus()
            return

        color = str(self.query_one("#color", Select).value)
        item = self._target

        if self._kind == "status":
            done = self.query_one("#done", Checkbox).value
            if item is None:
                self.dismiss(Status(id=new_id(), name=name, color=color, done=done))
                return
            item.done = done  # type: ignore[union-attr]
        elif item is None:
            self.dismiss(Tag(id=new_id(), name=name, color=color))
            return

        item.name = name
        item.color = color
        self.dismiss(item)


class SettingsScreen(ModalScreen[Optional[Config]]):
    """ステータスとタグを編集する設定画面

    保存すると Config を、取り消すと None を返す。編集は複製に対して行うので、
    取り消した場合は元の設定に影響しない。
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("ctrl+s", "save", "保存"),
        Binding("a", "add", "追加"),
        Binding("e", "edit", "編集"),
        Binding("d", "delete", "削除"),
        Binding("K", "move(-1)", "上へ"),
        Binding("J", "move(1)", "下へ"),
    ]

    def __init__(self, config: Config, usage: dict[str, int]) -> None:
        super().__init__()
        self._config = copy.deepcopy(config)
        self._usage = usage  # ステータス・タグのID -> 使っているタスク数
        self._kind = "status"  # 最後に操作した一覧

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog") as dialog:
            dialog.border_title = "設定"

            with Horizontal(id="settings-lists"):
                with Container(id="status-panel") as status_panel:
                    status_panel.border_title = "ステータス"
                    yield ItemTable(id="status-table")
                with Container(id="tag-panel") as tag_panel:
                    tag_panel.border_title = "タグ"
                    yield ItemTable(id="tag-table")

            yield Static(
                "a 追加  e 編集  d 削除  J/K 並べ替え  Tab 切替  Ctrl+S 保存",
                id="settings-hint",
            )
            yield Static("", id="settings-note")

            with Horizontal(id="settings-buttons"):
                yield Button("保存", variant="primary", compact=True, id="save")
                yield Button("取消", compact=True, id="cancel")

    def on_mount(self) -> None:
        status_table = self.query_one("#status-table", ItemTable)
        status_table.add_column("名前", width=10)
        status_table.add_column("色", width=8)
        status_table.add_column("完了", width=4)
        status_table.add_column("使用", width=4)

        tag_table = self.query_one("#tag-table", ItemTable)
        tag_table.add_column("名前", width=10)
        tag_table.add_column("色", width=8)
        tag_table.add_column("使用", width=4)

        self._reload()
        status_table.focus()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """操作対象 (ステータス / タグ) を、フォーカスされた一覧に合わせる"""
        if isinstance(event.widget, ItemTable):
            self._kind = "tag" if event.widget.id == "tag-table" else "status"
            self._update_note()

    def on_data_table_row_highlighted(self) -> None:
        self._update_note()

    def on_data_table_row_selected(self) -> None:
        """一覧で Enter を押したら編集する"""
        self.action_edit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self.action_save()
        else:
            self.dismiss(None)

    # ── 表示 ────────────────────────────────

    def _items(self, kind: str | None = None) -> list:
        """対象の一覧 (ステータスかタグ)"""
        return self._config.tags if (kind or self._kind) == "tag" else self._config.statuses

    def _table(self, kind: str | None = None) -> ItemTable:
        which = kind or self._kind
        return self.query_one("#tag-table" if which == "tag" else "#status-table", ItemTable)

    def _reload(self, *, keep_row: int | None = None) -> None:
        """両方の一覧を作り直す"""
        for kind in ("status", "tag"):
            table = self._table(kind)
            row = keep_row if (keep_row is not None and kind == self._kind) else table.cursor_row
            table.clear()
            for item in self._items(kind):
                cells = [
                    Text(item.name, style=item.color, no_wrap=True, overflow="ellipsis"),
                    Text(color_label(item.color), style="dim"),
                ]
                if kind == "status":
                    cells.append(Text("✓" if item.done else "", style="green"))
                cells.append(Text(str(self._usage.get(item.id, 0)), style="dim"))
                table.add_row(*cells)
            if row is not None:
                table.move_cursor(row=min(row, max(0, table.row_count - 1)))
        self._update_note()

    def _update_note(self) -> None:
        """選択中の項目についての注意書き"""
        item = self._selected()
        note = ""
        if item is None:
            note = "「a」で追加してください"
        elif self._kind == "status":
            if self._config.done_status() is None:
                note = "完了扱いのステータスがありません (space の完了切替が使えません)"
            elif len(self._config.statuses) == 1:
                note = "ステータスは1つ以上必要です"
            else:
                used = self._usage.get(item.id, 0)
                note = f"削除すると、このステータスの{used}件は先頭のステータスに移ります" if used else ""
        else:
            used = self._usage.get(item.id, 0)
            note = f"削除すると、{used}件のタスクからこのタグが外れます" if used else ""
        self.query_one("#settings-note", Static).update(Text(note, style="dim"))

    def _selected(self) -> Item | None:
        """選択中の項目"""
        table = self._table()
        items = self._items()
        row = table.cursor_row
        if row is not None and 0 <= row < len(items):
            return items[row]
        return None

    # ── アクション ──────────────────────────

    def action_add(self) -> None:
        self.app.push_screen(ItemEditScreen(self._kind), self._on_added)

    def _on_added(self, item: Optional[Item]) -> None:
        if item is None:
            return
        self._items().append(item)
        self._reload(keep_row=len(self._items()) - 1)

    def action_edit(self) -> None:
        item = self._selected()
        if item is None:
            return
        self.app.push_screen(ItemEditScreen(self._kind, item), self._on_edited)

    def _on_edited(self, item: Optional[Item]) -> None:
        # ItemEditScreen が元のオブジェクトを書き換えて返すので、並びは変わらない
        if item is not None:
            self._reload()

    def action_delete(self) -> None:
        item = self._selected()
        if item is None:
            return
        if self._kind == "status" and len(self._config.statuses) == 1:
            self.notify("ステータスは1つ以上必要です", severity="warning", timeout=4)
            return

        row = self._table().cursor_row
        self._items().remove(item)
        self._reload(keep_row=max(0, (row or 0) - 1))
        self.notify(f"削除しました: {item.name}", timeout=4)

    def action_move(self, offset: int) -> None:
        """並べ替える (ステータスの先頭は新しいタスクの初期値になる)"""
        items = self._items()
        row = self._table().cursor_row
        if row is None:
            return
        target = row + offset
        if not (0 <= row < len(items) and 0 <= target < len(items)):
            return
        items[row], items[target] = items[target], items[row]
        self._reload(keep_row=target)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self.dismiss(self._config)
