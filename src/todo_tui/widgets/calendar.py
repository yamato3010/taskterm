"""月カレンダーウィジェット"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from rich.cells import cell_len
from rich.text import Text
from textual.app import RenderResult
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from ..models import WEEKDAYS

# 曜日見出し (日曜始まり。WEEKDAYS は月曜始まりなので並べ替える)
_HEADER_DAYS = [WEEKDAYS[6], *WEEKDAYS[:6]]

# 1日あたり3桁 (日付2桁 + 印1桁) を空白1桁で区切る
_GRID_WIDTH = 7 * 3 + 6

# 常に6週分描いて、月をまたいでも高さが変わらないようにする
_WEEK_ROWS = 6

_MARK_OPEN = "•"  # 未完了のタスクがある日
_MARK_DONE = "·"  # その日のタスクが全て完了している


class MonthCalendar(Widget):
    """月カレンダー

    選択中の日を反転表示し、期限のあるタスクがある日に印を付ける。
    """

    class DateChanged(Message):
        """選択中の日が変わった"""

        def __init__(self, value: date) -> None:
            super().__init__()
            self.value = value

    can_focus = True

    BINDING_GROUP_TITLE = "カレンダー"

    # 矢印キーと vim 風の hjkl の両方で動かせるようにする
    BINDINGS = [
        Binding("left,h", "move_days(-1)", "前日", show=False),
        Binding("right,l", "move_days(1)", "翌日", show=False),
        Binding("up,k", "move_days(-7)", "前週", show=False),
        Binding("down,j", "move_days(7)", "翌週", show=False),
    ]

    DEFAULT_CSS = """
    MonthCalendar {
        width: 27;
        height: 8;
    }
    """

    selected: reactive[date] = reactive(date.today, init=False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # 期限日 -> (未完了数, 総数)。アプリ側から set_marks() で渡される
        self._marks: dict[date, tuple[int, int]] = {}

    def set_marks(self, marks: dict[date, tuple[int, int]]) -> None:
        """日ごとのタスク件数を受け取って印を更新する"""
        self._marks = marks
        self.refresh()

    def watch_selected(self, value: date) -> None:
        self.refresh()
        self.post_message(self.DateChanged(value))

    def move_days(self, days: int) -> None:
        """選択日を動かす"""
        self.selected = self.selected + timedelta(days=days)

    def action_move_days(self, days: int) -> None:
        self.move_days(days)

    def move_months(self, months: int) -> None:
        """月を移動する (日は移動先の月末に丸める)"""
        current = self.selected
        year, month = divmod(current.year * 12 + current.month - 1 + months, 12)
        month += 1
        last_day = calendar.monthrange(year, month)[1]
        self.selected = date(year, month, min(current.day, last_day))

    def render(self) -> RenderResult:
        today = date.today()
        selected = self.selected
        text = Text(no_wrap=True)

        # 見出し: 「2026年 8月」を中央に置く (全角を含むため表示幅で計算する)
        title = f"{selected.year}年 {selected.month}月"
        text.append(" " * max(0, (_GRID_WIDTH - cell_len(title)) // 2))
        text.append(title, style="bold")

        # 曜日 (土日は色を変える)。全角1文字=2桁なので空白1桁を足して3桁に揃える
        text.append("\n")
        for i, name in enumerate(_HEADER_DAYS):
            if i:
                text.append(" ")
            text.append(f"{name} ", style=_weekday_style(i))

        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
            selected.year, selected.month
        )
        for row in range(_WEEK_ROWS):
            text.append("\n")
            if row >= len(weeks):
                continue
            for i, day in enumerate(weeks[row]):
                if i:
                    text.append(" ")
                content, style = self._cell(day, selected, today)
                text.append(content, style=style)

        return text

    def _cell(self, day: date, selected: date, today: date) -> tuple[str, str]:
        """1日分の表示内容とスタイル"""
        open_count, total = self._marks.get(day, (0, 0))
        mark = _MARK_OPEN if open_count else (_MARK_DONE if total else " ")
        content = f"{day.day:>2}{mark}"

        if day == selected:
            return content, "reverse bold"
        if day.month != selected.month:
            return content, "dim"
        if day == today:
            return content, "bold underline"
        # date.weekday() は月曜=0 なので、日曜始まりの列番号に直す
        return content, _weekday_style((day.weekday() + 1) % 7)


def _weekday_style(column: int) -> str:
    """曜日の列 (0=日曜) に対する色"""
    if column == 0:
        return "red"
    if column == 6:
        return "blue"
    return ""
