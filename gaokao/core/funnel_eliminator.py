# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
漏斗式排除引擎 (Funnel Elimination Engine)
基于框框四步排除法：选科→学科→体检→兴趣

每步严格顺序执行，输出排除报告供用户参考。
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .volunteer_recommender import check_subject_match


@dataclass
class FunnelStage:
    """漏斗单个阶段"""
    name: str  # 阶段名称
    desc: str  # 阶段描述
    excluded_count: int  # 排除数量（专业数或学校数）
    remaining_count: int  # 剩余数量
    excluded_items: List[str] = field(default_factory=list)  # 被排除的具体项目


@dataclass
class FunnelReport:
    """漏斗排除报告"""
    stages: List[FunnelStage] = field(default_factory=list)
    total_initial: int = 0  # 初始总数量
    final_remaining: int = 0  # 最终剩余数量
    all_excluded_majors: Set[str] = field(default_factory=set)  # 所有被排除的专业


def create_funnel_eliminator() -> 'FunnelEliminator':
    """工厂函数，延迟导入依赖"""
    return FunnelEliminator()


class FunnelEliminator:
    """漏斗式排除引擎"""

    # ── 学科效能感阈值（低于此分数的学科相关专业建议排除）───
    EFFICACY_LOW_THRESHOLD = 2.0  # 1-5分量表，<2分视为弱项

    # ── 学科效能感→专业大类映射（仅3科：语/数/英）───
    # 语数英效能感低分对应的专业大类建议排除
    EFFICACY_SUBJECT_TO_MAJOR_CLASSES = {
        '语文': ['中国语言文学类', '外国语言文学类', '新闻传播学类', '教育学类',
                 '历史学类', '哲学类', '法学类', '社会学类', '政治学类',
                 '公共管理类', '旅游管理类'],
        '数学': ['数学类', '统计学类', '计算机类', '金融学类', '经济学类',
                 '管理科学与工程类', '工商管理类', '财政学类', '信息与计算科学'],
        '英语': ['外国语言文学类', '翻译类', '新闻传播学类', '国际经济与贸易',
                 '旅游管理类', '教育学类'],
    }

    def __init__(self):
        self._major_class_cache = {}  # 专业名→大类 缓存

    def _load_major_catalog(self, cursor) -> Dict[str, str]:
        """加载专业→大类映射"""
        if self._major_class_cache:
            return self._major_class_cache
        try:
            rows = cursor.execute('SELECT major_name, major_class FROM major_catalog').fetchall()
            self._major_class_cache = {r[0]: r[1] for r in rows if r[1]}
        except Exception:
            pass
        return self._major_class_cache

    def _get_major_class(self, major_name: str) -> str:
        """获取专业所属大类"""
        return self._major_class_cache.get(major_name, major_name)

    def run_funnel(
        self,
        cursor,
        all_schools: List[dict],
        user_subjects: List[str],
        efficacy_scores: Optional[Dict[str, float]] = None,
        constraint_result=None,
        holland_result=None,
    ) -> FunnelReport:
        """
        执行四步漏斗排除

        参数:
            cursor: 数据库游标
            all_schools: 初始候选学校列表（每所含 major_list 字段）
            user_subjects: 用户再选科目（不含首选）
            efficacy_scores: 学科效能感 {'语文': 4.0, '数学': 3.5, ...}
            constraint_result: 禁忌项校验结果
            holland_result: 项目自编 RIASEC 风格六维得分 {'R': 3, 'I': 4, 'A': 2, 'S': 5, 'E': 3, 'C': 2}
        """
        report = FunnelReport()
        current_schools = list(all_schools)
        report.total_initial = self._count_all_majors(current_schools)

        # 阶段1: 选科排除（硬性）
        stage1 = self._stage_subject_filter(current_schools, user_subjects)
        report.stages.append(stage1)
        current_schools = self._filter_schools_by_excluded(current_schools, stage1.excluded_items)
        report.all_excluded_majors.update(stage1.excluded_items)

        # 阶段2: 学科偏好排除（天赋）
        if efficacy_scores:
            stage2 = self._stage_subject_preference(
                current_schools, efficacy_scores
            )
            report.stages.append(stage2)
            current_schools = self._filter_schools_by_excluded(current_schools, stage2.excluded_items)
            report.all_excluded_majors.update(stage2.excluded_items)

        # 阶段3: 体检排除（身体条件）
        # P2-fix: getattr 安全访问 constraint_result.filtered_majors
        if constraint_result and getattr(constraint_result, 'filtered_majors', None):
            stage3 = self._stage_constraint_filter(
                current_schools, constraint_result.filtered_majors
            )
            report.stages.append(stage3)
            current_schools = self._filter_schools_by_excluded(current_schools, stage3.excluded_items)
            report.all_excluded_majors.update(stage3.excluded_items)

        # 阶段4: 兴趣意愿排除（霍兰德匹配）
        if holland_result:
            stage4 = self._stage_interest_filter(current_schools, holland_result)
            report.stages.append(stage4)
            current_schools = self._filter_schools_by_excluded(current_schools, stage4.excluded_items)
            report.all_excluded_majors.update(stage4.excluded_items)

        report.final_remaining = self._count_all_majors(current_schools)
        return report

    # ── 阶段1: 选科排除 ──

    def _stage_subject_filter(
        self, schools: List[dict], user_subjects: List[str]
    ) -> FunnelStage:
        """选科排除：不满足选科要求的专业被排除"""
        excluded = []
        for school in schools:
            for major in school.get('major_list', []):
                subject_req = major.get('subject_req', '') or ''
                if user_subjects and not check_subject_match(user_subjects, subject_req):
                    excluded.append(major['major_name'])
        remaining = self._count_all_majors(schools) - len(excluded)
        return FunnelStage(
            name='选科排除',
            desc='根据物理/历史选科组合，排除不满足选科要求的专业',
            excluded_count=len(excluded),
            remaining_count=remaining,
            excluded_items=list(set(excluded)),
        )

    # ── 阶段2: 学科偏好排除 ──

    def _stage_subject_preference(
        self, schools: List[dict], efficacy_scores: Dict[str, float]
    ) -> FunnelStage:
        """学科偏好排除：弱项学科对应的专业大类建议排除"""
        weak_subjects = [
            subj for subj, score in efficacy_scores.items()
            if score < self.EFFICACY_LOW_THRESHOLD and subj in self.EFFICACY_SUBJECT_TO_MAJOR_CLASSES
        ]
        if not weak_subjects:
            return FunnelStage(
                name='学科偏好排除',
                desc='无学科弱项，此阶段未排除专业',
                excluded_count=0,
                remaining_count=self._count_all_majors(schools),
            )

        weak_major_classes = set()
        for subj in weak_subjects:
            weak_major_classes.update(self.EFFICACY_SUBJECT_TO_MAJOR_CLASSES[subj])

        excluded = []
        for school in schools:
            for major in school.get('major_list', []):
                major_class = major.get('major_class', '') or ''
                # 也检查专业名是否命中大类
                if major_class in weak_major_classes:
                    excluded.append(major['major_name'])

        remaining = self._count_all_majors(schools) - len(excluded)
        weak_desc = '、'.join(weak_subjects)
        return FunnelStage(
            name='学科偏好排除',
            desc=f'学科效能感中{weak_desc}为弱项，排除相关专业大类',
            excluded_count=len(excluded),
            remaining_count=remaining,
            excluded_items=list(set(excluded)),
        )

    # ── 阶段3: 体检排除 ──

    def _stage_constraint_filter(
        self, schools: List[dict], filtered_majors: List[str]
    ) -> FunnelStage:
        """体检排除：根据禁忌项校验结果排除受限专业"""
        filtered_set = set(filtered_majors)
        excluded = []
        for school in schools:
            for major in school.get('major_list', []):
                major_name = major['major_name']
                major_class = major.get('major_class', '') or ''
                if major_name in filtered_set or major_class in filtered_set:
                    excluded.append(major_name)
        remaining = self._count_all_majors(schools) - len(excluded)
        return FunnelStage(
            name='体检排除',
            desc='根据体检受限代码，排除不予录取或限制录取的专业',
            excluded_count=len(excluded),
            remaining_count=remaining,
            excluded_items=list(set(excluded)),
        )

    # ── 阶段4: 兴趣意愿排除 ──

    # RIASEC 风格六维→专业大类推荐
    HOLLAND_MAJOR_MAPPING = {
        'R': ['机械类', '土木类', '电气类', '航空航天类', '仪器类', '能源动力类',
              '材料类', '测绘类', '矿业类',
              '船舶与海洋工程类', '农业工程类', '水产类', '纺织类',
              '公安学类'],  # 实用型（+2026新增）
        'I': ['数学类', '物理学类', '化学类', '生物科学类', '计算机类', '电子信息类',
              '统计学类', '地球物理类', '大气类',
              '人工智能类', '医学技术类', '审计学类',
              '心理学类'],  # 研究型（+2026新增：AI/医学技术/认知科学）
        'A': ['设计学类', '戏剧与影视学类', '音乐与舞蹈学类', '美术学类',
              '建筑类', '中国语言文学类', '新闻传播学类',
              '风景园林类'],  # 艺术型（+2026新增：智慧景观/艺术治疗）
        'S': ['教育学类', '心理学类', '社会学类', '护理学类', '公共管理类',
              '外国语言文学类', '体育学类'],  # 社会型
        'E': ['工商管理类', '金融学类', '法学类', '经济学类', '管理科学与工程类',
              '政治学类', '旅游管理类'],  # 企业型
        'C': ['会计类', '图书情报类', '统计学类', '管理科学与工程类', '财政学类',
              '审计学类'],  # 常规型（+2026新增：资源环境审计）
    }

    def _stage_interest_filter(
        self, schools: List[dict], holland_result: Dict[str, float]
    ) -> FunnelStage:
        """兴趣排除：RIASEC 风格最低1-2维对应的非推荐专业大类建议排除"""
        if not holland_result:
            return FunnelStage(
                name='兴趣意愿排除',
                desc='无 RIASEC 风格兴趣结果，此阶段未排除专业',
                excluded_count=0,
                remaining_count=self._count_all_majors(schools),
            )

        # 找得分最低的1-2个维度
        sorted_dims = sorted(holland_result.items(), key=lambda x: x[1])
        weak_dims = [dim for dim, score in sorted_dims[:2] if score < 3.0]
        if not weak_dims:
            return FunnelStage(
                name='兴趣意愿排除',
                desc='RIASEC 风格各维度得分均衡，此阶段未排除专业',
                excluded_count=0,
                remaining_count=self._count_all_majors(schools),
            )

        # 这些弱维度不推荐的专业大类
        non_recommended_classes = set()
        for dim in weak_dims:
            non_recommended_classes.update(self.HOLLAND_MAJOR_MAPPING.get(dim, []))

        # 只排除既不是推荐也不是强兴趣维度的专业
        strong_dims = [dim for dim, score in sorted_dims[-2:] if score >= 4.0]
        recommended_classes = set()
        for dim in strong_dims:
            recommended_classes.update(self.HOLLAND_MAJOR_MAPPING.get(dim, []))

        # 只在弱维度且不匹配强推荐维度时排除
        exclude_classes = non_recommended_classes - recommended_classes

        excluded = []
        for school in schools:
            for major in school.get('major_list', []):
                major_class = major.get('major_class', '') or ''
                if major_class in exclude_classes:
                    excluded.append(major['major_name'])

        remaining = self._count_all_majors(schools) - len(excluded)
        weak_desc = '、'.join(weak_dims)
        return FunnelStage(
            name='兴趣意愿排除',
            desc=f'项目自编 RIASEC 风格兴趣中{weak_desc}维度得分较低，建议避开相关专业大类',
            excluded_count=len(excluded),
            remaining_count=remaining,
            excluded_items=list(set(excluded)),
        )

    # ── 工具方法 ──

    @staticmethod
    def _count_all_majors(schools: List[dict]) -> int:
        """统计所有学校的专业总数"""
        total = 0
        for school in schools:
            total += len(school.get('major_list', []))
        return total

    @staticmethod
    def _filter_schools_by_excluded(
        schools: List[dict], excluded_items: List[str]
    ) -> List[dict]:
        """从学校列表中移除被排除的专业"""
        excluded_set = set(excluded_items)
        result = []
        for school in schools:
            new_majors = [
                m for m in school.get('major_list', [])
                if m['major_name'] not in excluded_set
            ]
            if new_majors:
                school_copy = dict(school)
                school_copy['major_list'] = new_majors
                result.append(school_copy)
        return result

    @staticmethod
    def format_report(report: FunnelReport) -> str:
        """格式化排除报告为文本"""
        lines = [f'漏斗排除报告: 初始{report.total_initial}个专业 → 最终剩余{report.final_remaining}个专业\n']
        for i, stage in enumerate(report.stages, 1):
            lines.append(
                f'  第{i}步 {stage.name}: 排除{stage.excluded_count}个专业，剩余{stage.remaining_count}个'
            )
            if stage.excluded_items and len(stage.excluded_items) <= 10:
                lines.append(f'    排除项: {", ".join(stage.excluded_items[:10])}')
        return '\n'.join(lines)
