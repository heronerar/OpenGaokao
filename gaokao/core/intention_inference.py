# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
意愿推断引擎 (Intention Inference Engine)
从多维数据中推断用户真实意愿，检测冲突，生成意愿画像。

设计理念：
1. 用户说想学什么 ≠ 用户适合学什么
2. 用户没说 ≠ 用户没想法（数据会说话）
3. 能力 + 兴趣 + 家庭 + 价值观 = 真实意愿（四维融合）

三层推断：
- 信号层：从分数/选科/竞赛/家庭等提取倾向信号
- 画像层：聚合为结构化意愿画像
- 冲突层：检测能力-意愿-性格-家庭间的矛盾
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from .revocation_risk import get_revocation_risk


# ── 推断信号定义 ──

@dataclass
class InferenceSignal:
    """单个推断信号"""
    signal_type: str        # academic / interest / competition / family / values
    source: str             # 数据来源字段名（如 math_score, physics_willingness）
    inferred_major: str     # 推断的专业方向
    confidence: float       # 0-1（高/中/低）
    weight: float           # 该信号在聚合中的权重
    reason: str             # 推断依据


@dataclass
class Conflict:
    """冲突检测"""
    conflict_type: str      # capability-intent / personality-intent / family-intent / trend-intent
    severity: str           # warning / alert
    signal_a: str           # 信号A
    signal_b: str           # 信号B（矛盾方）
    description: str        # 冲突描述
    suggestion: str         # 建议


@dataclass
class IntentProfile:
    """用户意愿画像"""
    # ── 明确意愿（用户自己说的）───
    explicit_majors: List[str] = field(default_factory=list)
    explicit_industries: List[str] = field(default_factory=list)
    explicit_confidence: str = 'unknown'  # high / medium / low / none

    # ── 推断意愿（数据告诉我们的）───
    inferred_majors: List[str] = field(default_factory=list)
    inferred_confidence: float = 0  # 0-1
    inferred_signals: List[InferenceSignal] = field(default_factory=list)

    # ── 家庭暗示 ──
    family_majors: List[str] = field(default_factory=list)
    family_budget_level: str = ''    # low / medium / high / very_high

    # ── 冲突检测 ──
    conflicts: List[Conflict] = field(default_factory=list)

    # ── 融合推荐 ──
    # 最终推荐专业列表（按综合得分排序）
    final_recommendations: List[str] = field(default_factory=list)
    # 是否需要追问（置信度低时触发）
    needs_probing: bool = False
    probing_questions: List[str] = field(default_factory=list)


# ── 学科能力 → 专业方向映射 ──
ACADEMIC_SIGNALS = {
    # 数学
    'math_excellent': {
        'condition': lambda q: _is_score_excellent(q, 'math'),
        'majors': ['数学与应用数学', '计算机科学', '统计学', '数据科学', '金融学'],
        'confidence': 0.85,
        'reason': '数学成绩突出（前10%），逻辑/计算能力强',
    },
    'math_good': {
        'condition': lambda q: _is_score_good(q, 'math'),
        'majors': ['计算机科学', '统计学', '电子信息工程', '自动化'],
        'confidence': 0.65,
        'reason': '数学成绩良好（前30%），具备理工科基础',
    },
    # 语文
    'chinese_excellent': {
        'condition': lambda q: _is_score_excellent(q, 'chinese'),
        'majors': ['汉语言文学', '新闻学', '法学', '历史学', '哲学'],
        'confidence': 0.85,
        'reason': '语文成绩突出（前10%），文字/表达能力强',
    },
    'chinese_good': {
        'condition': lambda q: _is_score_good(q, 'chinese'),
        'majors': ['汉语言文学', '法学', '新闻传播学'],
        'confidence': 0.65,
        'reason': '语文成绩良好（前30%），具备文科基础',
    },
    # 英语
    'english_excellent': {
        'condition': lambda q: _is_score_excellent(q, 'english'),
        'majors': ['外国语言文学', '国际关系', '翻译', '国际贸易'],
        'confidence': 0.75,
        'reason': '英语成绩突出（前10%），语言天赋明显',
    },
    'english_good': {
        'condition': lambda q: _is_score_good(q, 'english'),
        'majors': ['外国语言文学', '国际贸易', '新闻传播学'],
        'confidence': 0.55,
        'reason': '英语成绩良好（前30%），适合跨文化方向',
    },
}

