"""自分宛てチャット (Slack や Teams の自分宛てメッセージのような書き置き)

タスクに紐付かない思いつきを、メッセージアプリのように吹き出しで並べる。
送る・書き換える・消すたびにその場で chat.json に保存する (閉じる前に落ちても残す)。
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Callable, Optional

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Right, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static, TextArea

from .. import storage
from ..config import Config
from ..models import ChatMessage, Task, format_due
from .confirm import ConfirmDeleteScreen
from .task_edit import TaskEditScreen

log = logging.getLogger(__name__)

_HINT_INPUT = "Enter 送信   Shift+Enter 改行   Tab メッセージを選ぶ   Esc 閉じる"
_HINT_LOG = "j/k 選択   e 書き換え   d 削除   t タスクにする   Tab 入力欄へ   Esc 閉じる"


def _day_label(day: date, today: date) -> str:
    """日付の区切りに出す文字 (今年なら年を省く)"""
    label = format_due(day)
    return label if day.year == today.year else f"{day.year}/{label}"


class Bubble(Static):
    """メッセージ1件の吹き出し (右下に送った時刻を出す)"""

    def __init__(self, message: ChatMessage, index: int) -> None:
        # 本文に [ ] が入っても markup と解釈されないよう Text で渡す
        super().__init__(Text(message.text), classes="bubble")
        self.index = index
        stamp = message.sent_at.strftime("%H:%M") if message.sent_at else ""
        self.border_subtitle = f"編集済 {stamp}".strip() if message.edited else stamp
        # 本文が短くても右下の時刻が欠けないよう、枠の角と余白の分を足した幅は取る
        self.styles.min_width = cell_len(self.border_subtitle) + 6


class ChatInput(TextArea):
    """メッセージの入力欄 (Enter で送信、Shift+Enter で改行)

    TextArea は Enter を改行として扱うため、送信と改行のキーを入れ替える。
    Shift+Enter は端末が Enter と区別して送ってくる場合 (kitty キーボード
    プロトコル対応の端末) だけ届く。
    """

    class Submitted(Message):
        """Enter が押された (本文は入力欄の text から読む)"""

        def __init__(self, chat_input: ChatInput) -> None:
            super().__init__()
            self.chat_input = chat_input

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.Submitted(self))
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return
        await super()._on_key(event)


class ChatLog(VerticalScroll):
    """吹き出しを並べるスクロール領域

    フォーカスがある間は j/k で吹き出しを1件ずつ選び、選んだメッセージに対して
    書き換え・削除・タスク化ができる (入力欄にいる間は文字入力を優先する)。
    """

    BINDINGS = [
        Binding("k,up", "select(-1)", "上へ", show=False),
        Binding("j,down", "select(1)", "下へ", show=False),
        Binding("e", "screen.edit", "書き換え"),
        Binding("d", "screen.delete", "削除"),
        Binding("t", "screen.make_task", "タスクにする"),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.selected: int | None = None

    def on_focus(self) -> None:
        """入ってきたら最新のメッセージから選び始める"""
        bubbles = self.query(Bubble)
        if self.selected is None and bubbles:
            self.select(bubbles.last().index)

    def action_select(self, offset: int) -> None:
        if self.selected is not None:
            self.select(self.selected + offset)

    def select(self, index: int) -> None:
        """index 番目の吹き出しを選ぶ (範囲外は端に寄せる)"""
        bubbles = list(self.query(Bubble))
        if not bubbles:
            self.selected = None
            return
        index = max(0, min(index, len(bubbles) - 1))
        self.selected = index
        for bubble in bubbles:
            bubble.set_class(bubble.index == index, "selected")
        self.scroll_to_widget(bubbles[index], animate=False)


class ChatScreen(ModalScreen[None]):
    """自分宛てチャット

    下の入力欄に書いて Enter で送る。Tab で吹き出しの一覧に移ると、選んだ
    メッセージを書き換え (e)・削除 (d)・タスクにする (t) ことができる。
    渡された messages はこの画面が直接書き換えて保存する。
    """

    BINDINGS = [
        Binding("escape", "close", "閉じる"),
    ]

    def __init__(
        self,
        messages: list[ChatMessage],
        config: Config,
        default_due: date,
        on_task_added: Callable[[Optional[Task]], None],
    ) -> None:
        super().__init__()
        self._messages = messages
        # タスクにするときの追加フォーム用 (期限の初期値は a キーと同じく選択日)
        self._config = config
        self._default_due = default_due
        self._on_task_added = on_task_added
        # 入力欄で書き換え中のメッセージ (None なら入力は送信になる)
        self._editing: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="chat-dialog") as dialog:
            dialog.border_title = "自分へのメモ"
            yield ChatLog(id="chat-log")
            yield ChatInput(
                placeholder="メッセージを書いて Enter で送信",
                soft_wrap=True,
                show_line_numbers=False,
                id="chat-input",
            )
            yield Static(_HINT_INPUT, id="chat-hint")

    def on_mount(self) -> None:
        self._reload()
        self.query_one("#chat-input", ChatInput).focus()

    def on_descendant_focus(self) -> None:
        """フォーカスのある側 (入力欄 / 一覧) に合わせて案内を変える"""
        self._update_hint()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Enter で送信、または書き換えを確定する"""
        event.stop()
        text = event.chat_input.text.strip()
        if not text:
            return

        if self._editing is None:
            self._messages.append(ChatMessage(text, sent_at=datetime.now()))
            keep = None
        else:
            message = self._messages[self._editing]
            if text != message.text:
                message.text = text
                message.edited = True
            keep = self._editing
            self._editing = None

        event.chat_input.clear()
        self._save()
        self._reload(keep=keep)
        # 書き換えのあとは、続けて別のメッセージを扱えるよう一覧に戻る
        if keep is not None:
            self.query_one("#chat-log", ChatLog).focus()

    # ── 表示 ────────────────────────────────

    def _reload(self, *, keep: int | None = None) -> None:
        """吹き出しを作り直して末尾 (keep があればその吹き出し) を見せる"""
        log_view = self.query_one("#chat-log", ChatLog)
        today = date.today()
        widgets: list[Widget] = []
        last_day: date | None = None
        for i, message in enumerate(self._messages):
            day = message.sent_at.date() if message.sent_at else None
            # 日付が変わるところに区切りを入れる (時刻の無い旧データは区切らない)
            if day is not None and day != last_day:
                widgets.append(Static(f"── {_day_label(day, today)} ──", classes="chat-day"))
                last_day = day
            # 自分の発言なのでメッセージアプリと同じく右に寄せる。align は子を
            # ひとかたまりで寄せるため、1件ずつ包んでそれぞれを右端に揃える
            widgets.append(Right(Bubble(message, i)))
        if not widgets:
            widgets.append(
                Static("まだメッセージはありません — 下の欄に書いて Enter", classes="chat-empty")
            )

        with self.app.batch_update():
            log_view.remove_children()
            log_view.mount_all(widgets)
        log_view.selected = None
        if keep is not None and self._messages:
            self.call_after_refresh(log_view.select, keep)
        else:
            self.call_after_refresh(log_view.scroll_end, animate=False)
        self._update_hint()

    def _update_hint(self) -> None:
        hint = self.query_one("#chat-hint", Static)
        if self._editing is not None:
            hint.update("書き換えて Enter (Esc で取りやめ)")
        elif self.focused is self.query_one("#chat-log", ChatLog):
            hint.update(_HINT_LOG)
        else:
            hint.update(_HINT_INPUT)

    def _save(self) -> None:
        """保存する (失敗しても画面は使い続けられるよう、知らせるだけにする)"""
        try:
            storage.save_messages(self._messages)
        except OSError as e:
            log.error("チャットの保存エラー: %s", e)
            self.notify(f"保存できませんでした: {e}", severity="error", timeout=8)

    def _selected(self) -> int | None:
        """一覧で選択中のメッセージの位置"""
        index = self.query_one("#chat-log", ChatLog).selected
        return index if index is not None and 0 <= index < len(self._messages) else None

    # ── アクション ──────────────────────────

    def action_edit(self) -> None:
        """選択中のメッセージを入力欄で書き換える"""
        index = self._selected()
        if index is None:
            return
        self._editing = index
        input_widget = self.query_one("#chat-input", ChatInput)
        input_widget.text = self._messages[index].text
        input_widget.focus()
        input_widget.move_cursor(input_widget.document.end)
        self._update_hint()

    def action_delete(self) -> None:
        """選択中のメッセージを消す (戻せないので確認を挟む)"""
        index = self._selected()
        if index is None:
            return
        message = self._messages[index]
        self.app.push_screen(
            ConfirmDeleteScreen(message.text, kind="メッセージ", undoable=False),
            lambda confirmed: self._on_delete_confirmed(message, confirmed),
        )

    def _on_delete_confirmed(self, message: ChatMessage, confirmed: Optional[bool]) -> None:
        if not confirmed:
            return
        index = self._messages.index(message)
        self._messages.remove(message)
        self._save()
        self._reload(keep=max(0, index - 1))
        self.query_one("#chat-log", ChatLog).focus()

    def action_make_task(self) -> None:
        """選択中のメッセージをタイトルにして、タスクの追加フォームを開く

        メッセージは消さずに残す (タスクにしたあとも経緯として読み返せるように)。
        """
        index = self._selected()
        if index is None:
            return
        self.app.push_screen(
            TaskEditScreen(
                self._config,
                default_due=self._default_due,
                default_title=self._messages[index].text,
            ),
            self._on_task_saved,
        )

    def _on_task_saved(self, task: Optional[Task]) -> None:
        self._on_task_added(task)
        if task is not None:
            self.notify(f"タスクに追加しました: {task.title}", timeout=4)

    def action_close(self) -> None:
        """書き換え中なら取りやめ、そうでなければ閉じる"""
        if self._editing is not None:
            self._editing = None
            self.query_one("#chat-input", ChatInput).clear()
            self.query_one("#chat-log", ChatLog).focus()
            self._update_hint()
            return
        self.dismiss(None)
