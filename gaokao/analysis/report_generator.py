# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
考生深度分析报告生成器
────────────────────────────────
纯算法驱动，无 LLM 依赖。从问卷数据 + 引擎结果生成八维结构化分析。

八维：
  1. 考生画像总览 — 六维雷达 + 综合标签
  2. 学科能力分析 — 学科自我评价偏差 + 优势映射
  3. 偏好维度解析 — 项目自编大五维度 + RIASEC 风格 TOP3 + 交叉解读
  4. 职业价值偏好分析 — 十维雷达 + 张力识别
  5. 家庭资源评估 — 资源评级 + 预算匹配 + 专项机会
  6. 风险画像 — 承压/决策/体检/三维风险
  7. 回归与数据质量 — 位次趋势 + 概率置信区间 + 稀疏度
  8. 综合建议 — 策略配比 + 地域 + 调剂 + 家校沟通
"""
import math
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════
# 数据模型
# ═══════════════════════════════════════════════

@dataclass
class RadarDimension:
    """雷达图一个维度"""
    name: str          # 维度名
    score: float       # 0-100 标准分
    label: str         # 等级标签（如"优秀"/"中等"/"偏低"）
    detail: str = ''   # 一句话解读

@dataclass
class TensionPair:
    """职业价值偏好/大五维度张力对。"""
    dim_a: str         # 维度 A 名
    score_a: float     # A 的分数
    dim_b: str         # 维度 B 名
    score_b: float     # B 的分数
    tension: float     # 张力值 0-1（越大越矛盾）
    interpretation: str  # 解读

@dataclass
class AnalysisSection:
    """报告一个章节"""
    title: str
    icon: str
    summary: str                    # 2-3 句总结
    radar: List[RadarDimension] = field(default_factory=list)
    items: List[Dict] = field(default_factory=list)   # 详细条目列表
    tensions: List[TensionPair] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

@dataclass
class AnalysisReport:
    """完整八维分析报告"""
    profile_label: str                  # 综合画像标签
    radar: List[RadarDimension] = field(default_factory=list)  # 六维总览雷达
    sections: List[AnalysisSection] = field(default_factory=list)
    checklist: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════

def generate_report(questionnaire, matching_result=None, db_path: str = '') -> AnalysisReport:
    """
    从问卷 + 引擎结果生成八维分析报告。

    参数:
        questionnaire: UserQuestionnaire 对象（236 题解析后）
        matching_result: MatchingResult 对象（可选，提供推荐和管道数据）
        db_path: 数据库路径（可选，用于查询历史数据趋势）
    """
    q = questionnaire
    report = AnalysisReport(profile_label='')

    # ── 1. 考生画像总览 ──
    radar = _build_overview_radar(q)
    report.radar = radar
    report.profile_label = _build_profile_label(q, radar)

    # ── 2-8. 各章节 ──
    report.sections = [
        _analyze_academic(q),
        _analyze_personality(q),
        _analyze_values(q),
        _analyze_family(q),
        _analyze_risk(q, matching_result),
        _analyze_data_quality(q, matching_result, db_path),
        _analyze_recommendation(q, matching_result),
    ]

    # ── 综合建议清单 ──
    report.checklist = _build_checklist(q, matching_result)

    return report


def report_to_dict(report: AnalysisReport) -> Dict:
    """序列化为前端可用的 JSON 字典。"""
    def _radar_to_list(items):
        return [{'name': r.name, 'score': round(r.score, 1), 'label': r.label, 'detail': r.detail}
                for r in items]

    def _tension_to_list(items):
        return [{'dimA': t.dim_a, 'scoreA': round(t.score_a, 1),
                 'dimB': t.dim_b, 'scoreB': round(t.score_b, 1),
                 'tension': round(t.tension, 2), 'text': t.interpretation}
                for t in items]

    return {
        'profileLabel': report.profile_label,
        'radar': _radar_to_list(report.radar),
        'sections': [
            {
                'title': s.title,
                'icon': s.icon,
                'summary': s.summary,
                'radar': _radar_to_list(s.radar),
                'items': s.items,
                'tensions': _tension_to_list(s.tensions),
                'warnings': s.warnings,
            }
            for s in report.sections
        ],
        'checklist': report.checklist,
    }


# ═══════════════════════════════════════════════
# 1. 考生画像总览
# ═══════════════════════════════════════════════

def _build_overview_radar(q) -> List[RadarDimension]:
    """六维总览雷达：学科力/大五维度/兴趣/价值偏好/风险/资源。"""
    dims = []

    # 学科力：基于语数英成绩 + 项目自编学科自我评价
    academic_score = _calc_academic_power(q)
    dims.append(RadarDimension('学科力', academic_score,
                               _score_label(academic_score),
                               '语数英成绩 + 项目自编学科自我评价综合'))

    # 偏好维度：基于项目自编大五维度问卷完成度
    personality_score = _calc_personality_power(q)
    dims.append(RadarDimension('大五问卷完成度', personality_score,
                               _score_label(personality_score),
                               '项目自编大五维度问卷完成度'))

    # 兴趣：基于项目自编 RIASEC 风格问卷完成度
    interest_score = _calc_interest_power(q)
    dims.append(RadarDimension('兴趣明确度', interest_score,
                               _score_label(interest_score),
                               '项目自编 RIASEC 风格问卷完成度'))

    # 价值偏好：基于项目自编职业价值偏好问卷完成度
    value_score = _calc_values_power(q)
    dims.append(RadarDimension('价值偏好问卷完成度', value_score,
                               _score_label(value_score),
                               '项目自编职业价值偏好问卷完成度'))

    # 风险偏好：基于稳定偏好和承压能力
    risk_score = _calc_risk_power(q)
    dims.append(RadarDimension('风险偏好', risk_score,
                               _score_label(risk_score),
                               '稳定偏好 + 承压能力'))

    # 家庭资源：基于家庭资源评估
    resource_score = _calc_resource_power(q)
    dims.append(RadarDimension('家庭资源', resource_score,
                               _score_label(resource_score),
                               '预算 + 人脉 + 专项计划'))

    return dims


def _build_profile_label(q, radar) -> str:
    """生成综合画像标签，如: 理工探索型·稳定倾向·资源中等"""
    # 第一段：学科倾向
    cat = q.category or ''
    if '物理' in cat:
        academic_tag = '理工型'
    elif '历史' in cat:
        academic_tag = '人文型'
    else:
        academic_tag = '综合型'

    # 第二段：兴趣问卷完成度
    interest = _calc_interest_power(q)
    if interest >= 70:
        personality_tag = '目标明确'
    elif interest >= 40:
        personality_tag = '探索中'
    else:
        personality_tag = '待定位'

    # 第三段：稳定倾向
    stab = q.stability_preference or 3
    if stab >= 4:
        stability_tag = '稳定倾向'
    elif stab <= 2:
        stability_tag = '挑战倾向'
    else:
        stability_tag = '均衡型'

    return f'{academic_tag}·{personality_tag}·{stability_tag}'


# ═══════════════════════════════════════════════
# 2. 学科能力分析
# ═══════════════════════════════════════════════

def _analyze_academic(q) -> AnalysisSection:
    section = AnalysisSection(
        title='学科能力深度分析',
        icon='🧠',
        summary='',
    )
    items = []
    warnings = []

    # 语数英单科分析
    subjects = [
        ('语文', q.chinese_score, 'chinese'),
        ('数学', q.math_score, 'math'),
        ('英语', q.english_score, 'english'),
    ]
    for subj_name, score, key in subjects:
        if score is None:
            continue
        # 相对位次估算（满分150/150/150，按分数百分比粗估）
        max_score = 150
        pct = min(100, (score / max_score) * 100)
        label = _score_label(pct)
        detail = f'{subj_name}{score}分，相对水平{label}'

        # 学科自我评价与当前成绩的差异
        efficacy = (q.subject_self_efficacy or {}).get(key, 0)
        if efficacy > 0:
            efficacy_pct = efficacy / 5 * 100
            gap = efficacy_pct - pct
            if gap > 20:
                detail += f'；学科自我评价较高（{efficacy:.1f}/5），与当前成绩信号存在差异，建议结合老师评价和近期成绩复核'
                warnings.append(f'⚠️ {subj_name}自我评价与当前成绩信号差异较大（自评{efficacy:.1f}/5 vs 成绩{label}），建议复核后再选专业方向')
            elif gap < -20:
                detail += f'；学科自我评价较低（{efficacy:.1f}/5），与当前成绩信号存在差异，建议结合多次成绩和老师评价复核'
            else:
                detail += f'；学科自我评价与当前成绩信号接近（{efficacy:.1f}/5）'

        items.append({
            'subject': subj_name,
            'score': score,
            'level': label,
            'detail': detail,
            'efficacy': round(efficacy, 1) if efficacy else None,
        })

    # 选考科目分析
    if '物理' in (q.category or ''):
        if q.physics_achievement:
            items.append({
                'subject': '物理', 'score': None,
                'level': q.physics_achievement,
                'detail': f'物理自评"{q.physics_achievement}"，意愿"{q.physics_willingness or "未填"}"'
                          + (f'，方向偏好"{q.physics_direction}"' if q.physics_direction else ''),
            })
        if q.chemistry_achievement:
            items.append({
                'subject': '化学', 'score': None,
                'level': q.chemistry_achievement,
                'detail': f'化学自评"{q.chemistry_achievement}"，意愿"{q.chemistry_willingness or "未填"}"',
            })
    elif '历史' in (q.category or ''):
        if q.history_achievement:
            items.append({
                'subject': '历史', 'score': None,
                'level': q.history_achievement,
                'detail': f'历史自评"{q.history_achievement}"，意愿"{q.history_willingness or "未填"}"',
            })
        if q.foreign_language_achievement:
            items.append({
                'subject': '外语', 'score': None,
                'level': q.foreign_language_achievement,
                'detail': f'外语自评"{q.foreign_language_achievement}"，意愿"{q.foreign_language_willingness or "未填"}"',
            })

    # 优势学科 → 专业类映射
    advantage_map = {
        '数学': ['数学类', '统计学类', '金融工程', '数据科学', '计算机类', '物理学类'],
        '语文': ['中国语言文学类', '新闻传播学类', '哲学类', '历史学类', '法学类'],
        '英语': ['外国语言文学类', '翻译', '国际经济与贸易', '商务英语', '外交学'],
        '物理': ['物理学类', '电子信息类', '电气类', '机械类', '航空航天类', '兵器类'],
        '化学': ['化学类', '药学类', '材料类', '化工与制药类', '环境科学与工程类'],
        '生物': ['生物科学类', '医学类', '农学类', '食品科学与工程类'],
        '历史': ['历史学类', '考古学', '文物保护技术', '政治学类'],
        '政治': ['政治学类', '法学类', '马克思主义理论类', '公共管理类'],
        '地理': ['地理科学类', '地质学类', '测绘类', '城乡规划', '旅游管理类'],
    }
    adv = q.advantage_1 or ''
    if adv in advantage_map:
        items.append({
            'subject': '优势→专业映射',
            'score': None,
            'level': '参考',
            'detail': f'你的第一优势"{adv}"推荐关注：{"、".join(advantage_map[adv][:5])}',
        })

    section.summary = f'共分析 {len(items)} 项学科维度'
    section.items = items
    section.warnings = warnings
    return section


# ═══════════════════════════════════════════════
# 3. 偏好维度解析
# ═══════════════════════════════════════════════

# 大五维度中文 + 解读模板
BIG_FIVE_DIMS = {
    'O': {'name': '开放性', 'high': '富有想象力和好奇心，适合创造性/研究型工作', 'low': '务实稳重，偏好确定性高的工作'},
    'C': {'name': '尽责性', 'high': '自律有序、追求完美，适合需要精确性的职业', 'low': '灵活适应，不太适合高度流程化的岗位'},
    'E': {'name': '外向性', 'high': '善于社交和表达，适合团队协作/管理/销售', 'low': '独立思考型，适合研究/技术/创作类'},
    'A': {'name': '宜人性', 'high': '善解人意，适合教育/医疗/社会服务', 'low': '竞争意识强，适合商业/法律/谈判类'},
    'N': {'name': '情绪稳定性', 'high': '情绪起伏大，高压岗位需谨慎', 'low': '情绪稳定，适合高压/高风险决策岗'},
}

# RIASEC 风格 TOP3 代码组合 → 适配方向
HOLLAND_COMBO_MAP = {
    'RIS': '工程/技术研究——动手能力强、善于分析',
    'RIA': '工程/设计——兼具动手能力和创造力',
    'RIC': '工程/数据——动手+精确，适合制造/质检',
    'IAR': '科研/设计——理论导向，适合学术/研发',
    'IAS': '科研/教育——适合高校/研究所',
    'IEC': '科研/管理——适合技术管理层',
    'ASE': '教育/管理——人际导向，适合教学/HR',
    'ASC': '教育/行政——适合学校/机关管理',
    'ART': '艺术/设计——创造力突出，适合创意产业',
    'SEC': '管理/行政——组织能力强，适合政企管理',
    'SER': '管理/服务——适合公共管理/社区工作',
    'CIE': '数据/技术——精确+分析，适合金融/统计',
    'CIS': '数据/教育——适合信息管理/教学',
}

def _analyze_personality(q) -> AnalysisSection:
    section = AnalysisSection(
        title='偏好维度解析（项目自编，非心理诊断）',
        icon='🧬',
        summary='',
    )
    items = []
    radar = []

    # 项目自编大五维度
    bf = getattr(q, 'big_five_answers', None) or {}
    if bf:
        dim_scores = _calc_big_five_scores(bf)
        for dim_code, score in dim_scores.items():
            info = BIG_FIVE_DIMS.get(dim_code, {})
            name = info.get('name', dim_code)
            interp = info.get('high', '') if score >= 60 else info.get('low', '')
            radar.append(RadarDimension(name, score, _score_label(score), interp))
            items.append({
                'dimension': name,
                'score': round(score, 1),
                'level': _score_label(score),
                'interpretation': interp,
            })
    else:
        items.append({'dimension': '大五维度偏好', 'score': None, 'level': '未填写',
                      'interpretation': '未填写项目自编大五维度问卷，偏好维度分析缺失'})

    # 项目自编 RIASEC 风格兴趣偏好
    hl = getattr(q, 'holland_answers', None) or {}
    if hl:
        holland_scores = _calc_holland_scores(hl)
        sorted_dims = sorted(holland_scores.items(), key=lambda x: -x[1])
        top3 = ''.join([d for d, s in sorted_dims[:3]])
        combo_interp = HOLLAND_COMBO_MAP.get(top3, f'{top3}型——综合特质组合')
        items.append({
            'dimension': 'RIASEC 风格 TOP3',
            'score': None,
            'level': top3,
            'interpretation': combo_interp,
            'scores': {d: round(s, 1) for d, s in holland_scores.items()},
        })
        # 大五维度 × RIASEC 风格交叉解读
        if bf:
            cross = _cross_interpret(dim_scores, holland_scores)
            if cross:
                items.append({'dimension': '大五维度×RIASEC 风格交叉', 'score': None, 'level': '综合',
                              'interpretation': cross})
    else:
        items.append({'dimension': 'RIASEC 风格兴趣偏好', 'score': None, 'level': '未填写',
                      'interpretation': '未填写项目自编兴趣偏好问卷，专业方向信号缺失'})

    section.radar = radar
    section.summary = (
        f'大五维度{"已分析" if bf else "未填写"}，'
        f'RIASEC 风格{"已分析" if hl else "未填写"}；'
        '问卷未经心理测量学验证，结果仅作方向参考'
    )
    section.items = items
    return section


def _calc_big_five_scores(bf: Dict) -> Dict[str, float]:
    """从大五答案计算五维标准化分数（0-100）。"""
    # 正向题号 + 反向题号映射（简化版）
    forward = {
        'O': [1,2,3,4,5,6,9,10],
        'C': [11,12,13,14,15,17,19,20],
        'E': [21,22,23,24,25,26,29,30],
        'A': [31,32,33,34,35,36,39,40],
        'N': [41,42,43,44,45,46,49,50],
    }
    reverse_map = {7:'O', 8:'O', 16:'C', 18:'C', 27:'E', 28:'E', 37:'A', 38:'A', 47:'N', 48:'N'}

    scores = {}
    for dim, nos in forward.items():
        vals = []
        for n in nos:
            v = bf.get(n)
            if v is not None: vals.append(int(v))
        # 反向题
        for n, d in reverse_map.items():
            if d == dim:
                v = bf.get(n)
                if v is not None: vals.append(6 - int(v))  # 1-5 反转
        if vals:
            scores[dim] = (sum(vals) / len(vals)) / 5 * 100
        else:
            scores[dim] = 50
    return scores


def _calc_holland_scores(hl: Dict) -> Dict[str, float]:
    """从项目自编 RIASEC 风格答案计算六维分数。"""
    dims = {'R': 0, 'I': 0, 'A': 0, 'S': 0, 'E': 0, 'C': 0}
    counts = {'R': 0, 'I': 0, 'A': 0, 'S': 0, 'E': 0, 'C': 0}

    # 简化：每道 A/B 题对 A/B 维度各 +1
    # 实际映射参考 personality_items._RIASEC_PAIRS_LOCAL
    pairs = {
        1:('R','I'),2:('R','I'),3:('R','I'),4:('R','I'),5:('R','I'),6:('R','I'),7:('R','I'),
        8:('A','S'),9:('A','S'),10:('A','S'),11:('A','S'),12:('A','S'),13:('A','S'),
        14:('E','C'),15:('E','C'),16:('E','C'),17:('E','C'),18:('E','C'),19:('E','C'),
        20:('R','A'),21:('R','A'),22:('R','A'),23:('R','A'),24:('R','A'),25:('R','A'),
        26:('I','E'),27:('I','E'),28:('I','E'),29:('I','E'),30:('I','E'),31:('I','E'),
        32:('S','C'),33:('S','C'),34:('S','C'),35:('S','C'),36:('S','C'),37:('S','C'),
        38:('R','S'),39:('R','S'),40:('R','S'),41:('R','S'),42:('R','S'),43:('R','S'),
        44:('I','A'),45:('I','A'),46:('I','A'),47:('I','A'),48:('I','A'),49:('I','A'),
        50:('E','R'),51:('E','R'),52:('E','R'),53:('E','R'),54:('E','R'),55:('E','R'),
        56:('C','I'),57:('C','I'),58:('C','I'),59:('C','I'),60:('C','I'),61:('C','I'),
        62:('A','E'),63:('A','E'),64:('A','E'),65:('A','E'),66:('A','E'),67:('A','E'),
        68:('S','R'),69:('S','R'),70:('S','R'),71:('S','R'),72:('S','R'),73:('S','R'),
        74:('C','A'),75:('C','A'),76:('C','A'),
    }
    for qno, (a_dim, b_dim) in pairs.items():
        ans = hl.get(qno)
        if ans == 'A':
            dims[a_dim] += 1
            counts[a_dim] += 1
        elif ans == 'B':
            dims[b_dim] += 1
            counts[b_dim] += 1

    # 标准化到 0-100
    max_possible = max(max(counts.values()), 1)
    return {d: round(s / max_possible * 100, 1) for d, s in dims.items()}


def _cross_interpret(bf_scores, holland_scores) -> str:
    """大五维度 × RIASEC 风格交叉解读。"""
    parts = []

    o = bf_scores.get('O', 50)
    top_holland = max(holland_scores, key=holland_scores.get) if holland_scores else ''

    if o >= 65 and top_holland == 'I':
        parts.append('高开放性+研究型→适合探索性强的前沿领域（科研/AI/新药研发）')
    elif o >= 65 and top_holland == 'A':
        parts.append('高开放性+艺术型→创造力突出，适合设计/文创/新媒体')
    elif o < 40 and top_holland == 'C':
        parts.append('低开放性+常规型→偏好稳定可预测的工作，适合财会/审计/行政')

    n = bf_scores.get('N', 50)
    if n >= 65:
        parts.append('情绪波动较大，建议避免高压力/高竞争岗位（如投行/急诊），优先选择节奏可控的工作')
    elif n < 35 and top_holland == 'E':
        parts.append('情绪稳定+企业型→适合在压力下做决策的管理岗位')

    e = bf_scores.get('E', 50)
    if e >= 65 and top_holland == 'S':
        parts.append('高外向+社会型→人际驱动型人才，适合教育/咨询/公益')
    elif e < 40 and top_holland == 'I':
        parts.append('内向+研究型→深度思考型人才，适合独立研究/数据分析/编程')

    return '；'.join(parts) if parts else ''


# ═══════════════════════════════════════════════
# 4. 职业价值偏好冲突分析
# ═══════════════════════════════════════════════

TENSION_PAIRS = [
    ('income', 'stability', '收入', '稳定'),
    ('achievement', 'balance', '成就', '生活平衡'),
    ('autonomy', 'help', '自主', '助人'),
    ('leadership', 'learning', '管理', '学习'),
    ('creative', 'location', '创造', '地域'),
]

def _analyze_values(q) -> AnalysisSection:
    section = AnalysisSection(
        title='职业价值偏好冲突分析（项目自编）',
        icon='⚖️',
        summary='',
    )
    cv = q.career_values or {}
    items = []
    tensions = []

    if not cv:
        items.append({'dimension': '职业价值偏好', 'score': None, 'level': '未填写',
                      'interpretation': '未填写项目自编职业价值偏好问卷，无法进行冲突分析'})
        section.summary = '职业价值偏好问卷未填写'
        section.items = items
        return section

    # 十维分数
    dim_names = {
        'income': '经济回报', 'stability': '稳定保障', 'achievement': '成就感',
        'help': '助人贡献', 'creative': '创造力', 'balance': '生活平衡',
        'leadership': '领导力', 'autonomy': '自主性', 'location': '地域偏好',
        'learning': '持续学习',
    }
    for key, score in cv.items():
        name = dim_names.get(key, key)
        pct = (score / 5) * 100 if score else 0
        items.append({'dimension': name, 'score': round(score, 1) if score else None,
                      'level': _score_label(pct), 'interpretation': ''})

    # 张力对
    for dim_a, dim_b, label_a, label_b in TENSION_PAIRS:
        sa = cv.get(dim_a, 0)
        sb = cv.get(dim_b, 0)
        if sa and sb:
            tension = abs(sa - sb) / 5  # 0-1
            if tension >= 0.4:
                if sa > sb:
                    text = f'你更看重{label_a}（{sa:.1f}）而非{label_b}（{sb:.1f}），这可能导致在"高薪但不稳定"和"稳定但收入一般"之间倾向前者——志愿选择时注意不要因为追求热门专业而忽略保底'
                else:
                    text = f'你更看重{label_b}（{sb:.1f}）而非{label_a}（{sa:.1f}），倾向选择"确定性"——建议在保底之余留 1-2 个"冲"的名额给潜在高回报专业'
                tensions.append(TensionPair(label_a, sa*20, label_b, sb*20, tension, text))

    top_val = max(cv.items(), key=lambda x: x[1]) if cv else (None, 0)
    section.summary = f'最高职业价值偏好维度：{dim_names.get(top_val[0], "—")}（{top_val[1]:.1f}/5）'
    section.items = items
    section.tensions = tensions
    return section


# ═══════════════════════════════════════════════
# 5. 家庭资源评估
# ═══════════════════════════════════════════════

def _analyze_family(q) -> AnalysisSection:
    section = AnalysisSection(
        title='家庭资源与策略评估',
        icon='👨‍👩‍👧',
        summary='',
    )
    items = []

    # 预算
    budget = q.total_budget or ''
    budget_tier = '未知'
    if '2万' in budget:
        budget_tier = '经济型（2万以内）'
    elif '4-6' in budget:
        budget_tier = '标准型（4-6万，覆盖多数公办本科）'
    elif '6-10' in budget:
        budget_tier = '充裕型（6-10万，可考虑部分中外合作）'
    elif '10-15' in budget or '15万' in budget:
        budget_tier = '宽裕型（10万+，中外合作/民办不受限）'
    items.append({'dimension': '预算水平', 'score': None, 'level': budget_tier,
                  'interpretation': f'年度总预算{budget}'})

    # 人脉资源
    resources = q.family_resources or []
    if resources:
        items.append({'dimension': '家庭人脉', 'score': None, 'level': f'{len(resources)}项',
                      'interpretation': f'拥有：{"、".join(resources)}'})

    # 专项计划
    special = q.special_plan_eligibility or []
    if special and '无' not in special:
        items.append({'dimension': '专项计划', 'score': None, 'level': '有资格',
                      'interpretation': f'符合：{"、".join(special)}，可获得降分录取机会'})

    section.summary = f'预算{budget_tier}，家庭人脉{len(resources or [])}项'
    section.items = items
    return section


# ═══════════════════════════════════════════════
# 6. 风险画像
# ═══════════════════════════════════════════════

def _analyze_risk(q, result) -> AnalysisSection:
    section = AnalysisSection(
        title='风险画像与策略建议',
        icon='⚠️',
        summary='',
    )
    items = []
    warnings = []

    # 承压能力
    stress_map = {
        '能适应很高强度的压力': '极强',
        '能适应较高压力': '较强',
        '能适应中等压力': '中等',
        '只能适应较低压力': '偏低',
        '偏好低压稳定环境': '低',
    }
    stress_level = stress_map.get(q.stress_tolerance or '', '未评估')
    items.append({'dimension': '承压能力', 'score': None, 'level': stress_level,
                  'interpretation': f'自评"{q.stress_tolerance or "未填"}"'})

    # 决策风格
    decision = q.decision_control or '未填'
    items.append({'dimension': '决策风格', 'score': None, 'level': decision,
                  'interpretation': f'自评"{decision}"'})

    # 体检限制
    hs = q.health_screening
    if hs:
        health_issues = []
        if hs.color_vision and hs.color_vision != '正常':
            health_issues.append(f'色觉:{hs.color_vision}')
        if hs.vision and '正常' not in hs.vision:
            health_issues.append(f'视力:{hs.vision}')
        if health_issues:
            warnings.append(f'🏥 体检限制：{"、".join(health_issues)}，部分专业受限')
            items.append({'dimension': '体检限制', 'score': None, 'level': '有限制',
                          'interpretation': '、'.join(health_issues)})

    # 滑档/退档/高分低就
    if result:
        bao_count = len(result.recommendations.get('保', []))
        total = sum(len(v) for v in result.recommendations.values())
        if bao_count < 3:
            warnings.append(f'🔴 保底仅 {bao_count} 个，滑档风险高——建议增加保底至 5 个以上')
        if total < 15:
            warnings.append(f'🔴 推荐总数仅 {total} 个，志愿覆盖不足')

    # 风险策略推断
    stab = q.stability_preference or 3
    strategy = '均衡型'
    if stab >= 4:
        strategy = '稳健型（建议冲20%/稳50%/保30%）'
    elif stab <= 2:
        strategy = '积极型（建议冲35%/稳40%/保25%）'
    items.append({'dimension': '推荐策略', 'score': None, 'level': strategy,
                  'interpretation': f'基于稳定偏好({stab}/5)+承压能力推断'})

    section.summary = f'承压{stress_level}，策略{strategy}'
    section.items = items
    section.warnings = warnings
    return section


# ═══════════════════════════════════════════════
# 7. 回归与数据质量
# ═══════════════════════════════════════════════

def _analyze_data_quality(q, result, db_path) -> AnalysisSection:
    section = AnalysisSection(
        title='数据质量与回归分析',
        icon='📊',
        summary='',
    )
    items = []
    warnings = []

    # ── 1. 数据年份与权重 ──
    items.append({
        'dimension': '历史数据覆盖',
        'score': None,
        'level': '3 年',
        'interpretation': '采用 2023 / 2024 / 2025 年官方录取位次数据，按指数衰减权重 0.5 : 0.3 : 0.2 加权拟合。'
                         '越近的年份权重越大——因为招生计划波动对新数据影响更小',
    })

    # ── 2. 指数衰减概率模型 ──
    items.append({
        'dimension': '概率计算模型',
        'score': None,
        'level': '指数衰减模型',
        'interpretation': (
            '录取概率 P = 50% + 50% × (1 − e^(−2 · |Δrank| / pred_rank))\n'
            '其中：\n'
            '• Δrank = 考生位次 − 预测今年最低录取位次（越小越有优势）\n'
            '• pred_rank = 基于 3 年加权中位数预测的今年录取位次\n'
            '• 趋势钳制：每年位次变化率限制在 ±30% 以内，防止极值年份过度影响预测\n'
            '• 当考生位次 ≤ 预测位次时，概率 ≥ 50%；考生位次 ≥ 预测位次×1.5 时，概率 < 10%\n'
            '• 置信区间：基于历史波动率计算，约 ±5 个百分点（95% 置信水平）'
        ),
    })

    # ── 3. 概率置信区间说明 ──
    items.append({
        'dimension': '置信区间 (CI)',
        'score': None,
        'level': '95% CI ±5pp',
        'interpretation': (
            '每个录取概率附带一个 95% 置信区间，含义是：如果今年招生情况与过去 3 年类似，'
            '真实录取概率有 95% 的可能性落在显示概率 ±5 个百分点之内。\n'
            '注意：这不是保证！如果某校今年大幅扩招或缩招，实际概率可能偏离区间。'
        ),
    })

    # ── 4. 数据稀疏度分析 ──
    if result and result.data_sparsity_warning:
        items.append({
            'dimension': '数据稀疏度',
            'score': None,
            'level': '⚠️ 稀疏',
            'interpretation': f'⚠️ {result.data_sparsity_warning}',
        })
        warnings.append(f'⚠️ {result.data_sparsity_warning}')
    else:
        items.append({
            'dimension': '数据稀疏度',
            'score': None,
            'level': '充足',
            'interpretation': '当前位次段在 3 年历史数据中均有充足样本，概率估计可靠度较高。'
                             '建议关注标注为"新增专业"的选项——这些专业没有历史数据，概率为专家估算值',
        })

    # ── 5. 新旧高考体系位次可比性 ──
    items.append({
        'dimension': '新旧高考位次可比性',
        'score': None,
        'level': '3+1+2 新高考',
        'interpretation': (
            '2025年起的高考数据已按新高考（物理类/历史类）分类统计。\n'
            '• 2020-2024 年为旧高考（理科/文科），位次已作跨体系校准\n'
            '• 算法仅在相同高考体系内计算趋势——不会跨体系（旧/新）计算位次变化率\n'
            '• 旧高考→新高考位次映射通过同位次百分位法转换，可能引入 1%-3% 的额外偏差'
        ),
    })

    # ── 6. 贝叶斯先验（历史类稀疏数据处理） ──
    items.append({
        'dimension': '贝叶斯先验修正',
        'score': None,
        'level': '启用（历史类稀疏场景）',
        'interpretation': (
            '当历史类数据不足 3 条时，引擎自动启用贝叶斯先验估计：\n'
            '• 先验分布：基于同校物理类位次比例推算历史类近似位次\n'
            '• 似然函数：已有的稀疏历史类位次观测值（如有）\n'
            '• 后验估计：先验与似然加权融合——数据越稀疏，先验权重越大\n'
            '• 标记：此类推荐的"置信度"字段显示为"low"，提示用户人工核实'
        ),
    })

    # ── 7. 模型限制与免责 ──
    items.append({
        'dimension': '模型限制',
        'score': None,
        'level': '透明披露',
        'interpretation': (
            '本模型不做以下预测：\n'
            '① 当年招生计划变化（某校突然扩招/缩招/停招）\n'
            '② 当年考生报考热度变化（某专业突然成为"热门/冷门"）\n'
            '③ 政策变化（如批次合并、计划调整等）\n'
            '④ 个体层面的面试/体检/政审等主观筛选\n'
            '因此，概率仅作为"基于历史数据的统计参考"，不能视为录取承诺。'
        ),
    })

    # ── 8. 引擎版本 ──
    items.append({
        'dimension': '算法引擎版本',
        'score': None,
        'level': 'OpenGaokao V3.0',
        'interpretation': '指数衰减概率模型 + 项目自编四维偏好融合（大五维度×RIASEC 风格×学科自我评价×职业价值偏好）+ '
                         '7 步透明漏斗排除 + 贝叶斯稀疏先验修正',
    })

    section.summary = (
        f'3 年数据 × 指数衰减加权，置信区间约 ±5pp。'
        f'{len(warnings)} 项数据质量告警。概率模型透明可审计——每个数字都有公式和来源。'
    )
    section.items = items
    section.warnings = warnings
    return section


# ═══════════════════════════════════════════════
# 8. 综合建议
# ═══════════════════════════════════════════════

def _analyze_recommendation(q, result) -> AnalysisSection:
    section = AnalysisSection(
        title='综合建议',
        icon='🎯',
        summary='',
    )
    items = []

    # 冲稳保配比
    stab = q.stability_preference or 3
    if stab >= 4:
        ratio = '冲 20% / 稳 50% / 保 30%'
    elif stab <= 2:
        ratio = '冲 35% / 稳 40% / 保 25%'
    else:
        ratio = '冲 25% / 稳 45% / 保 30%'
    items.append({'dimension': '冲稳保配比', 'score': None, 'level': ratio,
                  'interpretation': '基于你的风险偏好和承压能力推荐'})

    # 地域策略
    prov_pref = q.province_preference or ''
    if '省内' in prov_pref:
        items.append({'dimension': '地域策略', 'score': None, 'level': '省内优先',
                      'interpretation': '省内院校录取数据更充分、概率更准确；省外院校注意当地招生计划变化'})
    elif '出省' in prov_pref:
        items.append({'dimension': '地域策略', 'score': None, 'level': '出省优先',
                      'interpretation': '出省可拓宽选择面，但注意省外院校在云南招生计划可能较少、波动较大'})
    else:
        items.append({'dimension': '地域策略', 'score': None, 'level': '不限',
                      'interpretation': '全国范围选择，按专业质量优先筛选'})

    # 调剂策略
    adjust = q.major_adjustment or q.major_adjustment_attitude or ''
    if '不服从' in adjust:
        items.append({'dimension': '调剂策略', 'score': None, 'level': '不服从',
                      'interpretation': '⚠️ 不服从调剂会增加退档风险。如果选择不服从，必须确保保底院校的每个专业都可接受'})
    else:
        items.append({'dimension': '调剂策略', 'score': None, 'level': '服从',
                      'interpretation': '服从调剂降低退档风险，但可能被分配到不喜欢的专业'})

    # 家校沟通
    decision = q.decision_control or ''
    if '家长' in decision:
        items.append({'dimension': '家校沟通', 'score': None, 'level': '家长主导',
                      'interpretation': '建议家长和考生一起查看推荐结果，重点关注"保"档院校是否双方认可'})
    elif '自己' in decision:
        items.append({'dimension': '家校沟通', 'score': None, 'level': '考生自主',
                      'interpretation': '自主决策型，但建议也和家长分享推荐结果——尤其预算和地域方面需家庭支持'})

    section.summary = ratio
    section.items = items
    return section


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def _score_label(score: float) -> str:
    if score >= 80: return '优秀'
    if score >= 60: return '良好'
    if score >= 40: return '中等'
    if score >= 20: return '偏低'
    return '待提升'


def _calc_academic_power(q) -> float:
    """学科力综合分 0-100"""
    scores = [s for s in [q.chinese_score, q.math_score, q.english_score] if s]
    if not scores:
        return 30  # 无数据时给一个中等偏低默认
    avg_pct = sum(s / 150 for s in scores) / len(scores) * 100
    # 叠加项目自编学科自我评价
    eff = q.subject_self_efficacy or {}
    if eff:
        eff_avg = sum(eff.values()) / len(eff) / 5 * 100
        return (avg_pct * 0.7 + eff_avg * 0.3)
    return avg_pct


def _calc_personality_power(q) -> float:
    bf = getattr(q, 'big_five_answers', None) or {}
    if not bf:
        return 10
    return min(100, len(bf) / 50 * 100)


def _calc_interest_power(q) -> float:
    hl = getattr(q, 'holland_answers', None) or {}
    if not hl:
        return 10
    return min(100, len(hl) / 76 * 100)


def _calc_values_power(q) -> float:
    cv = q.career_values or {}
    if not cv:
        return 10
    filled = sum(1 for v in cv.values() if v > 0)
    return min(100, filled / 10 * 100)


def _calc_risk_power(q) -> float:
    stab = q.stability_preference or 3
    return stab / 5 * 100


def _calc_resource_power(q) -> float:
    score = 30  # 基准
    budget = q.total_budget or ''
    if '6-10' in budget or '10-15' in budget or '15万' in budget:
        score += 25
    elif '4-6' in budget:
        score += 15
    resources = q.family_resources or []
    score += min(25, len(resources) * 8)
    special = q.special_plan_eligibility or []
    if special and '无' not in special:
        score += 15
    return min(100, score)


def _build_checklist(q, result) -> List[str]:
    """综合建议清单"""
    items = []

    # 保底检查
    if result:
        bao = len(result.recommendations.get('保', []))
        total = sum(len(v) for v in result.recommendations.values())
        items.append(f'✓ 推荐总数 {total} 个，保底 {bao} 个')
        if bao < 5:
            items.append(f'⚠ 保底偏少（{bao} 个），建议补充至 5+ 个')

    # 体检
    hs = q.health_screening
    if hs and (hs.color_vision != '正常' if hs.color_vision else False):
        items.append('⚠ 色觉异常考生：报考前逐条核验招生章程体检要求')

    # 调剂
    adjust = q.major_adjustment or q.major_adjustment_attitude or ''
    if '不服从' in adjust:
        items.append('⚠ 不服从调剂：务必确认保底院校的每个专业都可接受')

    # 预算
    budget = q.total_budget or ''
    if '2万' in budget:
        items.append('💡 预算紧张：优先筛选学费 ≤6000 元/年的公办院校')

    # 共识
    items.append('🔲 最终提交前与家人确认：预算、地域、专业方向是否一致')

    # 免责
    items.append('📋 免责声明：以上概率基于历史数据统计，不代表当年录取结果')

    return items
