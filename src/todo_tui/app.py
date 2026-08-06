"""todo - メインアプリケーション"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from . import storage
from .models import Task, format_due, next_priority, sort_tasks
from .screens.task_edit import TaskEditScreen
from .widgets.calendar import MonthCalendar
from .widgets.task_list import TaskTable

log = logging.getLogger(__name__)

CSS_PATH = Path(__file__).parent / "styles" / "app.tcss"


class TodoApp(App):
    """todo アプリケーション"""

    TITLE = "todo"
    CSS_PATH = CSS_PATH

    # 端末のANSIパレット (ユーザーのターミナル配色設定) をそのまま使うテーマ
    THEME = "ansi-dark"

    BINDINGS = [
        Binding("a", "add", "追加"),
        Binding("e", "edit", "編集"),
        Binding("space", "toggle_done", "完了"),
        Binding("d", "delete", "削除"),
        Binding("u", "undo", "戻す"),
        Binding("p", "cycle_priority", "優先度"),
        Binding("v", "toggle_view", "表示切替"),
        Binding("t", "today", "今日"),
        Binding("tab", "focus_next", "パネル移動", show=False),
        # h/l はカレンダーにフォーカスが無くても日を動かせるようにする
        # (カレンダーにフォーカスがあるときは MonthCalendar 側の同じキーが働く)
        Binding("h", "move_day(-1)", "前日", show=False),
        Binding("l", "move_day(1)", "翌日", show=False),
        Binding("left_square_bracket", "move_month(-1)", "前月", show=False),
        Binding("right_square_bracket", "move_month(1)", "翌月", show=False),
        Binding("q", "quit", "終了"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._tasks: list[Task] = storage.load_tasks()
        self._deleted: Task | None = None  # u キーで戻せる、直前に削除したタスク
        self._show_all = False  # False: 選択日のみ / True: 全件

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="main"):
            # 左: TODOリスト (下端に選択中タスクのメモ)
            with Vertical(id="task-panel"):
                yield TaskTable(id="task-table")
                yield Static("", id="task-detail")

            # 右: カレンダーと内訳
            with Vertical(id="side-panel"):
                with Container(id="calendar-panel") as calendar_panel:
                    calendar_panel.border_title = "カレンダー"
                    yield MonthCalendar(id="calendar")
                with Container(id="summary-panel") as summary_panel:
                    summary_panel.border_title = "内訳"
                    yield Static("", id="summary")

        yield Footer()

    def on_mount(self) -> None:
        self.theme = self.THEME
        self.query_one("#task-table", TaskTable).focus()
        self._refresh()

    # ── イベント ────────────────────────────

    def on_month_calendar_date_changed(self, event: MonthCalendar.DateChanged) -> None:
        """カレンダーの選択日が変わったら一覧を作り直す"""
        self._refresh()

    def on_data_table_row_highlighted(self) -> None:
        """カーソル移動でメモ表示を追従させる"""
        self._update_detail()

    def on_data_table_row_selected(self) -> None:
        """一覧で Enter を押したら編集する"""
        self.action_edit()

    # ── 表示の更新 ──────────────────────────

    def _refresh(self) -> None:
        """一覧・カレンダーの印・内訳をまとめて作り直す"""
        today = date.today()
        visible = self._visible_tasks(today)

        self.query_one("#task-table", TaskTable).update_tasks(visible, today)
        self.query_one("#calendar", MonthCalendar).set_marks(self._marks())
        self._update_title(visible)
        self._update_summary(today)
        self._update_detail()

    def _visible_tasks(self, today: date) -> list[Task]:
        """一覧に出すタスク

        既定では選択日が期限のタスクだけを出す。ただし今日を選んでいるときは
        期限切れの未完了タスクも足す (見落とすと困るため)。
        v キーで全件表示に切り替えると、期限なしのタスクも含めて全部出す。
        """
        if self._show_all:
            return sort_tasks(self._tasks)

        selected = self.query_one("#calendar", MonthCalendar).selected
        tasks = [t for t in self._tasks if t.due == selected]
        if selected == today:
            tasks += [t for t in self._tasks if t.is_overdue(today)]
        return sort_tasks(tasks)

    def _marks(self) -> dict[date, tuple[int, int]]:
        """カレンダーの印用に、期限日ごとの (未完了数, 総数) を数える"""
        marks: dict[date, tuple[int, int]] = {}
        for task in self._tasks:
            if task.due is None:
                continue
            open_count, total = marks.get(task.due, (0, 0))
            marks[task.due] = (open_count + (0 if task.done else 1), total + 1)
        return marks

    def _update_title(self, visible: list[Task]) -> None:
        """左パネルのタイトルに、今出している範囲と件数を書く"""
        selected = self.query_one("#calendar", MonthCalendar).selected
        scope = "全件" if self._show_all else format_due(selected)
        done = sum(1 for t in visible if t.done)
        self.query_one("#task-panel").border_title = (
            f"TODO — {scope}  {len(visible)}件 (完了 {done})"
        )

    def _update_summary(self, today: date) -> None:
        """右下の内訳を更新する"""
        selected = self.query_one("#calendar", MonthCalendar).selected
        open_tasks = [t for t in self._tasks if not t.done]
        overdue = sum(1 for t in open_tasks if t.is_overdue(today))
        today_count = sum(1 for t in open_tasks if t.due == today)
        day_count = sum(1 for t in open_tasks if t.due == selected)
        no_due = sum(1 for t in open_tasks if t.due is None)

        lines = [
            f"未完了 {len(open_tasks)}件 / 全 {len(self._tasks)}件",
            "",
            f"選択日 {format_due(selected)}: {day_count}件",
            f"今日: {today_count}件",
        ]
        lines.append(
            f"[bold red]期限切れ: {overdue}件[/]" if overdue else f"期限切れ: {overdue}件"
        )
        hint = "" if self._show_all else "  [dim](v で表示)[/]"
        lines.append(f"期限なし: {no_due}件{hint}")
        lines += ["", "[dim]• 未完了あり  · 完了のみ[/]"]

        self.query_one("#summary", Static).update("\n".join(lines))

    def _update_detail(self) -> None:
        """一覧の下に、選択中タスクのメモを1行で出す"""
        task = self.query_one("#task-table", TaskTable).selected_task
        detail = self.query_one("#task-detail", Static)
        if task is None:
            detail.update(Text("タスクがありません — a で追加", style="dim"))
        elif task.memo:
            detail.update(Text(f"✎ {task.memo}", no_wrap=True, overflow="ellipsis"))
        else:
            detail.update(Text("(メモなし)", style="dim"))

    def _save(self) -> None:
        """タスクを保存して表示を更新する"""
        try:
            storage.save_tasks(self._tasks)
        except OSError as e:
            log.error("保存エラー: %s", e)
            self.notify(f"保存できませんでした: {e}", severity="error", timeout=8)
        self._refresh()

    def _selected_task(self) -> Task | None:
        """一覧で選択中のタスク (無ければ知らせて None)"""
        task = self.query_one("#task-table", TaskTable).selected_task
        if task is None:
            self.notify("対象のタスクがありません", timeout=4)
        return task

    # ── アクション ──────────────────────────

    def action_add(self) -> None:
        """タスクを追加する (期限の初期値はカレンダーの選択日)"""
        selected = self.query_one("#calendar", MonthCalendar).selected
        self.push_screen(TaskEditScreen(default_due=selected), self._on_edited)

    def action_edit(self) -> None:
        """選択中のタスクを編集する"""
        task = self._selected_task()
        if task is not None:
            self.push_screen(TaskEditScreen(task), self._on_edited)

    def _on_edited(self, task: Optional[Task]) -> None:
        """フォームが閉じたときの処理 (取消なら None が来る)"""
        if task is None:
            return
        if all(t.id != task.id for t in self._tasks):
            self._tasks.append(task)
        self._save()

    def action_toggle_done(self) -> None:
        """完了・未完了を切り替える"""
        task = self._selected_task()
        if task is not None:
            task.done = not task.done
            self._save()

    def action_cycle_priority(self) -> None:
        """優先度を 高 → 中 → 低 と切り替える"""
        task = self._selected_task()
        if task is not None:
            task.priority = next_priority(task.priority)
            self._save()

    def action_delete(self) -> None:
        """選択中のタスクを削除する (u キーで元に戻せる)"""
        task = self._selected_task()
        if task is None:
            return
        self._tasks = [t for t in self._tasks if t.id != task.id]
        self._deleted = task
        self._save()
        self.notify(f"削除しました: {task.title} — u で元に戻す", timeout=6)

    def action_undo(self) -> None:
        """直前に削除したタスクを戻す"""
        if self._deleted is None:
            self.notify("元に戻せる削除はありません", timeout=4)
            return
        self._tasks.append(self._deleted)
        self.notify(f"元に戻しました: {self._deleted.title}", timeout=4)
        self._deleted = None
        self._save()

    def action_toggle_view(self) -> None:
        """選択日のみ / 全件 を切り替える"""
        self._show_all = not self._show_all
        self._refresh()

    def action_today(self) -> None:
        """カレンダーを今日に戻す"""
        calendar = self.query_one("#calendar", MonthCalendar)
        calendar.selected = date.today()
        # 既に今日を選んでいると DateChanged が飛ばないため、ここでも更新する
        self._refresh()

    def action_move_day(self, days: int) -> None:
        """カレンダーの選択日を動かす"""
        self.query_one("#calendar", MonthCalendar).move_days(days)

    def action_move_month(self, months: int) -> None:
        """カレンダーの月を移動する"""
        self.query_one("#calendar", MonthCalendar).move_months(months)
