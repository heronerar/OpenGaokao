# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
投考禁忌项校验模块 (Constraint Checker)
基于《普通高等学校招生体检工作指导意见》体检代码11-39

功能:
1. 硬性过滤：不予录取类（代码11-16）→ 过滤所有专业
2. 专业限制：限制录取类（代码21-26）→ 过滤受限专业
3. 软性提示：不宜就读类（代码31-39）→ 标记"不建议报考"
4. 军警校专项校验：政审+体检+年龄+政治面貌
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ── 不予录取类（代码11-16）───
# 系统自动过滤所有专业

CONTRAINDICATION_ALL = {
    '11': {'name': '严重心脏病、心肌病、高血压病', 'action': 'all_filter'},
    '12': {'name': '重症支气管扩张、哮喘、恶性肿瘤、慢性肾炎、尿毒症', 'action': 'all_filter'},
    '13': {'name': '严重血液、内分泌及代谢系统疾病、风湿性疾病', 'action': 'all_filter'},
    '14': {'name': '重症或难治性癫痫、严重精神病未治愈', 'action': 'all_filter'},
    '15': {'name': '慢性肝炎且肝功能不正常', 'action': 'all_filter'},
    '16': {'name': '结核病（除治愈情况外）', 'action': 'all_filter'},
}

# ── 限制录取类（代码21-26）───
# 系统过滤对应受限专业

CONTRAINDICATION_RESTRICTED = {
    '21': {
        'name': '色弱',
        'restricted_majors': ['化学类', '药学类', '生物科学类', '公安技术类', '地质学类',
                              '材料类', '环境类', '食品类', '医学类', '农学类'],
    },
    '22': {
        'name': '色盲',
        'restricted_majors': ['天文学', '摄影', '交通运输', '化学类', '生物学类',
                              '医学类', '美术', '艺术设计', '心理学'],
    },
    '23': {
        'name': '不能准确识别颜色',
        'restricted_majors': ['经济学类', '计算机科学与技术', '管理学类',
                              '工商管理', '行政管理'],
    },
    '24': {
        'name': '裸眼视力<5.0',
        'restricted_majors': ['飞行技术', '航海技术', '消防工程', '刑事科学技术'],
    },
    '25': {
        'name': '裸眼视力<4.8',
        'restricted_majors': ['轮机工程', '民族传统体育', '体育教育'],
    },
    '26': {
        'name': '公安类要求综合不达标',
        'restricted_majors': ['公安学类', '公安技术类'],
    },
}

# ── 不宜就读类（代码31-39）───
# 系统提示"不建议报考"，允许填报

NOT_RECOMMENDED = {
    '31': {
        'name': '主要脏器手术后或有相关病史',
        'not_recommended_majors': ['地矿类', '水利类', '交通运输类'],
    },
    '34': {
        'name': '矫正视力>400度',
        'not_recommended_majors': ['海洋技术', '核工程', '生物医学工程'],
    },
    '35': {
        'name': '矫正视力>800度',
        'not_recommended_majors': ['地矿类', '医学类', '法学类', '工学类'],
    },
    '37': {
        'name': '听力障碍',
        'not_recommended_majors': ['法学', '外语', '新闻学', '教育学', '播音主持'],
    },
    '39': {
        'name': '斜视、嗅觉迟钝、口吃',
        'not_recommended_majors': ['医学类', '药学', '护理学'],
    },
}

# ── 警校体检标准（PRD §2.5.3）───

POLICE_ACADEMY_STANDARDS = {
    'male_height_min': 170,
    'male_special_height_min': 175,
    'female_height_min': 160,
    'male_bmi_min': 17.3,
    'male_bmi_max': 27.3,
    'female_bmi_min': 17.1,
    'female_bmi_max': 25.7,
    'vision_min': 4.8,
    'tech_vision_min': 4.9,
    'forbidden': ['纹身', '斜视>15度', '色盲', '色弱'],
}

# ── 军校报考条件 ──

MILITARY_ACADEMY_STANDARDS = {
    'age_min': 17,
    'age_max': 20,
    'political_status_required': ['中共党员', '共青团员'],
    'political_review_scope': '考生本人 + 直系亲属及主要社会关系',
}

