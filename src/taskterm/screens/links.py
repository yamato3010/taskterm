"""タスクに紐づくリンクの一覧・編集

Teams のスレッドや Backlog のチケットなど、タスクの背景を辿るための参照先を
まとめて置く。一覧で Enter (またはクリック) を押すと既定のブラウザで開く。
"""

from __future__ import annotations

from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Input, Label, Static

from ..models import Link, normalize_url

# 一覧のセル幅 (URLは長いので、これに収まらない分は「…」で切る。
# 切らずに置くと列が広がって、表に横スクロールバーが出てしまう)
_CELL_WIDTH = 64


def _clip(text: str, style: str = "") -> Text:
    """一覧の1行に収まるよう「…」で切ったテキスト"""
    clipped = Text(text, style=style, no_wrap=True, overflow="ellipsis")
    clipped.truncate(_CELL_WIDTH, overflow="ellipsis")
    return clipped


class LinkTable(DataTable):
    """リンクの一覧 (矢印キーに加えて jk でも動かせる)"""

    BINDINGS = [
        Binding("k", "cursor_up", "上へ", show=False),
        Binding("j", "cursor_down", "下へ", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.cursor_type = "row"


class LinkEditScreen(ModalScreen[Optional[Link]]):
    """リンク1件の追加・編集

    保存すると Link を、取り消すと None を返す。編集の場合は渡された Link を
    そのまま書き換えて返す。
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
        Binding("ctrl+s", "save", "保存"),
    ]

    def __init__(self, link: Link | None = None) -> None:
        super().__init__()
        self._target = link

    def compose(self) -> ComposeResult:
        link = self._target

        with Vertical(id="link-dialog") as dialog:
            dialog.border_title = f"リンクを{'編集' if link else '追加'}"

            yield Label("タイトル (空欄ならURLをそのまま出します)")
            yield Input(
                value=link.title if link else "",
                placeholder="Backlog チケット",
                compact=True,
                id="link-title",
            )

            yield Label("URL")
            yield Input(
                value=link.url if link else "",
                placeholder="https://",
                compact=True,
                id="link-url",
            )

            with Horizontal(id="link-buttons"):
                yield Button("保存", variant="primary", compact=True, id="save")
                yield Button("取消", compact=True, id="cancel")

    def on_mount(self) -> None:
        self.query_one("#link-title", Input).focus()

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
        url_input = self.query_one("#link-url", Input)
        url = normalize_url(url_input.value)
        if not url:
            self.notify("URLを入力してください", severity="warning", timeout=4)
            url_input.focus()
            return

        title = self.query_one("#link-title", Input).value.strip()
        link = self._target
        if link is None:
            self.dismiss(Link(title=title, url=url))
            return

        link.title = title
        link.url = url
        self.dismiss(link)


class LinksScreen(ModalScreen[Optional[list[Link]]]):
    """タスクのリンク一覧

    Enter で選択中のリンクをブラウザで開く。a / e / d / J / K で中身を編集でき、
    変更があれば新しいリンクのリストを、変更せずに閉じた場合は None を返す。
    """

    BINDINGS = [
        Binding("escape", "close", "閉じる"),
        Binding("a", "add", "追加"),
        Binding("e", "edit", "編集"),
        Binding("d", "delete", "削除"),
        Binding("K", "move(-1)", "上へ"),
        Binding("J", "move(1)", "下へ"),
    ]

    def __init__(self, title: str, links: list[Link]) -> None:
        super().__init__()
        self._title = title
        # 呼び出し元のリストを直接いじらないよう複製に対して編集する
        self._links = [Link(link.title, link.url) for link in links]
        self._edited = False

    def compose(self) -> ComposeResult:
        with Vertical(id="links-dialog") as dialog:
            dialog.border_title = f"リンク — {self._title}"
            dialog.border_subtitle = "Esc 閉じる"

            yield LinkTable(id="links-table")
            yield Static(
                "Enter 開く  a 追加  e 編集  d 削除  J/K 並べ替え",
                id="links-hint",
            )

    def on_mount(self) -> None:
        table = self.query_one("#links-table", LinkTable)
        table.add_column("#", width=2)
        table.add_column("リンク")
        self._reload()
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """一覧で Enter を押す (行をクリックする) と開く

        止めておかないと、この画面の Enter が裏のTODOリストにも届いてしまう
        (メイン画面が Enter を「タスクを編集」に使っているため)。
        """
        event.stop()
        self.action_open()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        """カーソル移動も裏の画面には伝えない"""
        event.stop()

    # ── 表示 ────────────────────────────────

    def _reload(self, *, keep_row: int | None = None) -> None:
        """一覧を作り直す

        1行目にタイトル、2行目にURLを出す (URLは長いので折り返さず「…」で切る)。
        """
        table = self.query_one("#links-table", LinkTable)
        row = keep_row if keep_row is not None else table.cursor_row
        table.clear()
        for i, link in enumerate(self._links, 1):
            cell = _clip(link.label())
            cell.append("\n")
            cell.append_text(_clip(link.url, "dim"))
            table.add_row(Text(str(i), style="dim"), cell, height=2)
        if row is not None:
            table.move_cursor(row=min(row, max(0, table.row_count - 1)))
        self._update_hint()

    def _update_hint(self) -> None:
        """リンクが無いときは追加のしかたを出す"""
        hint = self.query_one("#links-hint", Static)
        if self._links:
            hint.update("Enter 開く  a 追加  e 編集  d 削除  J/K 並べ替え")
        else:
            hint.update("リンクはまだありません — a で追加できます")

    def _selected(self) -> Link | None:
        """選択中のリンク"""
        row = self.query_one("#links-table", LinkTable).cursor_row
        if row is not None and 0 <= row < len(self._links):
            return self._links[row]
        return None

    # ── アクション ──────────────────────────

    def action_open(self) -> None:
        """選択中のリンクを既定のブラウザで開く"""
        link = self._selected()
        if link is None:
            return
        self.app.open_url(link.url)
        self.notify(f"ブラウザで開きます: {link.label()}", timeout=4)

    def action_add(self) -> None:
        self.app.push_screen(LinkEditScreen(), self._on_added)

    def _on_added(self, link: Optional[Link]) -> None:
        if link is None:
            return
        self._links.append(link)
        self._edited = True
        self._reload(keep_row=len(self._links) - 1)

    def action_edit(self) -> None:
        link = self._selected()
        if link is None:
            return
        self.app.push_screen(LinkEditScreen(link), self._on_edited)

    def _on_edited(self, link: Optional[Link]) -> None:
        # LinkEditScreen が元のオブジェクトを書き換えて返すので、並びは変わらない
        if link is None:
            return
        self._edited = True
        self._reload()

    def action_delete(self) -> None:
        link = self._selected()
        if link is None:
            return
        row = self.query_one("#links-table", LinkTable).cursor_row
        self._links.remove(link)
        self._edited = True
        self._reload(keep_row=max(0, (row or 0) - 1))
        self.notify(f"削除しました: {link.label()}", timeout=4)

    def action_move(self, offset: int) -> None:
        """並べ替える"""
        row = self.query_one("#links-table", LinkTable).cursor_row
        if row is None:
            return
        target = row + offset
        if not (0 <= row < len(self._links) and 0 <= target < len(self._links)):
            return
        self._links[row], self._links[target] = self._links[target], self._links[row]
        self._edited = True
        self._reload(keep_row=target)

    def action_close(self) -> None:
        self.dismiss(self._links if self._edited else None)
