# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
选科指导模块 (Subject Guidance)
为高一/高二学生提供选科建议（3+1+2模式或6选3模式）

核心功能：
1. 基于成绩数据的选科优化
2. 基于enroll_detail真实数据的选科覆盖率分析
3. 基于兴趣测试的专业覆盖率分析
4. 基于职业倾向的选科组合推荐

输入：
- 各科成绩（语文/数学/英语 + 物理/历史/化学/生物/政治/地理）
- 项目自编 RIASEC 风格兴趣代码（可选）
- 职业倾向（可选）
- 目标专业方向（可选）

输出：
- 最优选科组合（3门）
- 专业覆盖率（基于enroll_detail真实数据）
- 赋分优势分析
- 推荐依据

用法：
    python algorithms/subject_guidance.py
    python algorithms/subject_guidance.py --student-name "李四" --scores "语文:85,数学:92,英语:88,物理:78,化学:82" --holland REI --career 工程师
"""
import sqlite3
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from itertools import combinations



@dataclass
class SubjectCombo:
    """选科组合"""
    subjects: List[str]  # 3门科目（1首选+2再选）
    preferred: str = ''  # 首选科目（物理/历史）
    elective: List[str] = field(default_factory=list)  # 再选科目（2门）
    pattern: str = '3+1+2'  # '3+1+2' or '6选3'
    # 评估指标
    professional_coverage: float = 0.0  # 专业覆盖率（0-1）
    school_coverage: float = 0.0  # 学校覆盖率（0-1）
    enroll_coverage: float = 0.0  # 招生计划覆盖率（0-1）
    advantage_score: float = 0.0  # 赋分优势分（0-100）
    interest_match: float = 0.0  # 兴趣匹配度（0-1）
    career_fit: float = 0.0  # 职业匹配度（0-1）
    composite_score: float = 0.0  # 综合评分
    reasons: List[str] = field(default_factory=list)


@dataclass
class GuidanceResult:
    """选科指导结果"""
    student_name: str
    best_combo: SubjectCombo
    top_combos: List[SubjectCombo]
    all_combos: List[SubjectCombo]
    analysis: str


# ── 科目满分映射（用于归一化）───
SUBJECT_FULL_SCORES = {
    '语文': 150, '数学': 150, '英语': 150,
    '物理': 100, '历史': 100,
    '化学': 100, '生物': 100, '政治': 100, '地理': 100,
}

# ── 科目权重映射 ──
SUBJECT_WEIGHTS = {
    '语文': 1.0,
    '数学': 1.5,  # 数学最重要
    '英语': 1.2,
    '物理': 1.3,
    '历史': 1.2,
    '化学': 1.1,
    '生物': 1.0,
    '政治': 0.9,
    '地理': 0.8,
}

# ── 专业选科要求（基于教育部指引）──
# 格式: {专业类: (必须科目, 推荐科目, 覆盖率加成)}
MAJOR_SUBJECT_REQUIREMENTS = {
    '计算机类': ({'物理'}, {'数学'}, 0.95),
    '电子信息类': ({'物理'}, {'数学', '化学'}, 0.93),
    '自动化类': ({'物理'}, {'数学', '化学'}, 0.90),
    '电气工程类': ({'物理'}, {'数学'}, 0.92),
    '机械类': ({'物理'}, {'数学'}, 0.88),
    '土木类': ({'物理'}, {'化学'}, 0.85),
    '材料类': ({'物理', '化学'}, set(), 0.80),
    '化工与制药类': ({'化学'}, {'物理'}, 0.82),
    '临床医学类': ({'物理', '化学'}, {'生物'}, 0.90),
    '口腔医学类': ({'物理', '化学'}, {'生物'}, 0.88),
    '药学类': ({'化学'}, {'生物'}, 0.85),
    '护理学类': ({'生物'}, set(), 0.75),
    '法学类': ({'历史'}, {'政治'}, 0.70),
    '汉语言文学类': ({'历史'}, set(), 0.72),
    '经济学类': ({'历史'}, {'数学'}, 0.78),
    '工商管理类': ({'历史'}, set(), 0.75),
    '教育学类': ({'历史'}, set(), 0.73),
    '新闻传播类': ({'历史'}, set(), 0.74),
    '数学类': ({'物理'}, {'化学'}, 0.85),
    '物理学类': ({'物理'}, {'化学'}, 0.88),
    '化学类': ({'化学'}, {'物理'}, 0.86),
    '生物科学类': ({'生物'}, {'化学'}, 0.82),
    '环境类': ({'化学'}, {'生物'}, 0.78),
    '建筑类': ({'物理'}, set(), 0.83),
    '农学类': ({'生物'}, {'化学'}, 0.76),
    '心理学类': ({'物理', '生物'}, set(), 0.79),
    '金融学类': ({'历史'}, {'数学'}, 0.77),
    '会计类': ({'历史'}, set(), 0.74),
    '体育类': (set(), set(), 0.60),
    '艺术类': (set(), set(), 0.55),
}

# ── RIASEC 风格兴趣代码→推荐科目 ──
HOLLAND_SUBJECT_MAP = {
    'R': ['物理', '化学', '生物'],  # 实际型
    'I': ['物理', '化学', '数学'],  # 研究型
    'A': ['历史', '语文', '英语'],  # 艺术型
    'S': ['历史', '政治', '英语'],  # 社会型
    'E': ['历史', '政治', '数学'],  # 企业型
    'C': ['数学', '化学', '物理'],  # 常规型
}

# ── 职业倾向→推荐科目 ──
CAREER_SUBJECT_MAP = {
    '工程师': ['物理', '数学', '化学'],
    '医生': ['物理', '化学', '生物'],
    '教师': ['语文', '英语', '历史'],
    '律师': ['历史', '政治', '语文'],
    '程序员': ['物理', '数学', '信息技术'],
    '金融': ['数学', '历史', '政治'],
    '科研': ['物理', '化学', '生物'],
    '艺术': ['语文', '英语', '历史'],
    '公务员': ['政治', '历史', '语文'],
    '商科': ['数学', '历史', '英语'],
}


class SubjectGuidanceEngine:
    """选科指导引擎"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'yunnan_gaokao.db'
            )
        self._db_path = db_path

    def guidance(
        self,
        student_name: str = '考生',
        scores: Dict[str, float] = None,
        holland_code: str = None,
        career_preference: str = None,
        target_major: str = None,
        pattern: str = '3+1+2',
        top_n: int = 5,
    ) -> GuidanceResult:
        """
        执行选科指导

        参数:
            student_name: 学生姓名
            scores: 各科成绩 {科目: 分数}
            holland_code: 项目自编 RIASEC 风格兴趣代码（如'REI'）
            career_preference: 职业倾向
            target_major: 目标专业方向
            pattern: 选科模式（'3+1+2' or '6选3'）
            top_n: 返回前N个最优组合
        """
        # 1. 计算基础分（基于成绩）
        score_analysis = self._analyze_scores(scores or {})

        # 2. 生成所有可能的选科组合
        all_combos = self._generate_combos(pattern)

        # 3. 评估每个组合
        evaluated = []
        for combo in all_combos:
            # 基础分
            combo.advantage_score = self._calc_advantage(combo, scores or {})

            # 专业覆盖率
            combo.professional_coverage = self._calc_coverage(combo, target_major)

            # 兴趣匹配
            combo.interest_match = self._calc_interest_match(combo, holland_code)

            # 职业匹配
            combo.career_fit = self._calc_career_fit(combo, career_preference)

            # 综合评分
            combo.composite_score = (
                combo.advantage_score * 0.25 +
                combo.professional_coverage * 100 * 0.35 +
                combo.school_coverage * 100 * 0.15 +
                combo.enroll_coverage * 100 * 0.1 +
                combo.interest_match * 100 * 0.1 +
                combo.career_fit * 100 * 0.05
            )

            # 生成推荐理由
            combo.reasons = self._generate_reasons(combo, scores or {}, holland_code, career_preference)

            evaluated.append(combo)

        # 4. 排序
        evaluated.sort(key=lambda x: x.composite_score, reverse=True)

        # 5. 生成分析报告
        analysis = self._generate_analysis(evaluated[:top_n], score_analysis)

        return GuidanceResult(
            student_name=student_name,
            best_combo=evaluated[0] if evaluated else None,
            top_combos=evaluated[:top_n],
            all_combos=evaluated,
            analysis=analysis,
        )

    def _analyze_scores(self, scores: Dict[str, float]) -> Dict:
        """分析各科成绩"""
        if not scores:
            return {'average': 0, 'strongest': '', 'weakest': ''}

        avg = sum(scores.values()) / len(scores)
        strongest = max(scores, key=scores.get)
        weakest = min(scores, key=scores.get)

        return {
            'average': avg,
            'strongest': strongest,
            'weakest': weakest,
            'details': scores,
        }

    def _generate_combos(self, pattern: str) -> List[SubjectCombo]:
        """生成所有可能的选科组合"""
        if pattern == '3+1+2':
            # 3+1+2: 语数外 + 物理/历史(1) + 其他4选2
            base_subjects = ['物理', '历史']  # 首选科目
            elective_subjects = ['化学', '生物', '政治', '地理']

            combos = []
            for preferred in base_subjects:
                for pair in combinations(elective_subjects, 2):
                    combo = SubjectCombo(
                        subjects=[preferred] + list(pair),
                        preferred=preferred,
                        elective=list(pair),
                        pattern=pattern,
                    )
                    combos.append(combo)
            return combos
        else:  # 6选3
            all_subjects = ['物理', '历史', '化学', '生物', '政治', '地理']
            combos = []
            for combo in combinations(all_subjects, 3):
                combo_list = list(combo)
                # 找出首选科目
                preferred = '物理' if '物理' in combo_list else ('历史' if '历史' in combo_list else '')
                # P1-normal #4: 6选3模式下保留所有3门科目作为再选科目，不截断
                elective = [s for s in combo_list if s not in [preferred]]
                combos.append(SubjectCombo(
                    subjects=combo_list,
                    preferred=preferred,
                    elective=elective,  # 不再 [:2] 截断
                    pattern=pattern,
                ))
            return combos

    def _calc_advantage(self, combo: SubjectCombo, scores: Dict[str, float]) -> float:
        """
        计算赋分优势分
        考虑：
        1. 绝对分数（越高越好）
        2. 科目权重（数英理化更重要）
        3. 相对优势（在自己所有科目中的排名）

        P1-normal #3: 按科目满分归一化（语数英150 vs 理化生政史地100）
        """
        if not scores:
            return 50.0  # 无数据时给中等分

        weighted_scores = []
        for subject in combo.subjects:
            score = scores.get(subject, 0)
            weight = SUBJECT_WEIGHTS.get(subject, 1.0)
            full_score = SUBJECT_FULL_SCORES.get(subject, 100)
            # 归一化到 0-100 再乘权重
            normalized = (score / full_score) * 100 if full_score else 0
            weighted_scores.append(normalized * weight)

        if not weighted_scores:
            return 50.0

        avg = sum(weighted_scores) / len(weighted_scores)

        # 标准化到0-100
        max_possible = 100 * 1.5  # 满分100 × 最高权重1.5
        normalized = min(100, (avg / max_possible) * 100)

        return normalized

    def _calc_coverage(self, combo: SubjectCombo, target_major: str = None) -> float:
        """
        计算专业覆盖率（基于enroll_detail真实数据）
        """
        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            c = conn.cursor()

            # 获取所有major_class的选科要求分布
            c.execute('''
                SELECT major_class, subject_req, COUNT(*) as cnt
                FROM enroll_detail
                WHERE major_class IS NOT NULL AND major_class != ''
                  AND subject_req IS NOT NULL AND subject_req != ''
                GROUP BY major_class, subject_req
            ''')

            # 统计每个major_class的总招生计划
            major_totals = {}
            major_reqs = {}
            for row in c.fetchall():
                mc, req, cnt = row
                major_totals[mc] = major_totals.get(mc, 0) + cnt
                if mc not in major_reqs:
                    major_reqs[mc] = {}
                major_reqs[mc][req] = cnt

            conn.close()
        except Exception:
            return 0.5  # fallback

        if not major_totals:
            return 0.5

        combo_set = set(combo.subjects)
        elective_set = set(combo.elective) if combo.elective else combo_set

        total_majors = len(major_totals)
        total_enroll = sum(major_totals.values())

        # 计算该组合能覆盖多少major_class
        covered_majors = 0
        covered_enroll = 0

        for mc, total_cnt in major_totals.items():
            reqs = major_reqs.get(mc, {})
            # 该专业类中能被当前选科覆盖的招生计划比例
            can_apply_cnt = 0
            for req, cnt in reqs.items():
                if self._check_subject_match(req, combo_set, elective_set):
                    can_apply_cnt += cnt

            # 如果能覆盖该专业类70%以上的招生计划，算作"能报考"
            if can_apply_cnt / total_cnt >= 0.7:
                covered_majors += 1
                covered_enroll += total_cnt

        coverage_rate = covered_majors / total_majors if total_majors > 0 else 0
        combo.school_coverage = covered_majors / total_majors if total_majors > 0 else 0
        combo.enroll_coverage = covered_enroll / total_enroll if total_enroll > 0 else 0

        # 如果指定了目标专业，优先使用该专业的覆盖率
        if target_major:
            target_coverage = 0
            for mc in major_totals:
                if target_major.lower() in mc.lower():
                    reqs = major_reqs.get(mc, {})
                    can_apply = sum(cnt for req, cnt in reqs.items()
                                    if self._check_subject_match(req, combo_set, elective_set))
                    target_coverage = can_apply / major_totals[mc] if major_totals[mc] > 0 else 0
                    break
            return target_coverage * 0.6 + coverage_rate * 0.4

        return coverage_rate

    def _check_subject_match(self, req: str, all_subjects: set, elective: set) -> bool:
        """
        检查选科要求是否匹配
        req格式: '化学', '不限', '政治', '化学和生物', '政治和地理'

        P1-urgent #3: 统一使用 all_subjects（含首选科目+再选科目）。
        原实现只检查 elective，导致"物理"作为首选科目时在单科要求场景下永远无法命中。
        """
        if req == '不限':
            return True
        if '和' in req:
            # 组合要求：需要同时选req中的所有科目（应检查全部科目）
            required = set(req.split('和'))
            return required.issubset(all_subjects)
        else:
            # 单科要求：首选+再选都算
            return req in all_subjects

    def _calc_interest_match(self, combo: SubjectCombo, holland_code: str = None) -> float:
        """计算兴趣匹配度"""
        if not holland_code:
            return 0.5

        # 获取 RIASEC 风格兴趣代码对应的推荐科目
        recommended = set()
        for code in holland_code:
            if code in HOLLAND_SUBJECT_MAP:
                recommended.update(HOLLAND_SUBJECT_MAP[code])

        if not recommended:
            return 0.5

        # 计算匹配比例
        combo_set = set(combo.subjects)
        match_count = len(combo_set & recommended)
        total_recommended = len(recommended)

        return match_count / total_recommended if total_recommended > 0 else 0.5

    def _calc_career_fit(self, combo: SubjectCombo, career_preference: str = None) -> float:
        """计算职业匹配度"""
        if not career_preference:
            return 0.5

        career_subjects = CAREER_SUBJECT_MAP.get(career_preference, [])
        if not career_subjects:
            return 0.5

        combo_set = set(combo.subjects)
        match_count = sum(1 for s in career_subjects if s in combo_set)
        total = len(career_subjects)

        return match_count / total if total > 0 else 0.5

    def _generate_reasons(self, combo: SubjectCombo, scores: Dict[str, float],
                          holland_code: str = None, career_preference: str = None) -> List[str]:
        """生成推荐理由"""
        reasons = []

        # 1. 真实覆盖率（基于enroll_detail数据）
        if combo.professional_coverage > 0.8:
            reasons.append(f'可报考{combo.professional_coverage*100:.0f}%的专业类（基于{combo.school_coverage*100:.0f}%院校）')
        elif combo.professional_coverage < 0.5:
            reasons.append(f'仅可报考{combo.professional_coverage*100:.0f}%的专业类，选择面较窄')

        # 2. 赋分优势
        if combo.advantage_score > 70:
            reasons.append(f'赋分优势明显（{combo.advantage_score:.0f}分）')
        elif combo.advantage_score < 50:
            reasons.append(f'赋分优势一般（{combo.advantage_score:.0f}分），建议提分')

        # 3. 兴趣匹配
        if holland_code and combo.interest_match > 0.7:
            reasons.append(f'与项目自编 RIASEC 风格兴趣代码 {holland_code} 高度匹配')

        # 4. 职业匹配
        if career_preference and combo.career_fit > 0.6:
            reasons.append(f'适合{career_preference}方向')

        # 5. 具体科目分析
        for subject in combo.subjects:
            if subject in scores:
                if scores[subject] > 80:
                    reasons.append(f'{subject}成绩优秀（{scores[subject]}分）')
                elif scores[subject] < 50:
                    reasons.append(f'{subject}成绩偏低（{scores[subject]}分），需重点关注')

        return reasons

    def _generate_analysis(self, top_combos: List[SubjectCombo], score_analysis: Dict) -> str:
        """生成分析报告"""
        lines = []

        lines.append('【选科分析报告】')
        lines.append('')

        # 1. 最优组合
        if top_combos:
            best = top_combos[0]
            lines.append(f'最优选科组合：{" + ".join(best.subjects)}')
            lines.append(f'综合评分：{best.composite_score:.1f}/100')
            lines.append(f'专业覆盖率：{best.professional_coverage*100:.0f}% | 院校覆盖率：{best.school_coverage*100:.0f}% | 招生计划覆盖率：{best.enroll_coverage*100:.0f}%')
            lines.append(f'赋分优势：{best.advantage_score:.0f}分')
            lines.append('')

            # 推荐理由
            if best.reasons:
                lines.append('推荐依据：')
                for reason in best.reasons:
                    lines.append(f'  • {reason}')
                lines.append('')

        # 2. TOP3组合对比
        if len(top_combos) >= 3:
            lines.append('TOP3选科组合对比：')
            for i, combo in enumerate(top_combos[:3], 1):
                lines.append(f'  {i}. {" + ".join(combo.subjects)} (综合{combo.composite_score:.1f}分)')

        # 3. 成绩分析
        if score_analysis.get('strongest'):
            lines.append('')
            lines.append(f'优势科目：{score_analysis["strongest"]}')
            lines.append(f'薄弱科目：{score_analysis["weakest"]}')

        return '\n'.join(lines)


