# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
生成示例 SQLite 数据库 — 合成的云南省高考录取数据
数据量：~60行，足够跑通完整推荐管道
所有分数、位次、招生与就业记录均为合成数据；生成后院校名统一加“示例·”前缀。
本数据库仅用于演示和测试，不可用于实际填报。
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'example.db')


def create_example_db():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── 一分一段表（10列）──
    c.execute('''CREATE TABLE score_distribution (
        year INTEGER, score INTEGER,
        physics_count INTEGER, physics_cumsum INTEGER,
        history_count INTEGER, history_cumsum INTEGER,
        wenke_count INTEGER, wenke_cumsum INTEGER,
        like_count INTEGER, like_cumsum INTEGER
    )''')
    scores_data = [
        (2025, 700, 50, 50, 10, 10, 10, 10, 50, 50),
        (2025, 650, 200, 250, 80, 90, 80, 90, 200, 250),
        (2025, 600, 800, 1050, 500, 590, 500, 590, 800, 1050),
        (2025, 580, 1200, 2250, 800, 1390, 800, 1390, 1200, 2250),
        (2025, 550, 3000, 5250, 2500, 3890, 2500, 3890, 3000, 5250),
        (2025, 520, 5000, 10250, 4500, 8390, 4500, 8390, 5000, 10250),
        (2025, 500, 8000, 18250, 7000, 15390, 7000, 15390, 8000, 18250),
        (2025, 480, 10000, 28250, 9000, 24390, 9000, 24390, 10000, 28250),
        (2025, 450, 15000, 43250, 12000, 36390, 12000, 36390, 15000, 43250),
    ]
    c.executemany(
        'INSERT INTO score_distribution VALUES (?,?,?,?,?,?,?,?,?,?)', scores_data
    )

    # ── 院校信息（10列）──
    c.execute('''CREATE TABLE school_info (
        school_id INTEGER, school_name TEXT, school_tier TEXT,
        school_tier_label TEXT, is_985 INTEGER, is_211 INTEGER,
        is_syl INTEGER, num_phd INTEGER, num_master INTEGER,
        syl_disciplines TEXT, location TEXT,
        province_full TEXT, level TEXT, school_type TEXT, history TEXT
    )''')
    schools = [
        (1, '云岭大学', 'L5', '985', 1, 1, 1, 80, 150, '计算机科学与技术;材料科学', '昆明', '云南', '本科', '综合', ''),
        (2, '滇南理工大学', 'L8', '211', 0, 1, 0, 30, 80, '电气工程;机械工程', '昆明', '云南', '本科', '理工', ''),
        (3, '春城师范大学', 'L12', '省重点', 0, 0, 0, 5, 30, '', '昆明', '云南', '本科', '师范', ''),
        (4, '大理学院', 'L16', '公办本科', 0, 0, 0, 0, 10, '', '大理', '云南', '本科', '综合', ''),
        (5, '玉溪师范学院', 'L18', '公办本科', 0, 0, 0, 0, 5, '', '玉溪', '云南', '本科', '师范', ''),
    ]
    c.executemany(
        'INSERT INTO school_info VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', schools
    )

    # ── 专业目录（公开查询所需的最小字段集合）──
    c.execute('''CREATE TABLE major_catalog (
        major_name TEXT, major_class TEXT, major_class_code TEXT,
        schools TEXT, category TEXT, remark TEXT, tuition_year INTEGER,
        employment_note TEXT, further_study_note TEXT
    )''')
    majors = [
        ('计算机科学与技术', '计算机类', '0809', '', '工学', '', 6000, '', ''),
        ('软件工程', '计算机类', '0809', '', '工学', '', 6000, '', ''),
        ('人工智能', '计算机类', '0809', '', '工学', '', 6000, '', ''),
        ('电气工程及其自动化', '电气类', '0806', '', '工学', '', 5500, '', ''),
        ('自动化', '自动化类', '0808', '', '工学', '', 5500, '', ''),
        ('临床医学', '临床医学类', '1002', '', '医学', '', 6000, '', ''),
        ('汉语言文学', '中国语言文学类', '0501', '', '文学', '', 5000, '', ''),
        ('法学', '法学类', '0301', '', '法学', '', 5000, '', ''),
        ('会计学', '工商管理类', '1202', '', '管理学', '', 5000, '', ''),
        ('数学与应用数学', '数学类', '0701', '', '理学', '', 4500, '', ''),
        ('英语', '外国语言文学类', '0502', '', '文学', '', 4500, '', ''),
        ('土木工程', '土木类', '0810', '', '工学', '', 4500, '', ''),
        ('材料科学与工程', '材料类', '0804', '', '工学', '', 5000, '', ''),
        ('生物科学', '生物科学类', '0710', '', '理学', '', 4500, '', ''),
        ('药学', '药学类', '1007', '', '医学', '', 5500, '', ''),
    ]
    c.executemany('INSERT INTO major_catalog VALUES (?,?,?,?,?,?,?,?,?)', majors)

    # ── 2025年投档线（8列）──
    c.execute('''CREATE TABLE score_line_2025 (
        school_name TEXT, group_code TEXT, subject_type TEXT,
        subject_req TEXT, min_score INTEGER, min_rank INTEGER,
        batch TEXT, enroll_count INTEGER
    )''')
    score_lines = [
        ('云岭大学', '01', '物理', '物理+化学', 620, 6500, '本科批B段', 120),
        ('云岭大学', '02', '物理', '物理', 610, 8000, '本科批B段', 80),
        ('滇南理工大学', '01', '物理', '物理+化学', 580, 12000, '本科批B段', 150),
        ('滇南理工大学', '02', '物理', '物理', 570, 15000, '本科批B段', 100),
        ('滇南理工大学', '03', '物理', '不限', 560, 18000, '本科批B段', 60),
        ('春城师范大学', '01', '物理', '物理+化学', 530, 30000, '本科批B段', 200),
        ('春城师范大学', '02', '物理', '不限', 510, 42000, '本科批B段', 180),
        ('大理学院', '01', '物理', '物理', 480, 60000, '本科批B段', 300),
        ('大理学院', '02', '物理', '不限', 460, 75000, '本科批B段', 250),
        ('玉溪师范学院', '01', '物理', '不限', 440, 90000, '本科批B段', 400),
        ('云岭大学', '11', '历史', '不限', 610, 3500, '本科批B段', 60),
        ('滇南理工大学', '11', '历史', '不限', 570, 8000, '本科批B段', 80),
        ('春城师范大学', '11', '历史', '不限', 530, 18000, '本科批B段', 150),
        ('大理学院', '11', '历史', '不限', 490, 35000, '本科批B段', 200),
    ]
    c.executemany(
        'INSERT INTO score_line_2025 VALUES (?,?,?,?,?,?,?,?)', score_lines
    )

    # ── 2024年投档线（5列）──
    c.execute('''CREATE TABLE score_line_2024 (
        school_name TEXT, subject_type TEXT,
        min_score_orig INTEGER, min_rank INTEGER, batch TEXT
    )''')
    score_lines_24 = [
        ('云岭大学', '理科', 625, 6200, '一本'),
        ('云岭大学', '文科', 615, 3200, '一本'),
        ('滇南理工大学', '理科', 585, 11500, '一本'),
        ('滇南理工大学', '文科', 575, 7500, '一本'),
        ('春城师范大学', '理科', 535, 29000, '一本'),
        ('春城师范大学', '文科', 535, 17000, '一本'),
        ('大理学院', '理科', 485, 58000, '二本'),
        ('大理学院', '文科', 495, 33000, '二本'),
        ('玉溪师范学院', '理科', 445, 88000, '二本'),
    ]
    c.executemany(
        'INSERT INTO score_line_2024 VALUES (?,?,?,?,?)', score_lines_24
    )

    # ── 历史录取明细（10列）+ 视图 ──
    c.execute('''CREATE TABLE enroll_detail (
        year INTEGER, school_name TEXT, major_name TEXT,
        subject_type TEXT, min_score INTEGER, min_rank INTEGER,
        enroll_count INTEGER, batch TEXT, batch_tier TEXT,
        tuition INTEGER
    )''')
    c.execute('''CREATE VIEW v_enroll_detail AS
        SELECT e.*, m.category, m.major_class
        FROM enroll_detail e
        LEFT JOIN major_catalog m ON e.major_name = m.major_name
    ''')

    enroll_data = [
        (2025, '云岭大学', '计算机科学与技术', '物理', 625, 6000, 80, '本科批B段', '本科', 6000),
        (2025, '云岭大学', '软件工程', '物理', 620, 7000, 60, '本科批B段', '本科', 6000),
        (2025, '云岭大学', '人工智能', '物理', 615, 7800, 40, '本科批B段', '本科', 6000),
        (2025, '云岭大学', '汉语言文学', '历史', 612, 3400, 30, '本科批B段', '本科', 5000),
        (2025, '滇南理工大学', '电气工程及其自动化', '物理', 585, 11000, 100, '本科批B段', '本科', 5500),
        (2025, '滇南理工大学', '自动化', '物理', 575, 13500, 80, '本科批B段', '本科', 5500),
        (2025, '滇南理工大学', '计算机科学与技术', '物理', 590, 10000, 60, '本科批B段', '本科', 5500),
        (2025, '春城师范大学', '数学与应用数学', '物理', 535, 28000, 50, '本科批B段', '本科', 4500),
        (2025, '春城师范大学', '汉语言文学', '物理', 525, 34000, 40, '本科批B段', '本科', 4500),
        (2025, '春城师范大学', '英语', '历史', 530, 17500, 60, '本科批B段', '本科', 4500),
        (2025, '大理学院', '土木工程', '物理', 485, 58000, 80, '本科批B段', '本科', 4500),
        (2025, '大理学院', '汉语言文学', '历史', 488, 34500, 50, '本科批B段', '本科', 4000),
        (2025, '玉溪师范学院', '会计学', '物理', 445, 87000, 50, '本科批B段', '本科', 4000),
        (2024, '云岭大学', '计算机科学与技术', '理科', 630, 5800, 75, '一本', '本科', 6000),
        (2024, '云岭大学', '软件工程', '理科', 625, 6800, 55, '一本', '本科', 6000),
        (2024, '云岭大学', '汉语言文学', '文科', 618, 3100, 28, '一本', '本科', 5000),
        (2024, '滇南理工大学', '电气工程及其自动化', '理科', 590, 10500, 95, '一本', '本科', 5500),
        (2024, '滇南理工大学', '计算机科学与技术', '理科', 595, 9500, 55, '一本', '本科', 5500),
        (2024, '春城师范大学', '数学与应用数学', '理科', 540, 27000, 45, '一本', '本科', 4500),
        (2024, '大理学院', '土木工程', '理科', 490, 56000, 75, '二本', '本科', 4500),
        (2023, '云岭大学', '计算机科学与技术', '理科', 635, 5500, 70, '一本', '本科', 6000),
        (2023, '滇南理工大学', '电气工程及其自动化', '理科', 595, 10000, 90, '一本', '本科', 5500),
    ]
    c.executemany(
        'INSERT INTO enroll_detail VALUES (?,?,?,?,?,?,?,?,?,?)', enroll_data
    )

    # ── 招生计划（7列）──
    c.execute('''CREATE TABLE enroll_plan_2025 (
        school_name TEXT, category TEXT, sp_name TEXT,
        subject_group TEXT, subject_req TEXT, batch TEXT,
        num INTEGER
    )''')
    plan_data = [
        ('云岭大学', '物理类', '计算机科学与技术', '01专业组', '物理+化学', '本科批B段', 80),
        ('云岭大学', '物理类', '软件工程', '01专业组', '物理+化学', '本科批B段', 60),
        ('云岭大学', '物理类', '人工智能', '01专业组', '物理+化学', '本科批B段', 40),
        ('云岭大学', '物理类', '数学与应用数学', '02专业组', '物理', '本科批B段', 30),
        ('云岭大学', '历史类', '汉语言文学', '11专业组', '不限', '本科批B段', 30),
        ('云岭大学', '历史类', '法学', '11专业组', '不限', '本科批B段', 25),
        ('滇南理工大学', '物理类', '电气工程及其自动化', '01专业组', '物理+化学', '本科批B段', 100),
        ('滇南理工大学', '物理类', '自动化', '01专业组', '物理+化学', '本科批B段', 80),
        ('滇南理工大学', '物理类', '计算机科学与技术', '01专业组', '物理+化学', '本科批B段', 60),
        ('滇南理工大学', '物理类', '会计学', '03专业组', '不限', '本科批B段', 40),
        ('滇南理工大学', '历史类', '会计学', '11专业组', '不限', '本科批B段', 30),
        ('春城师范大学', '物理类', '数学与应用数学', '01专业组', '物理+化学', '本科批B段', 50),
        ('春城师范大学', '物理类', '汉语言文学', '02专业组', '不限', '本科批B段', 40),
        ('春城师范大学', '物理类', '英语', '02专业组', '不限', '本科批B段', 30),
        ('春城师范大学', '历史类', '英语', '11专业组', '不限', '本科批B段', 40),
        ('春城师范大学', '历史类', '汉语言文学', '11专业组', '不限', '本科批B段', 50),
        ('大理学院', '物理类', '土木工程', '01专业组', '物理', '本科批B段', 80),
        ('大理学院', '物理类', '会计学', '02专业组', '不限', '本科批B段', 40),
        ('大理学院', '历史类', '汉语言文学', '11专业组', '不限', '本科批B段', 50),
        ('玉溪师范学院', '物理类', '会计学', '01专业组', '不限', '本科批B段', 50),
    ]
    c.executemany(
        'INSERT INTO enroll_plan_2025 VALUES (?,?,?,?,?,?,?)', plan_data
    )

    # ── 就业统计（3列）──
    c.execute('''CREATE TABLE major_employment_stats (
        major_name TEXT, employment_rate REAL, avg_salary_monthly REAL
    )''')
    emp_data = [
        ('计算机科学与技术', 0.94, 12000),
        ('软件工程', 0.93, 11500),
        ('人工智能', 0.95, 13500),
        ('电气工程及其自动化', 0.91, 9000),
        ('自动化', 0.89, 8500),
        ('汉语言文学', 0.82, 6000),
        ('法学', 0.78, 6500),
        ('会计学', 0.87, 7000),
        ('数学与应用数学', 0.85, 8000),
        ('英语', 0.80, 6000),
    ]
    c.executemany(
        'INSERT INTO major_employment_stats VALUES (?,?,?)', emp_data
    )

    # ── 专业撤销统计（4列）──
    c.execute('''CREATE TABLE major_revocation_stats (
        major_name TEXT, year INTEGER, revoke_count INTEGER,
        note TEXT
    )''')

    # 热门专业分析的可选外部映射；示例库不伪造 WEF 数据，但保留空 schema，
    # 让缺少真实外部数据明确表现为“无加分”，而不是运行告警。
    c.execute('''CREATE TABLE wef_occupation_mapping (
        wef_role_name TEXT, growth_rate_2030 REAL,
        mapped_major_classes TEXT, confidence REAL, wef_role_type TEXT
    )''')

    # 内容级来源标记：复制或改名数据库后仍必须被识别为合成示例数据。
    c.execute('''CREATE TABLE opengaokao_dataset_metadata (
        key TEXT PRIMARY KEY, value TEXT NOT NULL
    )''')
    c.executemany(
        'INSERT INTO opengaokao_dataset_metadata VALUES (?, ?)',
        [
            ('data_kind', 'synthetic_example'),
            ('dataset_id', 'opengaokao.synthetic-example.v1'),
            ('generator', 'data/generate_example_db.py'),
        ],
    )

    # 即使单独查看 SQL 结果，也必须能识别为示例数据，避免虚构记录冒充真实院校数据。
    for table in (
        'school_info', 'score_line_2025', 'score_line_2024',
        'enroll_detail', 'enroll_plan_2025',
    ):
        c.execute(f"UPDATE {table} SET school_name = '示例·' || school_name")

    conn.commit()
    conn.close()
    print(f'[OK] 示例数据库已生成: {DB_PATH}')
    total_tables = 11
    total_rows = (
        len(scores_data) + len(schools) + len(majors)
        + len(score_lines) + len(score_lines_24)
        + len(enroll_data) + len(plan_data) + len(emp_data)
    )
    print(f'     {total_tables} 张表, 约 {total_rows} 行数据')
    print(f'     5所学校, 15个专业, 物理类/历史类均覆盖')


if __name__ == '__main__':
    create_example_db()