# 物理/化学意愿 → 专业方向
SUBJECT_WILLINGNESS = {
    'physics_willing': {
        'condition': lambda q: _has_phys_field(q, 'physics_willingness', ['非常愿意', '比较愿意', '可以考虑']),
        'majors': ['电气工程', '机械工程', '电子信息工程', '自动化', '航空航天'],
        'confidence': 0.8,
        'reason': '物理学科意愿明确',
    },
    'physics_achievement': {
        'condition': lambda q: _has_phys_field(q, 'physics_achievement', ['物理很好', '物理较好']),
        'majors': ['物理学', '应用物理学', '电气工程', '电子信息'],
        'confidence': 0.85,
        'reason': '物理学科成就感强',
    },
    'chemistry_willing': {
        'condition': lambda q: _has_phys_field(q, 'chemistry_willingness', ['非常愿意', '比较愿意', '可以考虑']),
        'majors': ['化学', '材料科学', '药学', '化学工程'],
        'confidence': 0.75,
        'reason': '化学学科意愿明确',
    },
    'chemistry_achievement': {
        'condition': lambda q: _has_phys_field(q, 'chemistry_achievement', ['化学很好', '化学较好']),
        'majors': ['化学', '药学', '材料科学'],
        'confidence': 0.8,
        'reason': '化学学科成就感强',
    },
    'history_willing': {
        'condition': lambda q: _has_phys_field(q, 'history_willingness', ['非常愿意', '比较愿意', '可以考虑']),
        'majors': ['历史学', '考古学', '法学', '行政管理'],
        'confidence': 0.8,
        'reason': '历史学科意愿明确',
    },
    'history_achievement': {
        'condition': lambda q: _has_phys_field(q, 'history_achievement', ['历史很好', '历史较好']),
        'majors': ['历史学', '考古学', '法学'],
        'confidence': 0.85,
        'reason': '历史学科成就感强',
    },
    'language_willing': {
        'condition': lambda q: _has_phys_field(q, 'foreign_language_willingness', ['非常愿意', '比较愿意', '可以考虑']),
        'majors': ['外国语言文学', '翻译', '国际关系', '国际贸易'],
        'confidence': 0.75,
        'reason': '外语学科意愿明确',
    },
}

# 竞赛/优势科 → 专业方向
COMPETITION_SIGNALS = {
    'math_competition': {
        'condition': lambda q: _has_competition(q, ['数学竞赛']),
        'majors': ['数学与应用数学', '计算机科学', '统计学', '金融工程'],
        'confidence': 0.9,
        'reason': '有数学竞赛经历，理科竞赛导向',
    },
    'physics_competition': {
        'condition': lambda q: _has_competition(q, ['物理竞赛']),
        'majors': ['物理学', '电气工程', '电子信息', '自动化'],
        'confidence': 0.9,
        'reason': '有物理竞赛经历，工科竞赛导向',
    },
    'chemistry_competition': {
        'condition': lambda q: _has_competition(q, ['化学竞赛']),
        'majors': ['化学', '材料科学', '药学'],
        'confidence': 0.85,
        'reason': '有化学竞赛经历，化学竞赛导向',
    },
    'biology_competition': {
        'condition': lambda q: _has_competition(q, ['生物竞赛']),
        'majors': ['生物科学', '生物技术', '临床医学', '药学'],
        'confidence': 0.85,
        'reason': '有生物竞赛经历，生命科学竞赛导向',
    },
    'informatics_competition': {
        'condition': lambda q: _has_competition(q, ['信息学竞赛', '编程竞赛']),
        'majors': ['计算机科学与技术', '软件工程', '人工智能', '数据科学'],
        'confidence': 0.95,
        'reason': '有信息学竞赛经历，计算机竞赛导向',
    },
    'advantage_math': {
        'condition': lambda q: q.advantage_1 in ('数学',) or q.advantage_2 in ('数学',),
        'majors': ['数学与应用数学', '计算机科学', '统计学', '金融学'],
        'confidence': 0.8,
        'reason': '用户自认数学为优势学科',
    },
    'advantage_physics': {
        'condition': lambda q: q.advantage_1 in ('物理',) or q.advantage_2 in ('物理',),
        'majors': ['电气工程', '电子信息', '自动化', '机械工程'],
        'confidence': 0.8,
        'reason': '用户自认物理为优势学科',
    },
    'advantage_chinese': {
        'condition': lambda q: q.advantage_1 in ('语文',) or q.advantage_2 in ('语文',),
        'majors': ['汉语言文学', '新闻学', '法学', '哲学'],
        'confidence': 0.75,
        'reason': '用户自认语文为优势学科',
    },
    'advantage_english': {
        'condition': lambda q: q.advantage_1 in ('英语',) or q.advantage_2 in ('英语',),
        'majors': ['外国语言文学', '国际关系', '翻译'],
        'confidence': 0.7,
        'reason': '用户自认英语为优势学科',
    },
}

