#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rename_core.py

ファイル名一括変更の中核ロジック。GUI に依存しないので単体で再利用・確認できる。

処理の流れ:
    1. collect_files()   対象フォルダからファイルを集める
    2. Rule.make_names() 変更後のファイル名を組み立てる
    3. build_plan()      衝突や使えない文字を検証して RenameEntry の一覧にする
    4. execute_plan()    一時名を経由した 2 段階リネームで実際に変更する
    5. undo()            execute_plan() の結果をたどって元の名前に戻す
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

# 2 段階リネームの途中で使う一時的な拡張子
TMP_SUFFIX = ".__renametmp__"

# Windows のファイル名に使えない文字
INVALID_CHARS = '\\/:*?"<>|'

# Windows の予約デバイス名（拡張子を除いた部分がこれと一致すると作成できない）
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# 1 件ごとの状態
STATUS_OK = "ok"        # 変更できる
STATUS_SKIP = "skip"    # 変更後の名前が元と同じ
STATUS_ERROR = "error"  # 変更できない（衝突・使えない文字など）

# 並び順
SORT_NAME = "name"
SORT_MTIME = "mtime"


# ---------------------------------------------------------------- ユーティリティ

def natural_key(name: str):
    """数字を数値として扱う自然順ソート用キー（file2 < file10 になる）"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def col_letters(n: int) -> str:
    """1 -> A, 2 -> B, ... 26 -> Z, 27 -> AA（Excel の列名と同じ規則）"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(ord("A") + r) + s
    return s


def letters_to_num(s: str) -> int:
    """A -> 1, B -> 2, ... AA -> 27"""
    s = s.strip().upper()
    if not s or not s.isalpha():
        raise ValueError("開始文字が不正です。A〜Z の英字で指定してください。")
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def build_regex(pattern: str) -> re.Pattern:
    """
    ワイルドカードパターンを正規表現に変換する。
    "*" と "?" をそれぞれキャプチャグループにする（"*" は最短一致）。
    例: "*gps*.geojson" -> ^(.*?)gps(.*?)\\.geojson$
    """
    parts = []
    for ch in pattern:
        if ch == "*":
            parts.append("(.*?)")
        elif ch == "?":
            parts.append("(.)")
        else:
            parts.append(re.escape(ch))
    return re.compile("^" + "".join(parts) + "$", re.IGNORECASE)


def split_name(name: str, keep_ext: bool):
    """ファイル名を「変更する部分」と「そのまま残す拡張子」に分ける。"""
    if not keep_ext:
        return name, ""
    stem, dot, ext = name.rpartition(".")
    if not stem:
        # 拡張子なし（README）や .gitignore のようなドットファイルは全体を名前とみなす
        return name, ""
    return stem, dot + ext


def collect_files(folder, pattern="*", recursive=False, sort_by=SORT_NAME):
    """対象フォルダからファイルを集めて並べ替える。"""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError("フォルダが見つかりません: " + str(folder))

    pattern = (pattern or "").strip() or "*"
    walker = folder.rglob("*") if recursive else folder.glob("*")
    files = [p for p in walker
             if p.is_file() and fnmatch.fnmatch(p.name.lower(), pattern.lower())]

    if sort_by == SORT_MTIME:
        files.sort(key=lambda p: (p.stat().st_mtime, natural_key(p.name)))
    else:
        files.sort(key=lambda p: (natural_key(str(p.parent)), natural_key(p.name)))
    return files


# ---------------------------------------------------------------- 変更ルール

@dataclass
class ReplaceRule:
    """ファイル名の中の検索文字列を置換文字列に置き換える。"""

    search: str = ""
    replace: str = ""
    ignore_case: bool = False
    keep_ext: bool = True

    def make_names(self, files):
        names = []
        for path in files:
            stem, ext = split_name(path.name, self.keep_ext)
            if self.search:
                if self.ignore_case:
                    # 置換文字列の \1 などを特殊扱いさせないため、関数で差し込む
                    stem = re.sub(re.escape(self.search), lambda m: self.replace,
                                  stem, flags=re.IGNORECASE)
                else:
                    stem = stem.replace(self.search, self.replace)
            names.append(stem + ext)
        return names


