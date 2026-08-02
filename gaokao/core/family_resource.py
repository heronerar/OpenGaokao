# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
家庭资源评估模块 (Family Resource Assessment)
基于布迪厄三形式资本理论：经济资本 + 文化资本 + 社会资本

输入: 12题结构化问卷数据
输出: 家庭就业支持能力评级（高/中/低）+ 资源匹配建议
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


# ── 十大职业阶层分类（PRD §2.4.3）───

OCCUPATION_CLASSES = {
    1: {
        'name': '国家与社会管理者',
        'examples': '政府官员、公务员、事业单位领导',
        'employment_help': 5,
        'help_label': '体制内就业内推',
    },
    2: {
        'name': '经理人员',
        'examples': '企业老总、中高层管理干部',
        'employment_help': 4,
        'help_label': '企业内部推荐',
    },
    3: {
        'name': '私营企业主',
        'examples': '企业创办人、经营者',
        'employment_help': 4,
        'help_label': '自有企业就业/创业资金',
    },
    4: {
        'name': '专业技术人员',
        'examples': '医生、律师、教师、工程师、科研人员',
        'employment_help': 4,
        'help_label': '行业内推',
    },
    5: {
        'name': '办事人员',
        'examples': '办公室文员、行政助理、基层公务员',
        'employment_help': 3,
        'help_label': '基层岗位信息',
    },
    6: {
        'name': '个体工商户',
        'examples': '小商贩、个体经营者、零售餐饮服务',
        'employment_help': 3,
        'help_label': '小规模商业资源',
    },
    7: {
        'name': '商业服务人员',
        'examples': '售货员、服务员、保安、快递员',
        'employment_help': 2,
        'help_label': '有限基层信息',
    },
    8: {
        'name': '产业工人',
        'examples': '制造业操作工、建筑工人',
        'employment_help': 2,
        'help_label': '技术工岗位信息',
    },
    9: {
        'name': '农业劳动者',
        'examples': '种植户、养殖户',
        'employment_help': 2,
        'help_label': '有限农业资源',
    },
    10: {
        'name': '新的社会阶层',
        'examples': '网络主播、自由职业者、新媒体从业人员',
        'employment_help': 3,
        'help_label': '新兴行业渠道',
    },
}

# ── 五等份收入分组（PRD §2.4.4）───

INCOME_GROUPS = {
    1: {'name': '高收入组', 'range': '最高20%', 'resource': '充足就业资源支持、实习机会购买', 'score': 5},
    2: {'name': '中间偏上收入组', 'range': '次高20%', 'resource': '较好就业支持、适度资源购买', 'score': 4},
    3: {'name': '中间收入组', 'range': '中间20%', 'resource': '基础就业支持、有限资源购买', 'score': 3},
    4: {'name': '中间偏下收入组', 'range': '次低20%', 'resource': '基本就业指导、资源购买受限', 'score': 2},
    5: {'name': '低收入组', 'range': '最低20%', 'resource': '就业资源支持不足、依赖个人努力', 'score': 1},
}

# ── 学历评分 ──

EDUCATION_SCORES = {
    '硕士及以上': 5,
    '本科': 4,
    '大专': 3,
    '高中': 2,
    '初中及以下': 1,
}

# ── 行业背景映射 ──

INDUSTRY_NETWORKS = {
    '体制内': ['公务员', '事业单位', '国企'],
    '企业': ['民企', '外企', '合资'],
    '自由职业': ['个体经营', '自由撰稿', '独立顾问'],
    '农业': ['种植', '养殖', '农产品'],
    '新兴行业': ['互联网', '新媒体', '电商'],
}


@dataclass
class FamilyResourceResult:
    """家庭资源评估结果"""
    rating: str  # '高' / '中' / '低'
    economic_capital: float  # 经济资本得分 (0-100)
    cultural_capital: float  # 文化资本得分 (0-100)
    social_capital: float  # 社会资本得分 (0-100)
    total_score: float  # 综合得分 (0-100)
    details: Dict  # 详细评估数据
    suggestions: List[str]  # 专业选择建议