# 选科组合 → 专业大方向
SUBJECT_COMBO_SIGNALS = {
    '物化生': {
        'majors': ['临床医学', '计算机科学与技术', '电子信息工程', '自动化',
                    '生物科学', '药学', '数据科学'],
        'confidence': 0.75,
        'reason': '物化生组合，覆盖理工农医全方向，理科思维强',
    },
    '物化政': {
        'majors': ['法学', '计算机科学与技术', '电气工程', '行政管理',
                    '会计学', '汉语言文学'],
        'confidence': 0.7,
        'reason': '物化政组合，可报理工+法学/考公专业',
    },
    '物生地': {
        'majors': ['生物科学', '数据科学', '环境工程', '食品科学',
                    '计算机科学与技术'],
        'confidence': 0.65,
        'reason': '物生地组合，偏向生物+数据交叉',
    },
    '史政地': {
        'majors': ['法学', '汉语言文学', '历史学', '新闻传播学',
                    '行政管理', '社会学'],
        'confidence': 0.8,
        'reason': '史政地组合，纯文科思维，适合人文社科',
    },
    '史政生': {
        'majors': ['法学', '汉语言文学', '护理学', '社会工作',
                    '心理学'],
        'confidence': 0.7,
        'reason': '史政生组合，文科+生物，适合医疗人文交叉',
    },
    '史地政': {
        'majors': ['法学', '汉语言文学', '历史学', '思想政治教育',
                    '行政管理'],
        'confidence': 0.8,
        'reason': '史地政组合，纯文科，考公/考编主流方向',
    },
}

# 家庭背景暗示
FAMILY_SIGNALS = {
    'parent_medical': {
        'condition': lambda q: getattr(q, 'parent_occupation', '') in ('医生', '护士', '药师'),
        'majors': ['临床医学', '口腔医学', '药学', '护理学'],
        'confidence': 0.5,
        'reason': '家长从事医疗行业，可能有行业传承倾向',
    },
    'parent_tech': {
        'condition': lambda q: getattr(q, 'parent_occupation', '') in ('技术人员', '程序员', '工程师'),
        'majors': ['计算机科学与技术', '电子信息工程', '自动化', '通信工程'],
        'confidence': 0.4,
        'reason': '家长从事技术领域，可能有行业影响',
    },
    'parent_gov': {
        'condition': lambda q: getattr(q, 'parent_occupation', '') in ('公务员/事业单位',),
        'majors': ['法学', '汉语言文学', '会计学', '行政管理'],
        'confidence': 0.4,
        'reason': '家长在体制内，可能倾向考公方向',
    },
    'parent_business': {
        'condition': lambda q: getattr(q, 'parent_occupation', '') in ('企业高管', '个体经营'),
        'majors': ['工商管理', '金融学', '市场营销', '经济学'],
        'confidence': 0.35,
        'reason': '家长有经商背景，可能倾向商科',
    },
    'budget_high': {
        'condition': lambda q: _normalize_budget_label(q.total_budget) in ('10-15万元', '15万元以上'),
        'majors': ['计算机科学与技术', '金融学', '国际经济与贸易', '外语类'],
        'confidence': 0.3,
        'reason': '家庭预算充裕，可考虑高学费/出国方向',
    },
}