# ── 政治面貌限制院校 ──

POLITICAL_RESTRICTED_SCHOOLS = [
    '北京电子科技学院',
    '国防科技大学',
    '陆军工程大学',
    '空军军医大学',
    '海军军医大学',
    '陆军军医大学',
]

# ── 军警校受限专业（需综合判定）───

POLICE_RESTRICTED_MAJORS = ['公安学类', '公安技术类', '侦查学', '治安学', '刑事科学技术']
MILITARY_RESTRICTED_MAJORS = []  # 军校按院校维度校验，不在专业维度过滤


@dataclass
class ConstraintCheckResult:
    """禁忌项校验结果"""
    hard_filtered: bool  # 是否被硬性过滤（代码11-16）
    filtered_majors: List[str] = field(default_factory=list)  # 被过滤的专业
    warnings: List[str] = field(default_factory=list)  # 软性提示
    police_qualified: bool = True  # 警校报考资格
    military_qualified: bool = True  # 军校报考资格
    detailed_checks: Dict = field(default_factory=dict)
    # AUDIT-P0-010: 未成年人保护标记，下游报告生成可据此追加"监护人参与"提示
    is_minor: bool = False  # 是否为未成年考生（基于 q3_birth 推算）
    guardian_consent: bool = False  # 监护人是否已确认同意


