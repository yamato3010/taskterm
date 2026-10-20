"""タスク・チャットの保存・読み込み

タスクは JSON で ``~/.local/share/taskterm/tasks.json`` に、自分宛てチャットは
同じ場所の ``chat.json`` に保存する (``XDG_DATA_HOME`` があればそれに従う)。
チャットを別ファイルにしているのは、片方が壊れてももう片方を巻き込まないため。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from .config import APP_DIR_NAME, Config
from .models import ChatMessage, Task

log = logging.getLogger(__name__)


def data_dir() -> Path:
    """データディレクトリ"""
    base = os.environ.get("XDG_DATA_HOME")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_DIR_NAME


def tasks_path() -> Path:
    """タスクファイルのパス"""
    return data_dir() / "tasks.json"


def chat_path() -> Path:
    """チャットファイルのパス"""
    return data_dir() / "chat.json"


def load_tasks(config: Config) -> list[Task]:
    """タスクを読み込む

    ファイルが無ければ空のリストを返す。読めない・形式が違う場合は
    ``tasks.json.broken`` に退避してから空で始める (保存で上書きして失うのを防ぐ)。

    設定に無いステータス・タグを参照しているタスクと、ステータスを持たない
    旧形式のタスク (完了フラグだけの時代のデータ) は ``config`` に合わせて直す。
    """
    path = tasks_path()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as e:
        log.warning("タスクファイルを読めないため退避します (%s): %s", path, e)
        _quarantine(path)
        return []

    if not isinstance(data, list):
        log.warning("タスクファイルの形式が不正なため退避します: %s", path)
        _quarantine(path)
        return []

    tasks: list[Task] = []
    for item in data:
        try:
            task = Task.from_dict(item)
        except (AttributeError, KeyError, TypeError, ValueError) as e:
            log.warning("読み込めないタスクを飛ばします (%r): %s", item, e)
            continue
        config.normalize_task(task, legacy_done=bool(item.get("done")))
        tasks.append(task)
    return tasks


def save_tasks(tasks: list[Task]) -> None:
    """タスクを保存する

    書き込み中に落ちてもファイルが壊れないよう、一時ファイルに書いてから
    置き換える。失敗した場合は OSError を送出する。
    """
    _write_json(tasks_path(), [t.to_dict() for t in tasks])


def load_messages() -> list[ChatMessage]:
    """チャットを読み込む (古い順)

    ファイルが無ければ空のリストを返す。読めない・形式が違う場合は
    タスクと同じく ``chat.json.broken`` に退避してから空で始める。
    """
    path = chat_path()
    try:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as e:
        log.warning("チャットファイルを読めないため退避します (%s): %s", path, e)
        _quarantine(path)
        return []

    if not isinstance(data, list):
        log.warning("チャットファイルの形式が不正なため退避します: %s", path)
        _quarantine(path)
        return []

    messages: list[ChatMessage] = []
    for item in data:
        try:
            messages.append(ChatMessage.from_dict(item))
        except (AttributeError, TypeError, ValueError) as e:
            log.warning("読み込めないメッセージを飛ばします (%r): %s", item, e)
    return messages


def save_messages(messages: list[ChatMessage]) -> None:
    """チャットを保存する (失敗した場合は OSError を送出する)"""
    _write_json(chat_path(), [m.to_dict() for m in messages])


def _write_json(path: Path, data: list) -> None:
    """書き込み中に落ちてもファイルが壊れないよう、一時ファイルに書いてから置き換える"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def _quarantine(path: Path) -> None:
    """壊れたファイルを退避する (失敗しても起動は続ける)"""
    try:
        path.replace(path.parent / (path.name + ".broken"))
    except OSError as e:
        log.warning("退避に失敗しました: %s", e)
