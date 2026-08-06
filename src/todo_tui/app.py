"""todo - メインアプリケーション"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from . import storage
from .config import Config
from .models import Task, format_due, next_priority
from .screens.settings import SettingsScreen
from .screens.task_edit import TaskEditScreen
from .widgets.calendar import MonthCalendar
from .widgets.task_list import TaskTable

log = logging.getLogger(__name__)

CSS_PATH = Path(__file__).parent / "styles" / "app.tcss"


class TodoApp(App):
    """todo アプリケーション"""

    TITLE = "todo"
    CSS_PATH = CSS_PATH
    BINDING_GROUP_TITLE = "全体"

    # 端末のANSIパレット (ユーザーのターミナル配色設定) をそのまま使うテーマ
    THEME = "ansi-dark"

    # フッターに出すのは使用頻度の高いものだけ。show=False のキーも ? のヘルプには出る
    BINDINGS = [
        Binding("a", "add", "追加"),
        Binding("e", "edit", "編集"),
        Binding("space", "toggle_done", "完了"),
        Binding("s", "cycle_status", "状態"),
        Binding("d", "delete", "削除"),
        Binding("f", "filter_tag", "絞込"),
        Binding("v", "toggle_view", "表示"),
        Binding("comma", "settings", "設定"),
        Binding("question_mark", "show_help_panel", "ヘルプ"),
        Binding("q", "quit", "終了"),
        Binding("u", "undo", "削除を元に戻す", show=False),
        Binding("p", "cycle_priority", "優先度を切り替え", show=False),
        Binding("t", "today", "今日に戻る", show=False),
        Binding("tab", "focus_next", "パネル移動", show=False),
        # h/l はカレンダーにフォーカスが無くても日を動かせるようにする
        # (カレンダーにフォーカスがあるときは MonthCalendar 側の同じキーが働く)
        Binding("h", "move_day(-1)", "前日", show=False),
        Binding("l", "move_day(1)", "翌日", show=False),
        Binding("left_square_bracket", "move_month(-1)", "前月", show=False),
        Binding("right_square_bracket", "move_month(1)", "翌月", show=False),
        Binding("escape", "hide_help_panel", "ヘルプを閉じる", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = Config.load()
        self._tasks: list[Task] = storage.load_tasks(self._config)
        self._deleted: Task | None = None  # u キーで戻せる、直前に削除したタスク
        self._show_all = False  # False: 選択日のみ / True: 全件
        self._tag_filter: str | None = None  # 絞り込み中のタグID (None なら絞り込みなし)

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
                    calendar_panel.border_subtitle = "• 未完了 · 完了"
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

        self.query_one("#task-table", TaskTable).update_tasks(visible, today, self._config)
        self.query_one("#calendar", MonthCalendar).set_marks(self._marks())
        self._update_title(visible)
        self._update_summary(today)
        self._update_detail()

    def _filtered_tasks(self) -> list[Task]:
        """タグの絞り込みを適用したタスク (f キーで切り替える)"""
        if self._tag_filter is None:
            return self._tasks
        return [t for t in self._tasks if self._tag_filter in t.tags]

    def _visible_tasks(self, today: date) -> list[Task]:
        """一覧に出すタスク

        既定では選択日が期限のタスクだけを出す。ただし今日を選んでいるときは
        期限切れの未完了タスクも足す (見落とすと困るため)。
        v キーで全件表示に切り替えると、期限なしのタスクも含めて全部出す。
        どちらの場合もタグの絞り込みは効く。
        """
        tasks = self._filtered_tasks()
        if self._show_all:
            return self._config.sort_tasks(tasks)

        selected = self.query_one("#calendar", MonthCalendar).selected
        visible = [t for t in tasks if t.due == selected]
        if selected == today:
            visible += [t for t in tasks if self._config.is_overdue(t, today)]
        return self._config.sort_tasks(visible)

    def _marks(self) -> dict[date, tuple[int, int]]:
        """カレンダーの印用に、期限日ごとの (未完了数, 総数) を数える"""
        marks: dict[date, tuple[int, int]] = {}
        for task in self._filtered_tasks():
            if task.due is None:
                continue
            open_count, total = marks.get(task.due, (0, 0))
            done = self._config.is_done(task)
            marks[task.due] = (open_count + (0 if done else 1), total + 1)
        return marks

    def _filter_tag_name(self) -> str:
        """絞り込み中のタグ名 (絞り込んでいなければ空文字)"""
        tag = self._config.tag_by_id(self._tag_filter) if self._tag_filter else None
        return tag.name if tag else ""

    def _update_title(self, visible: list[Task]) -> None:
        """左パネルのタイトルに、今出している範囲と件数を書く"""
        selected = self.query_one("#calendar", MonthCalendar).selected
        scope = "全件" if self._show_all else format_due(selected)
        tag_name = self._filter_tag_name()
        scope += f" / {tag_name}" if tag_name else ""
        done = sum(1 for t in visible if self._config.is_done(t))
        self.query_one("#task-panel").border_title = (
            f"TODO — {scope}  {len(visible)}件 (完了 {done})"
        )

    def _update_summary(self, today: date) -> None:
        """右下の内訳を更新する"""
        config = self._config
        tasks = self._filtered_tasks()
        selected = self.query_one("#calendar", MonthCalendar).selected
        open_tasks = [t for t in tasks if not config.is_done(t)]

        text = Text(no_wrap=True)
        text.append(f"未完了 {len(open_tasks)}件 / 全 {len(tasks)}件\n")
        text.append(f"選択日 {format_due(selected)}: ")
        text.append(f"{sum(1 for t in open_tasks if t.due == selected)}件\n")

        overdue = sum(1 for t in open_tasks if config.is_overdue(t, today))
        text.append(f"期限切れ: {overdue}件\n", style="bold red" if overdue else "")

        text.append(f"期限なし: {sum(1 for t in open_tasks if t.due is None)}件")
        text.append("\n" if self._show_all else "  (v で表示)\n", style="dim")

        # ステータス別の件数 (設定の並び順・色で出す)
        text.append("\n")
        counts = Counter(config.status_of(t).id for t in tasks)
        for status in config.statuses:
            text.append(status.name, style=status.color)
            text.append(f" {counts.get(status.id, 0)}件\n", style="dim")

        tag_name = self._filter_tag_name()
        if tag_name:
            text.append(f"\n絞り込み: {tag_name}\n", style="dim")
            text.append("f で次のタグ / 解除", style="dim")

        self.query_one("#summary", Static).update(text)

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
        self.push_screen(
            TaskEditScreen(self._config, default_due=selected), self._on_edited
        )

    def action_edit(self) -> None:
        """選択中のタスクを編集する"""
        task = self._selected_task()
        if task is not None:
            self.push_screen(TaskEditScreen(self._config, task), self._on_edited)

    def _on_edited(self, task: Optional[Task]) -> None:
        """フォームが閉じたときの処理 (取消なら None が来る)"""
        if task is None:
            return
        if all(t.id != task.id for t in self._tasks):
            self._tasks.append(task)
        self._save()

    def action_toggle_done(self) -> None:
        """完了 ⇄ 未完了 を切り替える (完了扱いのステータスに移す / 戻す)"""
        task = self._selected_task()
        if task is None:
            return
        config = self._config
        if config.is_done(task):
            task.status = config.undone_status().id
        else:
            done = config.done_status()
            if done is None:
                self.notify(
                    "完了扱いのステータスがありません (, の設定画面で指定できます)",
                    severity="warning",
                    timeout=6,
                )
                return
            task.status = done.id
        self._save()

    def action_cycle_status(self) -> None:
        """ステータスを設定の並び順で次に進める"""
        task = self._selected_task()
        if task is not None:
            task.status = self._config.next_status(task).id
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

    def action_filter_tag(self) -> None:
        """タグの絞り込みを次のタグに切り替える (最後のタグの次は解除)"""
        ids = [t.id for t in self._config.tags]
        if not ids:
            self.notify("タグがありません (, の設定画面で追加できます)", timeout=5)
            return

        if self._tag_filter not in ids:
            self._tag_filter = ids[0]
        else:
            index = ids.index(self._tag_filter) + 1
            self._tag_filter = ids[index] if index < len(ids) else None

        self._refresh()
        tag_name = self._filter_tag_name()
        self.notify(
            f"絞り込み: {tag_name}" if tag_name else "絞り込みを解除しました", timeout=3
        )

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

    def action_settings(self) -> None:
        """設定画面を開く (ステータス・タグの追加・編集)"""
        self.push_screen(
            SettingsScreen(self._config, self._usage_counts()), self._on_settings_saved
        )

    def _usage_counts(self) -> dict[str, int]:
        """ステータス・タグごとに、使っているタスク数を数える"""
        counts: Counter[str] = Counter()
        for task in self._tasks:
            counts[task.status] += 1
            counts.update(task.tags)
        return counts

    def _on_settings_saved(self, config: Optional[Config]) -> None:
        """設定画面が保存して閉じたときの処理 (取消なら None が来る)"""
        if config is None:
            return
        self._config = config
        try:
            config.save()
        except OSError as e:
            log.error("設定の保存エラー: %s", e)
            self.notify(f"設定を保存できませんでした: {e}", severity="error", timeout=8)

        # 設定から消されたステータス・タグを参照しているタスクを直す
        for task in self._tasks:
            config.normalize_task(task)
        if self._tag_filter is not None and config.tag_by_id(self._tag_filter) is None:
            self._tag_filter = None

        self._save()
        self.notify("設定を保存しました", timeout=4)