def check_constraints(answers: Dict) -> ConstraintCheckResult:
    """
    投考禁忌项校验入口

    参数:
        answers: 问卷答案字典，包含以下键:
            exam_codes: 体检受限代码列表，如 ["21", "22"]
            left_eye_vision: 左眼裸眼视力
            right_eye_vision: 右眼裸眼视力
            color_vision: 色觉状态 (正常/色弱/色盲/颜色识别障碍)
            height: 身高cm
            weight: 体重kg
            tattoo: 是否有纹身 (bool)
            corrected_vision_degree: 矫正视力度数
            criminal_record: 有无犯罪记录 (bool)
            political_status: 政治面貌 (中共党员/共青团员/群众)
            foreign_language: 高考外语语种 (英语/日语/俄语等)
            birth_date: 出生日期 YYYY-MM-DD
            ethnicity: 民族
            birthplace: 生源地

    返回:
        ConstraintCheckResult
    """
    result = ConstraintCheckResult(hard_filtered=False)

    # AUDIT-P0-010: 未成年人保护标记（沿用 questionnaire_parser 的 birth → age 推算逻辑）
    # 若 answers 已携带 parser 的判定结果（is_minor / guardian_consent），优先采用；
    # 否则做一次轻量级本地推算，避免 constraint_checker 单独被调用时漏标未成年。
    _is_minor = bool(answers.get('is_minor', False))
    _consent = bool(answers.get('guardian_consent', False))
    if not _is_minor:
        birth_raw = (
            answers.get('birth_date')
            or answers.get('q3_birth')
            or answers.get('birth')
        )
        if birth_raw and isinstance(birth_raw, str):
            try:
                s = birth_raw.strip().replace('/', '-')
                if s.isdigit() and len(s) == 8:
                    s = f'{s[:4]}-{s[4:6]}-{s[6:8]}'
                parts = s.split('-')
                by = int(parts[0])
                bm = int(parts[1]) if len(parts) > 1 else 1
                bd = int(parts[2]) if len(parts) > 2 else 1
                # 与 parser 一致：高考首日 6/7 为年龄基准
                ref_year = int(answers.get('gaokao_year') or 2026)
                _age = ref_year - by
                if (6, 7) < (bm, bd):
                    _age -= 1
                if 0 < _age < 18:
                    _is_minor = True
            except (ValueError, IndexError, TypeError):
                pass
    result.is_minor = _is_minor
    result.guardian_consent = _consent
    if _is_minor:
        if not _consent:
            result.warnings.append(
                '⚠️ 未成年考生：需监护人同意方可生成完整推荐方案（隐私政策第7节）'
            )
        else:
            result.warnings.append(
                'ℹ️ 未成年考生（已获监护人同意）：报告将默认附加监护人参与提示'
            )

    # ── 0. 体检数据缺失兜底（防 None 与数值比较崩溃） ──
    # 设计原则：若体检字段缺失/None/无效，不做该项判定（不假设合格也不假设不合格），
    # 同时显式记录 warning，让上层与交付物明确告知"该项未校验"。
    _missing_health = []

    def _coerce_vision(v, label):
        """裸眼视力归一化为 float；None/空/不可解析 → 返回 None 并记录缺失"""
        if v is None or v == '':
            _missing_health.append(label)
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            _missing_health.append(label)
            return None

    def _coerce_int(v, label):
        if v is None or v == '':
            _missing_health.append(label)
            return None
        try:
            return int(float(v))
        except (ValueError, TypeError):
            _missing_health.append(label)
            return None

    answers = dict(answers)  # 不修改调用方
    answers['left_eye_vision'] = _coerce_vision(answers.get('left_eye_vision'), '左眼视力')
    answers['right_eye_vision'] = _coerce_vision(answers.get('right_eye_vision'), '右眼视力')
    answers['height'] = _coerce_int(answers.get('height'), '身高')
    answers['weight'] = _coerce_int(answers.get('weight'), '体重')
    cd = answers.get('corrected_vision_degree')
    answers['corrected_vision_degree'] = _coerce_int(cd, '矫正度数') or 0
    if answers.get('color_vision') in (None, ''):
        answers['color_vision'] = ''  # 不假设"正常"
        _missing_health.append('色觉')

    # ── 1. 体检代码11-16（不予录取）───
    exam_codes = answers.get('exam_codes', [])
    for code in exam_codes:
        if code in CONTRAINDICATION_ALL:
            result.hard_filtered = True
            result.warnings.append(f'⚠️ 体检代码{code}：{CONTRAINDICATION_ALL[code]["name"]} — 不予录取')

    if result.hard_filtered:
        result.detailed_checks['all_filter_codes'] = exam_codes
        return result

    # ── 2. 体检代码21-26（限制录取）───
    filtered_majors = []
    for code in exam_codes:
        if code in CONTRAINDICATION_RESTRICTED:
            info = CONTRAINDICATION_RESTRICTED[code]
            filtered_majors.extend(info['restricted_majors'])
            result.warnings.append(f'⛔ 体检代码{code}（{info["name"]}）— 受限专业已过滤')

    # ── 3. 色觉专项（问卷色觉字段 → 代码映射）───
    # 缺失视为未校验，不做受限专业过滤（避免误伤）；warning 在末尾统一汇总
    color_vision = answers.get('color_vision') or ''
    if color_vision == '色弱' and '21' not in exam_codes:
        filtered_majors.extend(CONTRAINDICATION_RESTRICTED['21']['restricted_majors'])
        result.warnings.append('⛔ 色弱 — 化学类/药学类/生物科学类等受限专业已过滤')
    elif color_vision == '色盲' and '22' not in exam_codes:
        filtered_majors.extend(CONTRAINDICATION_RESTRICTED['22']['restricted_majors'])
        result.warnings.append('⛔ 色盲 — 天文学/摄影/交通运输等受限专业已过滤')
    elif color_vision == '颜色识别障碍' and '23' not in exam_codes:
        filtered_majors.extend(CONTRAINDICATION_RESTRICTED['23']['restricted_majors'])
        result.warnings.append('⛔ 颜色识别障碍 — 经济学类/计算机等受限专业已过滤')

    # ── 4. 视力专项（仅在两眼数据都齐全时校验，否则归入未校验项） ──
    left_vision = answers.get('left_eye_vision')
    right_vision = answers.get('right_eye_vision')
    if left_vision is not None and right_vision is not None:
        if left_vision < 5.0 or right_vision < 5.0:
            filtered_majors.extend(CONTRAINDICATION_RESTRICTED['24']['restricted_majors'])
            result.warnings.append(f'⛔ 裸眼视力（左{left_vision}/右{right_vision}）<5.0 — 飞行技术/航海技术等受限')
        if left_vision < 4.8 or right_vision < 4.8:
            filtered_majors.extend(CONTRAINDICATION_RESTRICTED['25']['restricted_majors'])
            result.warnings.append(f'⛔ 裸眼视力（左{left_vision}/右{right_vision}）<4.8 — 轮机工程/体育教育等受限')

    # ── 5. 矫正视力 ──
    corrected_degree = answers.get('corrected_vision_degree') or 0
    if corrected_degree > 800:
        for m in NOT_RECOMMENDED['35']['not_recommended_majors']:
            if m not in filtered_majors:
                result.warnings.append(f'⚠️ 矫正视力{corrected_degree}度>800度 — 不建议报考{m}类专业')
    elif corrected_degree > 400:
        for m in NOT_RECOMMENDED['34']['not_recommended_majors']:
            if m not in filtered_majors:
                result.warnings.append(f'⚠️ 矫正视力{corrected_degree}度>400度 — 不建议报考{m}')

    # ── 6. 纹身 ──
    if answers.get('tattoo', False):
        result.warnings.append('⛔ 存在纹身 — 警校/军校报考受限')
        result.police_qualified = False
        result.military_qualified = False

    # ── 7. 警校资格校验 ──
    _check_police_qualified(result, answers)

    # ── 8. 军校资格校验 ──
    _check_military_qualified(result, answers)

    # ── 9. 政审 ──
    if answers.get('criminal_record', False):
        result.police_qualified = False
        result.military_qualified = False
        result.warnings.append('⛔ 有犯罪记录 — 警校/军校政审不合格')

    # ── 10. 政治面貌 ──
    political_status = answers.get('political_status', '')
    if political_status not in ('中共党员', '共青团员'):
        result.warnings.append(
            f'⚠️ 政治面貌（{political_status}）— '
            f'以下6所军校需党员/团员身份：{"/".join(POLITICAL_RESTRICTED_SCHOOLS[:3])}等'
        )

    # ── 11. 外语语种 ──
    foreign_lang = answers.get('foreign_language', '')
    if foreign_lang and foreign_lang != '英语':
        result.warnings.append(f'💡 高考外语语种为{foreign_lang}，部分专业可能仅招收英语考生')

    # ── 12. 单科成绩校验（PPT策略：单科不达标风险提示）───
    _check_single_subject_scores(result, answers)

    # ── 汇总去重 ──
    result.filtered_majors = list(dict.fromkeys(filtered_majors))

    # ── 缺失项明示（不静默跳过，让上层/报告可见） ──
    if _missing_health:
        missing_unique = list(dict.fromkeys(_missing_health))
        result.warnings.append(
            f'ℹ️ 体检数据未填写：{", ".join(missing_unique)} — 相关限制未完全校验，'
            f'报考前请自行确认《普通高等学校招生体检工作指导意见》对应条款。'
        )

    return result