# 深造意向 → 专业方向
FURTHER_STUDY_SIGNALS = {
    '考公务员': {
        'majors': ['法学', '汉语言文学', '计算机科学与技术', '会计学',
                    '行政管理', '审计学', '财政学'],
        'confidence': 0.85,
        'reason': '有考公意向，推荐考公热门专业',
    },
    '考事业单位': {
        'majors': ['教育学', '汉语言文学', '护理学', '计算机科学与技术'],
        'confidence': 0.75,
        'reason': '有考编意向，推荐事业单位对口专业',
    },
    '国内考研': {
        'majors': ['数学与应用数学', '物理学', '化学', '生物学',
                    '计算机科学与技术', '临床医学'],
        'confidence': 0.7,
        'reason': '考研导向，基础学科更容易深造',
    },
    '国内保研': {
        'majors': ['数学与应用数学', '计算机科学与技术', '临床医学', '法学'],
        'confidence': 0.7,
        'reason': '保研导向，需要学科实力强的学校',
    },
    '出国读研': {
        'majors': ['计算机科学与技术', '数学', '物理学', '化学',
                    '生物工程', '材料科学', '电气工程'],
        'confidence': 0.65,
        'reason': '出国导向，国际认可度高的基础/工科专业',
    },
    '直接就业': {
        'majors': ['计算机科学与技术', '软件工程', '电气工程', '自动化',
                    '财务管理', '护理学'],
        'confidence': 0.7,
        'reason': '就业导向，应用型专业优先',
    },
    '创业': {
        'majors': ['工商管理', '电子商务', '计算机科学与技术', '市场营销'],
        'confidence': 0.5,
        'reason': '创业导向，需要商业+技术复合能力',
    },
}


# ──────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────

def _is_score_excellent(q, subject: str) -> bool:
    """判断科目是否优秀（前10%）"""
    rank_map = {
        'math': (q.math_score, q.math_rank_pct),
        'chinese': (q.chinese_score, q.chinese_rank_pct),
        'english': (q.english_score, q.english_rank_pct),
    }
    score, rank = rank_map.get(subject, (None, ''))
    return rank in ('前5%', '前10%') or (score and score >= 135)


def _is_score_good(q, subject: str) -> bool:
    """判断科目是否良好（前30%）"""
    rank_map = {
        'math': (q.math_score, q.math_rank_pct),
        'chinese': (q.chinese_score, q.chinese_rank_pct),
        'english': (q.english_score, q.english_rank_pct),
    }
    score, rank = rank_map.get(subject, (None, ''))
    return rank in ('前10-30%', '前30%') or (score and 110 <= score < 135)


def _has_phys_field(q, field_name: str, values: List[str]) -> bool:
    """检查问卷字段是否匹配"""
    val = getattr(q, field_name, '')
    return val in values


def _has_competition(q, names: List[str]) -> bool:
    """检查竞赛是否包含指定名称"""
    return any(name in (q.competitions or []) for name in names)


def _get_subject_combo(q) -> str:
    """获取选科组合（标准化）"""
    combo = q.subject_combo or ''
    # 标准化：物理+化学+生物 → 物化生
    combo = combo.replace('物理', '物').replace('化学', '化')
    combo = combo.replace('生物', '生').replace('政治', '政')
    combo = combo.replace('地理', '地').replace('历史', '史')
    combo = combo.replace('+', '').replace(' ', '')
    return combo


def _normalize_budget_label(budget: str) -> str:
    aliases = {
        '2-4万': '2-4万元',
        '4-6万': '4-6万元',
        '6-10万': '6-10万元',
        '10-15万': '10-15万元',
        '15万以上': '15万元以上',
    }
    return aliases.get(budget or '', budget or '')


# ──────────────────────────────────────────
# 推断引擎
# ──────────────────────────────────────────

