# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
OpenGaokao CLI — 命令行入口

用法:
    python -m gaokao.cli --province yunnan --example             # 跑通示例数据
    python -m gaokao.cli --province yunnan --check-config         # 检查省份配置
    python -m gaokao.cli --province yunnan --check-data           # 检查数据库完整性
    python -m gaokao.cli --province yunnan --check-data --db data/example.db
    python -m gaokao.cli --list-provinces                         # 列出所有省份
"""
import argparse
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


def cmd_list_provinces():
    from gaokao.config.registry import get_registry
    reg = get_registry()
    configs = reg.list_all()
    if not configs:
        print('未发现任何省份配置。请检查 provinces/ 目录。')
        return 1
    print(f'已注册 {len(configs)} 个省份:')
    for slug, cfg in configs.items():
        print(f'  [{slug}] {cfg.name} — {cfg.gaokao_mode} / {cfg.volunteer_mode} (改革年份 {cfg.reform_year})')
    return 0


def cmd_check_config(province: str):
    from gaokao.config.registry import get_registry
    reg = get_registry()
    cfg = reg.get(province)
    if not cfg:
        print(f'❌ 未知省份: {province}')
        print(f'   可用: {list(reg.list_all().keys())}')
        return 1
    print(f'✅ {cfg.name} ({cfg.slug})')
    print(f'   高考模式: {cfg.gaokao_mode}')
    print(f'   志愿模式: {cfg.volunteer_mode}')
    print(f'   改革年份: {cfg.reform_year}')
    print(f'   科类标签: {cfg.category}')
    print(f'   批次数量: {len(cfg.batches)}')
    print(f'   概率阈值: 冲<{cfg.thresholds.get("chong_max",35)}% | 稳{cfg.thresholds.get("wen_range",[35,85])}% | 保≥{cfg.thresholds.get("bao_min",85)}%')
    print(f'   推荐器类型: {reg.get_recommender_type(province)}')
    print(f'   数据库路径: {cfg.db_path}')
    return 0


def cmd_run_example(province: str):
    """用示例数据跑通完整推荐流程"""
    from gaokao.config.registry import get_registry
    reg = get_registry()
    cfg = reg.get(province)
    if not cfg:
        print(f'❌ 未知省份: {province}')
        return 1

    db_path = os.path.join(PROJECT_ROOT, 'data', 'example.db')
    if not os.path.exists(db_path):
        print(f'❌ 示例数据库不存在: {db_path}')
        print(f'   请先运行: python data/generate_example_db.py')
        return 1

    print(f'🚀 OpenGaokao 示例运行 — {cfg.name}')
    print('⚠️  当前为虚构示例数据，仅用于功能演示，不可用于实际填报。')
    print(f'   数据库: {db_path}')
    print(f'   推荐器: {reg.get_recommender_type(province)}')

    from gaokao.core.questionnaire_parser import QuestionnaireParser

    # 从省份配置设置年份参数
    from gaokao.core.volunteer_recommender import configure_with_config as _configure
    _configure(cfg)

    # 设置 revocation_risk 的数据库路径（该模块有独立数据库连接）
    from gaokao.core.revocation_risk import set_db_path as _set_revocation_db
    _set_revocation_db(db_path)

    parser = QuestionnaireParser.create_by_category('物理类')
    test_data = {
        'q1_name': '示例考生',
        'q2_gender': '男',
        'q8c_political_status': '共青团员',
        'q9_color_vision': '无色盲色弱',
        'q10_vision': '视力正常',
        'q12_total_score': 580,
        'q13_rank': 15000,
        'q14_category': '物理类',
        'q15_subject_combo': '物理+化学+生物',
        'q40_total_budget': '4-6万元',
        'q43_core_demand': '专业实力优先',
        'q45_target_industries': ['信息技术/互联网'],
        'q56_province_preference': '优先省内，省外也可以',
        'q60_stability_preference': 3,
    }

    questionnaire = parser.parse(test_data)
    print(f'   考生: {questionnaire.name}, {questionnaire.category}, 位次 {questionnaire.rank}')

    # 用 matching_engine 跑完整流程
    engine = None
    try:
        from gaokao.core.matching_engine import MatchingEngine
        engine = MatchingEngine(db_path=db_path)

        # 模拟性格测试答案
        import random
        random.seed(42)  # 可复现
        big_five = {i: random.randint(2, 5) for i in range(1, 51)}
        holland = {i: ('A' if random.random() > 0.5 else 'B') for i in range(1, 77)}
        efficacy = {}
        for i in range(76, 91):
            efficacy[i] = random.randint(2, 5)
        career_vals = {}
        for i in range(91, 111):
            career_vals[i] = random.randint(2, 5)

        result = engine.match(
            questionnaire, big_five, holland, efficacy, career_vals, top_n=30,
        )

        print(f'\n✅ 推荐完成!')
        print(f'   冲: {len(result.recommendations.get("冲", []))} 所')
        print(f'   稳: {len(result.recommendations.get("稳", []))} 所')
        print(f'   保: {len(result.recommendations.get("保", []))} 所')
        print(f'   垫: {len(result.recommendations.get("垫", []))} 所')

        total = sum(len(v) for v in result.recommendations.values())
        print(f'   总计: {total} 所')
        if total <= 0:
            print('❌ 示例运行未产生推荐结果。')
            return 1

        if result.funnel_report:
            from gaokao.core.funnel_eliminator import FunnelEliminator
            print(f'\n📊 漏斗排除报告:')
            print(FunnelEliminator.format_report(result.funnel_report))

        if result.notes:
            print(f'\n📝 注意事项 ({len(result.notes)} 条):')
            for n in result.notes[:5]:
                print(f'   - {n}')
            if len(result.notes) > 5:
                print(f'   ... 共 {len(result.notes)} 条')

        return 0

    except Exception as e:
        print(f'\n❌ 运行失败: {e}')
        import traceback
        traceback.print_exc()
        return 1
    finally:
        if engine:
            engine.close()


def cmd_check_data(province: str, db_path: str):
    """检查省份数据库的数据完整性"""
    from gaokao.config.registry import get_registry
    reg = get_registry()
    cfg = reg.get(province)
    if not cfg:
        print(f'❌ 未知省份: {province}')
        return 1

    if not os.path.exists(db_path):
        print(f'❌ 数据库不存在: {db_path}')
        return 1

    import sqlite3
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    issues = []
    warnings = []
    info = []

    # 1. 必需表列表
    score_line_table = f"score_line_{cfg.score_line_year}"
    enroll_plan_table = f"enroll_plan_{cfg.plan_year}"
    required_tables = [
        score_line_table,
        'enroll_detail',
        enroll_plan_table,
        'school_info',
        'major_catalog',
        'score_distribution',
    ]
    optional_tables = [
        'major_employment_stats',
        'major_revocation_stats',
    ]

    # 获取实际表
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing = {row[0] for row in c.fetchall()}

    # 检查视图
    c.execute("SELECT name FROM sqlite_master WHERE type='view'")
    existing_views = {row[0] for row in c.fetchall()}
    if 'v_enroll_detail' not in existing_views:
        warnings.append('缺少视图 v_enroll_detail（引擎通过此视图查询 enroll_detail）')

    for t in required_tables:
        if t not in existing:
            issues.append(f'缺少必需表: {t}')
        else:
            c.execute(f'SELECT COUNT(*) FROM {t}')
            cnt = c.fetchone()[0]
            if cnt == 0:
                issues.append(f'表 {t} 为空')
            else:
                info.append(f'  {t}: {cnt} 行')

    for t in optional_tables:
        if t in existing:
            c.execute(f'SELECT COUNT(*) FROM {t}')
            cnt = c.fetchone()[0]
            info.append(f'  {t}: {cnt} 行（可选）')
        else:
            warnings.append(f'缺少可选表: {t}（对应功能减弱）')

    # 2. 校验 batch 值对齐
    if score_line_table in existing:
        c.execute(f'SELECT DISTINCT batch FROM {score_line_table}')
        db_batches = {row[0] for row in c.fetchall()}
        yaml_batches = set(cfg.batches.keys())
        unmatched = db_batches - yaml_batches
        if unmatched:
            issues.append(f'score_line_{cfg.score_line_year} 的 batch 值与 province.yaml 不匹配: {unmatched}')
        else:
            info.append(f'  batch 值与配置一致（{len(db_batches)} 个批次）')

    # 3. 校验科类
    if score_line_table in existing:
        c.execute(f'SELECT DISTINCT subject_type FROM {score_line_table}')
        db_subjects = {row[0] for row in c.fetchall()}
        all_aliases = set()
        for aliases in cfg.category.values():
            all_aliases.update(aliases)
        # 基本科类检查：如果用了科类配置外的值，告警（允许不限/空）
        for s in db_subjects:
            if s and s not in all_aliases and s != '不限':
                warnings.append(f'subject_type 含配置外值: "{s}"')

    # 4. 校验 enroll_detail 年份
    if 'enroll_detail' in existing:
        c.execute('SELECT DISTINCT year FROM enroll_detail ORDER BY year')
        years = [row[0] for row in c.fetchall()]
        expected = set(cfg.history_years)
        actual = set(years)
        missing_years = expected - actual
        if missing_years:
            warnings.append(f'enroll_detail 缺少年份 {missing_years}（概率计算精度下降）')
        info.append(f'  enroll_detail 年份: {years}')

    # 5. 交叉一致性：school_name
    if 'school_info' in existing and score_line_table in existing:
        c.execute(f'''
            SELECT DISTINCT e.school_name FROM {score_line_table} e
            LEFT JOIN school_info s ON e.school_name = s.school_name
            WHERE s.school_name IS NULL
        ''')
        orphans = [row[0] for row in c.fetchall()]
        if orphans:
            warnings.append(f'score_line 中的校名在 school_info 中不存在: {orphans}')

    if 'school_info' in existing and 'enroll_detail' in existing:
        c.execute('''
            SELECT DISTINCT e.school_name FROM enroll_detail e
            LEFT JOIN school_info s ON e.school_name = s.school_name
            WHERE s.school_name IS NULL
        ''')
        orphans = [row[0] for row in c.fetchall()]
        if orphans:
            warnings.append(f'enroll_detail 中的校名在 school_info 中不存在: {orphans}')

    # 6. 交叉一致性：major_name
    if 'major_catalog' in existing and 'enroll_detail' in existing:
        c.execute('''
            SELECT DISTINCT e.major_name FROM enroll_detail e
            LEFT JOIN major_catalog m ON e.major_name = m.major_name
            WHERE m.major_name IS NULL
        ''')
        orphans = [row[0] for row in c.fetchall()]
        if orphans:
            warnings.append(f'enroll_detail 中的专业名在 major_catalog 中不存在: {orphans}')

    conn.close()

    # ── 输出 ──
    print(f'📊 数据校验报告 — {cfg.name} ({cfg.slug})')
    print(f'   数据库: {db_path}')
    print(f'   投档线表: {score_line_table} / 招生计划表: {enroll_plan_table}')
    print()

    print(f'📋 表概览:')
    for line in info:
        print(line)
    print()

    if issues:
        print(f'❌ {len(issues)} 个问题（必须修复）:')
        for i, iss in enumerate(issues, 1):
            print(f'   {i}. {iss}')
        print()
    else:
        print(f'✅ 所有必需表均存在且有数据')
        print()

    if warnings:
        print(f'⚠️ {len(warnings)} 个警告（建议处理）:')
        for i, w in enumerate(warnings, 1):
            print(f'   {i}. {w}')
        print()

    if not issues:
        print(f'✅ 数据库校验通过！可以运行: python -m gaokao.cli --province {province} --example')
        return 0
    else:
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description='OpenGaokao CLI')
    parser.add_argument('--province', '-p', default='yunnan', help='省份标识')
    parser.add_argument('--list-provinces', action='store_true', help='列出所有省份')
    parser.add_argument('--check-config', action='store_true', help='检查省份配置')
    parser.add_argument('--check-data', action='store_true', help='检查数据库数据完整性')
    parser.add_argument('--db', default=None, help='数据库路径（覆盖省份默认路径）')
    parser.add_argument('--example', action='store_true', help='运行示例推荐')
    args = parser.parse_args()

    if args.list_provinces:
        return cmd_list_provinces()
    elif args.check_config:
        return cmd_check_config(args.province)
    elif args.check_data:
        db_path = args.db or os.path.join(PROJECT_ROOT, 'data', f'{args.province}_gaokao.db')
        return cmd_check_data(args.province, db_path)
    elif args.example:
        return cmd_run_example(args.province)
    else:
        parser.print_help()
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
