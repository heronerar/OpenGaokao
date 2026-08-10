# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""创建/重建主推荐链路使用的物化视图 v_enroll_detail — OpenGaokao 多省版

移植自 YGCare/scripts/create_views.py，按开源多省定位改造：
    - 按省解析 data/<省>_gaokao.db（而非单库硬编码）
    - **列清单 schema 无关**：PRAGMA 动态读取 enroll_detail 全部列，
      保全所有列 + 追加 norm_subject（YGCare 原版硬编码 ~40 列，
      会丢掉 OpenGaokao 多出的 rk_grade/disc_eval/各历史年份列等 24 列）
    - 索引按列是否存在条件创建，适配各省 schema 差异

每次某省数据导入/更新后 MUST 运行一次（共享陷阱 7：v_enroll_detail 是
物化表不是 VIEW，源表变了不会自动刷新）。引擎与回测都依赖此表
（gaokao/core/admission_probability.py、backtest.py），缺失或过期会直接出错。

实现方式：物化表（实表 + 索引），不用 SQLite VIEW + ROW_NUMBER —
后者每次查询都全表扫描+排序，慢 100 倍以上。

原子重建：先构建临时表 v_enroll_detail_new + 索引 + 去重校验，全部通过后
事务内 swap（DROP 旧 → RENAME 新）。任何中途失败，旧表仍可用，主链路不受影响。

物化策略：**1:1 直拷 enroll_detail（按年份过滤）+ 追加 norm_subject 列，不塌缩行**。

    重要：不照搬 YGCare create_views 的 ROW_NUMBER 去重。YGCare 按
    (年,校,专业,批次,norm) 去重，会把 OpenGaokao 院校专业组模式下**同校同专业
    但不同专业组**（sp_group_code/group_no 不同）的记录错误合并——实测会丢 1,714
    行真实专业组数据。OpenGaokao 的视图保持逐行/逐专业组粒度。

    - norm_subject 规范键（仅新增列，不影响行数）：
      物理/物理类/理科→'物理'，历史/历史类/文科→'历史'，供规范化 join 用。

年份口径（O-09 决策=选项 B）：--min-year 默认 2020，纳入 2020-2025 全部年份，并按
**年份分治去重**——2020-2022（旧高考拼写重复、0% 专业组）按 norm 去重清掉"理科≡物理/
文科≡历史"的双计；2023-2025 保持 1:1（不塌缩院校专业组）。依据见
docs/audit/03_data_quality_2020_2022_20260614.md。设 --min-year 2023 可回到旧线上
口径（仅新三年、纯 1:1）。

用法：
    python scripts/create_views.py                       # 默认 yunnan，2023+（复现现状）
    python scripts/create_views.py --min-year 2020       # 纳入 2020-2022（需评审数据质量）
