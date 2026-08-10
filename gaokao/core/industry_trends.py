# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
行业趋势分析模块

基于PPT《2025-6-21志愿填报公益讲座》中的行业洞察，为专业推荐增加行业趋势评分。
机会巨大行业加分，危机四伏行业减分。
"""

# ── 机会巨大的行业 → 专业映射 ──
OPPORTUNITY_INDUSTRIES = {
    # 科技驱动型
    '人工智能': {
        'majors': ['计算机科学与技术', '人工智能', '数据科学', '软件工程',
                    '智能科学与技术', '机器人工程', '自动化'],
        'trend_score': 0.95,
        'reason': 'AI技术深度应用，预计2030年渗透率达60%',
    },
    '半导体': {
        'majors': ['微电子科学与工程', '集成电路设计与集成系统', '电子信息工程',
                    '电子科学与技术', '通信工程'],
        'trend_score': 0.90,
        'reason': '半导体国产化为国家战略，市场规模2030年或达1.4万亿美元',
    },
    '量子计算': {
        'majors': ['量子信息科学', '物理学', '应用物理学', '数学与应用数学'],
        'trend_score': 0.85,
        'reason': '中国量子技术全球领先，市场规模2035年或超8000亿元',
    },
    '6G通信': {
        'majors': ['通信工程', '电子信息工程', '网络工程', '信息安全'],
        'trend_score': 0.80,
        'reason': '6G预计2030年商用，超高速率和低延迟',
    },
    '生物科技': {
        'majors': ['生物科学', '生物技术', '生物工程', '生物医学工程',
                    '药学', '临床医学', '口腔医学'],
        'trend_score': 0.90,
        'reason': '创新药市场规模2030年或达2000亿美元',
    },
    # 人口结构驱动型
    '银发经济': {
        'majors': ['护理学', '康复治疗学', '老年医学', '社会学',
                    '社会工作', '健康管理'],
        'trend_score': 0.85,
        'reason': '2035年60岁以上人口超4亿，市场规模2040年达23万亿元',
    },
    '医疗健康': {
        'majors': ['临床医学', '口腔医学', '医学影像学', '医学检验技术',
                    '远程医疗', '健康服务与管理'],
        'trend_score': 0.85,
        'reason': '老龄化加剧，远程医疗和可穿戴设备快速发展',
    },
    # 消费升级型
    '智能家居': {
        'majors': ['物联网工程', '电子信息工程', '计算机科学与技术',
                    '工业设计'],
        'trend_score': 0.75,
        'reason': '全屋智能从单品向生态互联演进',
    },
    '情绪经济': {
        'majors': ['心理学', '应用心理学', '社会工作', '教育学'],
        'trend_score': 0.70,
        'reason': '情绪价值消费市场快速崛起',
    },
    '低空经济': {
        'majors': ['航空航天工程', '飞行器设计与工程', '导航工程',
                    '无人驾驶航空器系统工程'],
        'trend_score': 0.80,
        'reason': '预计2025年达1.5万亿元，年均增速超25%',
    },
    '商业航天': {
        'majors': ['航空航天工程', '卫星工程', '通信工程', '材料科学与工程'],
        'trend_score': 0.80,
        'reason': '计划发射1.3万颗低轨卫星',
    },
    # 绿色经济
    '新能源': {
        'majors': ['新能源科学与工程', '电气工程及其自动化', '储能科学与工程',
                    '氢能科学与工程'],
        'trend_score': 0.85,
        'reason': '双碳目标引导能源转型',
    },
}

# ── 危机四伏的行业 → 专业映射 ──
RISK_INDUSTRIES = {
    '传统制造': {
        'majors': ['纺织工程', '轻化工程', '包装工程', '工业设计工程'],
        'risk_score': 0.70,
        'reason': '自动化替代加速，劳动密集型产业面临全面替代',
    },
    '传统零售': {
        'majors': ['市场营销（传统方向）', '零售管理'],
        'risk_score': 0.60,
        'reason': '电商渗透率持续提升，实体门店面临挑战',
    },
    '传统金融': {
        'majors': ['银行学', '传统金融学'],
        'risk_score': 0.50,
        'reason': 'AI和算法对标准化金融服务构成冲击',
    },
    '传统农业': {
        'majors': ['农学（传统方向）', '作物生产技术'],
        'risk_score': 0.55,
        'reason': '智慧农业替代小农经济',
    },
    '高污染能源': {
        'majors': ['采矿工程', '石油工程', '煤炭及深加工'],
        'risk_score': 0.80,
        'reason': '碳价或突破500元/吨，清洁替代加速',
    },
    # ── 中国本土人口结构衰减（少子化冲击） ──
    '学前教育衰退': {
        'majors': ['学前教育', '幼儿教育', '早期教育'],
        'risk_score': 0.85,
        'reason': '2024出生人口仅902万（2016=1786万腰斩），幼儿园规模化关停，5年内供大于求',
    },
    '初等师范衰退': {
        'majors': ['小学教育', '初等教育'],
        'risk_score': 0.75,
        'reason': '少子化向小学传导，2028前后小学入学人数断崖，传统师范供过于求',
    },
    '传统师范': {
        'majors': ['教育学（非公费）', '汉语言文学（师范）'],
        'risk_score': 0.60,
        'reason': '非公费师范就业难度上升，建议优先公费师范生',
    },
    '儿科产科衰减': {
        'majors': ['儿科学', '妇产科学（基础方向）'],
        'risk_score': 0.55,
        'reason': '新生儿数量减半，儿科/产科病源结构性下降（临床医学/护理总需求仍增）',
    },
}

# 专业 → 行业趋势评分缓存
_MAJOR_TREND_CACHE = {}


def get_trend_score(major_name: str) -> tuple:
    """
    获取专业的行业趋势评分

    返回: (score, reason)
        score: 0-1，越高越好（>0.7 机会行业，<0.5 风险行业，0.5-0.7 中性）
        reason: 趋势说明
    """
    if major_name in _MAJOR_TREND_CACHE:
        return _MAJOR_TREND_CACHE[major_name]

    best_score = 0.5  # 默认中性
    best_reason = '无明显行业趋势信号'

    # 先检查机会行业
    for industry, info in OPPORTUNITY_INDUSTRIES.items():
        for m in info['majors']:
            if m in major_name or major_name in m:
                if info['trend_score'] > best_score:
                    best_score = info['trend_score']
                    best_reason = f'✅ {industry}: {info["reason"]}'

    # 再检查风险行业（如果之前是中性或机会）
    if best_score >= 0.5:
        for industry, info in RISK_INDUSTRIES.items():
            for m in info['majors']:
                if m in major_name or major_name in m:
                    risk_adjusted = 1.0 - info['risk_score']
                    if risk_adjusted < best_score:
                        best_score = risk_adjusted
                        best_reason = f'⚠️ {industry}: {info["reason"]}'

    result = (best_score, best_reason)
    _MAJOR_TREND_CACHE[major_name] = result
    return result


def get_industry_report() -> dict:
    """获取完整行业趋势报告"""
    return {
        'opportunities': {k: {'majors': v['majors'], 'score': v['trend_score'], 'reason': v['reason']}
                          for k, v in OPPORTUNITY_INDUSTRIES.items()},
        'risks': {k: {'majors': v['majors'], 'risk': v['risk_score'], 'reason': v['reason']}
                  for k, v in RISK_INDUSTRIES.items()},
    }


def boost_major_scores_by_trend(majors: list) -> list:
    """
    根据行业趋势对专业列表进行加权排序

    返回: [(major, trend_score, reason), ...] 按趋势评分降序排列
    """
    scored = []
    for major in majors:
        score, reason = get_trend_score(major)
        scored.append((major, score, reason))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored
