"""jk でも動かせる選択リスト

Textual の SelectionList / OptionList に、一覧の移動キー (jk) を足しただけのもの。
複数選ぶ欄 (タグ・絞り込み) と1つ選ぶ欄 (ステータス) で使う。
"""

from __future__ import annotations

from textual.binding import Binding
from textual.widgets import OptionList, SelectionList

_MOVE_KEYS = [
    Binding("k", "cursor_up", "上へ", show=False),
    Binding("j", "cursor_down", "下へ", show=False),
]


class SelectList(SelectionList[str]):
    """複数選べる一覧 (矢印キーに加えて jk でも動かせる)"""

    BINDINGS = _MOVE_KEYS


class ChoiceList(OptionList):
    """1つだけ選ぶ一覧 (矢印キーに加えて jk でも動かせる)"""

    BINDINGS = _MOVE_KEYS