@dataclass
class AffixRule:
    """先頭・末尾への文字列追加と、先頭・末尾からの文字削除をまとめて行う。"""

    prefix: str = ""
    suffix: str = ""
    trim_head: int = 0
    trim_tail: int = 0
    keep_ext: bool = True

    def make_names(self, files):
        names = []
        for path in files:
            stem, ext = split_name(path.name, self.keep_ext)
            # 「削除してから追加する」順に適用する
            if self.trim_head > 0:
                stem = stem[self.trim_head:]
            if self.trim_tail > 0:
                stem = stem[:-self.trim_tail]
            names.append(self.prefix + stem + self.suffix + ext)
        return names


@dataclass
class SequenceRule:
    """A, B, C... または 001, 002... の連番を付ける。"""

    kind: str = "number"      # number（数字） / letter（英字）
    start: str = "1"
    step: int = 1
    digits: int = 3
    position: str = "prefix"  # prefix / suffix / replace / wildcard
    separator: str = "_"
    wildcard: str = ""        # position="wildcard" のときに使う対象パターン
    keep_ext: bool = True

    def make_names(self, files):
        tokens = self._tokens(len(files))
        names = []
        for path, token in zip(files, tokens):
            if self.position == "wildcard":
                names.append(self._apply_wildcard(path.name, token))
                continue
            stem, ext = split_name(path.name, self.keep_ext)
            if self.position == "prefix":
                stem = token + self.separator + stem
            elif self.position == "suffix":
                stem = stem + self.separator + token
            else:
                stem = token          # replace: 元の名前を捨てて連番だけにする
            names.append(stem + ext)
        return names

    def _tokens(self, count):
        """連番の文字列を count 個作る。"""
        step = self.step if self.step != 0 else 1
        if self.kind == "letter":
            base = letters_to_num(self.start or "A")
            return [col_letters(max(1, base + i * step)) for i in range(count)]
        try:
            base = int(str(self.start).strip() or "1")
        except ValueError:
            raise ValueError("開始番号が不正です。数字で指定してください。")
        return [str(base + i * step).zfill(max(0, self.digits)) for i in range(count)]

    def _apply_wildcard(self, name, token):
        """対象パターンの最初の * に当たる部分を連番で置き換える。"""
        pattern = (self.wildcard or "").strip() or "*"
        marks = [ch for ch in pattern if ch in "*?"]
        if "*" not in marks:
            return name
        group = marks.index("*") + 1          # 最初の * に対応するグループ番号
        match = build_regex(pattern).match(name)
        if not match:
            return name                       # パターンに一致しないファイルはそのまま
        start, end = match.span(group)
        return name[:start] + token + name[end:]


# ---------------------------------------------------------------- 計画の作成

@dataclass
class RenameEntry:
    """1 ファイル分の変更計画。"""

    path: Path
    new_name: str
    status: str = STATUS_OK
    message: str = ""
    selected: bool = True

    @property
    def new_path(self) -> Path:
        return self.path.parent / self.new_name

    @property
    def renamable(self) -> bool:
        return self.status == STATUS_OK


def _key(path: Path):
    """Windows は大文字小文字を区別しないので、比較用に小文字化したキーを作る。"""
    return (str(path.parent).lower(), path.name.lower())


def validate_name(name: str) -> str:
    """ファイル名として使えるかを調べ、問題があれば理由を返す（問題なければ空文字）。"""
    if not name:
        return "名前が空になります"
    bad = sorted({ch for ch in name if ch in INVALID_CHARS})
    if bad:
        return "使えない文字: " + " ".join(bad)
    if name != name.rstrip(" ."):
        return "末尾の空白・ピリオドは使えません"
    if name.split(".")[0].upper() in RESERVED_NAMES:
        return "Windows の予約語は使えません"
    return ""