class IntentionInferenceEngine:
    """意愿推断引擎 V1.0"""

    def __init__(self):
        self._all_signals = {}
        self._all_signals.update(ACADEMIC_SIGNALS)
        self._all_signals.update(SUBJECT_WILLINGNESS)
        self._all_signals.update(COMPETITION_SIGNALS)
        self._all_signals.update(FAMILY_SIGNALS)
        # SUBJECT_COMBO_SIGNALS and FURTHER_STUDY_SIGNALS handled separately in infer()

    def infer(self, questionnaire) -> IntentProfile:
        """
        执行完整推断

        返回: IntentProfile 意愿画像
        """
        profile = IntentProfile()

        # ── Step 1: 提取明确意愿 ──
        profile.explicit_majors = list(questionnaire.vertical_majors or [])
        profile.explicit_majors = [m for m in profile.explicit_majors if m != '都不考虑']
        profile.explicit_industries = list(questionnaire.target_industries or [])

        # 明确意愿置信度
        has_majors = bool(profile.explicit_majors)
        has_industries = bool(profile.explicit_industries)
        # P1-normal #7: civil_service 兼容字符串和列表两种类型
        _cs = questionnaire.civil_service or ''
        if isinstance(_cs, list):
            has_civil_service = any(v in ('必须保留', '优先考虑') for v in _cs)
        else:
            has_civil_service = _cs in ('必须保留', '优先考虑')
        has_further_study = False
        _fs_raw = questionnaire.further_study
        if isinstance(_fs_raw, list) and _fs_raw:
            has_further_study = True
        elif isinstance(_fs_raw, str) and _fs_raw.strip():
            has_further_study = True

        if has_majors and (has_industries or has_civil_service):
            profile.explicit_confidence = 'high'
        elif has_majors or (has_industries and has_civil_service):
            profile.explicit_confidence = 'medium'
        elif has_industries or has_civil_service or has_further_study:
            profile.explicit_confidence = 'low'
        else:
            profile.explicit_confidence = 'none'

        # ── Step 2: 信号推断 ──
        inferred_majors = []
        total_weight = 0

        for signal_name, signal_def in self._all_signals.items():
            if signal_def['condition'](questionnaire):
                sig = InferenceSignal(
                    signal_type=self._classify_signal_type(signal_name),
                    source=signal_name,
                    inferred_major=signal_def['majors'][0],
                    confidence=signal_def['confidence'],
                    weight=signal_def['confidence'] * self._get_signal_weight(signal_name),
                    reason=signal_def['reason'],
                )
                profile.inferred_signals.append(sig)
                inferred_majors.extend(signal_def['majors'])
                total_weight += sig.weight

        # 按信号权重聚合推断专业
        profile.inferred_majors = self._aggregate_majors(inferred_majors, top_n=15)

        if profile.inferred_signals:
            avg_conf = sum(s.confidence for s in profile.inferred_signals) / len(profile.inferred_signals)
            profile.inferred_confidence = min(1.0, avg_conf * (1 + len(profile.inferred_signals) * 0.05))

        # ── Step 3: 选科组合推断 ──
        combo = _get_subject_combo(questionnaire)
        if combo in SUBJECT_COMBO_SIGNALS:
            combo_def = SUBJECT_COMBO_SIGNALS[combo]
            sig = InferenceSignal(
                signal_type='subject_combo',
                source=f'subject_combo:{combo}',
                inferred_major=combo_def['majors'][0],
                confidence=combo_def['confidence'],
                weight=combo_def['confidence'] * 0.8,
                reason=combo_def['reason'],
            )
            profile.inferred_signals.append(sig)
            profile.inferred_majors.extend(combo_def['majors'])
            profile.inferred_majors = self._aggregate_majors(profile.inferred_majors, top_n=15)

        # ── Step 4: 深造意向推断 ──
        family_majors = []
        _fs_raw = questionnaire.further_study or []
        if isinstance(_fs_raw, str):
            _fs_raw = [_fs_raw]  # 兼容字符串形式
        for plan in _fs_raw:
            # P1-urgent #5: 兼容 dict（问卷答案可能是 {label: '考公务员'} 等形式）
            if isinstance(plan, dict):
                plan = plan.get('label', '') or plan.get('value', '') or plan.get('text', '')
            if isinstance(plan, str) and plan in FURTHER_STUDY_SIGNALS:
                fs = FURTHER_STUDY_SIGNALS[plan]
                family_majors.extend(fs['majors'])

        # 考公意向单独处理
        cs_pref = questionnaire.civil_service or ''
        if cs_pref in ('必须保留', '优先考虑'):
            family_majors.extend(['法学', '汉语言文学', '计算机科学与技术',
                                   '会计学', '行政管理', '审计学', '财政学'])

        profile.family_majors = self._aggregate_majors(family_majors, top_n=10)

        # ── Step 5: 预算等级 ──
        budget_map = {
            '2万元以内': 'low',
            '2-4万元': 'low',
            '4-6万元': 'medium',
            '6-10万元': 'high',
            '10-15万元': 'very_high',
            '15万元以上': 'very_high',
        }
        profile.family_budget_level = budget_map.get(
            _normalize_budget_label(questionnaire.total_budget), ''
        )

        # ── Step 6: 冲突检测 ──
        self._detect_conflicts(profile, questionnaire)

        # ── Step 7: 融合推荐 ──
        profile.final_recommendations = self._fuse_recommendations(profile)

        # ── Step 8: 是否需要追问 ──
        self._check_probing(profile, questionnaire)

        return profile

    # ──────────────────────────────────────────
    # 私有方法
    # ──────────────────────────────────────────

    def _classify_signal_type(self, name: str) -> str:
        """判断信号类型"""
        if name.startswith('math_') or name.startswith('chinese_') or name.startswith('english_'):
            return 'academic'
        if name.startswith('physics_') or name.startswith('chemistry_') or name.startswith('history_'):
            return 'interest'
        if name.startswith('advantage_') or name.endswith('_competition'):
            return 'competition'
        if name.startswith('parent_') or name.startswith('budget_'):
            return 'family'
        return 'values'

    def _get_signal_weight(self, name: str) -> float:
        """信号权重（竞赛 > 学科能力 > 家庭 > 其他）"""
        if '_competition' in name:
            return 1.5
        if name.startswith('math_') or name.startswith('chinese_'):
            return 1.2
        if name.startswith('parent_') or name.startswith('budget_'):
            return 0.5
        return 1.0

    def _aggregate_majors(self, majors: List[str], top_n: int = 15) -> List[str]:
        """聚合专业列表（去重 + 频次排序）"""
        counts = {}
        for m in majors:
            counts[m] = counts.get(m, 0) + 1
        sorted_majors = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [m for m, c in sorted_majors[:top_n]]

    def _find_overlap(self, set_a: set, set_b: set) -> set:
        """找两个专业集合的交集（支持模糊匹配）"""
        overlap = set()
        for a in set_a:
            for b in set_b:
                # 精确匹配
                if a == b:
                    overlap.add(a)
                # 包含匹配（如"计算机科学与技术"包含"计算机科学"）
                elif a in b or b in a:
                    overlap.add(a)
                # 关键词匹配（共享3+个连续字）
                else:
                    for i in range(len(a) - 2):
                        sub = a[i:i+3]
                        if sub in b:
                            overlap.add(a)
                            break
        return overlap

    def _detect_conflicts(self, profile: IntentProfile, questionnaire):
        """冲突检测"""
        explicit = set(profile.explicit_majors)
        inferred = set(profile.inferred_majors)
        family = set(profile.family_majors)

        # 冲突1: 明确意愿 vs 推断意愿（用户想学的 vs 数据说的）
        if explicit and inferred:
            overlap = self._find_overlap(explicit, inferred)
            if len(overlap) == 0:
                profile.conflicts.append(Conflict(
                    conflict_type='capability-intent',
                    severity='alert',
                    signal_a=f'用户意愿: {", ".join(list(explicit)[:3])}',
                    signal_b=f'能力推断: {", ".join(list(inferred)[:3])}',
                    description='用户明确意愿与数据推断的专业方向无交集',
                    suggestion='建议与考生沟通：是坚持个人意愿，还是考虑数据建议的方向？',
                ))

        # 冲突2: 能力不足
        weak_subjects = self._detect_weak_subjects(questionnaire)
        if weak_subjects:
            req_majors = []
            if '数学' in weak_subjects:
                # 数学弱但想学计算机/金融
                for m in profile.explicit_majors:
                    if any(k in m for k in ['计算机', '金融', '数学', '数据', '统计']):
                        req_majors.append(m)
            if req_majors:
                profile.conflicts.append(Conflict(
                    conflict_type='capability-intent',
                    severity='alert',
                    signal_a=f'弱项科目: {", ".join(weak_subjects)}',
                    signal_b=f'目标专业: {", ".join(req_majors)}',
                    description='目标专业对弱项科目有较高要求，学习可能困难',
                    suggestion='建议：考虑对该科目要求较低的相关专业',
                ))

        # 冲突3: 家庭预算 vs 意向
        budget = profile.family_budget_level
        if budget == 'low' and '出国读研' in (questionnaire.further_study or []):
            profile.conflicts.append(Conflict(
                conflict_type='family-intent',
                severity='warning',
                signal_a='家庭预算紧张',
                signal_b='出国读研意向',
                description='家庭预算有限，出国读研可能增加经济压力',
                suggestion='建议：考虑国内考研或公费出国项目',
            ))

        # 冲突4: 目标专业撤销风险（按专业级查询，不按专业类一刀切）
        for m in profile.explicit_majors:
            risk = get_revocation_risk(m, '')  # 不指定学校，查全国趋势
            if risk['level'] >= 2:
                profile.conflicts.append(Conflict(
                    conflict_type='trend-intent',
                    severity='warning',
                    signal_a=f'目标专业: {m}',
                    signal_b=risk['label'],
                    description=f'{m}近5年被较多高校撤销（{risk["details"].get("tier_breakdown", {})}），建议关注该专业的最新就业数据',
                    suggestion='建议：选择该专业时重点关注学校的办学实力和行业认可度',
                ))

    def _detect_weak_subjects(self, questionnaire) -> List[str]:
        """检测弱势科目"""
        weak = []
        for subject, (score_field, rank_field) in [
            ('数学', ('math_score', 'math_rank_pct')),
            ('语文', ('chinese_score', 'chinese_rank_pct')),
            ('英语', ('english_score', 'english_rank_pct')),
        ]:
            score = getattr(questionnaire, score_field, None)
            rank = getattr(questionnaire, rank_field, '')
            if rank in ('后30%', '后50%') or (score and score <= 90):
                weak.append(subject)
        return weak

    def _fuse_recommendations(self, profile: IntentProfile) -> List[str]:
        """
        融合推荐：意愿优先级 > 推断
        最终排序规则：
        1. 明确意愿（最高）
        2. 深造意向推荐（补充）
        3. 推断意愿（补充）
        """
        seen = set()
        result = []

        def _add(major: str):
            if major and major not in seen:
                result.append(major)
                seen.add(major)

        # 第1优先级：明确意愿（按用户输入顺序）
        for m in profile.explicit_majors:
            _add(m)

        # P2-fix: 移除优先级2死代码——优先级1已将所有explicit_majors加入seen，
        # 原"明确意愿+推断共识"循环中 m not in seen 永远为False，从未执行。

        # 第2优先级：深造意向推荐
        for m in profile.family_majors:
            if m not in seen:
                _add(m)

        # 第4优先级：推断意愿（补充）
        for m in profile.inferred_majors:
            _add(m)

        # 第5优先级：家庭预算暗示（高预算可补充出国导向专业）
        if profile.family_budget_level in ('very_high', 'high'):
            for m in ['计算机科学与技术', '金融学', '国际经济与贸易', '外语类']:
                _add(m)

        return result[:25]

    def _check_probing(self, profile: IntentProfile, questionnaire):
        """检查是否需要追问"""
        profile.needs_probing = False
        profile.probing_questions = []

        # 情形1: 明确意愿为none + 推断置信度也低
        if profile.explicit_confidence == 'none' and profile.inferred_confidence < 0.5:
            profile.needs_probing = True
            profile.probing_questions = [
                '你对什么学科比较感兴趣？',
                '你希望将来从事什么类型的工作？',
                '你平时最喜欢做什么？',
            ]

        # 情形1.5: 明确意愿为none + 推断信号不足（少于3个）
        elif profile.explicit_confidence == 'none' and len(profile.inferred_signals) < 3:
            profile.needs_probing = True
            profile.probing_questions = [
                '我们对你的兴趣方向了解不够，能多说说你的想法吗？',
                '你平时更喜欢理科还是文科？',
            ]

        # 情形2: 有明确冲突
        if len(profile.conflicts) >= 2:
            profile.needs_probing = True
            profile.probing_questions = [
                '你的目标专业与能力推断存在差异，你更倾向于哪个方向？',
                '你对未来的规划是否考虑过风险因素？',
            ]

        # 情形3: 明确意愿为low（有模糊意向但不够明确）
        elif profile.explicit_confidence == 'low':
            profile.needs_probing = True
            profile.probing_questions = [
                '你的意向还不够明确，能多说说你的想法吗？',
            ]
