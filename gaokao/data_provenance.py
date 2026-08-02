# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""识别 SQLite 数据库是否为 OpenGaokao 合成示例数据。"""
from __future__ import annotations

import sqlite3
from pathlib import Path


METADATA_TABLE = 'opengaokao_dataset_metadata'
SYNTHETIC_DATA_KIND = 'synthetic_example'
REAL_DATA_KIND = 'real'
UNMARKED_DATA_KIND = 'unmarked'


class DatabaseProvenanceError(RuntimeError):
    """数据库来源标记缺失、冲突或不可读取。"""


def inspect_database_provenance(db_path: str | Path) -> str:
    """返回数据内容类型；复制或改名数据库不会改变该结果。"""
    path = Path(db_path)
    if not path.exists() or path.stat().st_size == 0:
        raise DatabaseProvenanceError(f'数据库不存在或为空: {path}')

    try:
        with sqlite3.connect(str(path)) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            marker = None
            if METADATA_TABLE in tables:
                metadata = dict(
                    conn.execute(f'SELECT key, value FROM {METADATA_TABLE}')
                )
                marker = metadata.get('data_kind')
                if not marker:
                    raise DatabaseProvenanceError(
                        f'{METADATA_TABLE} 缺少 data_kind'
                    )

            synthetic_names = False
            if 'school_info' in tables:
                total, marked = conn.execute(
                    """SELECT COUNT(*),
                              SUM(CASE WHEN school_name LIKE '示例·%' THEN 1 ELSE 0 END)
                       FROM school_info
                       WHERE school_name IS NOT NULL AND TRIM(school_name) <> ''"""
                ).fetchone()
                synthetic_names = total > 0 and marked == total
    except sqlite3.Error as exc:
        raise DatabaseProvenanceError(f'无法读取数据库来源标记: {exc}') from exc

    allowed = {None, SYNTHETIC_DATA_KIND, REAL_DATA_KIND}
    if marker not in allowed:
        raise DatabaseProvenanceError(f'未知 data_kind: {marker}')
    if marker == REAL_DATA_KIND and synthetic_names:
        raise DatabaseProvenanceError('数据来源标记与“示例·”内容冲突')
    if marker == SYNTHETIC_DATA_KIND or synthetic_names:
        return SYNTHETIC_DATA_KIND
    if marker == REAL_DATA_KIND:
        return REAL_DATA_KIND
    return UNMARKED_DATA_KIND