# ── 单科成绩要求映射（常见专业单科门槛）───
SINGLE_SUBJECT_REQUIREMENTS = {
    '英语': {
        'threshold': 110,
        'restricted_majors': ['外国语言文学', '英语', '翻译', '国际经济与贸易',
                              '商务英语', '旅游管理'],
        'warning': '英语单科成绩低于110分，部分外语/国际贸易类专业可能有单科要求',
    },
    '数学': {
        'threshold': 110,
        'restricted_majors': ['数学与应用数学', '统计学', '金融工程', '数据科学',
                              '信息与计算科学'],
        'warning': '数学单科成绩低于110分，部分数学/统计/金融类专业可能有单科要求',
    },
    '语文': {
        'threshold': 110,
        'restricted_majors': ['汉语言文学', '新闻传播学', '广告学'],
        'warning': '语文单科成绩低于110分，部分中文/新闻类专业可能有单科要求',
    },
}


def _check_single_subject_scores(result: ConstraintCheckResult, answers: Dict) -> None:
    """单科成绩校验（PPT策略：关注单科成绩不达标风险）"""
    for subject, config in SINGLE_SUBJECT_REQUIREMENTS.items():
        score = answers.get(f'{subject.lower()}_score')
        if score is not None and score < config['threshold']:
            result.warnings.append(
                f'⚠️ {subject}单科{score}分<{config["threshold"]}分 — {config["warning"]}'
            )


