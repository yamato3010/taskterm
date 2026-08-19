"""タスクのチェックリスト (サブタスク) の一覧・編集

1つのタスクを手順に分解して並べる。項目は期限やステータスを持たないため、
一覧・カレンダー・内訳の数え方には影響しない (タスクは1件のまま)。
"""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Input, Static

from ..models import Subtask, subtask_progress

# 進捗バーの長さ (画面の幅に「 10/10」を足しても収まる長さ)
_BAR_WIDTH = 20

_HINT = "space 完了  a 追加  e 書き換え  d 削除  J/K 並べ替え"


def progress_text(subtasks: list[Subtask]) -> Text:
    """進捗バーと「完了数/総数」(四半期パネルと同じ見た目にする)"""
    done, total = subtask_progress(subtasks)
    filled = int(_BAR_WIDTH * done / total) if total else 0

    text = Text(no_wrap=True)
    text.append("█" * filled, style="cyan")
    text.append("░" * (_BAR_WIDTH - filled), style="bright_black")
    text.append(f" {done}/{total}")
    return text


class SubtaskTable(DataTable):
    """チェックリストの一覧 (矢印キーに加えて jk でも動かせる)"""

    BINDINGS = [
        Binding("k", "cursor_up", "上へ", show=False),
        Binding("j", "cursor_down", "下へ", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cursor_type = "row"


class SubtasksScreen(ModalScreen[Optional[list[Subtask]]]):
    """タスクのチェックリスト

    space (または Enter) で完了を切り替える。下の入力欄に書いて Enter を押すと
    追加され、続けて書けるよう入力欄に残る。変更があれば新しいリストを、
    変更せずに閉じた場合は None を返す。
    """

    BINDINGS = [
        Binding("escape", "close", "閉じる"),
        Binding("space", "toggle", "完了"),
        Binding("a", "add", "追加"),
        Binding("e", "edit", "書き換え"),
        Binding("d", "delete", "削除"),
        Binding("K", "move(-1)", "上へ"),
        Binding("J", "move(1)", "下へ"),
    ]

    def __init__(self, title: str, subtasks: list[Subtask]) -> None:
        super().__init__()
        self._title = title
        # 呼び出し元のリストを直接いじらないよう複製に対して編集する
        self._subtasks = [Subtask(item.title, item.done) for item in subtasks]
        self._edited = False
        # 入力欄で書き換え中の行 (None なら入力は追加になる)
        self._editing: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="subtasks-dialog") as dialog:
            dialog.border_title = f"チェックリスト — {self._title}"
            dialog.border_subtitle = "Esc 閉じる"

            yield Static(id="subtasks-progress")
            yield SubtaskTable(id="subtasks-table")
            yield Input(placeholder="項目を書いて Enter で追加", compact=True, id="subtasks-input")
            yield Static(_HINT, id="subtasks-hint")

    def on_mount(self) -> None:
        table = self.query_one("#subtasks-table", SubtaskTable)
        # 印の列 (幅は ✓ が端末で全角に扱われても崩れないよう2桁とる)
        table.add_column("", width=2)
        table.add_column("項目")
        self._reload()
        # 項目が無いうちは書くことしかできないので入力欄から始める
        if self._subtasks:
            table.focus()
        else:
            self.query_one("#subtasks-input", Input).focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """一覧で Enter を押す (行をクリックする) と完了を切り替える

        止めておかないと、この画面の Enter が裏のTODOリストにも届いてしまう
        (メイン画面が Enter を「タスクを編集」に使っているため)。
        """
        event.stop()
        self.action_toggle()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """カーソル移動も裏の画面には伝えない"""
        event.stop()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """入力欄で Enter を押したら、追加または書き換えを確定する"""
        event.stop()
        title = event.value.strip()
        if not title:
            return

        if self._editing is None:
            self._subtasks.append(Subtask(title))
            row = len(self._subtasks) - 1
        else:
            self._subtasks[self._editing].title = title
            row = self._editing
            self._editing = None

        self._edited = True
        event.input.value = ""
        self._reload(keep_row=row)

    # ── 表示 ────────────────────────────────

    def _reload(self, *, keep_row: int | None = None) -> None:
        """一覧と進捗を作り直す"""
        table = self.query_one("#subtasks-table", SubtaskTable)
        row = keep_row if keep_row is not None else table.cursor_row
        table.clear()
        for item in self._subtasks:
            # 印はカレンダーと同じ字を使う (全角の「・」は幅に収まらないので半角)
            check = Text("✓", style="green") if item.done else Text("·", style="dim")
            title = Text(item.title, style="dim strike" if item.done else "", no_wrap=True)
            table.add_row(check, title)
        if row is not None:
            table.move_cursor(row=min(row, max(0, table.row_count - 1)))

        self.query_one("#subtasks-progress", Static).update(progress_text(self._subtasks))
        self._update_hint()

    def _update_hint(self) -> None:
        """項目が無いときは書きかたを出す"""
        hint = self.query_one("#subtasks-hint", Static)
        if self._editing is not None:
            hint.update("書き換えて Enter (Esc で閉じると元のまま)")
        elif self._subtasks:
            hint.update(_HINT)
        else:
            hint.update("項目はまだありません — 下の欄に書いて Enter")

    def _selected_row(self) -> int | None:
        """選択中の行 (項目が無ければ None)"""
        row = self.query_one("#subtasks-table", SubtaskTable).cursor_row
        return row if row is not None and 0 <= row < len(self._subtasks) else None

    # ── アクション ──────────────────────────

    def action_toggle(self) -> None:
        """完了 ⇄ 未完了 を切り替える"""
        row = self._selected_row()
        if row is None:
            return
        item = self._subtasks[row]
        item.done = not item.done
        self._edited = True
        self._reload(keep_row=row)

    def action_add(self) -> None:
        """入力欄に移って新しい項目を書く"""
        self._editing = None
        input_widget = self.query_one("#subtasks-input", Input)
        input_widget.value = ""
        input_widget.focus()
        self._update_hint()

    def action_edit(self) -> None:
        """選択中の項目を入力欄で書き換える"""
        row = self._selected_row()
        if row is None:
            return
        self._editing = row
        input_widget = self.query_one("#subtasks-input", Input)
        input_widget.value = self._subtasks[row].title
        input_widget.focus()
        input_widget.action_end()
        self._update_hint()

    def action_delete(self) -> None:
        """選択中の項目を消す (確認は挟まない。書き直すほうが早いため)"""
        row = self._selected_row()
        if row is None:
            return
        item = self._subtasks.pop(row)
        self._editing = None
        self._edited = True
        self._reload(keep_row=max(0, row - 1))
        self.notify(f"削除しました: {item.title}", timeout=4)

    def action_move(self, offset: int) -> None:
        """並べ替える (手順の順序を直せるように)"""
        row = self._selected_row()
        target = None if row is None else row + offset
        if target is None or not 0 <= target < len(self._subtasks):
            return
        self._subtasks[row], self._subtasks[target] = self._subtasks[target], self._subtasks[row]
        self._edited = True
        self._reload(keep_row=target)

    def action_close(self) -> None:
        self.dismiss(self._subtasks if self._edited else None)