def print_guidance(result: GuidanceResult):
    """打印选科指导结果"""
    print(f'\n{"="*60}')
    print(f'{result.student_name} 的选科指导报告')
    print(f'{"="*60}')
    print(result.analysis)

    # TOP5组合详细列表
    if result.top_combos:
        print(f'\n{"="*60}')
        print('TOP5 选科组合详细评估')
        print(f'{"="*60}')
        print(f'{"排名":>4s} {"选科组合":>20s} {"综合":>8s} {"覆盖":>8s} {"赋分":>8s} {"兴趣":>6s} {"职业":>6s}')
        print('-' * 60)

        for i, combo in enumerate(result.top_combos[:5], 1):
            row = '{:>4d} {:>20s} {:>8.1f} {:>8.1f}% {:>8.0f} {:>6.1f} {:>6.1f}'.format(
                i,
                ' + '.join(combo.subjects),
                combo.composite_score,
                combo.professional_coverage * 100,
                combo.advantage_score,
                combo.interest_match,
                combo.career_fit,
            )
            print(row)

        # 推荐理由
        print(f'\n{"="*60}')
        print('推荐理由')
        print(f'{"="*60}')
        for i, combo in enumerate(result.top_combos[:3], 1):
            print(f'\n组合{i}: {" + ".join(combo.subjects)}')
            for reason in combo.reasons:
                print(f'  • {reason}')


