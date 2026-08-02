# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
偏好问卷辅助引擎 V3.0
实现四项项目自编问卷：
1. 大五维度偏好问卷 — 50题，5维度，含反向计分
2. RIASEC 风格兴趣偏好问卷 — 76题，迫选配对计分
3. 学科自我评价问卷 — 15题，3维度（语文/数学/英语）
4. 职业价值偏好问卷 — 20题，10维度

输出：大五维度 + RIASEC 风格代码 + 学科自我评价 + 职业价值偏好 + 专业方向TOP10。
题面未经心理测量学验证，不是标准化心理量表，也不作诊断。
"""
from typing import Dict, List, Tuple
from dataclasses import dataclass, field


# ── A-08题号配置集中管理 ──
# 物理类: 学科自我评价起始题号76, 职业价值偏好起始题号91
# 历史类: 学科自我评价起始题号77, 职业价值偏好起始题号92
QUESTION_BASES = {
    'physics':  {'self_efficacy': 76, 'career_values': 91},
    'history':  {'self_efficacy': 77, 'career_values': 92},
}


@dataclass
class TestResult:
    """项目自编偏好问卷结果"""
    big_five: Dict[str, float]          # 大五维度得分 {O, C, E, A, N}
    holland_code: str                   # RIASEC 风格代码（如RIA，字段名为兼容保留）
    holland_scores: Dict[str, int]      # RIASEC 风格各维度原始分
    self_efficacy: Dict[str, float]     # 学科自我评价 {chinese, math, english}
    career_values: Dict[str, float]     # 职业价值偏好10维度得分
    sd_score: int                       # 社会赞许性检测分数
    confidence: str                     # 置信度 high/medium/low
    recommendations: List[str]          # 专业推荐TOP10


# ──────────────────────────────────────────
# RIASEC 风格迫选配对表：每道题 (A维度, B维度)
# 选A→A维度+1分，选B→B维度+1分
# ──────────────────────────────────────────
RIASEC_PAIRS: Dict[int, Tuple[str, str]] = {
    # 组1: R vs I（动手操作 vs 分析思考）
    1: ('R', 'I'),   2: ('R', 'I'),   3: ('R', 'I'),   4: ('R', 'I'),
    5: ('R', 'I'),   6: ('R', 'I'),   7: ('R', 'I'),
    # 组2: A vs S（创造表达 vs 助人互动）
    8: ('A', 'S'),   9: ('A', 'S'),   10: ('A', 'S'),  11: ('A', 'S'),
    12: ('A', 'S'),  13: ('A', 'S'),
    # 组3: E vs C（影响领导 vs 组织秩序）
    14: ('E', 'C'),  15: ('E', 'C'),  16: ('E', 'C'),  17: ('E', 'C'),
    18: ('E', 'C'),  19: ('E', 'C'),
    # 组4: R vs A（动手操作 vs 创造表达）
    20: ('R', 'A'),  21: ('R', 'A'),  22: ('R', 'A'),  23: ('R', 'A'),
    24: ('R', 'A'),  25: ('R', 'A'),
    # 组5: I vs E（分析思考 vs 影响领导）
    26: ('I', 'E'),  27: ('I', 'E'),  28: ('I', 'E'),  29: ('I', 'E'),
    30: ('I', 'E'),  31: ('I', 'E'),
    # 组6: S vs C（助人互动 vs 组织秩序）
    32: ('S', 'C'),  33: ('S', 'C'),  34: ('S', 'C'),  35: ('S', 'C'),
    36: ('S', 'C'),  37: ('S', 'C'),
    # 组7: R vs S（动手操作 vs 助人互动）
    38: ('R', 'S'),  39: ('R', 'S'),  40: ('R', 'S'),  41: ('R', 'S'),
    42: ('R', 'S'),  43: ('R', 'S'),
    # 组8: I vs A（分析思考 vs 创造表达）
    44: ('I', 'A'),  45: ('I', 'A'),  46: ('I', 'A'),  47: ('I', 'A'),
    48: ('I', 'A'),  49: ('I', 'A'),
    # 组9: E vs R（影响领导 vs 动手操作）
    50: ('E', 'R'),  51: ('E', 'R'),  52: ('E', 'R'),  53: ('E', 'R'),
    54: ('E', 'R'),  55: ('E', 'R'),
    # 组10: C vs I（组织秩序 vs 分析思考）
    56: ('C', 'I'),  57: ('C', 'I'),  58: ('C', 'I'),  59: ('C', 'I'),
    60: ('C', 'I'),  61: ('C', 'I'),
    # 组11: A vs E（创造表达 vs 影响领导）
    62: ('A', 'E'),  63: ('A', 'E'),  64: ('A', 'E'),  65: ('A', 'E'),
    66: ('A', 'E'),  67: ('A', 'E'),
    # 组12: S vs R（助人互动 vs 动手操作）
    68: ('S', 'R'),  69: ('S', 'R'),  70: ('S', 'R'),  71: ('S', 'R'),
    72: ('S', 'R'),  73: ('S', 'R'),
    # 组13: C vs A（组织秩序 vs 创造表达）
    74: ('C', 'A'),  75: ('C', 'A'),  76: ('C', 'A'),
}

# 默认维度映射（未配对题目fallback）
_DEFAULT_DIM = {
    'R': list(range(1, 14)),
    'I': list(range(14, 26)),
    'A': list(range(26, 38)),
    'S': list(range(38, 50)),
    'E': list(range(50, 62)),
    'C': list(range(62, 74)),
}


class PersonalityTestEngine:
    """性格职业测试引擎 V3.0"""

    # ── 项目自编大五维度定义 ──
    BIG_FIVE = {
        'O': {'正向': [1, 2, 3, 4, 5, 6, 9, 10], '反向': [7, 8]},
        'C': {'正向': [11, 12, 13, 14, 15, 17, 19, 20], '反向': [16, 18]},
        'E': {'正向': [21, 22, 23, 24, 25, 26, 29, 30], '反向': [27, 28]},
        'A': {'正向': [31, 32, 33, 34, 35, 36, 39, 40], '反向': [37, 38]},
        'N': {'正向': [41, 42, 43, 44, 45, 46, 49, 50], '反向': [47, 48]},
    }

    # ── 项目自编学科自我评价题号映射 ──
    SELF_EFFICACY = {
        'chinese': list(range(1, 6)),   # q76-q80 (语文5题)
        'math':    list(range(6, 11)),  # q81-q85 (数学5题)
        'english': list(range(11, 16)), # q86-q90 (英语5题)
    }

    # ── 项目自编职业价值偏好维度定义（10维度×2题）───
    CAREER_VALUES = {
        'income':      [1, 2],   # q91-q92  收入水平
        'stability':   [3, 4],   # q93-q94  工作稳定
        'achievement': [5, 6],   # q95-q96  成就感
        'help':        [7, 8],   # q97-q98  帮助他人
        'creative':    [9, 10],  # q99-q100 创造力
        'balance':     [11, 12], # q101-q102 工作生活平衡
        'leadership':  [13, 14], # q103-q104 领导力
        'autonomy':    [15, 16], # q105-q106 独立性
        'location':    [17, 18], # q107-q108 地域偏好
        'learning':    [19, 20], # q109-q110 持续学习
    }

    # ── RIASEC 风格维度→专业方向 ──
    HOLLAND_MAJOR_MAP = {
        'R': ['机械工程', '电气工程', '土木工程', '汽车工程'],
        'I': ['计算机科学', '物理学', '数学', '化学'],
        'A': ['艺术设计', '音乐表演', '影视制作', '建筑学'],
        'S': ['教育学', '心理学', '医学', '社会工作'],
        'E': ['工商管理', '金融学', '市场营销', '法学'],
        'C': ['会计学', '信息管理', '行政管理', '统计学'],
    }

    # ── 大五维度→专业倾向修正 ──
    BIG_FIVE_MAJOR_BOOST = {
        # 高开放性 → 偏创意/研究型
        'O_high':  ['艺术设计', '影视制作', '哲学', '建筑学', '新闻传播'],
        # 高尽责性 → 偏条理/执行型
        'C_high':  ['会计学', '法学', '行政管理', '医学', '信息管理'],
        # 高外向性 → 偏社交/领导型
        'E_high':  ['市场营销', '新闻传播', '工商管理', '法学', '教育学'],
        # 高宜人性 → 偏助人/合作型
        'A_high':  ['教育学', '心理学', '社会工作', '护理学', '人力资源管理'],
        # 低神经质（情绪稳定）→ 可承受高压专业
        'N_low':   ['金融学', '法学', '临床医学', '工商管理', '计算机科学'],
    }

    # ── 学科自我评价→专业倾向修正 ──
    EFFICACY_MAJOR_BOOST = {
        # 高语文效能 → 偏文字/语言型
        'chinese_high': ['中国语言文学', '新闻传播', '历史学', '哲学', '法学'],
        # 高数学效能 → 偏逻辑/数据型
        'math_high':    ['计算机科学', '数学', '统计学', '金融学', '数据科学'],
        # 高英语效能 → 偏外语/跨文化型
        'english_high':  ['外语类', '国际关系', '新闻传播', '国际贸易', '旅游管理'],
    }

    # ── 职业价值偏好→专业倾向修正 ──
    VALUES_MAJOR_BOOST = {
        'income_high':      ['金融学', '计算机科学', '工商管理', '法学', '市场营销'],
        'stability_high':   ['教育学', '行政管理', '医学', '会计学', '汉语言文学'],
        'creative_high':    ['艺术设计', '建筑学', '影视制作', '广告学', '音乐表演'],
        'help_high':        ['教育学', '心理学', '医学', '社会工作', '护理学'],
        'leadership_high':  ['工商管理', '法学', '政治学', '行政管理', '金融学'],
    }

    # ──────────────────────────────────────────
    # 核心计算
    # ──────────────────────────────────────────

    def calculate_big_five(self, answers: Dict[int, int]) -> Dict[str, float]:
        """
        计算项目自编大五维度问卷得分

        参数:
            answers: {题号: 得分(1-5)}

        返回:
            {'O': 4.2, 'C': 3.8, 'E': 3.5, 'A': 4.0, 'N': 2.8}
        """
        scores = {}
        for dim, qs in self.BIG_FIVE.items():
            vals = []
            for q in qs['正向']:
                if q in answers:
                    vals.append(answers[q])
            for q in qs['反向']:
                if q in answers:
                    vals.append(6 - answers[q])  # 反向计分
            scores[dim] = round(sum(vals) / len(vals), 1) if vals else 0.0
        return scores

    def calculate_holland(self, answers: Dict[int, str]) -> Tuple[str, Dict[str, int], bool]:
        """
        计算项目自编 RIASEC 风格代码（迫选配对计分）

        参数:
            answers: {题号: 'A'或'B'}

        返回:
            (职业代码如'RIA', {各维度原始分}, has_tie: 第3/4位是否平分)
        """
        scores = {'R': 0, 'I': 0, 'A': 0, 'S': 0, 'E': 0, 'C': 0}

        for q_num, choice in answers.items():
            if q_num in RIASEC_PAIRS:
                dim_a, dim_b = RIASEC_PAIRS[q_num]
                if choice == 'A':
                    scores[dim_a] += 1
                elif choice == 'B':
                    scores[dim_b] += 1
            else:
                # fallback: 按题号所在范围判断默认维度
                for dim, q_range in _DEFAULT_DIM.items():
                    if q_num in q_range:
                        scores[dim] += 1
                        break

        # 取前3个高分维度
        sorted_dims = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        code = ''.join([d[0] for d in sorted_dims[:3]])

        # H-01: 检测平分 — 若第3与第4维度分数相同，置信度应降级
        has_tie = False
        if len(sorted_dims) >= 4 and sorted_dims[2][1] == sorted_dims[3][1]:
            has_tie = True

        return code, scores, has_tie

    def calculate_self_efficacy(self, answers: Dict[int, int],
                                 category: str = 'physics') -> Dict[str, float]:
        """
        计算项目自编学科自我评价

        参数:
            answers: {全局题号: 得分(1-5)}
            category: 'physics' 或 'history'
                     物理类: 语文q76-q80, 数学q81-q85, 英语q86-q90
                     历史类: 语文q77-q81, 数学q82-q86, 英语q87-q91

        返回:
            {'chinese': 3.8, 'math': 3.2, 'english': 4.0}
        """
        efficacy = {}
        # 物理类起始题号76，历史类起始题号77
        base = QUESTION_BASES[category]['self_efficacy']

        for subject, local_indices in self.SELF_EFFICACY.items():
            vals = []
            for local_idx in local_indices:
                # 全局题号 = base + 局部索引-1
                global_q = base + local_idx - 1
                if global_q in answers:
                    vals.append(answers[global_q])
            efficacy[subject] = round(sum(vals) / len(vals), 1) if vals else 0.0

        return efficacy

    def calculate_career_values(self, answers: Dict[int, int],
                                 category: str = 'physics') -> Dict[str, float]:
        """
        计算项目自编职业价值偏好

        参数:
            answers: {全局题号: 得分(1-5)}
            category: 'physics' 或 'history'
                     物理类: q91-q110
                     历史类: q92-q111（偏移+1）

        返回:
            {'income': 3.5, 'stability': 4.0, ...} 共10个维度
        """
        values = {}
        # 物理类起始题号91，历史类起始题号92
        base = QUESTION_BASES[category]['career_values']

        for dimension, local_indices in self.CAREER_VALUES.items():
            vals = []
            for local_idx in local_indices:
                global_q = base + local_idx - 1
                if global_q in answers:
                    vals.append(answers[global_q])
            values[dimension] = round(sum(vals) / len(vals), 1) if vals else 0.0

        return values

    # ──────────────────────────────────────────
    # 推荐生成（融合大五维度 + RIASEC 风格 + 学科自我评价 + 职业价值偏好）
    # ──────────────────────────────────────────

    def generate_recommendations(
        self,
        big_five: Dict[str, float],
        holland_code: str,
        self_efficacy: Dict[str, float],
        career_values: Dict[str, float],
    ) -> List[str]:
        """
        生成专业推荐TOP10

        融合策略：
        1. RIASEC 风格代码 → 基础推荐（6个专业）
        2. 大五维度 → 倾向修正（+3-5个专业，加权）
        3. 学科自我评价 → 优势学科方向修正
        4. 职业价值偏好 → 方向匹配修正
        5. 去重 + 加权排序 → TOP10
        """
        # 步骤1: RIASEC 风格基础推荐（带权重）
        candidate_scores: Dict[str, float] = {}

        for code in holland_code:
            if code in self.HOLLAND_MAJOR_MAP:
                weight = 3.0 if code == holland_code[0] else 2.0 if code == holland_code[1] else 1.0
                for major in self.HOLLAND_MAJOR_MAP[code]:
                    candidate_scores[major] = candidate_scores.get(major, 0) + weight

        # 步骤2: 大五维度倾向修正（A-05: 梯度权重，避免阈值悬崖）
        for dim, boost_key in [('O', 'O_high'), ('C', 'C_high'), ('E', 'E_high'), ('A', 'A_high')]:
            w = self._gradient_weight(big_five.get(dim, 0))
            if w > 0:
                self._boost_candidates(candidate_scores, self.BIG_FIVE_MAJOR_BOOST[boost_key], w)
        # N低分→更稳定（反向梯度）
        n_w = self._gradient_weight(5.0 - big_five.get('N', 3))
        if n_w > 0:
            self._boost_candidates(candidate_scores, self.BIG_FIVE_MAJOR_BOOST['N_low'], n_w)

        # 步骤3: 学科自我评价修正（A-05: 梯度权重）
        for subj, boost_key in [('chinese', 'chinese_high'), ('math', 'math_high'), ('english', 'english_high')]:
            w = self._gradient_weight(self_efficacy.get(subj, 0))
            if w > 0:
                self._boost_candidates(candidate_scores, self.EFFICACY_MAJOR_BOOST[boost_key], w)

        # 步骤4: 职业价值偏好修正（A-05: 梯度权重，取最高3维度）
        sorted_values = sorted(career_values.items(), key=lambda x: x[1], reverse=True)
        for val_name, val_score in sorted_values[:3]:
            w = self._gradient_weight(val_score, max_weight=1.0)
            if w > 0 and val_name in self.VALUES_MAJOR_BOOST:
                self._boost_candidates(candidate_scores, self.VALUES_MAJOR_BOOST[val_name], w)

        # 步骤5: 排序去重 → TOP10
        sorted_majors = sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)
        return [m[0] for m in sorted_majors[:10]]

    @staticmethod
    def _boost_candidates(scores: Dict[str, float], majors: List[str], weight: float):
        """为候选专业加分"""
        for major in majors:
            scores[major] = scores.get(major, 0) + weight

    # ── A-05 梯度权重（避免阈值悬崖）───
    @staticmethod
    def _gradient_weight(score: float, low: float = 3.0, high: float = 4.0,
                         max_weight: float = 1.5) -> float:
        """
        梯度权重: score < low → 0, low≤score<high → 线性插值, score ≥ high → max_weight
        """
        if score < low:
            return 0.0
        if score >= high:
            return max_weight
        # H-6 fix: 防止 low == high 导致除零
        if high == low:
            return max_weight if score >= low else 0.0
        return round((score - low) / (high - low) * max_weight, 2)

    # ──────────────────────────────────────────
    # SD检测（社会赞许性）
    # ──────────────────────────────────────────

    def calculate_sd(self, big_five_answers: Dict[int, int],
                     efficacy_answers: Dict[int, int],
                     category: str = 'physics') -> int:
        """
        社会赞许性检测

        AUDIT-P1-022: SD检测题号根据 category 动态适配。
        物理类自我效能起始题号=76（检测题78,81），历史类=77（检测题79,82）。

        检测题：
        - 大五维度第12题（尽责性正向）选5分→计1分
        - 大五维度第24题（外向性正向）选5分→计1分
        - 学科自我评价第3题（base+2）选5分→计1分
        - 学科自我评价第6题（base+5）选5分→计1分

        返回: 0-4分
        """
        base = QUESTION_BASES.get(category, QUESTION_BASES['physics'])['self_efficacy']
        sd = 0
        # 大五维度第12题（尽责性正向，倾向于选"好"的答案）
        if 12 in big_five_answers and big_five_answers[12] == 5:
            sd += 1
        # 大五维度第24题（外向性正向）
        if 24 in big_five_answers and big_five_answers[24] == 5:
            sd += 1
        # 学科自我评价题中明显"全选高分"的检测
        # 第3题（语文效能，base+2：物理78/历史79）
        if (base + 2) in efficacy_answers and efficacy_answers[(base + 2)] == 5:
            sd += 1
        # 第6题（数学效能，base+5：物理81/历史82）
        if (base + 5) in efficacy_answers and efficacy_answers[(base + 5)] == 5:
            sd += 1
        return sd

    # ──────────────────────────────────────────
    # 总入口
    # ──────────────────────────────────────────

    def run_test(
        self,
        big_five_answers: Dict[int, int],
        holland_answers: Dict[int, str],
        efficacy_answers: Dict[int, int],
        career_values_answers: Dict[int, int],
        category: str = 'physics',
    ) -> TestResult:
        """
        运行完整测试

        参数:
            big_five_answers:     大五维度问卷答案 {题号: 1-5分}
            holland_answers:      RIASEC 风格问卷答案 {题号: 'A'或'B'}
            efficacy_answers:     学科自我评价答案 {全局题号: 1-5分}
            career_values_answers: 职业价值偏好答案 {全局题号: 1-5分}
            category:             'physics' 或 'history'（用于题号映射）

        返回:
            TestResult对象
        """
        big_five = self.calculate_big_five(big_five_answers)
        holland_code, holland_scores, holland_has_tie = self.calculate_holland(holland_answers)
        self_efficacy = self.calculate_self_efficacy(efficacy_answers, category)
        career_values = self.calculate_career_values(career_values_answers, category)
        sd_score = self.calculate_sd(big_five_answers, efficacy_answers, category)

        recommendations = self.generate_recommendations(
            big_five, holland_code, self_efficacy, career_values
        )

        # 置信度: SD检测为主，RIASEC 风格维度平分降级
        if sd_score == 0:
            confidence = 'medium' if holland_has_tie else 'high'
        elif sd_score <= 2:
            confidence = 'medium'  # P1-fix: sd_score 1-2 应为 medium，而非 low
        else:
            confidence = 'low'

        return TestResult(
            big_five=big_five,
            holland_code=holland_code,
            holland_scores=holland_scores,
            self_efficacy=self_efficacy,
            career_values=career_values,
            confidence=confidence,
            sd_score=sd_score,
            recommendations=recommendations,
        )


def main():
    """测试用例"""
    engine = PersonalityTestEngine()

    print('=' * 70)
    print('偏好问卷辅助引擎 V3.0（项目自编，非心理诊断）')
    print('=' * 70)

    # ── 大五维度偏好（50题，1-5分）───
    big_five_answers = {
        1: 4, 2: 5, 3: 3, 4: 4, 5: 5, 6: 4, 7: 2, 8: 3, 9: 5, 10: 4,
        11: 4, 12: 5, 13: 3, 14: 4, 15: 5, 16: 2, 17: 4, 18: 3, 19: 5, 20: 4,
        21: 3, 22: 4, 23: 5, 24: 3, 25: 4, 26: 3, 27: 2, 28: 3, 29: 4, 30: 3,
        31: 4, 32: 5, 33: 3, 34: 4, 35: 5, 36: 4, 37: 2, 38: 3, 39: 4, 40: 5,
        41: 3, 42: 2, 43: 4, 44: 3, 45: 2, 46: 3, 47: 4, 48: 3, 49: 2, 50: 3,
    }

    # ── RIASEC 风格兴趣偏好（76题，A/B二选一）───
    # 模拟随机选择
    import random
    random.seed(42)
    holland_answers = {i: random.choice(['A', 'B']) for i in range(1, 77)}

    # ── 学科自我评价（15题，1-5分，全局题号76-90）───
    efficacy_answers = {
        76: 4, 77: 4, 78: 3, 79: 4, 80: 4,   # 语文效能 → ~4.0
        81: 3, 82: 3, 83: 4, 84: 3, 85: 3,     # 数学效能 → ~3.2
        86: 4, 87: 3, 88: 5, 89: 4, 90: 4,     # 英语效能 → ~4.0
    }

    # ── 职业价值偏好（20题，1-5分，全局题号91-110）───
    career_values_answers = {
        91: 4, 92: 3,   # 收入
        93: 3, 94: 4,   # 稳定
        95: 5, 96: 4,   # 成就
        97: 3, 98: 3,   # 助人
        99: 4, 100: 4,  # 创造
        101: 3, 102: 3, # 平衡
        103: 3, 104: 2, # 领导力
        105: 4, 106: 3, # 独立
        107: 4, 108: 4, # 地域
        109: 5, 110: 4, # 持续学习
    }

    # 运行测试
    result = engine.run_test(
        big_five_answers, holland_answers,
        efficacy_answers, career_values_answers,
    )

    print(f'\n【测试结果】')
    bf = result.big_five
    print(f'大五维度偏好: O={bf["O"]} C={bf["C"]} E={bf["E"]} A={bf["A"]} N={bf["N"]}')
    print(f'RIASEC 风格代码: {result.holland_code}')
    print(f'  各维度分: R={result.holland_scores["R"]} I={result.holland_scores["I"]} '
          f'A={result.holland_scores["A"]} S={result.holland_scores["S"]} '
          f'E={result.holland_scores["E"]} C={result.holland_scores["C"]}')
    print(f'学科自我评价: 语文={result.self_efficacy["chinese"]} '
          f'数学={result.self_efficacy["math"]} '
          f'英语={result.self_efficacy["english"]}')
    print(f'职业价值偏好（TOP3）:')
    sorted_cv = sorted(result.career_values.items(), key=lambda x: x[1], reverse=True)
    for name, score in sorted_cv[:3]:
        print(f'  {name}: {score}')
    print(f'SD检测: {result.sd_score}/4')
    print(f'置信度: {result.confidence}')

    print(f'\n【专业推荐】(TOP 10)')
    for i, major in enumerate(result.recommendations[:10], 1):
        print(f'  {i}. {major}')

    print('\n' + '=' * 70)
    print('测试完成！')


if __name__ == '__main__':
    main()