"""
import argparse
import os
import sqlite3
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NEW_TABLE = 'v_enroll_detail_new'
FINAL_TABLE = 'v_enroll_detail'

# 年份分治边界：此年以下（旧高考，科类标签存在"理科≡物理/文科≡历史"拼写重复，
# 且 0% 带专业组）按 norm 去重；此年及以上（含 2023-2024 旧高考单标签、2025 新高考
# 院校专业组）保持 1:1，避免误并专业组（O-09 报告依据；2023 = 云南口径切换边界）。
DEDUP_BELOW_YEAR = 2023

# 默认纳入年份下界（OG-F-48：函数与 CLI 共用同一常量，避免两入口口径漂移）。
# 2020 = 纳入 2020-2025、对 <2023 做年份感知去重（O-09 决议=选项 B）。
DEFAULT_MIN_YEAR = 2020

# 索引定义：(索引名后缀, [列...])；列不全则跳过该索引（多省 schema 安全）
INDEX_SPECS = [
    ('school', ['school_name']),
    ('year_school', ['year', 'school_name']),
    ('year_subject', ['year', 'subject_type']),
    ('year_school_tier', ['year', 'school_name', 'subject_type', 'batch_tier']),
    ('year_school_major', ['year', 'school_name', 'major_name']),
]


def resolve_db_path(province: str) -> str:
    return os.path.join(PROJECT_ROOT, 'data', f'{province}_gaokao.db')


def _enroll_detail_columns(cur: sqlite3.Cursor) -> list:
    """动态读取 enroll_detail 全部列（schema 无关，保全多省列差异）。"""
    rows = cur.execute('PRAGMA table_info(enroll_detail)').fetchall()
    return [r[1] for r in rows]


def create_views(db_path: str, min_year: int = DEFAULT_MIN_YEAR) -> None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cols = _enroll_detail_columns(cur)
    if not cols:
        conn.close()
        print('❌ enroll_detail 表不存在或无列', file=sys.stderr)
        sys.exit(1)
    if 'norm_subject' in cols:
        cols = [c for c in cols if c != 'norm_subject']  # 防重复列
    col_csv = ', '.join(cols)

    # ── 第一步：清掉前次失败残留的临时表 ──
    cur.execute(f'DROP TABLE IF EXISTS {NEW_TABLE}')

    # ── 第二步：构建临时表（年份分治：<DEDUP_BELOW_YEAR 按 norm 去重，否则 1:1）──
    # 2020-2022：旧高考拼写重复（理科≡物理/文科≡历史），按 (年,校,专业,批次,norm) 去重，
    #   优先保留 物理/历史 拼写（_pri=1），同组内按 rowid 取首条；这三年 0% 专业组，去重安全。
    # 2023+：保持 1:1，不塌缩专业组（2025 院校专业组同(校,专业,批次,norm)合法多行）。
    cur.execute(f"""
    CREATE TABLE {NEW_TABLE} AS
    WITH base AS (
        SELECT {col_csv},
            CASE
                WHEN subject_type IN ('物理','物理类','理科') THEN '物理'
                WHEN subject_type IN ('历史','历史类','文科') THEN '历史'
                ELSE subject_type
            END AS norm_subject,
            CASE WHEN subject_type IN ('物理','历史','物理类','历史类') THEN 1 ELSE 2 END AS _pri
        FROM enroll_detail
        WHERE CAST(year AS INTEGER) >= {min_year}
    ),
    ranked AS (
        SELECT *,
            CASE WHEN CAST(year AS INTEGER) < {DEDUP_BELOW_YEAR}
                THEN ROW_NUMBER() OVER (
                    PARTITION BY year, school_name, major_name, batch, norm_subject, min_rank
                    ORDER BY _pri, subject_type)
                ELSE 1 END AS _rn
        FROM base
    )
    SELECT {col_csv}, norm_subject FROM ranked WHERE _rn = 1
    """)

    # ── 第二步续：临时表索引（_new 后缀避免与最终表冲突）──
    for suffix, idx_cols in INDEX_SPECS:
        if all(c in cols for c in idx_cols):
            cur.execute(
                f'CREATE INDEX idx_ved_{suffix}_new ON {NEW_TABLE}({", ".join(idx_cols)})'
            )

    # ── 第二步续：年份感知校验（任一不达标 → 不 swap，旧表保留）──
    # 不再做全局 1:1，因为 <DEDUP_BELOW_YEAR 的年份是有意去重的。改为分治断言：
    #   ① 新表非空、不超过源表 year>=min_year 行数（无行膨胀）；
    #   ② year>=DEDUP_BELOW_YEAR：视图==源表逐年 1:1（确认未误并专业组）；
    #   ③ year<DEDUP_BELOW_YEAR：去重彻底，无残留 (年,校,专业,批次,norm) 重复组。
    orig = cur.execute('SELECT COUNT(*) FROM enroll_detail').fetchone()[0]
    src_filtered = cur.execute(
        'SELECT COUNT(*) FROM enroll_detail WHERE CAST(year AS INTEGER) >= ?',
        (min_year,)
    ).fetchone()[0]
    new_cnt = cur.execute(f'SELECT COUNT(*) FROM {NEW_TABLE}').fetchone()[0]

    def _fail(msg):
        cur.execute(f'DROP TABLE IF EXISTS {NEW_TABLE}')
        conn.close()
        print(f'❌ {msg}，旧表保留', file=sys.stderr)
        sys.exit(1)

    if new_cnt == 0:
        _fail(f'新临时表为空（min_year={min_year}）')
    if new_cnt > src_filtered:
        _fail(f'新临时表 {new_cnt:,} > 源表 year>={min_year} 的 {src_filtered:,}，疑似行膨胀')

    # ② 1:1 区间逐年核对
    for (yr,) in cur.execute(
        f'SELECT DISTINCT year FROM {NEW_TABLE} '
        f'WHERE CAST(year AS INTEGER) >= {DEDUP_BELOW_YEAR}'
    ).fetchall():
        vc = cur.execute(f'SELECT COUNT(*) FROM {NEW_TABLE} WHERE year=?', (yr,)).fetchone()[0]
        sc = cur.execute('SELECT COUNT(*) FROM enroll_detail WHERE year=?', (yr,)).fetchone()[0]
        if vc != sc:
            _fail(f'{yr} 年应 1:1 但视图 {vc:,} ≠ 源 {sc:,}（疑似误并专业组）')

    # ③ 去重区间无残留重复组
    dup = cur.execute(f"""
        SELECT COUNT(*) FROM (
            SELECT 1 FROM {NEW_TABLE}
            WHERE CAST(year AS INTEGER) < {DEDUP_BELOW_YEAR} AND subject_type IS NOT NULL
            GROUP BY year, school_name, major_name, batch, norm_subject, min_rank
            HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    if dup != 0:
        _fail(f'去重区间(<{DEDUP_BELOW_YEAR})仍有 {dup} 个重复组')

    # ── 第三步：事务内原子 swap ──
    # BEGIN IMMEDIATE 立即拿写锁，避免并发写造成 SQLITE_BUSY。
    # SQLite 中类型不符的 DROP 会报错，先查 sqlite_master 看实际类型再 drop。
    try:
        cur.execute('BEGIN IMMEDIATE')
        row = cur.execute(
            "SELECT type FROM sqlite_master WHERE name=?", (FINAL_TABLE,)
        ).fetchone()
        if row:
            if row[0] == 'view':
                cur.execute(f'DROP VIEW {FINAL_TABLE}')
            elif row[0] == 'table':
                cur.execute(f'DROP TABLE {FINAL_TABLE}')
        cur.execute(f'ALTER TABLE {NEW_TABLE} RENAME TO {FINAL_TABLE}')
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        try:
            cur.execute(f'DROP TABLE IF EXISTS {NEW_TABLE}')
            conn.commit()
        except sqlite3.Error:
            pass
        conn.close()
        print(f'❌ swap 失败（旧表保留）: {e}', file=sys.stderr)
        sys.exit(1)

    # ── 第四步：索引重命名为最终名（幂等，避免下次运行 _new 名冲突）──
    for suffix, idx_cols in INDEX_SPECS:
        if not all(c in cols for c in idx_cols):
            continue
        cur.execute(f'DROP INDEX IF EXISTS idx_ved_{suffix}_new')
        cur.execute(
            f'CREATE INDEX IF NOT EXISTS idx_ved_{suffix} '
            f'ON {FINAL_TABLE}({", ".join(idx_cols)})'
        )
    conn.commit()

    dedup_note = ('1:1' if min_year >= DEDUP_BELOW_YEAR
                  else f'<{DEDUP_BELOW_YEAR} 去重 / >= 保 1:1')
    print(f'enroll_detail 全表:        {orig:,}')
    print(f'v_enroll_detail (year>={min_year}): {new_cnt:,}（源筛 {src_filtered:,}，{dedup_note}）')
    print(f'保留列数:                  {len(cols) + 1}（{len(cols)} 原始列 + norm_subject）')
    conn.close()
    print('✅ v_enroll_detail 物化表 + 索引创建成功（原子 swap）')


def main():
    parser = argparse.ArgumentParser(description='OpenGaokao 重建 v_enroll_detail 物化视图')
    parser.add_argument('--province', type=str, default='yunnan',
                        help='省份 slug（对应 data/<省>_gaokao.db），默认 yunnan')
    parser.add_argument('--min-year', type=int, default=DEFAULT_MIN_YEAR,
                        help='纳入视图的最早年份。默认 2020（含 2020-2022，按年份感知去重）；'
                             '设 2023 仅含新三年（旧线上口径，纯 1:1）')
    args = parser.parse_args()

    db_path = resolve_db_path(args.province)
    if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
        print(f'❌ 数据库不存在或为 0 字节假文件: {db_path}', file=sys.stderr)
        sys.exit(1)

    print(f'省份: {args.province}')
    print(f'数据库: {db_path}')
    print(f'最早年份: {args.min_year}')
    create_views(db_path, min_year=args.min_year)


if __name__ == '__main__':
    main()
