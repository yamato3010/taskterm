"""削除の確認 (押し間違いで消えないように d の前に挟む)"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDeleteScreen(ModalScreen[bool]):
    """タスクを削除してよいか尋ねる

    削除するなら True を、取り消すなら False を返す。
    """

    BINDINGS = [
        Binding("y", "confirm", "削除"),
        Binding("n", "cancel", "取消"),
        Binding("escape", "cancel", "取消"),
    ]

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog") as dialog:
            dialog.border_title = "削除の確認"
            dialog.border_subtitle = "y 削除   n / Esc 取消"

            body = Text("このタスクを削除します\n\n")
            body.append(self._title, style="bold")
            body.append("\n\nu キーで元に戻せます", style="dim")
            yield Static(body, id="confirm-message")

            with Horizontal(id="confirm-buttons"):
                yield Button("削除", variant="error", compact=True, id="delete")
                yield Button("取消", compact=True, id="cancel")

    def on_mount(self) -> None:
        # 押し間違いで消えないよう、初期フォーカスは「取消」に置く
        self.query_one("#cancel", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "delete")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