def main():
    import argparse
    parser = argparse.ArgumentParser(description='YGCare选科指导')
    parser.add_argument('--student-name', type=str, default='考生')
    parser.add_argument('--scores', type=str, default='',
                        help='各科成绩，格式：语文:85,数学:92,英语:88,物理:78,历史:65,化学:82,生物:75,政治:70,地理:68')
    parser.add_argument(
        '--holland', type=str, default='',
        help='项目自编 RIASEC 风格兴趣代码（如 REI；参数名为兼容保留）',
    )
    parser.add_argument('--career', type=str, default='', help='职业倾向')
    parser.add_argument('--target-major', type=str, default='', help='目标专业方向')
    parser.add_argument('--pattern', type=str, default='3+1+2', choices=['3+1+2', '6选3'])
    parser.add_argument('--top', type=int, default=5, help='返回TOP N')

    args = parser.parse_args()

    # 解析成绩
    scores = {}
    if args.scores:
        for item in args.scores.split(','):
            if ':' in item:
                subj, score = item.split(':', 1)
                scores[subj.strip()] = float(score.strip())

    engine = SubjectGuidanceEngine()
    result = engine.guidance(
        student_name=args.student_name,
        scores=scores,
        holland_code=args.holland,
        career_preference=args.career,
        target_major=args.target_major,
        pattern=args.pattern,
        top_n=args.top,
    )

    print_guidance(result)


if __name__ == '__main__':
    # 默认测试
    main()
