"""ステータスの選択 (s キー)

設定の並び順で次に送る形だと、完了扱いのステータスに入った時点でタスクが
完了タブへ移ってしまい、そこから先に送れない。そのため一覧から選ぶ形にしている。
"""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

from ..config import Config
from ..models import Status
from ..widgets.select_list import ChoiceList


class StatusScreen(ModalScreen[Optional[str]]):
    """タスクのステータスを選ぶモーダル

    選んだステータスの ID を、取り消すと None を返す。
    """

    BINDINGS = [Binding("escape", "cancel", "取消")]

    def __init__(self, config: Config, task_title: str, current_id: str) -> None:
        super().__init__()
        self._config = config
        self._task_title = task_title
        self._current_id = current_id

    def compose(self) -> ComposeResult:
        with Vertical(id="status-dialog") as dialog:
            dialog.border_title = "ステータス"
            dialog.border_subtitle = "Enter 決定   Esc 取消"

            yield Static(
                Text(self._task_title, style="bold", no_wrap=True, overflow="ellipsis"),
                id="status-task",
            )
            yield ChoiceList(
                *[self._option(s) for s in self._config.statuses], id="status-list"
            )

    def _option(self, status: Status) -> Option:
        """ステータス1件の選択肢 (今のものと、選ぶと完了タブへ移るものに印を付ける)"""
        label = Text(no_wrap=True, overflow="ellipsis")
        label.append("▸ " if status.id == self._current_id else "  ", style="dim")
        label.append(status.name, style=status.color)
        if status.done:
            label.append("  (完了タブへ)", style="dim")
        return Option(label, id=status.id)

    def on_mount(self) -> None:
        """今のステータスにカーソルを合わせて開く"""
        choices = self.query_one("#status-list", ChoiceList)
        choices.highlighted = next(
            (i for i, s in enumerate(self._config.statuses) if s.id == self._current_id), 0
        )
        choices.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        """変えずに閉じる"""
        self.dismiss(None)
