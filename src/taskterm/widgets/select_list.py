"""jk でも動かせる選択リスト

Textual の SelectionList に、一覧の移動キー (jk) を足しただけのもの。
タスクの追加・編集フォームのタグ欄と、絞り込み画面のステータス・タグ欄で使う。
"""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import SelectionList


class SelectList(SelectionList[str]):
    """複数選べる一覧 (矢印キーに加えて jk でも動かせる)"""

    BINDINGS = [
        Binding("k", "cursor_up", "上へ", show=False),
        Binding("j", "cursor_down", "下へ", show=False),
    ]
