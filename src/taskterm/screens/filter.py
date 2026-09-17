"""一覧の絞り込み (ステータス・タグ)

ステータス・タグとも複数選べる。何も選ばなければその項目では絞らず、
タグを複数選んだときは「いずれかを含む」タスクが出る。
選んだ条件はアプリを閉じるまでの一時的なもので、設定には保存しない。
"""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Label
from textual.widgets.selection_list import Selection

from ..config import Config
from ..models import Filter, textual_color
from ..widgets.select_list import SelectList


class FilterScreen(ModalScreen[Optional[Filter]]):
    """一覧の絞り込みを決めるモーダル

    適用すると Filter を、取り消すと None を返す。Ctrl+R は全ての条件を外した
    Filter を返す (絞り込みの解除)。
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("ctrl+s", "apply", "適用"),
        Binding("ctrl+r", "clear", "解除"),
    ]

    def __init__(self, config: Config, current: Filter) -> None:
        super().__init__()
        self._config = config
        self._current = current

    def compose(self) -> ComposeResult:
        config = self._config

        with Vertical(id="filter-dialog") as dialog:
            dialog.border_title = "絞り込み"
            dialog.border_subtitle = "Esc 取消"

            yield Label("ステータス (space で選択。無選択なら全て)")
            yield SelectList(
                *[
                    Selection(
                        Content.styled(status.name, textual_color(status.color)),
                        status.id,
                        status.id in self._current.statuses,
                    )
                    for status in config.statuses
                ],
                compact=True,
                id="filter-statuses",
            )

            yield Label("タグ (いずれかを含むタスクが出ます)")
            if config.tags:
                yield SelectList(
                    *[
                        Selection(
                            Content.styled(tag.name, textual_color(tag.color)),
                            tag.id,
                            tag.id in self._current.tags,
                        )
                        for tag in config.tags
                    ],
                    compact=True,
                    id="filter-tags",
                )
            else:
                yield Label("タグは設定画面 (, キー) で追加できます", id="filter-no-tags")

            with Horizontal(id="filter-buttons"):
                yield Button("適用 (^S)", variant="primary", compact=True, id="apply")
                yield Button("解除 (^R)", compact=True, id="clear")

    def on_mount(self) -> None:
        self.query_one("#filter-statuses", SelectList).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "apply":
            self.action_apply()
        else:
            self.action_clear()

    def action_apply(self) -> None:
        """選んだ条件で絞り込む"""
        statuses = set(self.query_one("#filter-statuses", SelectList).selected)
        tags = (
            set(self.query_one("#filter-tags", SelectList).selected)
            if self._config.tags
            else set()
        )
        self.dismiss(Filter(statuses=statuses, tags=tags))

    def action_clear(self) -> None:
        """絞り込みを解除して閉じる"""
        self.dismiss(Filter())

    def action_cancel(self) -> None:
        """変えずに閉じる"""
        self.dismiss(None)