def assess_family_resource(answers: Dict) -> FamilyResourceResult:
    """
    家庭资源评估入口

    参数:
        answers: 问卷答案字典，包含以下键:
            father_occupation: 父亲职业类型 (1-10)
            mother_occupation: 母亲职业类型 (1-10)
            family_income_group: 家庭年收入区间 (1-5)
            father_education: 父亲学历 (字符串)
            mother_education: 母亲学历 (字符串)
            family_industry: 家庭行业背景 (枚举)
            gov_relative_count: 体制内亲属数 (整数)
            business_contact_count: 企业人脉数 (整数)
            professional_relative_count: 专业人士亲属数 (整数)
            has_internship_opportunity: 是否提供实习机会 (布尔)
            family_support_level: 就业支持重视程度 (1-5)
            dependency_on_family: 依赖家庭资源的程度 (1-5)

    返回:
        FamilyResourceResult
    """
    # ── 经济资本评估 ──
    economic = _calc_economic_capital(answers)

    # ── 文化资本评估 ──
    cultural = _calc_cultural_capital(answers)

    # ── 社会资本评估 ──
    social = _calc_social_capital(answers)

    # ── 综合得分（加权）───
    total = economic['score'] * 0.3 + cultural['score'] * 0.3 + social['score'] * 0.4

    # ── 评级判定 ──
    rating = _determine_rating(economic, cultural, social, total)

    # ── 建议生成 ──
    suggestions = _generate_suggestions(rating, economic, cultural, social, answers)

    return FamilyResourceResult(
        rating=rating,
        economic_capital=economic['score'],
        cultural_capital=cultural['score'],
        social_capital=social['score'],
        total_score=round(total, 1),
        details={
            'economic': economic,
            'cultural': cultural,
            'social': social,
        },
        suggestions=suggestions,
    )


def _calc_economic_capital(answers: Dict) -> Dict:
    """经济资本：家庭收入 + 实习机会加成

    注：docstring原提到"学费承受力"，但问卷答案中无对应字段。
    如需加入学费承受力，应在问卷中增加 q78b_tuition_tolerance 字段。
    """
    income_group = answers.get('family_income_group', 5)
    income_info = INCOME_GROUPS.get(income_group, INCOME_GROUPS[5])

    # 基础分（来自收入分组）
    base_score = income_info['score'] * 20  # 0-100

    # 实习机会加成（经济资本的可观察指标）
    # P1-urgent #4: 兼容两种字段名——前端表单用 q85_has_internship，
    #  API 直接传 has_internship_opportunity
    has_internship = (
        answers.get('has_internship_opportunity', False)
        or answers.get('has_internship', False)
        or answers.get('q85_has_internship', False)
    )
    bonus = 5 if has_internship else 0

    score = min(100, base_score + bonus)

    return {
        'score': score,
        'income_group': income_group,
        'income_name': income_info['name'],
        'has_internship': has_internship,
    }


def _calc_cultural_capital(answers: Dict) -> Dict:
    """文化资本：父母教育水平"""
    father_edu = answers.get('father_education', '')
    mother_edu = answers.get('mother_education', '')

    father_score = EDUCATION_SCORES.get(father_edu, 1)
    mother_score = EDUCATION_SCORES.get(mother_edu, 1)

    # 取父母中较高者为主（文化资本以家庭中最高指导能力为准）
    max_score = max(father_score, mother_score)
    # 同时考虑两者（取平均作为文化环境指标）
    avg_score = (father_score + mother_score) / 2

    # 综合：60%最高 + 40%平均
    composite = max_score * 0.6 + avg_score * 0.4
    normalized = composite * 20  # 0-100

    return {
        'score': min(100, normalized),
        'father_education': father_edu,
        'mother_education': mother_edu,
        'father_score': father_score,
        'mother_score': mother_score,
    }


