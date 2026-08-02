# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""通用省份数据导入器（CSV → SQLite）— 兑现"用户自助清洗数据"

OG-O-17：在此之前，新增省份要从零抄一份 generate_<省>_db.py（Python）。本工具让
**有能力自助的用户只需把清洗好的数据放成 CSV**，跑一条命令即可建库，不必写 Python——
符合 OpenGaokao 开源底色与 2026-06-14 决策"自助清洗也要允许"。

输入约定：
    一个目录，内含若干 `<表名>.csv`，文件名即目标表名，首行为列名。
    例：score_line_2025.csv / enroll_detail.csv / school_info.csv / major_catalog.csv
       / enroll_plan_2025.csv / score_distribution.csv / major_employment_stats.csv ...
    表名/列名/含义见 docs/data-guide.md（规范 schema 出处）。

设计要点（吸取 create_views 的教训：schema 无关，不硬编码列）：
    - 列**按 CSV 表头**建，不预设固定列集——用户多列少列都不丢/不炸。
    - 列类型**按列名推断**（min_rank/year/*_count→INTEGER，employment_rate→REAL，余 TEXT），
      保证 min_rank 等关键列是数值型（位次比较依赖）。空串→NULL。
    - 导入 enroll_detail 后自动调 create_views 建 v_enroll_detail（引擎依赖）。
    - 自动接 post_import_validation 做导入后质检（科类标签门禁 + 覆盖率），带退出码。

用法：
    python scripts/import_province.py --province hunan --src path/to/hunan_csv/
    python scripts/import_province.py --province hunan --src ... --no-validate   # 跳过质检
    python scripts/import_province.py --province hunan --src ... --force         # 覆盖已存在的库
"""
import argparse
import csv
import os
import sqlite3
import subprocess
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)
import create_views  # 复用 v_enroll_detail 物化重建（同 scripts/ 目录）

# 列名→类型推断（与 docs/data-guide.md 文档化 schema 一致）
_INT_COLS = {
    'year', 'score', 'min_score', 'min_rank', 'max_score', 'max_rank',
    'enroll_count', 'num', 'is_985', 'is_211', 'is_syl', 'num_phd', 'num_master',
    'school_id', 'revoke_count', 'min_score_orig', 'planned_count', 'tuition',
    'planned_result', 'group_enroll', 'group_min_score', 'group_min_rank',
    'group_planned', 'enroll_count', 'is_new',
}
_REAL_COLS = {'employment_rate', 'avg_salary_monthly'}
_INT_SUFFIXES = ('_count', '_cumsum', '_rank', '_2025', '_2024', '_2023', '_2022')


def _col_type(name: str) -> str:
    n = name.strip().lower()
    if n in _REAL_COLS:
        return 'REAL'
    if n in _INT_COLS or n.endswith(_INT_SUFFIXES):
        return 'INTEGER'
    return 'TEXT'


def _coerce(value: str, col_type: str):
    """空串→NULL；数值列尽量转数值，转不动则原样（容错，不静默吞数据）。"""
    if value is None:
        return None
    v = value.strip()
    if v == '':
        return None
    if col_type == 'INTEGER':
        try:
            return int(float(v))  # 容 "15000.0" 这类
        except ValueError:
            return v  # 转不动保留原值，交给 post_import 暴露，而非静默归零
    if col_type == 'REAL':
        try:
            return float(v)
        except ValueError:
            return v
    return v


def _import_csv(conn: sqlite3.Connection, table: str, csv_path: str) -> int:
    with open(csv_path, 'r', encoding='utf-8-sig', newline='') as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            print(f'  ⚠️ {table}: CSV 为空，跳过')
            return 0
        cols = [c.strip() for c in header]
        types = [_col_type(c) for c in cols]
        col_defs = ', '.join(f'"{c}" {t}' for c, t in zip(cols, types))

        cur = conn.cursor()
        cur.execute(f'DROP TABLE IF EXISTS "{table}"')
        cur.execute(f'CREATE TABLE "{table}" ({col_defs})')
        placeholders = ', '.join('?' for _ in cols)
        insert_sql = f'INSERT INTO "{table}" VALUES ({placeholders})'

        n = 0
        batch = []
        for row in reader:
            if not row or all(x.strip() == '' for x in row):
                continue
            # 行列数对齐表头（多截少补 None）
            row = (row + [None] * len(cols))[:len(cols)]
            batch.append([_coerce(v, t) for v, t in zip(row, types)])
            if len(batch) >= 2000:
                cur.executemany(insert_sql, batch)
                n += len(batch)
                batch = []
        if batch:
            cur.executemany(insert_sql, batch)
            n += len(batch)
        conn.commit()
        return n


def main():
    parser = argparse.ArgumentParser(description='OpenGaokao 通用省份数据导入器（CSV→SQLite）')
    parser.add_argument('--province', required=True, help='省份 slug（生成 data/<slug>_gaokao.db）')
    parser.add_argument('--src', required=True, help='含 <表名>.csv 的目录')
    parser.add_argument('--force', action='store_true', help='覆盖已存在的数据库')
    parser.add_argument('--no-validate', action='store_true', help='跳过导入后质检')
    parser.add_argument('--no-views', action='store_true', help='跳过 v_enroll_detail 重建')
    args = parser.parse_args()

    src = os.path.abspath(args.src)
    if not os.path.isdir(src):
        print(f'❌ 源目录不存在: {src}', file=sys.stderr)
        sys.exit(1)
    csvs = sorted(f for f in os.listdir(src) if f.lower().endswith('.csv'))
    if not csvs:
        print(f'❌ 源目录无 CSV 文件: {src}', file=sys.stderr)
        sys.exit(1)

    db_path = os.path.join(PROJECT_ROOT, 'data', f'{args.province}_gaokao.db')
    if os.path.exists(db_path) and os.path.getsize(db_path) > 0 and not args.force:
        print(f'❌ 数据库已存在: {db_path}（加 --force 覆盖）', file=sys.stderr)
        sys.exit(1)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    print(f'省份: {args.province}')
    print(f'源目录: {src}')
    print(f'目标库: {db_path}\n')

    # OG-F-50: 原子导入——先建到临时库，全部成功再 os.replace 落位；中途失败删临时库、
    # 目标库保持不动，绝不留"部分表存在"的残缺库（此前逐表 commit 中断会留半库）。
    tmp_path = db_path + '.importing'
    if os.path.exists(tmp_path):
        os.remove(tmp_path)

    conn = sqlite3.connect(tmp_path)
    loaded = {}
    try:
        for fname in csvs:
            table = os.path.splitext(fname)[0]
            n = _import_csv(conn, table, os.path.join(src, fname))
            loaded[table] = n
            print(f'  ✅ {table}: {n:,} 行')
        conn.close()  # 先释放写锁，create_views 内部会另开连接做原子 swap

        # 必填表提示（缺失不阻断，但明确告警，避免用户以为建好了）
        required = ['enroll_detail', 'school_info', 'major_catalog']
        missing = [t for t in required if t not in loaded]
        if missing:
            print(f'\n⚠️ 缺少必填表: {missing}（引擎可能无法正常推荐，见 docs/data-guide.md）')

        # 建 v_enroll_detail（引擎依赖；在临时库上建）
        if 'enroll_detail' in loaded and not args.no_views:
            print('\n[建视图] v_enroll_detail ...')
            create_views.create_views(tmp_path)  # 用 DEFAULT_MIN_YEAR(2020)，与 CLI 一致
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        print(f'\n❌ 导入失败，已回滚（目标库未改动）: {e}', file=sys.stderr)
        sys.exit(1)

    # 全部成功 → 原子落位（覆盖旧库，--force 已在前面校验）
    os.replace(tmp_path, db_path)

    # 导入后质检
    if not args.no_validate:
        print('\n[质检] post_import_validation ...')
        script = os.path.join(SCRIPTS_DIR, 'post_import_validation.py')
        proc = subprocess.run(
            [sys.executable, script, '--province', args.province, '--quick'],
            cwd=PROJECT_ROOT,
        )
        if proc.returncode != 0:
            print('\n❌ 导入完成但质检未通过（见上方报告）——请修数据后重导', file=sys.stderr)
            sys.exit(1)

    print(f'\n✅ 导入完成: {db_path}')
    print(f'   下一步：编写 provinces/{args.province}/province.yaml 后运行')
    print(f'   python -m gaokao.cli --province {args.province} --check-data')


if __name__ == '__main__':
    main()
