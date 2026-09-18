"""taskterm - メインアプリケーション"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Optional

from rich.cells import cell_len
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Footer, Header, Static, Tab, Tabs

from . import storage
from .config import Config
from .models import (
    Filter,
    Link,
    Quarter,
    Subtask,
    Task,
    format_due,
    next_priority,
    priority_label,
    quarter_of,
    subtask_progress,
)
from .screens.about import AboutScreen
from .screens.confirm import ConfirmDeleteScreen
from .screens.filter import FilterScreen
from .screens.links import LinksScreen
from .screens.memo import MemoViewScreen
from .screens.settings import SettingsScreen
from .screens.status import StatusScreen
from .screens.subtasks import SubtasksScreen
from .screens.task_edit import TaskEditScreen
from .widgets.calendar import MonthCalendar
from .widgets.task_list import TaskTable

log = logging.getLogger(__name__)


def _memo_tail(memo: str, pane: Widget) -> tuple[str, bool]:
    """詳細欄に出すメモと、入りきらず削ったかどうか

    メモは日付ごとに書き足していくため、収まらないときは古い先頭ではなく
    新しい末尾を残す (折り返しを見込んだ行数で数える)。
    """
    width, height = pane.content_size.width, pane.content_size.height
    if width <= 0 or height <= 0:
        return memo, False

    # 1行目はタスクの概要に使うため、メモに使えるのは残りの行
    limit = height - 1
    kept: list[str] = []
    used = 0
    for line in reversed(memo.splitlines()):
        used += max(1, -(-cell_len(line) // width))
        # 1行も出せなくなるのは避けるため、最初の1行は溢れても残す
        if used > limit and kept:
            return "\n".join(kept), True
        kept.insert(0, line)
    return memo, used > limit


# 四半期の進捗バーの長さ (右パネルの幅27桁に「 100%」を足しても収まる長さ)
_BAR_WIDTH = 21


def _quarter_text(quarter: Quarter, today: date) -> Text:
    """四半期パネルの中身 (年度と期間 / 進捗バー / 終了までの日数 の3行)"""
    remaining = quarter.remaining(today)
    ratio = (quarter.days - remaining) / quarter.days
    # 切り上げると最終日より前に満タンに見えてしまうので切り捨てる
    filled = int(_BAR_WIDTH * ratio)

    text = Text(no_wrap=True)
    text.append(f"{quarter.fiscal_year}年度 {quarter.number}Q", style="bold")
    start, end = quarter.start, quarter.end
    text.append(f"  {start.month}/{start.day} – {end.month}/{end.day}\n", style="dim")

    text.append("█" * filled, style="cyan")
    text.append("░" * (_BAR_WIDTH - filled), style="bright_black")
    text.append(f" {round(ratio * 100):>3}%\n")

    text.append(f"終了まで {remaining}日 (全 {quarter.days}日)", style="dim")
    return text


CSS_PATH = Path(__file__).parent / "styles" / "app.tcss"


class TodoApp(App):
    """taskterm アプリケーション"""

    TITLE = "taskterm"
    CSS_PATH = CSS_PATH
    BINDING_GROUP_TITLE = "全体"

    # 端末のANSIパレット (ユーザーのターミナル配色設定) をそのまま使うテーマ
    THEME = "ansi-dark"

    # フッターに出すのは使用頻度の高いものだけ。show=False のキーも ? のヘルプには出る
    BINDINGS = [
        Binding("a", "add", "追加"),
        Binding("e", "edit", "編集"),
        Binding("space", "toggle_done", "完了"),
        Binding("s", "change_status", "状態"),
        Binding("d", "delete", "削除"),
        Binding("f", "filter", "絞込"),
        Binding("m", "memo", "メモ"),
        Binding("o", "links", "リンク"),
        Binding("c", "subtasks", "チェック"),
        Binding("v", "toggle_view", "表示"),
        Binding("w", "toggle_tab", "タブ"),
        Binding("comma", "settings", "設定"),
        Binding("question_mark", "show_help_panel", "ヘルプ"),
        Binding("q", "quit", "終了"),
        Binding("i", "about", "このアプリについて", show=False),
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
        self._filter = Filter()  # 絞り込み中のステータス・タグ (空なら絞り込みなし)
        self._done_view = False  # 「完了」タブを見ているか (起動時は「未完了」)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Horizontal(id="main"):
            # 左: TODOリスト (下端に選択中タスクの概要とメモ)
            with Vertical(id="task-panel"):
                # 一覧の上に「未完了 / 完了」のタブ。フッターは端末が狭いと末尾から
                # 切れてしまうので、切り替えキーの案内はタブの横にも出す
                with Horizontal(id="task-tabs-row"):
                    tabs = Tabs(Tab("未完了", id="open"), Tab("完了", id="done"), id="task-tabs")
                    # 切り替えは w キーに任せ、tab キーのパネル移動に割り込ませない
                    tabs.can_focus = False
                    yield tabs
                    yield Static("◂ w で切替", id="tab-hint")
                yield TaskTable(id="task-table")
                with Container(id="memo-pane") as memo_pane:
                    memo_pane.border_title = "詳細"
                    yield Static("", id="task-meta")
                    yield Static("", id="task-memo")

            # 右: カレンダーと内訳
            with Vertical(id="side-panel"):
                with Container(id="calendar-panel") as calendar_panel:
                    calendar_panel.border_title = "カレンダー"
                    calendar_panel.border_subtitle = "• 未完了 · 完了"
                    yield MonthCalendar(id="calendar")
                # 設定でオンのときだけ出す (既定はオフ)
                with Container(id="quarter-panel") as quarter_panel:
                    quarter_panel.border_title = "四半期"
                    yield Static("", id="quarter")
                with Container(id="summary-panel") as summary_panel:
                    summary_panel.border_title = "内訳"
                    yield Static("", id="summary")

        # コマンドパレットの案内はフッターの幅を食うので出さない
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.theme = self.THEME
        self.query_one("#task-table", TaskTable).focus()
        self._refresh()

    # ── イベント ────────────────────────────

    def on_month_calendar_date_changed(self, event: MonthCalendar.DateChanged) -> None:
        """カレンダーの選択日が変わったら一覧を作り直す"""
        self._refresh()

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        """タブが変わったら一覧を作り直す (w キーでもクリックでもここに来る)"""
        self._done_view = event.tab.id == "done"
        self._refresh()

    def on_data_table_row_highlighted(self) -> None:
        """カーソル移動でメモ表示を追従させる"""
        self._update_memo()

    def on_data_table_row_selected(self) -> None:
        """一覧で Enter を押したら編集する"""
        self.action_edit()

    # ── 表示の更新 ──────────────────────────

    def _refresh(self) -> None:
        """一覧・カレンダーの印・内訳をまとめて作り直す"""
        today = date.today()
        visible = self._visible_tasks(today)

        self.query_one("#task-table", TaskTable).update_tasks(
            visible, today, self._config, done_view=self._done_view
        )
        self.query_one("#calendar", MonthCalendar).set_marks(self._marks())
        self._update_title(visible)
        self._update_quarter(today)
        self._update_summary(today)
        self._update_memo()

    def _filtered_tasks(self) -> list[Task]:
        """絞り込みを適用したタスク (f キーの絞り込み画面で決める)"""
        if not self._filter.is_active:
            return self._tasks
        status_of = self._config.status_of
        return [t for t in self._tasks if self._filter.matches(t, status_of(t).id)]

    def _visible_tasks(self, today: date) -> list[Task]:
        """一覧に出すタスク

        「完了」タブでは完了したタスクだけを、期限に関わらず全件、完了日の
        新しい順で出す (溜まった分をあとから見返すための場所)。

        「未完了」タブは既定では選択日が期限のタスクだけを出す。ただし今日を
        選んでいるときは期限切れのタスクも足す (見落とすと困るため)。
        v キーで全件表示に切り替えると、期限なしのタスクも含めて全部出す。
        どちらのタブでも f キーの絞り込みは効く (完了タブはタグのみ)。
        """
        config = self._config
        if self._done_view:
            # ステータスで絞り込んだままだと完了タブが必ず空になるので、タグだけ効かせる
            done = [
                t for t in self._tasks if config.is_done(t) and self._filter.matches_tags(t)
            ]
            return config.sort_done_tasks(done)

        tasks = [t for t in self._filtered_tasks() if not config.is_done(t)]
        if config.show_all:
            return config.sort_tasks(tasks)

        selected = self.query_one("#calendar", MonthCalendar).selected
        visible = [t for t in tasks if t.due == selected]
        if selected == today:
            visible += [t for t in tasks if config.is_overdue(t, today)]
        return config.sort_tasks(visible)

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

    def _filter_names(self) -> tuple[list[str], list[str]]:
        """絞り込み中のステータス名とタグ名 (どちらも設定の並び順)"""
        statuses = [s.name for s in self._config.statuses if s.id in self._filter.statuses]
        tags = [t.name for t in self._config.tags if t.id in self._filter.tags]
        return statuses, tags

    def _update_title(self, visible: list[Task]) -> None:
        """左パネルのタイトルに、今出している範囲と件数を書く"""
        statuses, tags = self._filter_names()
        if self._done_view:
            # 完了タブはステータスの絞り込みを掛けないので、タグだけ書く
            scope = "完了"
            names = "・".join(tags)
        else:
            selected = self.query_one("#calendar", MonthCalendar).selected
            scope = "全件" if self._config.show_all else format_due(selected)
            names = "・".join(statuses + tags)
        scope += f" / {names}" if names else ""
        self.query_one("#task-panel").border_title = f"TODO — {scope}  {len(visible)}件"

    def _update_quarter(self, today: date) -> None:
        """四半期パネルを更新する (設定でオフなら枠ごと隠す)

        「今が何Qか」を知るためのものなので、カレンダーの選択日ではなく今日を見る。
        """
        panel = self.query_one("#quarter-panel")
        panel.display = self._config.show_quarter
        if not self._config.show_quarter:
            return
        quarter = quarter_of(today, self._config.fiscal_start_month)
        self.query_one("#quarter", Static).update(_quarter_text(quarter, today))

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
        text.append("\n" if self._config.show_all else "  (v で表示)\n", style="dim")

        # ステータス別の件数 (設定の並び順・色で出す)
        # ここはステータスの分布を見るためのものなので、ステータスの絞り込みは掛けない
        text.append("\n")
        counts = Counter(
            config.status_of(t).id for t in self._tasks if self._filter.matches_tags(t)
        )
        for status in config.statuses:
            text.append(status.name, style=status.color)
            text.append(f" {counts.get(status.id, 0)}件\n", style="dim")

        statuses, tags = self._filter_names()
        if statuses or tags:
            text.append("\n絞り込み\n", style="dim")
            if statuses:
                text.append(f"状態 {'・'.join(statuses)}\n", style="dim")
            if tags:
                text.append(f"タグ {'・'.join(tags)}\n", style="dim")
            text.append("f で変更・解除", style="dim")

        self.query_one("#summary", Static).update(text)

    def _update_memo(self) -> None:
        """一覧の下の詳細欄を、選択中タスクの内容にする

        1行目にタスクの概要を出す (一覧のタグ列は幅に収まらない分を切っているため、
        複数のタグはここで読む)。その下にメモを折り返して出し、入りきらないときは
        新しい末尾側だけを残して、全文は m キーの全画面表示に任せる。
        """
        task = self.query_one("#task-table", TaskTable).selected_task
        pane = self.query_one("#memo-pane")
        meta = self.query_one("#task-meta", Static)
        body = self.query_one("#task-memo", Static)

        pane.border_title = "詳細"
        if task is None:
            meta.update("")
            body.update(Text("タスクがありません — a で追加", style="dim"))
            return

        meta.update(Text(self._task_meta(task), style="dim", no_wrap=True, overflow="ellipsis"))
        if not task.memo:
            body.update(Text("(メモなし) — m で書けます", style="dim"))
            return

        tail, clipped = _memo_tail(task.memo, pane)
        body.update(Text(tail))
        # 前に書いた分があることが分かるように、収まらないときだけ見かたを添える
        if clipped:
            pane.border_title = "詳細 (m でメモ全文)"

    def _save(self) -> None:
        """タスクを保存して表示を更新する"""
        try:
            storage.save_tasks(self._tasks)
        except OSError as e:
            log.error("保存エラー: %s", e)
            self.notify(f"保存できませんでした: {e}", severity="error", timeout=8)
        self._refresh()

    def _save_config(self) -> None:
        """設定を保存する (失敗しても操作は続けられるよう、知らせるだけにする)"""
        try:
            self._config.save()
        except OSError as e:
            log.error("設定の保存エラー: %s", e)
            self.notify(f"設定を保存できませんでした: {e}", severity="error", timeout=8)

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
            # 追加したタスクが今のタブに出ないと、消えてしまったように見える
            self._show_tab(done=self._config.is_done(task))
        self._save()

    def action_toggle_done(self) -> None:
        """完了 ⇄ 未完了 を切り替える (完了扱いのステータスに移す / 戻す)"""
        task = self._selected_task()
        if task is None:
            return
        config = self._config
        if config.is_done(task):
            config.apply_status(task, config.undone_status().id, date.today())
        else:
            done = config.done_status()
            if done is None:
                self.notify(
                    "完了扱いのステータスがありません (, の設定画面で指定できます)",
                    severity="warning",
                    timeout=6,
                )
                return
            config.apply_status(task, done.id, date.today())
        self._save()

    def action_change_status(self) -> None:
        """ステータスを一覧から選び直す

        並び順で次に送る形だと、完了扱いに入った時点でタスクが完了タブへ移り、
        そこから先に送れなくなるため選ぶ形にしている。
        """
        task = self._selected_task()
        if task is None:
            return
        self.push_screen(
            StatusScreen(self._config, task.title, self._config.status_of(task).id),
            lambda status_id: self._on_status_chosen(task, status_id),
        )

    def _on_status_chosen(self, task: Task, status_id: Optional[str]) -> None:
        """選ばれたステータスに移す (取り消したら None が来る)"""
        if status_id is None:
            return
        self._config.apply_status(task, status_id, date.today())
        self._save()

    def action_cycle_priority(self) -> None:
        """優先度を 高 → 中 → 低 と切り替える"""
        task = self._selected_task()
        if task is not None:
            task.priority = next_priority(task.priority)
            self._save()

    def action_delete(self) -> None:
        """選択中のタスクを削除する (確認してから消す)"""
        task = self._selected_task()
        if task is None:
            return
        self.push_screen(
            ConfirmDeleteScreen(task.title),
            lambda confirmed: self._on_delete_confirmed(task, confirmed),
        )

    def _on_delete_confirmed(self, task: Task, confirmed: Optional[bool]) -> None:
        """確認画面で削除を選んだときだけ消す (u キーで元に戻せる)"""
        if not confirmed:
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

    def action_memo(self) -> None:
        """選択中タスクのメモを全画面で開く (そこから編集もできる)"""
        task = self._selected_task()
        if task is None:
            return
        self.push_screen(
            MemoViewScreen(task.title, self._task_meta(task), task.memo),
            lambda memo: self._on_memo_edited(task, memo),
        )

    def action_links(self) -> None:
        """選択中タスクのリンクを開く (一覧から選んでブラウザで開く)"""
        task = self._selected_task()
        if task is None:
            return
        self.push_screen(
            LinksScreen(task.title, task.links),
            lambda links: self._on_links_edited(task, links),
        )

    def _on_links_edited(self, task: Task, links: Optional[list[Link]]) -> None:
        """リンク画面で編集された場合だけ保存する (開いただけなら None が来る)"""
        if links is None:
            return
        task.links = links
        self._save()

    def action_subtasks(self) -> None:
        """選択中タスクのチェックリストを開く (そこで追加・完了もできる)"""
        task = self._selected_task()
        if task is None:
            return
        self.push_screen(
            SubtasksScreen(task.title, task.subtasks),
            lambda subtasks: self._on_subtasks_edited(task, subtasks),
        )

    def _on_subtasks_edited(self, task: Task, subtasks: Optional[list[Subtask]]) -> None:
        """チェックリスト画面で編集された場合だけ保存する (見ただけなら None が来る)"""
        if subtasks is None:
            return
        task.subtasks = subtasks
        self._save()

    def _task_meta(self, task: Task) -> str:
        """詳細欄とメモ画面の見出しに出すタスクの概要

        タグを先頭に置く。ステータス・期限・優先度は一覧にも列があるので、
        幅が足りずに末尾が切れる場合は、一覧では読めないタグだけが残る。
        """
        tags = [tag.name for tag in self._config.tags_of(task)]
        parts = [" ".join(tags)] if tags else []
        parts.append(self._config.status_of(task).name)
        if task.due:
            parts.append(format_due(task.due))
        parts.append(f"優先度 {priority_label(task.priority)}")
        if task.subtasks:
            checked, total = subtask_progress(task.subtasks)
            parts.append(f"チェック {checked}/{total}")
        if task.links:
            parts.append(f"リンク {len(task.links)}件 (o で開く)")
        return "   ".join(parts)

    def _on_memo_edited(self, task: Task, memo: Optional[str]) -> None:
        """メモ画面で編集された場合だけ保存する (読むだけなら None が来る)"""
        if memo is None:
            return
        task.memo = memo
        self._save()

    def action_toggle_view(self) -> None:
        """選択日のみ / 全件 を切り替える (次の起動でも同じ表示で始める)"""
        if self._done_view:
            self.notify("完了タブは常に全件です (w で未完了に戻ります)", timeout=4)
            return
        self._config.show_all = not self._config.show_all
        self._save_config()
        self._refresh()

    def action_toggle_tab(self) -> None:
        """未完了 ⇄ 完了 のタブを切り替える"""
        self._show_tab(done=not self._done_view)

    def _show_tab(self, *, done: bool) -> None:
        """タブを開く (一覧の更新はタブのイベント側で行う)"""
        self.query_one("#task-tabs", Tabs).active = "done" if done else "open"

    def action_filter(self) -> None:
        """絞り込み画面を開く (ステータス・タグで一覧を絞る)"""
        self.push_screen(
            FilterScreen(self._config, self._filter), self._on_filter_changed
        )

    def _on_filter_changed(self, new_filter: Optional[Filter]) -> None:
        """絞り込み画面で決まった条件を反映する (取り消したら None が来る)"""
        if new_filter is None:
            return
        self._filter = new_filter
        self._refresh()

        statuses, tags = self._filter_names()
        names = "・".join(statuses + tags)
        self.notify(
            f"絞り込み: {names}" if names else "絞り込みを解除しました", timeout=3
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
        self._save_config()

        # 設定から消されたステータス・タグを参照しているタスクを直す
        for task in self._tasks:
            config.normalize_task(task)
        # 設定から消された項目が絞り込みに残らないようにする
        self._filter.statuses &= {s.id for s in config.statuses}
        self._filter.tags &= {t.id for t in config.tags}

        self._save()
        self.notify("設定を保存しました", timeout=4)

    def action_about(self) -> None:
        """このアプリについての画面を開く"""
        self.push_screen(AboutScreen())