def _calc_social_capital(answers: Dict) -> Dict:
    """社会资本：职业阶层 + 社会网络"""
    father_occ = answers.get('father_occupation', 10)
    mother_occ = answers.get('mother_occupation', 10)

    father_occ_info = OCCUPATION_CLASSES.get(father_occ, OCCUPATION_CLASSES[10])
    mother_occ_info = OCCUPATION_CLASSES.get(mother_occ, OCCUPATION_CLASSES[10])

    # 父母阶层得分（H-5 fix: 与教育资本一致，取 max*0.6 + avg*0.4，不再固定父亲优先）
    father_occ_score = father_occ_info['employment_help']
    mother_occ_score = mother_occ_info['employment_help']
    max_occ_score = max(father_occ_score, mother_occ_score)
    avg_occ_score = (father_occ_score + mother_occ_score) / 2
    occ_composite = max_occ_score * 0.6 + avg_occ_score * 0.4

    # 社会网络扩展（亲属资源加分）
    # H-6 fix: 防止负数输入
    gov_count = max(0, answers.get('gov_relative_count', 0))
    business_count = max(0, answers.get('business_contact_count', 0))
    prof_count = max(0, answers.get('professional_relative_count', 0))

    network_bonus = min(20, gov_count * 3 + business_count * 2 + prof_count * 2)

    # 行业背景匹配
    industry = answers.get('family_industry', '')
    industry_support = 10 if industry in ('体制内', '企业') else 5

    # 综合
    base = occ_composite * 16  # 0-80
    score = min(100, base + network_bonus + industry_support)

    return {
        'score': score,
        'father_occupation': father_occ,
        'mother_occupation': mother_occ,
        'father_occ_name': father_occ_info['name'],
        'mother_occ_name': mother_occ_info['name'],
        'gov_relative_count': gov_count,
        'business_contact_count': business_count,
        'professional_relative_count': prof_count,
        'industry': industry,
    }


def _determine_rating(economic: Dict, cultural: Dict, social: Dict, total: float) -> str:
    """
    评级判定（PRD §2.4.5）

    注：职业阶层代码 1=最高(管理者) → 10=最低(新阶层)
         收入组代码 1=高收入组 → 5=低收入组
    因此"高阶层"对应小数字(<=)，"低阶层"对应大数字(>=)

    高: 父母阶层<=4 + 收入组<=2 + 学历>=本科
    中: 父母阶层<=5 + 收入组<=3
    低: 父母阶层>=7 或 收入组>=4
    """
    # 从social里取父母职业阶层
    father_occ = social.get('father_occupation', 10)
    mother_occ = social.get('mother_occupation', 10)
    income_group = economic.get('income_group', 5)

    father_edu = cultural.get('father_education', '')
    mother_edu = cultural.get('mother_education', '')
    max_edu_score = max(
        EDUCATION_SCORES.get(father_edu, 1),
        EDUCATION_SCORES.get(mother_edu, 1),
    )

    # 高: 阶层<=4(专业技术人员及以上) + 收入<=2(中间偏上及以上) + 学历>=本科
    if (min(father_occ, mother_occ) <= 4 and income_group <= 2 and max_edu_score >= 4):
        return '高'

    # 中: 阶层<=5(办事人员及以上) + 收入<=3(中间及以上)
    if (min(father_occ, mother_occ) <= 5 and income_group <= 3):
        return '中'

    # 低: 阶层>=7(商业服务人员及以下) 或 收入>=4(中间偏下及以下)
    if (max(father_occ, mother_occ) >= 7 or income_group >= 4):
        return '低'

    # 综合得分兜底
    if total >= 70:
        return '高'
    elif total >= 40:
        return '中'
    else:
        return '低'


