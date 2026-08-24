"""メモの表示・編集 (全画面)

メモは複数行で長くなるため、一覧の下のメモ欄には収まらない分を全画面で扱う。
表示は markdown として描く (書くのは素のテキストエディタのまま)。
"""

from __future__ import annotations

from typing import Optional

from markdown_it import MarkdownIt
from markdown_it.rules_core import StateCore
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static, TextArea


def _hard_break(state: StateCore) -> None:
    """段落中の改行 (softbreak) を、そのまま改行する扱い (hardbreak) に変える"""
    for token in state.tokens:
        if token.type == "inline" and token.children:
            for child in token.children:
                if child.type == "softbreak":
                    child.type = "hardbreak"


def _markdown_parser() -> MarkdownIt:
    """メモ用の markdown パーサ

    markdown 本来の規則では単独の改行はつながってしまうが、markdown を意識せず
    書いた今までのメモが1つの段落にまとめられて読めなくなるため、改行は
    そのまま改行として描く。

    HTML は解釈しない (html=False)。`<確認>` のような書き方をタグと見なして
    消してしまうと、書いたはずのメモが読めなくなるため。
    """
    parser = MarkdownIt("gfm-like", {"html": False})
    parser.core.ruler.push("taskterm_hard_break", _hard_break)
    return parser


class MemoScroll(VerticalScroll):
    """メモ本文のスクロール領域 (矢印キーに加えて jk でも動かせる)"""

    BINDINGS = [
        Binding("j", "scroll_down", "下へ", show=False),
        Binding("k", "scroll_up", "上へ", show=False),
    ]


class MemoEditScreen(ModalScreen[Optional[str]]):
    """メモを全画面で編集する

    Enter は改行なので、閉じたときに自動保存する。本文を書き換えていれば
    その本文を、変えていなければ None を返す。
    """

    BINDINGS = [
        Binding("escape", "save", "保存して閉じる"),
        Binding("ctrl+s", "save", "保存して閉じる"),
    ]

    def __init__(self, title: str, memo: str) -> None:
        super().__init__()
        self._title = title
        self._memo = memo

    def compose(self) -> ComposeResult:
        with Vertical(id="memo-dialog") as dialog:
            dialog.border_title = "メモを編集"
            dialog.border_subtitle = "Esc 保存して閉じる   Ctrl+Z 取り消し"
            yield Static(Text(self._title, style="bold"), id="memo-header")
            yield TextArea(
                self._memo,
                soft_wrap=True,
                show_line_numbers=False,
                id="memo-editor",
            )

    def on_mount(self) -> None:
        editor = self.query_one("#memo-editor", TextArea)
        editor.focus()
        # 続きを書き足すことが多いので末尾から始める
        editor.move_cursor(editor.document.end)

    def action_save(self) -> None:
        memo = self.query_one("#memo-editor", TextArea).text.strip()
        # 読むだけで閉じたときに保存が走らないよう、変えていなければ None を返す
        self.dismiss(memo if memo != self._memo else None)


class MemoViewScreen(ModalScreen[Optional[str]]):
    """メモを全画面で読む (e キーで編集に切り替えられる)

    編集した場合は新しい本文を、変更せずに閉じた場合は None を返す。
    """

    BINDINGS = [
        Binding("escape", "close", "閉じる"),
        Binding("e", "edit", "編集"),
    ]

    def __init__(self, title: str, meta: str, memo: str) -> None:
        super().__init__()
        self._title = title
        self._meta = meta
        self._memo = memo
        self._edited = False

    def compose(self) -> ComposeResult:
        with Vertical(id="memo-dialog") as dialog:
            dialog.border_title = "メモ"
            dialog.border_subtitle = "e 編集   j/k スクロール   Esc 閉じる"

            header = Text(self._title, style="bold")
            if self._meta:
                header.append(f"\n{self._meta}", style="dim")
            yield Static(header, id="memo-header")

            with MemoScroll(id="memo-body"):
                yield Markdown(parser_factory=_markdown_parser, id="memo-text")

    def on_mount(self) -> None:
        self._show_memo()
        self.query_one("#memo-body", MemoScroll).focus()

    def _show_memo(self) -> None:
        body = self.query_one("#memo-text", Markdown)
        # 案内文は本文と見分けが付くように薄くする (色は tcss 側)
        body.set_class(not self._memo, "empty")
        body.update(self._memo or "(メモなし) — e で書けます")

    def action_edit(self) -> None:
        self.app.push_screen(MemoEditScreen(self._title, self._memo), self._on_edited)

    def _on_edited(self, memo: Optional[str]) -> None:
        """編集から戻ったら、閉じずにそのまま表示を更新する"""
        if memo is None:
            return
        self._memo = memo
        self._edited = True
        self._show_memo()

    def action_close(self) -> None:
        self.dismiss(self._memo if self._edited else None)