def _check_police_qualified(result: ConstraintCheckResult, answers: Dict) -> None:
    """警校报考资格校验（缺失项只跳过该项判定，不假设合格/不合格）"""
    gender = answers.get('gender', '男')
    height = answers.get('height')          # 可能为 None（未填）
    weight = answers.get('weight')
    left_vision = answers.get('left_eye_vision')
    right_vision = answers.get('right_eye_vision')
    color_vision = answers.get('color_vision') or ''
    tattoo = answers.get('tattoo', False)

    # 身高
    if height is not None:
        height_min = POLICE_ACADEMY_STANDARDS['female_height_min'] if gender == '女' else POLICE_ACADEMY_STANDARDS['male_height_min']
        if height < height_min:
            result.police_qualified = False
            result.warnings.append(f'⛔ 身高{height}cm < 警校要求{height_min}cm — 警校资格不合格')

    # BMI（身高+体重都齐全才算）
    if height is not None and weight is not None and height > 0:
        bmi = weight / ((height / 100) ** 2)
        bmi_min = POLICE_ACADEMY_STANDARDS['female_bmi_min'] if gender == '女' else POLICE_ACADEMY_STANDARDS['male_bmi_min']
        bmi_max = POLICE_ACADEMY_STANDARDS['female_bmi_max'] if gender == '女' else POLICE_ACADEMY_STANDARDS['male_bmi_max']
        if bmi < bmi_min or bmi > bmi_max:
            result.police_qualified = False
            result.warnings.append(f'⛔ BMI={bmi:.1f}（{bmi_min}-{bmi_max}）— 警校体格不合格')

    # 视力
    min_vision = POLICE_ACADEMY_STANDARDS['vision_min']
    if left_vision is not None and right_vision is not None:
        if left_vision < min_vision or right_vision < min_vision:
            result.police_qualified = False
            result.warnings.append(f'⛔ 裸眼视力不足{min_vision} — 警校资格不合格')

    # 色觉（缺失就不判定）
    if color_vision in ('色盲', '色弱'):
        result.police_qualified = False
        result.warnings.append(f'⛔ 色觉异常（{color_vision}）— 警校资格不合格')


def _check_military_qualified(result: ConstraintCheckResult, answers: Dict) -> None:
    """军校报考资格校验"""
    birth_date = answers.get('birth_date', '')
    if not birth_date:
        return

    try:
        from datetime import datetime
        birth = datetime.strptime(birth_date, '%Y-%m-%d')
        today = datetime(2026, 9, 1)  # 假设2026年9月入学
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))

        age_min = MILITARY_ACADEMY_STANDARDS['age_min']
        age_max = MILITARY_ACADEMY_STANDARDS['age_max']
        if age < age_min or age > age_max:
            result.military_qualified = False
            result.warnings.append(
                f'⛔ 年龄{age}岁（{age_min}-{age_max}岁）— 军校资格不合格'
            )
    except (ValueError, TypeError):
        pass


# ── 问卷字段映射（AUDIT-P0-012）───
#
# 本文件早期使用 q88-q101 编号作为问卷字段，但实际问卷 JSON
# （questionnaire/volunteer_survey_*.json）使用 q9_color_vision /
# q10_vision / q11c_height 等命名。两套体系并存导致 14 项禁忌校验静默
# 失效（answers dict 找不到 q88-q101 字段就跳过校验）。
#
# 现修正为：
# 1. 将"问卷 JSON 字段名 → constraint_checker 期望的 answers key"映射集中在此，
#    供 questionnaire_parser / matching_engine 在构造 answers dict 时参考；
# 2. 不再使用 q88-q101 编号——它们从未出现在真实问卷中。