def _generate_suggestions(
    rating: str, economic: Dict, cultural: Dict, social: Dict, answers: Dict
) -> List[str]:
    """根据评级生成专业选择建议"""
    suggestions = []

    if rating == '高':
        suggestions.append('家庭资源充足，可优先考虑高投入高回报专业（商科、艺术、中外合作）')
        suggestions.append('建议利用家庭人脉资源，选择与家庭行业背景相关的专业方向')
    elif rating == '中':
        suggestions.append('家庭资源中等，建议以个人兴趣和能力为主，适度考虑家庭人脉匹配')
        suggestions.append('可选择技术类/体制内就业方向专业，平衡投入与产出')
    else:
        suggestions.append('家庭资源有限，建议优先选择技术壁垒高、个人能力主导的专业')
        suggestions.append('谨慎选择高学费专业（艺术、医学、中外合作），避免投入产出失衡')
        suggestions.append('优先考虑体制内考试方向专业（法学、师范、计算机），降低就业对家庭资源依赖')

    # 行业背景补充建议
    industry = answers.get('family_industry', '')
    if industry == '体制内':
        suggestions.append('家庭体制内背景，可考虑法学、行政管理、财政学等考公优势专业')
    elif industry == '企业':
        suggestions.append('家庭企业背景，可考虑管理、经济、计算机等与商业相关的专业')

    return suggestions


# ── 问卷字段定义（前端采集用）───

QUESTIONNAIRE_FIELDS = [
    {
        'id': 'q76_father_occupation',
        'text': '父亲当前职业类型',
        'type': 'single_choice',
        'options': [f"{k}. {v['name']}" for k, v in OCCUPATION_CLASSES.items()],
    },
    {
        'id': 'q77_mother_occupation',
        'text': '母亲当前职业类型',
        'type': 'single_choice',
        'options': [f"{k}. {v['name']}" for k, v in OCCUPATION_CLASSES.items()],
    },
    {
        'id': 'q78_family_income',
        'text': '家庭年收入区间',
        'type': 'single_choice',
        'options': [f"{k}. {v['name']}（{v['range']}）" for k, v in INCOME_GROUPS.items()],
    },
    {
        'id': 'q79_father_education',
        'text': '父亲最高学历',
        'type': 'single_choice',
        'options': list(EDUCATION_SCORES.keys()),
    },
    {
        'id': 'q80_mother_education',
        'text': '母亲最高学历',
        'type': 'single_choice',
        'options': list(EDUCATION_SCORES.keys()),
    },
    {
        'id': 'q81_family_industry',
        'text': '家庭主要社会网络行业',
        'type': 'single_choice',
        'options': list(INDUSTRY_NETWORKS.keys()),
    },
    {
        'id': 'q82_gov_relative_count',
        'text': '体制内（公务员/事业单位）亲属数量',
        'type': 'integer',
        'min': 0,
        'max': 20,
    },
    {
        'id': 'q83_business_contact_count',
        'text': '企业/商业领域人脉数量',
        'type': 'integer',
        'min': 0,
        'max': 50,
    },
    {
        'id': 'q84_professional_relative_count',
        'text': '专业人士（医生/律师/教师/工程师）亲属数量',
        'type': 'integer',
        'min': 0,
        'max': 20,
    },
    {
        'id': 'q85_has_internship',
        'text': '家庭能否提供实习机会',
        'type': 'boolean',
    },
    {
        'id': 'q86_family_support_level',
        'text': '家庭对子女就业支持的重视程度',
        'type': 'scale',
        'min': 1,
        'max': 5,
        'labels': {'1': '完全不干预', '5': '全力安排'},
    },
    {
        'id': 'q87_dependency_on_family',
        'text': '您对未来就业中依赖家庭资源的程度评估',
        'type': 'scale',
        'min': 1,
        'max': 5,
        'labels': {'1': '完全不依赖', '5': '非常依赖'},
    },
]


if __name__ == '__main__':
    # 测试用例
    test_answers = {
        'father_occupation': 4,
        'mother_occupation': 5,
        'family_income_group': 3,
        'father_education': '本科',
        'mother_education': '大专',
        'family_industry': '体制内',
        'gov_relative_count': 2,
        'business_contact_count': 1,
        'professional_relative_count': 3,
        'has_internship_opportunity': True,
        'family_support_level': 4,
        'dependency_on_family': 3,
    }

    result = assess_family_resource(test_answers)
    print(f'评级: {result.rating}')
    print(f'经济资本: {result.economic_capital:.1f}')
    print(f'文化资本: {result.cultural_capital:.1f}')
    print(f'社会资本: {result.social_capital:.1f}')
    print(f'综合得分: {result.total_score:.1f}')
    print(f'建议: {result.suggestions}')