def build_plan(files, rule):
    """変更後の名前を組み立て、衝突や使えない名前を検出して一覧にする。"""
    entries = [RenameEntry(path=p, new_name=n)
               for p, n in zip(files, rule.make_names(files))]

    # 変更後の名前が同じフォルダ内で重なっていないか数える
    counts = {}
    for entry in entries:
        key = _key(entry.new_path)
        counts[key] = counts.get(key, 0) + 1

    # 名前を明け渡すファイル（この相手との衝突は 2 段階リネームで解消できる）
    freed = {_key(e.path) for e in entries if e.new_name != e.path.name}

    for entry in entries:
        reason = validate_name(entry.new_name)
        if entry.new_name == entry.path.name:
            entry.status, entry.message = STATUS_SKIP, "変更なし"
        elif reason:
            entry.status, entry.message = STATUS_ERROR, reason
        elif counts[_key(entry.new_path)] > 1:
            entry.status, entry.message = STATUS_ERROR, "変更後の名前が重複しています"
        elif entry.new_path.exists() and _key(entry.new_path) not in freed:
            entry.status, entry.message = STATUS_ERROR, "同じ名前のファイルが既にあります"
        elif len(str(entry.new_path)) > 255:
            entry.status, entry.message = STATUS_ERROR, "パスが長すぎます"
        else:
            entry.status, entry.message = STATUS_OK, ""
        entry.selected = entry.renamable
    return entries


# ---------------------------------------------------------------- 実行と取り消し

def _rollback(staged):
    """一時名のままになっているファイルを元の名前に戻す。"""
    for tmp_path, old_path, _ in reversed(staged):
        try:
            if tmp_path.exists():
                tmp_path.rename(old_path)
        except OSError:
            pass


def _revert(pairs):
    """(変更前, 変更後) の組を逆順にたどって変更前の名前に戻す。"""
    for old_path, new_path in reversed(pairs):
        try:
            if new_path.exists():
                new_path.rename(old_path)
        except OSError:
            pass


def execute_plan(entries):
    """
    選択されたファイルの名前を、一時名を経由した 2 段階リネームで変更する。

    2 段階にすることで A→B, B→A のような名前の入れ替えも安全に処理できる。
    途中で失敗した場合は、その時点までの変更をすべて元に戻す。

    Returns:
        (done, errors)
        done   ... (変更前パス, 変更後パス) の一覧
        errors ... (パス, エラーメッセージ) の一覧
    """
    targets = [e for e in entries if e.selected and e.renamable]
    staged = []   # (一時パス, 変更前パス, 変更後パス)
    errors = []

    # 第 1 段階: いったん一時的な名前にする
    for entry in targets:
        tmp_path = entry.path.with_name(entry.path.name + TMP_SUFFIX)
        counter = 0
        while tmp_path.exists():
            counter += 1
            tmp_path = entry.path.with_name(entry.path.name + TMP_SUFFIX + str(counter))
        try:
            entry.path.rename(tmp_path)
            staged.append((tmp_path, entry.path, entry.new_path))
        except OSError as exc:
            errors.append((entry.path, str(exc)))
            _rollback(staged)
            return [], errors

    # 第 2 段階: 目的の名前にする
    done = []
    for tmp_path, old_path, new_path in staged:
        try:
            tmp_path.rename(new_path)
            done.append((old_path, new_path))
        except OSError as exc:
            errors.append((old_path, str(exc)))
            _revert(done)      # 変更済みの分を戻す
            _rollback(staged)  # 一時名のままの分を戻す
            return [], errors

    return done, errors


def undo(history):
    """execute_plan() の結果を使って、変更前のファイル名に戻す。"""
    entries = []
    for old_path, new_path in history:
        entry = RenameEntry(path=new_path, new_name=old_path.name)
        if not new_path.exists():
            entry.status = STATUS_ERROR
            entry.message = "ファイルが見つかりません"
            entry.selected = False
        entries.append(entry)
    return execute_plan(entries)