# 问卷 JSON 实际字段 → check_constraints answers 期望 key
QUESTIONNAIRE_FIELD_MAP = {
    # 基本信息
    'q3_birth': 'birth_date',
    'q4_ethnicity': 'ethnicity',
    'q8c_political_status': 'political_status',
    # 身体健康
    'q9_color_vision': 'color_vision',
    'q10_vision': 'vision',  # 单值视力，构造 answers 时同步赋给 left/right
    'q11_hearing': 'hearing',
    'q11b_smell': 'smell',
    'q11c_height': 'height',
    'q11d_weight': 'weight',
    'q11e_tattoo': 'tattoo',
    # 高考情况
    'q16_foreign_language': 'foreign_language',
    # 家庭背景
    'q41a_criminal_record': 'criminal_record',
}


def build_answers_from_questionnaire_json(raw: Dict) -> Dict:
    """便捷工具：将原始问卷 JSON answers 转成 check_constraints 期望的 answers dict。

    matching_engine._build_constraint_answers 是生产路径（带 questionnaire 对象），
    本函数用于：测试场景、命令行批处理、第三方集成。
    """
    out: Dict = {}
    for json_key, target_key in QUESTIONNAIRE_FIELD_MAP.items():
        if json_key not in raw:
            continue
        val = raw[json_key]
        if target_key == 'vision':
            # 单视力字段同步左右眼
            try:
                v = float(val)
                out['left_eye_vision'] = v
                out['right_eye_vision'] = v
            except (ValueError, TypeError):
                pass
        elif target_key == 'tattoo':
            out['tattoo'] = str(val).strip() in (
                '有', '是', 'yes', 'Yes', 'True', 'true', '1',
            )
        elif target_key == 'criminal_record':
            out['criminal_record'] = str(val).strip() in (
                '有', '是', 'yes', 'Yes', 'True', 'true', '1',
            )
        else:
            out[target_key] = val
    return out


if __name__ == '__main__':
    # 测试用例1：色弱
    test1 = {
        'gender': '男',
        'exam_codes': [],
        'color_vision': '色弱',
        'left_eye_vision': 5.0,
        'right_eye_vision': 5.1,
        'height': 175,
        'weight': 65,
        'tattoo': False,
        'corrected_vision_degree': 350,
        'criminal_record': False,
        'political_status': '共青团员',
        'foreign_language': '英语',
        'birth_date': '2007-05-15',
        'ethnicity': '汉族',
        'birthplace': '云南省昆明市',
    }

    result1 = check_constraints(test1)
    print('=== 色弱测试 ===')
    print(f'硬性过滤: {result1.hard_filtered}')
    print(f'受限专业: {result1.filtered_majors[:5]}')
    print(f'警校资格: {result1.police_qualified}')
    print(f'军校资格: {result1.military_qualified}')
    print(f'提示: {result1.warnings}')
    print()

    # 测试用例2：严重心脏病
    test2 = {
        'gender': '男',
        'exam_codes': ['11'],
        'color_vision': '正常',
        'left_eye_vision': 5.0,
        'right_eye_vision': 5.0,
        'height': 170,
        'weight': 60,
        'tattoo': False,
        'corrected_vision_degree': 0,
        'criminal_record': False,
        'political_status': '共青团员',
        'foreign_language': '英语',
        'birth_date': '2007-03-20',
        'ethnicity': '汉族',
        'birthplace': '云南省大理州',
    }

    result2 = check_constraints(test2)
    print('=== 严重心脏病测试 ===')
    print(f'硬性过滤: {result2.hard_filtered}')
    print(f'提示: {result2.warnings}')
    print()

    # 测试用例3：警校资格
    test3 = {
        'gender': '女',
        'exam_codes': ['21'],
        'color_vision': '色弱',
        'left_eye_vision': 4.6,
        'right_eye_vision': 4.7,
        'height': 158,
        'weight': 50,
        'tattoo': True,
        'corrected_vision_degree': 500,
        'criminal_record': False,
        'political_status': '共青团员',
        'foreign_language': '英语',
        'birth_date': '2007-08-10',
        'ethnicity': '白族',
        'birthplace': '云南省大理州',
    }

    result3 = check_constraints(test3)
    print('=== 警校资格测试（多项不合格）===')
    print(f'硬性过滤: {result3.hard_filtered}')
    print(f'警校资格: {result3.police_qualified}')
    print(f'军校资格: {result3.military_qualified}')
    print(f'提示: {result3.warnings}')
