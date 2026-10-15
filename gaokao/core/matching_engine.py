# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
匹配引擎 (Matching Engine) V3.0
融合项目自编偏好问卷、其他问卷偏好与位次匹配，生成个性化志愿推荐方案。

核心功能：
1. 四维融合推荐（RIASEC 风格兴趣+大五维度+学科自我评价+职业价值偏好）
2. 问卷偏好融合（专业/城市/行业/地域/体检限制）
3. 位次匹配（跨年度标准化）
4. 冲稳保推荐（风险策略+偏好过滤）
"""
import logging
import sqlite3
import threading
from typing import Dict, List, Optional, Set, Tuple, Any
from dataclasses import dataclass, field

from .rank_converter import RankConverter
from .admission_probability import AdmissionProbability
from .volunteer_recommender import VolunteerRecommender, UserProfile, STRATEGY_CONFIGS, Recommendation
from .personality_test import PersonalityTestEngine, TestResult
from .questionnaire_parser import QuestionnaireParser, UserQuestionnaire
from .family_resource import assess_family_resource
from .constraint_checker import check_constraints
from .revocation_risk import get_revocation_risk
from .industry_strong_schools import get_industry_strong_match


@dataclass
class MajorPreference:
    """专业偏好"""
    major_name: str
    score: float
    reason: str
    is_new_major: bool = False  # 2026新增专业，无历史录取数据
    revocation_risk: str = ''   # 撤销风险标签：rising/stable/declining/none
    employment_rate: float = 0  # 就业率（0-1）
    avg_salary: float = 0       # 平均月薪（元）


@dataclass
class SchoolRecommendation:
    """院校推荐"""
    school_name: str
    category: str
    probability: float
    confidence: str
    predicted_rank: int
    school_quality: str
    location: str
    tuition: float
    recommended_majors: List[MajorPreference]
    reasons: List[str]
    tier_level: str = ''       # L1-L13
    tier_name: str = ''        # 清北/华五人/C9等
    similar_alternatives: List[str] = field(default_factory=list)
    batch: str = ''  # 批次：提前本科批B段/本科批B段/高职专科批等
    group_code: str = ''       # 专业组代码，如 "01"
    group_name: str = ''       # 专业组名称，如 "01专业组"
    subject_req: str = ''      # 选科要求，如 "化学"


@dataclass
class MatchingResult:
    """匹配结果"""
    user_profile: UserProfile
    personality_result: Optional[TestResult]
    questionnaire: UserQuestionnaire
    risk_strategy: str
    recommendations: Dict[str, List[SchoolRecommendation]]
    summary: str
    notes: List[str] = field(default_factory=list)  # H-05: 空推荐/稀疏推荐说明
    intention_profile: Optional = None  # 意愿画像（可选，避免循环导入）
    family_resource_result: Optional = None  # 家庭资源评估结果
    constraint_result: Optional = None  # 禁忌项校验结果
    funnel_report: Optional = None  # 漏斗排除报告（四步排除法）
    breadth_warnings: List[str] = field(default_factory=list)  # 专业宽度预警（脱敏样例场景）
    candidate_pool_warning: str = ''  # 候选池不足预警（C9）
    data_sparsity_warning: str = ''  # 数据稀疏预警（Step 3：历史类数据稀疏时的红色提示）
    must_ack_warnings: List[str] = field(default_factory=list)  # P1-4 必读告警（合规要点）


class MatchingEngine:
    """匹配引擎 V3.0"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()

        self.rank_converter = RankConverter(db_path)
        self.prob_calculator = AdmissionProbability(db_path)
        self.volunteer_recommender = VolunteerRecommender(db_path)
        self.personality_engine = PersonalityTestEngine()
        self.intention_engine = None  # 延迟导入，避免循环依赖

    def _init_local(self):
        """初始化 per-thread 数据库连接"""
        if not hasattr(self._local, 'cursor'):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.cursor = conn.cursor()

    def _get_cursor(self):
        """获取当前线程的 cursor"""
        if not hasattr(self._local, 'cursor'):
            self._init_local()
        return self._local.cursor

    def match(
        self,
        questionnaire: UserQuestionnaire,
        big_five_answers: Dict[int, int] = None,
        holland_answers: Dict[int, str] = None,
        efficacy_answers: Dict[int, int] = None,
        career_values_answers: Dict[int, int] = None,
        top_n: int = 80,
    ) -> MatchingResult:
        """
        执行匹配 V3.0

        参数:
            questionnaire: 用户问卷数据
            big_five_answers: 项目自编大五维度问卷答案 {题号: 1-5分}
            holland_answers: 项目自编 RIASEC 风格问卷答案 {题号: 'A'或'B'}
            efficacy_answers: 项目自编学科自我评价答案 {全局题号: 1-5分}
            career_values_answers: 项目自编职业价值偏好答案 {全局题号: 1-5分}
            top_n: 推荐数量
        """
        # Step 1: 意愿推断（先于偏好问卷，因为意愿优先级更高）
        intention_profile = None
        try:
            if self.intention_engine is None:
                from .intention_inference import IntentionInferenceEngine
                self.intention_engine = IntentionInferenceEngine()
            intention_profile = self.intention_engine.infer(questionnaire)
        except Exception as e:
            logging.warning(f"意愿推断失败: {e}")
            pass  # 容错：推断失败不影响主流程

        # Step 2: 偏好问卷（四维融合，修正V3.0: 传递category用于题号映射）
        # AUDIT-P0-011: 若调用方未显式传入答案，回退使用 questionnaire 自带答案
        # （parse 阶段已从 raw_data 中提取大五维度/RIASEC 风格答案）
        if not big_five_answers:
            big_five_answers = getattr(questionnaire, 'big_five_answers', None)
        if not holland_answers:
            holland_answers = getattr(questionnaire, 'holland_answers', None)

        personality_result = None
        if big_five_answers and holland_answers and efficacy_answers and career_values_answers:
            cat = 'history' if questionnaire.category == '历史类' else 'physics'
            personality_result = self.personality_engine.run_test(
                big_five_answers, holland_answers,
                efficacy_answers, career_values_answers,
                cat,
            )
        elif big_five_answers or holland_answers:
            # 部分作答时给出明确诊断，避免静默丢失个性化
            missing = []
            if not big_five_answers:
                missing.append('项目自编大五维度问卷')
            if not holland_answers:
                missing.append('项目自编 RIASEC 风格兴趣偏好问卷')
            if not efficacy_answers:
                missing.append('项目自编学科自我评价问卷')
            if not career_values_answers:
                missing.append('职业价值偏好问卷')
            logging.warning(
                f"[P0-011] 偏好问卷分析跳过：缺失问卷 {missing}；"
                f"报告中的『偏好画像』与『专业匹配理由』将无个性化内容"
            )

        # Step 2.5: 禁忌项校验 + 家庭资源评估
        constraint_result = None
        family_resource_result = None
        constraint_notes = []
        try:
            # 构建禁忌项答案
            constraint_answers = self._build_constraint_answers(questionnaire)
            constraint_result = check_constraints(constraint_answers)
            constraint_notes.extend(constraint_result.warnings)
            # 硬性过滤：将被限制专业加入排除列表
            if constraint_result.filtered_majors:
                questionnaire.excluded_majors = list(
                    set(questionnaire.excluded_majors) | set(constraint_result.filtered_majors)
                )
            if constraint_result.hard_filtered:
                constraint_notes.append('⚠️ 体检不予录取，系统无法生成推荐，请联系管理员。')
        except Exception as e:
            # AUDIT-P1-024: 禁忌项是 P0 级保护逻辑，异常必须显著告警
            # 之前的"静默警告"会让考生收到没过滤体检限制的方案而不察觉
            # 改进: 异常时记录 CRITICAL 级日志 + 增加首条醒目警告（report 必须展示）
            logging.critical(
                f"[P1-024 CRITICAL] 禁忌项校验失败 (questionnaire_id={getattr(questionnaire, 'questionnaire_id', 'N/A')}): "
                f"{type(e).__name__}: {e}",
                exc_info=True
            )
            from .constraint_checker import ConstraintCheckResult as _CR
            constraint_result = _CR(hard_filtered=False)
            # 警告放在最前，确保在报告所有展示位置都最先呈现
            critical_warning = (
                f'🚨 重要提醒：禁忌项校验未能执行（系统异常 {type(e).__name__}）。'
                f'本方案未过滤体检/政审/选科限制等强制条件，'
                f'请务必在报考前由家长/老师人工核对每所院校的招生章程。'
            )
            constraint_result.warnings.insert(0, critical_warning)
            constraint_notes.insert(0, critical_warning)

        try:
            family_answers = self._build_family_answers(questionnaire)
            if family_answers:
                family_resource_result = assess_family_resource(family_answers)
                if family_resource_result.rating == '低':
                    constraint_notes.append(
                        '💡 家庭就业资源评估为"低" — 建议优先考虑技术壁垒高、个人能力主导的专业方向。'
                    )
        except Exception as e:
            # AUDIT-P1-024: 家庭资源评估失败，增加 user-facing 警告
            logging.warning(f"家庭资源评估失败: {e}", exc_info=True)
            constraint_notes.append(
                f'⚠️ 家庭资源评估未能执行（{type(e).__name__}），就业资源建议未纳入推荐。'
            )

        # Step 2.6: 漏斗式排除（选科→学科→体检→兴趣 四步顺序过滤）
        funnel_report = None
        try:
            from .funnel_eliminator import FunnelEliminator
            funnel = FunnelEliminator()
            # 获取全量候选学校（不限制位次，用于漏斗统计）
            user_subjects_list = []
            if questionnaire.subject_combo:
                user_subjects_list = [s.strip() for s in questionnaire.subject_combo.split('+') if s.strip()]
                # 去掉首选科目（物理/历史），只保留再选科目
                user_subjects_list = [s for s in user_subjects_list if s not in ('物理', '历史')]
            # 学科自我评价分数
            eff_scores = None
            if personality_result and hasattr(personality_result, 'self_efficacy'):
                eff_scores = personality_result.self_efficacy
            # RIASEC 风格结果（兼容既有对象字段）
            holland = None
            if personality_result and hasattr(personality_result, 'holland'):
                holland = personality_result.holland
            # 获取全量学校+专业列表
            subject_type = '历史' if questionnaire.category == '历史类' else '物理'
            all_schools_with_majors = self._get_all_schools_with_majors(self._get_cursor(), subject_type)
            if all_schools_with_majors:
                funnel_report = funnel.run_funnel(
                    self._get_cursor(), all_schools_with_majors,
                    user_subjects_list, eff_scores,
                    constraint_result, holland,
                )
        except Exception as e:
            # AUDIT-P1-024: 漏斗排除失败，告警让下游知道"未按选科/体检/兴趣过滤"
            logging.warning(f"漏斗消除失败: {e}", exc_info=True)
            constraint_notes.append(
                f'⚠️ 选科/体检/兴趣漏斗过滤未能执行（{type(e).__name__}），'
                f'推荐结果可能包含不匹配的院校，请人工核对。'
            )

        # Step 3: 构建用户画像
        user_profile = self._build_user_profile(questionnaire)

        # Step 4: 风险策略推断
        risk_strategy = self._infer_risk_strategy(questionnaire, personality_result)
        user_profile.risk_tolerance = risk_strategy

        # Step 5: 生成推荐方案（传递意愿画像）
        recommendations = self._generate_recommendations(
            user_profile, questionnaire, personality_result,
            intention_profile, top_n,
        )

        # H-05: 空推荐/稀疏推荐说明
        notes = []
        notes.extend(constraint_notes)  # 禁忌项+家庭资源提示

        # P1-4 必读告警：合规要点、退档风险、医学受限等"客户必须看见"的提示
        must_ack_warnings: List[str] = []

        # ── F4: 服从调剂风险提示（云南专业组模式，不服从=退档风险）──
        chong_count = len(recommendations.get('冲', []))
        adjustment = questionnaire.major_adjustment or questionnaire.major_adjustment_attitude or ''
        if '不服从' in adjustment:
            warn_msg = (
                '⛔ 不服从专业调剂高风险：考生问卷选择了“不服从”。云南新高考采用院校专业组模式，'
                '投档后若所填专业分数不够且不服从组内调剂，将被直接退档，本批次后续志愿不再检索。'
                '建议仅在确认该专业组内所有专业均可接受、且目标专业录取位次有充分安全垫时才选择不服从。'
            )
            notes.append(warn_msg)
            must_ack_warnings.append(warn_msg)
        if chong_count > 0:
            warn_msg = (
                '⚠️ 服从调剂提示：云南新高考采用"院校专业组"模式，投档后若所填专业分数不够，'
                '如不服从专业调剂将被直接退档（本批次后续志愿不再检索）。'
                f'冲档志愿共{chong_count}所，建议在冲档志愿中勾选"服从专业调剂"以降低退档风险。'
            )
            notes.append(warn_msg)
            must_ack_warnings.append(warn_msg)  # P1-4: 退档风险 → 必读

        # 动态冲稳保比例调整警告
        ratio_warnings = recommendations.pop('_warnings', [])
        notes.extend(ratio_warnings)
        # 漏斗排除报告
        if funnel_report and funnel_report.stages:
            from .funnel_eliminator import FunnelEliminator
            notes.append(FunnelEliminator.format_report(funnel_report))
        for cat in ['冲', '稳', '保']:
            if not recommendations.get(cat):
                notes.append(f'【{cat}】档无匹配院校 — 当前位次({user_profile.rank})在该概率区间内未找到符合条件的学校，建议放宽专业或地域偏好。')
        total = sum(len(v) for v in recommendations.values())
        if total < 10:
            notes.append(f'推荐总数仅{total}所（低于10所），候选池较窄，可能与位次范围设置或偏好限制有关。')

        # 专业宽度预警（脱敏样例场景）
        major_breadth_notes = self._check_major_breadth(user_profile)
        notes.extend(major_breadth_notes)

        # 关键分数段 / 专科段考生：职业本科同等效力提示
        score = questionnaire.total_score or 0
        from .volunteer_recommender import get_config as _get_vrcfg
        _vrcfg = _get_vrcfg()
        if _vrcfg is not None:
            benke_line = _vrcfg.get_score_line(questionnaire.category, '本科线')
        else:
            from .volunteer_recommender import _BENCHMARK_FALLBACK as _bf
            benke_line = _bf.get(questionnaire.category, _bf['物理类'])['本科线']
        is_critical_or_zhuanke = score < benke_line + 30
        if is_critical_or_zhuanke and score >= 200:
            notes.append(
                '💡 职业本科（公办职业技术大学）参考：依据2021国务院学位委员会《关于做好本科'
                '层次职业学校学士学位授权与授予工作意见》，职业本科颁发全日制本科学历及学士'
                '学位证书，在就业、考研、考公等方面与普通本科具有同等法律效力。对于在民办'
                '本科（学费高）与高职专科之间犹豫的考生，公办职业本科是性价比较高的选择。'
                '另可关注"3+2专本贯通"或"高职本科联合培养"项目，入校即锁定升本路径。'
            )

        # C9: 候选池不足预警 — 总推荐<10所且专科段或低分段时触发
        candidate_pool_warning = ''
        if total < 10 and user_profile.rank and user_profile.rank > 80000:
            candidate_pool_warning = (
                f'⚠ 本批次候选数据有限（推荐仅{total}所），可能受限于专科批/历史类数据覆盖率，'
                f'方案仅供参考，建议结合官方招生计划再确认。'
            )

        # Step 5: 生成摘要
        summary = self._generate_summary(
            user_profile, questionnaire, personality_result,
            risk_strategy, recommendations, notes,
        )

        # Step 3: 数据稀疏预警（历史类 2025 年首年新高考，数据量 < 2000 条时触发）
        data_sparsity_warning = ''
        if user_profile.subject_type in ('历史', '历史类', '文科'):
            try:
                from .volunteer_recommender import CURRENT_SCORE_LINE_YEAR
                row = self._get_cursor().execute(
                    f"SELECT COUNT(*) FROM score_line_{CURRENT_SCORE_LINE_YEAR} WHERE subject_type IN ('历史', '历史类')"
                ).fetchone()
                history_count = int(row[0]) if row else 0
                if history_count < 2000:
                    data_sparsity_warning = (
                        f'历史类 2025 年首年新高考，全省数据仅 {history_count} 条'
                        f'（约为物理类 1/3），单年位次波动较大；'
                        '建议保底位次低于自身 15%，本方案已自动扩大保底范围。'
                    )
            except Exception as e:
                logging.warning(f'data_sparsity_warning detection failed: {e}')

        # P1-4: 候选池告警、数据稀疏告警也归入必读
        if candidate_pool_warning:
            must_ack_warnings.append(candidate_pool_warning)
        if data_sparsity_warning:
            must_ack_warnings.append(f'⚠ 数据稀疏提示：{data_sparsity_warning}')
        # 禁忌项 / 体检受限提示也属于合规要点
        for n in constraint_notes:
            if ('禁忌' in n or '受限' in n or '色盲' in n or '色弱' in n) and n not in must_ack_warnings:
                must_ack_warnings.append(n)

        return MatchingResult(
            user_profile=user_profile,
            personality_result=personality_result,
            questionnaire=questionnaire,
            risk_strategy=risk_strategy,
            recommendations=recommendations,
            summary=summary,
            notes=notes,
            intention_profile=intention_profile,
            family_resource_result=family_resource_result,
            constraint_result=constraint_result,
            funnel_report=funnel_report,
            breadth_warnings=major_breadth_notes,
            candidate_pool_warning=candidate_pool_warning,
            data_sparsity_warning=data_sparsity_warning,
            must_ack_warnings=must_ack_warnings,
        )

    # ──────────────────────────────────────────
    # 用户画像构建
    # ──────────────────────────────────────────

    def _build_user_profile(self, questionnaire: UserQuestionnaire) -> UserProfile:
        budget_min, budget_max = self._get_budget_range(questionnaire)
        excluded_majors = self._get_excluded_majors(questionnaire)
        preferred_cities = self._extract_preferred_cities(questionnaire)
        preferred_majors = self._extract_preferred_majors(questionnaire)

        return UserProfile(
            score=questionnaire.total_score,
            rank=questionnaire.rank,
            category=questionnaire.category,
            preferred_cities=preferred_cities,
            preferred_majors=preferred_majors,
            excluded_majors=excluded_majors,
            risk_tolerance='balanced',
            budget_min=budget_min,
            budget_max=budget_max,
            include_early_batch=self._should_include_early_batch(questionnaire),
            wants_military=self._has_special_school(questionnaire, ('军事院校',)),
            wants_police=self._has_special_school(questionnaire, ('公安警校',)),
            wants_teacher_directed=self._has_special_school(
                questionnaire, ('免费师范生', '公费师范生')
            ),
            wants_special_directed=self._has_special_school(questionnaire, ('定向医学生',)),
            has_national_special=self._has_special_plan(questionnaire, ('国家专项计划',)),
            has_local_special=self._has_special_plan(questionnaire, ('地方专项计划',)),
            has_university_special=self._has_special_plan(questionnaire, ('高校专项计划',)),
        )

    def _has_special_school(self, questionnaire: UserQuestionnaire, keywords: Tuple[str, ...]) -> bool:
        selected = questionnaire.special_schools or []
        return any(any(keyword in item for keyword in keywords) for item in selected)

    def _has_special_plan(self, questionnaire: UserQuestionnaire, keywords: Tuple[str, ...]) -> bool:
        selected = questionnaire.special_plan_eligibility or []
        return any(any(keyword in item for keyword in keywords) for item in selected)

    def _should_include_early_batch(self, questionnaire: UserQuestionnaire) -> bool:
        selected = questionnaire.special_schools or []
        if not selected or any('都不考虑' in item for item in selected):
            return False
        return any(
            any(keyword in item for keyword in (
                '军事院校', '公安警校', '免费师范生', '公费师范生',
                '定向医学生', '民族班'
            ))
            for item in selected
        )

    def _allowed_early_batches(self, user_profile: UserProfile) -> set:
        allowed = set()
        if user_profile.wants_teacher_directed:
            allowed.update({'提前本科批A段', '提前本科批D段'})
        if user_profile.wants_military or user_profile.wants_police:
            allowed.add('提前本科批B段')
        if user_profile.wants_flying or user_profile.wants_fire or user_profile.wants_navy:
            allowed.add('提前本科批C段')
        if user_profile.wants_special_directed:
            allowed.add('提前专科批A段')
        if user_profile.wants_military_nco:
            allowed.add('提前专科批B段')
        return allowed

    def _candidate_batches(self, school_name: str, group_code: str, subject_type: str = None) -> List[str]:
        from .volunteer_recommender import CURRENT_SCORE_LINE_YEAR
        norm_type = self.volunteer_recommender.prob_calculator._normalize_subject_type(
            subject_type, CURRENT_SCORE_LINE_YEAR
        ) if subject_type else None
        params = [school_name]
        query = f'SELECT DISTINCT batch FROM score_line_{CURRENT_SCORE_LINE_YEAR} WHERE school_name=?'
        if group_code:
            query += ' AND group_code=?'
            params.append(group_code)
        if norm_type:
            query += ' AND subject_type=?'
            params.append(norm_type)
        rows = self._get_cursor().execute(query, params).fetchall()
        return [r[0] for r in rows if r and r[0]]

    def _filter_candidates_by_batch_eligibility(self, candidates: List, user_profile: UserProfile) -> List:
        """主匹配按用户自报资格过滤提前批，避免军警/定向项目混入普通方案。"""
        if not candidates:
            return candidates
        allowed_early = self._allowed_early_batches(user_profile)
        filtered = []
        for item in candidates:
            school_name = item[0] if isinstance(item, tuple) else item
            group_code = str(item[1]) if isinstance(item, tuple) and len(item) > 1 else ''
            batches = self._candidate_batches(school_name, group_code, user_profile.subject_type)
            if not batches:
                filtered.append(item)
                continue
            if any(not b.startswith('提前') for b in batches):
                filtered.append(item)
                continue
            if any(b in allowed_early for b in batches):
                filtered.append(item)
        return filtered

    # ──────────────────────────────────────────
    # 风险策略推断（融合问卷+职业价值偏好）
    # ──────────────────────────────────────────

    def _infer_risk_strategy(
        self,
        questionnaire: UserQuestionnaire,
        personality_result: Optional[TestResult],
    ) -> str:
        score = 0

        # 稳定性偏好（1-5分）
        score += questionnaire.stability_preference

        # 压力承受力
        stress_map = {
            '能适应很高强度的压力（高强度竞争环境）': 1,
            '能适应很高强度的压力': 1,
            '能适应较高压力': 2,
            '能适应中等压力': 3,
            '只能适应较低压力': 4,
            '偏好低压稳定环境': 5,
        }
        if questionnaire.stress_tolerance in stress_map:
            score += stress_map[questionnaire.stress_tolerance]

        # 核心诉求
        if '学校名气优先' in questionnaire.core_demand:
            score += 2
        if '就业率优先' in questionnaire.core_demand:
            score += 1

        # 四维性格融合影响（校准V3.0: 阈值调整为3.5）
        if personality_result:
            # 大五：神经质高→更保守
            if personality_result.big_five.get('N', 3) > 3.5:
                score += 1
            # 职业价值偏好：工作稳定偏好高→更保守
            cv = personality_result.career_values or {}
            if cv.get('stability', 3) >= 3.5:
                score += 1
            # 职业价值偏好：收入水平高→更激进
            if cv.get('income', 3) >= 3.5:
                score -= 1

        if score <= 5:
            return 'aggressive'
        elif score <= 10:
            return 'balanced'
        else:
            return 'conservative'

    # ──────────────────────────────────────────
    # 推荐方案生成
    # ──────────────────────────────────────────

    def _generate_recommendations(
        self,
        user_profile: UserProfile,
        questionnaire: UserQuestionnaire,
        personality_result: Optional[TestResult],
        intention_profile,  # IntentProfile from intention_inference
        top_n: int,
    ) -> Dict[str, List[SchoolRecommendation]]:
        # Step 0: 判断分数段和科类优先级
        score_segment = self._get_score_segment(questionnaire)
        category = questionnaire.category

        # Step 1: 获取候选院校（传递选科组合用于学校匹配）
        user_subjects = None
        if questionnaire.subject_combo:
            user_subjects = [s.strip() for s in questionnaire.subject_combo.split('+') if s.strip()]

        # 高位次考生（位次<5000）：扩大候选池，否则冲稳保数量不够
        if user_profile.rank < 500:
            tolerance = 5.0  # 超高分（清北档）
        elif user_profile.rank < 5000:
            tolerance = 2.0  # 高分（985/C9档）
        else:
            tolerance = 0.30
        candidates = self.volunteer_recommender.filter_candidates(
            user_profile.rank, tolerance=tolerance,
            subject_type=user_profile.subject_type,
            user_subjects=user_subjects,
            exclude_early_batches=not user_profile.include_early_batch,
        )
        candidates = self._filter_candidates_by_batch_eligibility(candidates, user_profile)
        if not candidates:
            return {'冲': [], '稳': [], '保': []}

        # Step 2: 计算录取概率并分类（动态冲稳保比例调整）
        base_config = STRATEGY_CONFIGS.get(
            user_profile.risk_tolerance, STRATEGY_CONFIGS['balanced'],
        )

        # 框框策略：云南=院校专业组模式（有调剂），检测专业组干净程度
        dirty_count = 0
        has_dirty = False
        excluded_majors = user_profile.excluded_majors or []
        if excluded_majors and candidates:
            # 抽样检查前N所院校专业组是否干净
            for item in candidates[:100]:
                school_name = item[0] if isinstance(item, tuple) else item
                # AUDIT-P1-009: 传入科类避免另一科类的招生专业污染干净度判断
                is_clean, _ = self.volunteer_recommender.check_major_group_clean(
                    school_name, excluded_majors,
                    subject_type=getattr(user_profile, 'subject_type', None),
                )
                if not is_clean:
                    dirty_count += 1
                    has_dirty = True
            if dirty_count > 10:  # 超过10所不干净，视为大范围污染
                has_dirty = True

        config, ratio_warnings = self.volunteer_recommender.adjust_chong_wen_bao_ratio(
            base_config, has_dirty, dirty_count,
        )

        chong_list, wen_list, bao_list = self.volunteer_recommender.classify_schools(
            candidates, user_profile.rank, config,
            subject_type=user_profile.subject_type,
            score_segment=score_segment,
        )

        # Step 3: 应用偏好过滤
        chong_list = self.volunteer_recommender.apply_preferences(chong_list, user_profile)
        wen_list = self.volunteer_recommender.apply_preferences(wen_list, user_profile)
        bao_list = self.volunteer_recommender.apply_preferences(bao_list, user_profile)

        # ── 跨档去重（同一院校专业组只能出现在一个档）──
        def _rec_key(r):
            return (r.school_name, r.group_code)

        chong_keys = {_rec_key(r) for r in chong_list}
        wen_list = [r for r in wen_list if _rec_key(r) not in chong_keys]
        bao_keys = chong_keys | {_rec_key(r) for r in wen_list}
        bao_list = [r for r in bao_list if _rec_key(r) not in bao_keys]

        # 按比例分配目标数量（在_add_major_recommendations之前截断，避免处理将被丢弃的学校）
        total_slots = top_n
        n_chong = int(total_slots * config.get('chong_ratio', 0.15))
        n_wen = int(total_slots * config.get('wen_ratio', 0.55))
        n_bao = total_slots - n_chong - n_wen

        # 按学校层级预排序，确保截断时取的是质量最高的（多取3倍给后续排序留余地）
        def _pre_sort_key(r):
            tier = getattr(r, 'school_tier', '') or ''
            if tier.startswith('L'):
                try:
                    return int(tier[1:])
                except ValueError:
                    pass
            return 99

        chong_list = sorted(chong_list, key=_pre_sort_key)[:n_chong * 3] if n_chong > 0 else []
        wen_list = sorted(wen_list, key=_pre_sort_key)[:n_wen * 3] if n_wen > 0 else []
        bao_list = sorted(bao_list, key=_pre_sort_key)[:n_bao * 3 + 10] if n_bao > 0 else []

        # Step 3.5: 兜底志愿安全检查
        safe_bao, unsafe_bao = self.volunteer_recommender.check_safety_net(
            bao_list, user_profile, user_profile.rank, user_profile.subject_type,
        )
        # 安全兜底在前，不安全兜底在后（带警告标签）
        bao_list = safe_bao + unsafe_bao

        # ── F3 兜底保障：保底缺失时强制填充 ──
        n_bao_target = int(top_n * config.get('bao_ratio', 0.30))
        if len(bao_list) < min(3, n_bao_target):
            # 保底不足时，从候选池中捞概率>=50%的学校作为垫档
            # 候选池按 min_rank ASC 排序（最难考的在前），保底学校在末尾，
            # 因此从末尾倒序检查前 80 所
            fallback_bao = []
            _checked = set()
            # 反向遍历：取候选池末尾 80 所（位次最大、最容易考上的）
            scan_pool = list(reversed(candidates[-80:]))
            for item in scan_pool:
                school_name = item[0] if isinstance(item, tuple) else item
                if school_name in _checked:
                    continue
                _checked.add(school_name)
                group_code = item[1] if isinstance(item, tuple) else ''
                # 跳过已存在于bao_list的学校
                if any(r.school_name == school_name for r in bao_list + fallback_bao):
                    continue
                result = None
                if isinstance(item, tuple) and group_code:
                    result = self.volunteer_recommender.prob_calculator.calculate_group(
                        user_profile.rank, school_name, group_code, subject_type=user_profile.subject_type
                    )
                if result is None:
                    result = self.volunteer_recommender.calculate_probability(
                        user_profile.rank, school_name, subject_type=user_profile.subject_type
                    )
                if result is None or result.probability < 50:
                    continue
                fallback_bao.append(Recommendation(
                    school_name=school_name,
                    category='垫',
                    probability=result.probability,
                    confidence=result.confidence,
                    predicted_rank=result.predicted_rank,
                    reasons=result.reasons + ['⚠️ 垫档（概率50%-85%），安全性低于标准保档志愿，请谨慎填报'],
                    extra_reasons=['⚠️ 该档作为保底不够保险（概率<85%），建议增加更稳妥的保底校'],
                    safety_warning=['垫档志愿，录取概率未达85%标准'],
                ))
                if len(bao_list) + len(fallback_bao) >= max(n_bao_target, 5):
                    break
            if fallback_bao:
                bao_list.extend(fallback_bao)
                ratio_warnings.append(
                    f'⚠️ 标准保底（≥85%概率）仅{len(bao_list) - len(fallback_bao)}所，不足{n_bao_target}所，'
                    f'系统已补充{len(fallback_bao)}所概率50%-85%的学校作为兜底，请谨慎评估。'
                )
            else:
                ratio_warnings.append(
                    f'⚠️ 保底志愿严重不足（标准≥85%概率仅{len(bao_list)}所），'
                    f'且未找到概率50%以上的补充学校。建议放宽地域或专业偏好。'
                )

        # Step 4: 融合推荐专业（使用意愿画像 + 项目自编偏好问卷 + 行业趋势）
        recommended_majors = self._get_recommended_majors(
            personality_result, questionnaire, intention_profile,
        )

        # Step 5: 为每所院校推荐专业（按科类过滤）— 仅处理预截断的列表
        subject_type = user_profile.subject_type
        excluded_majors = user_profile.excluded_majors or []
        chong_recs = self._add_major_recommendations(
            chong_list, recommended_majors, subject_type, user_profile.rank,
            excluded_majors=excluded_majors)
        wen_recs = self._add_major_recommendations(
            wen_list, recommended_majors, subject_type, user_profile.rank,
            excluded_majors=excluded_majors)
        bao_recs = self._add_major_recommendations(
            bao_list, recommended_majors, subject_type, user_profile.rank,
            excluded_majors=excluded_majors)

        # Step 6: 按综合质量排序（好学校好专业排前面，差学校差专业排后面）
        self.volunteer_recommender._load_trend_caches()
        chong_recs = self._sort_by_composite_quality(chong_recs, config, user_profile, questionnaire, personality_result)
        wen_recs = self._sort_by_composite_quality(wen_recs, config, user_profile, questionnaire, personality_result)
        bao_recs = self._sort_by_composite_quality(bao_recs, config, user_profile, questionnaire, personality_result)

        # Step 7: 保档层次保护（关键分数段）
        if score_segment == '关键分数段':
            bao_recs = self._protect_tier_level(bao_recs, questionnaire)

        # Step 8: 各档截取到目标数量，不足时保留实际数量
        chong_recs = chong_recs[:n_chong]
        wen_recs = wen_recs[:n_wen]
        bao_recs = bao_recs[:n_bao]

        # Step 8.5: 拆分"垫档"（50%-85% 概率，不符合标准保档≥85%）为独立类别
        # 防止前端/报告把 50%-85% 当作"保"档展示，违反 CLAUDE.md 绝对约束
        fallback_recs = [r for r in bao_recs if r.category == '垫']
        bao_recs = [r for r in bao_recs if r.category == '保']

        # 运行时硬检查：'保' 档所有 Recommendation 必须 probability >= 85
        # AUDIT-P1-015: 修复循环内修改 bao_recs 导致后续迭代漏检的 bug
        # 原代码在 for 循环内重建 fallback_recs/bao_recs，遍历中修改容器会跳过元素
        # 现改为：循环只标记 r.category，循环结束后统一过滤一次
        for r in bao_recs:
            if r.probability < 85:
                logging.error(
                    f'[P0-A3] 保档混入 probability<85 的学校: '
                    f'{r.school_name} prob={r.probability}'
                )
                # 仅标记不合规的学校
                r.category = '垫'
        # 循环结束后统一重建 fallback_recs 和 bao_recs
        fallback_recs = [r for r in bao_recs if r.category == '垫']
        bao_recs = [r for r in bao_recs if r.category != '垫']

        return {'冲': chong_recs, '稳': wen_recs, '保': bao_recs,
                '垫': fallback_recs, '_warnings': ratio_warnings}

    def _get_score_segment(self, questionnaire) -> str:
        """根据分数判断所处分数段"""
        from .volunteer_recommender import get_score_segment
        score = questionnaire.total_score
        category = questionnaire.category
        return get_score_segment(score, category)

    def _sort_by_composite_quality(self, recs: List, config: Dict = None,
                                   user_profile=None, questionnaire=None,
                                   personality_result=None) -> List:
        """按综合质量排序：好学校好专业排前面，差学校差专业排后面

        主排序：综合质量分（降序）
        次排序：学校层级L1-L21（升序，L1排前）
        微调1：稳档分数利用率（同质量时，概率越靠近下限45%分越不浪费）
        微调2：城市匹配奖励（符合用户城市偏好+3分）
        微调3：深造意向适配（考研→有硕博点院校+2分，考公→政法类强校+2分）
        微调4：学科自我评价奖励（自评≥4.0的学科对应专业+1.5分）
        """
        # 稳档分数利用率微调：同质量时优先概率靠近45%的学校
        def _utilization(rec) -> float:
            if getattr(rec, 'category', '') != '稳':
                return 0.0
            prob = getattr(rec, 'probability', 50)
            if prob < 75:
                return 0.5 * (1.0 - (prob - 45) / 30)  # 最高+0.5
            else:
                return -0.2

        preferred_cities = (user_profile.preferred_cities if user_profile else None) or []
        config = config or {}

        # 深造意向：预计算一次，避免每次排序重复解析
        further_study = list(questionnaire.further_study or []) if questionnaire else []
        civil_service = (questionnaire.civil_service or '') if questionnaire else ''
        wants_postgrad = any(fs in ('国内考研', '国内保研') for fs in further_study)
        wants_civil = civil_service in ('必须保留', '优先考虑') or '考公务员' in further_study or '考事业单位' in further_study
        wants_abroad = '出国读研' in further_study

        # 深造意向：学校保研强度缓存（避免重复查DB）
        _postgrad_cache: Dict[str, float] = {}

        def _postgrad_strength(school_name: str) -> float:
            """返回 0.0-3.0 的保研强度分（基于 num_phd 量化 + 985/211 加成）"""
            if school_name in _postgrad_cache:
                return _postgrad_cache[school_name]
            try:
                cursor = self.volunteer_recommender._get_cursor()
                cursor.execute(
                    "SELECT num_phd, num_master, is_985, is_211 FROM school_info WHERE school_name=?",
                    (school_name,)
                )
                row = cursor.fetchone()
                if not row:
                    _postgrad_cache[school_name] = 0.0
                    return 0.0
                num_phd = int(row[0] or 0)
                num_master = int(row[1] or 0)
                is_985 = row[2] in ('1', 1)
                is_211 = row[3] in ('1', 1)

                # 基础分：博士点/硕士点数量分档（反映科研深度）
                if num_phd >= 50:
                    base = 2.5  # 顶尖研究型大学（清北/华五）
                elif num_phd >= 20:
                    base = 2.0  # 强 985
                elif num_phd >= 10:
                    base = 1.5  # 强 211
                elif num_phd >= 1:
                    base = 1.0  # 有博士点（保研保底）
                elif num_master >= 10:
                    base = 0.7  # 强硕士点
                elif num_master >= 1:
                    base = 0.4  # 有硕士点
                else:
                    base = 0.0

                # 985/211 额外加成（推免名额向双一流倾斜）
                if is_985:
                    base += 0.5
                elif is_211:
                    base += 0.2

                result = min(base, 3.0)
            except Exception:
                result = 0.0
            _postgrad_cache[school_name] = result
            return result

        # 政法类关键词：考公强校
        _CIVIL_KEYWORDS = ('政法', '法学', '公安', '警察', '司法', '检察')

        # 学科自我评价→专业关键词映射（1-5分制，≥4.0为优势信号）
        efficacy = {}
        if personality_result and hasattr(personality_result, 'self_efficacy'):
            efficacy = personality_result.self_efficacy or {}
        _EFFICACY_MAJOR_KEYWORDS = {
            'math':    ('数学', '统计', '金融', '计算机', '精算', '经济'),
            'chinese': ('汉语', '文学', '新闻', '传播', '中文', '编辑'),
            'english': ('英语', '翻译', '外语', '国际'),
        }
        strong_subjects = {subj for subj, score in efficacy.items() if score >= 4.0}

        def _efficacy_bonus(rec) -> float:
            if not strong_subjects:
                return 0.0
            majors = getattr(rec, 'recommended_majors', []) or []
            major_names = ' '.join(getattr(m, 'major_name', '') for m in majors)
            bonus = 0.0
            for subj in strong_subjects:
                keywords = _EFFICACY_MAJOR_KEYWORDS.get(subj, ())
                if any(kw in major_names for kw in keywords):
                    bonus += 1.5
                    break  # 最多加一次，避免叠加过高
            return bonus

        # 基础学科跳板策略：考研/保研意向 + 985院校 + 基础学科专业 → 额外+1.5分
        # 教育部基础学科保研倾斜政策：985基础学科班保研率可达50%（普通经管类仅15%）
        _BASIC_DISCIPLINE_KEYWORDS = (
            '数学', '物理学', '化学', '生物科学', '生物学', '天文',
            '地质', '地理科学', '大气', '海洋', '生态',
            '哲学', '历史学', '考古', '中国语言文学', '汉语言',
            '基础医学', '强基'
        )

        def _basic_discipline_bonus(rec) -> float:
            if not wants_postgrad:
                return 0.0
            # 仅在 985/211 院校提供跳板价值（双非保研率太低）
            quality = getattr(rec, 'school_quality', '') or ''
            if '985' not in quality and '211' not in quality:
                return 0.0
            majors = getattr(rec, 'recommended_majors', []) or []
            major_names = ' '.join(getattr(m, 'major_name', '') for m in majors)
            if any(kw in major_names for kw in _BASIC_DISCIPLINE_KEYWORDS):
                return 1.5
            return 0.0

        # 行业强校识别：双一流学科 + 非双一流强校补丁
        _syl_cache: Dict[str, str] = {}

        def _get_syl(school_name: str) -> str:
            if school_name in _syl_cache:
                return _syl_cache[school_name]
            try:
                cursor = self.volunteer_recommender._get_cursor()
                cursor.execute(
                    "SELECT syl_disciplines FROM school_info WHERE school_name=?",
                    (school_name,)
                )
                row = cursor.fetchone()
                result = (row[0] if row and row[0] else '') or ''
            except Exception:
                result = ''
            _syl_cache[school_name] = result
            return result

        # 用户位次（供区域强工科校验使用）
        user_rank = user_profile.rank if user_profile else 0

        def _industry_strong_bonus(rec) -> float:
            """行业强校奖励，含 tier 分级 + 趋势校验 + 位次校验

            分级（tier）：
              national  — 全国行业话语权（如温州医科大学的眼视光）：全分数段奖励
              regional  — 区域强工科（如浙工大的化工）：仅中分段考生（位次30k-100k）奖励

            "强校"只解决"能进头部"，不改变"行业本身命运"。
            因此奖励还按推荐专业的趋势分加权：
              趋势分 ≥0.5（中性或机会） → 全额
              趋势分 0.3-0.5（轻度风险） → 折半
              趋势分 <0.3（重度风险，如儿科/采矿/学前教育） → 不奖励
            """
            majors = getattr(rec, 'recommended_majors', []) or []
            if not majors:
                return 0.0
            major_text = ' '.join(getattr(m, 'major_name', '') for m in majors)
            syl = _get_syl(rec.school_name)
            tier = get_industry_strong_match(rec.school_name, major_text, syl)
            if not tier:
                return 0.0

            # 区域型只在中分段（位次 30k-100k）有意义
            #   高分段（<30k）：本来就能进 985/211，不需要区域工科补丁
            #   低分段（>100k）：够不到这些一本，无意义
            if tier == 'regional':
                if not (30000 <= user_rank <= 100000):
                    return 0.0
                base_bonus = 1.0
            else:  # national
                base_bonus = 2.0

            # 趋势校验
            from .industry_trends import get_trend_score
            min_trend = 1.0
            for m in majors:
                name = getattr(m, 'major_name', '') or ''
                if not name:
                    continue
                score, _ = get_trend_score(name)
                if score < min_trend:
                    min_trend = score

            if min_trend >= 0.5:
                return base_bonus
            elif min_trend >= 0.3:
                return base_bonus * 0.5
            else:
                return 0.0

        def _score(rec):
            composite = self.volunteer_recommender.compute_composite_score(rec)
            tier = getattr(rec, 'tier_level', '') or ''
            if tier.startswith('L'):
                try:
                    tier_num = int(tier[1:])
                except ValueError:
                    tier_num = 99
            else:
                tier_num = 99

            util = _utilization(rec)

            # 城市匹配奖励
            city_bonus = 3.0 if (preferred_cities and getattr(rec, 'city_preferred', True)) else 0.0

            # 深造意向奖励（各项独立，可叠加，上限5分）
            further_bonus = 0.0
            school_name = rec.school_name
            quality = getattr(rec, 'school_quality', '') or ''
            is_985 = '985' in quality
            is_211 = '211' in quality or is_985  # 985 同时也是 211

            if wants_postgrad:
                # 保研主要发生在 985/211（双非保研率 <5%）。给末流双非按博士点加分对低分段考生是误导
                if is_211:
                    further_bonus += _postgrad_strength(school_name)  # 0.0-3.0 量化分
            if wants_civil and any(kw in school_name for kw in _CIVIL_KEYWORDS):
                further_bonus += 2.0
            if wants_abroad and is_985:
                # 出国意向 + 985：仅在中高分段（位次≤50000）有意义。
                # 位次>50000 的考生够不到任何 985，奖励永远不触发；
                # 但显式校验可避免未来候选池逻辑变化时产生误奖励
                if user_rank and user_rank <= 50000:
                    further_bonus += 2.0
            further_bonus = min(further_bonus, 5.0)

            # 学科自我评价奖励
            efficacy_bonus = _efficacy_bonus(rec)

            # 基础学科跳板奖励（985/211基础学科 + 考研意向）
            basic_bonus = _basic_discipline_bonus(rec)

            # 行业强校奖励（学校命中 AND 推荐专业落在该校强势学科）
            industry_bonus = _industry_strong_bonus(rec)

            return (composite + util + city_bonus + further_bonus + efficacy_bonus + basic_bonus + industry_bonus, -tier_num)

        return sorted(recs, key=_score, reverse=True)

    def _sort_by_segment(self, recs: List, segment: str, category: str) -> List:
        """根据分数段+科类对学校推荐排序"""
        from .volunteer_recommender import SCORE_SEGMENT_WEIGHTS

        weights = SCORE_SEGMENT_WEIGHTS.get(segment, {}).get(
            category, SCORE_SEGMENT_WEIGHTS['中分段']['物理类']
        )
        school_w = weights['school_weight']
        major_w = weights['major_weight']
        city_w = weights['city_weight']

        def _score(rec):
            # 学校质量分: 基于L1-L21层级精细打分（L1=最高21分, L21=最低1分）
            tier = getattr(rec, 'tier_level', '')
            if tier and tier.startswith('L'):
                try:
                    school_score = 22 - int(tier[1:])  # L1=21, L21=1
                except ValueError:
                    school_score = 1
            else:
                # 兜底：用旧标签粗略估计
                quality = getattr(rec, 'school_quality', '')
                if '985' in quality:
                    school_score = 10
                elif '211' in quality:
                    school_score = 9
                elif '双一流' in quality:
                    school_score = 8
                else:
                    school_score = 1

            # 专业匹配分: 有推荐专业=3, 无=1
            major_score = 3 if getattr(rec, 'recommended_majors', []) else 1

            # 城市分: 有地点=2, 无=1
            city_score = 2 if getattr(rec, 'location', '') else 1

            return school_w * school_score + major_w * major_score + city_w * city_score

        return sorted(recs, key=_score, reverse=True)

    def _protect_tier_level(self, bao_recs: List, questionnaire) -> List:
        """
        保档层次保护：关键分数段考生，确保"保"档中有足够本科/专科院校
        PPT策略：关键线上保本科/专科层次优先
        """
        if not bao_recs:
            return bao_recs

        from .volunteer_recommender import get_config as _get_vrcfg
        _vrcfg = _get_vrcfg()
        if _vrcfg is not None:
            benke_line = _vrcfg.get_score_line(questionnaire.category, '本科线')
        else:
            from .volunteer_recommender import _BENCHMARK_FALLBACK as _bf
            benke_line = _bf.get(questionnaire.category, _bf['物理类'])['本科线']
        score = questionnaire.total_score or 0

        # 本科线附近30分以内：优先保留本科院校
        if score >= benke_line and score <= benke_line + 30:
            benke_schools = [r for r in bao_recs if r.batch and '本科' in r.batch]
            zhuanke_schools = [r for r in bao_recs if r.batch and '专科' in r.batch]
            other_schools = [r for r in bao_recs if not r.batch or ('本科' not in r.batch and '专科' not in r.batch)]
            # 本科院校排前
            return benke_schools + other_schools + zhuanke_schools

        # 专科线附近30分以内：确保有专科保底
        if score < benke_line and score >= 200:
            zhuanke_schools = [r for r in bao_recs if r.batch and '专科' in r.batch]
            other_schools = [r for r in bao_recs if not r.batch or '专科' not in r.batch]
            return zhuanke_schools + other_schools

        return bao_recs

    def _get_recommended_majors(
        self,
        personality_result: Optional[TestResult],
        questionnaire: UserQuestionnaire,
        intention_profile=None,
    ) -> List[Tuple[str, str]]:
        """
        获取推荐专业列表 V5.1
        核心原则：明确意愿 > 推断意愿 > 深造规划 > 价值偏好 > 项目自编偏好问卷

        返回: [(major_name, source), ...]
        source ∈ {"explicit", "industry", "further_study", "values", "personality", "civil_service"}
        """
        seen = set()

        def _add(major: str, source: str = "explicit"):
            if major and major not in seen:
                seen.add(major)
                return (major, source)
            return None

        results = []

        # ── 1. 明确意愿（最高优先级，强制TOP 3）───
        explicit_majors = []
        if questionnaire.vertical_majors:
            for m in questionnaire.vertical_majors:
                if m != '都不考虑':
                    item = _add(m, 'explicit')
                    if item:
                        results.append(item)
                        explicit_majors.append(m)

        if questionnaire.acceptable_majors:
            for m in questionnaire.acceptable_majors:
                item = _add(m, 'explicit')
                if item:
                    results.append(item)
                    explicit_majors.append(m)

        # ── 2. 目标行业 → 行业映射 ──
        industry_major_map = {
            '信息技术/互联网': ['计算机科学与技术', '软件工程', '人工智能', '数据科学',
                                 '电子信息工程', '通信工程'],
            '金融/银行': ['金融学', '经济学', '会计学', '财务管理', '金融工程'],
            '教育/培训': ['教育学', '心理学', '汉语言文学', '英语', '数学与应用数学'],
            '医疗/健康': ['临床医学', '口腔医学', '药学', '护理学', '生物医学工程'],
            '法律/政务': ['法学', '政治学与行政学', '社会学', '行政管理'],
            '传媒/艺术': ['新闻传播学', '广播电视学', '艺术设计', '数字媒体技术'],
            '制造业/工程': ['机械工程', '电气工程', '土木工程', '自动化', '测控技术'],
            '能源/环保': ['能源与动力工程', '环境工程', '新能源科学与工程', '电气工程'],
            '建筑/房地产': ['建筑学', '城乡规划', '土木工程', '工程管理'],
            '出版/文博': ['编辑出版学', '图书馆学', '档案学', '文物与博物馆学'],
            '社会服务/NGO': ['社会工作', '公共事业管理', '社会学'],
        }
        for industry in questionnaire.target_industries:
            if industry in industry_major_map:
                for m in industry_major_map[industry]:
                    item = _add(m, 'industry')
                    if item:
                        results.append(item)

        # ── 3. 深造意向适配 ──
        further_study = questionnaire.further_study or []
        further_study_map = {
            '考公务员': ['法学', '汉语言文学', '计算机科学与技术', '会计学',
                        '行政管理', '财务管理', '审计学', '财政学'],
            '考事业单位': ['法学', '汉语言文学', '计算机科学与技术', '会计学',
                          '行政管理', '财务管理', '审计学', '财政学'],
            '国内考研': ['数学与应用数学', '物理学', '化学', '生物学',
                        '计算机科学与技术', '临床医学', '法学'],
            '国内保研': ['数学与应用数学', '物理学', '化学', '生物学',
                        '计算机科学与技术', '临床医学', '法学'],
            '出国读研': ['计算机科学与技术', '数学', '物理学', '化学',
                        '生物工程', '材料科学', '电气工程'],
            '直接就业': ['计算机科学与技术', '软件工程', '电气工程', '自动化',
                        '财务管理', '护理学', '口腔医学技术'],
            '创业': ['工商管理', '计算机科学与技术', '电子商务', '市场营销'],
        }
        for fs in further_study:
            if fs in further_study_map:
                for m in further_study_map[fs]:
                    item = _add(m, 'further_study')
                    if item:
                        results.append(item)

        # ── 考公务员意向（独立于深造意向，q44）───
        cs_pref = questionnaire.civil_service or ''
        if cs_pref in ('必须保留', '优先考虑'):
            for m in ['法学', '汉语言文学', '计算机科学与技术', '会计学',
                      '行政管理', '审计学', '财政学', '税收学', '经济学']:
                item = _add(m, 'civil_service')
                if item:
                    results.append(item)

        # ── 4. 职业价值偏好加权 ──
        if personality_result and personality_result.career_values:
            cv = personality_result.career_values
            values_majors = []
            if cv.get('income', 3) >= 3.5:
                values_majors.extend(['计算机科学与技术', '微电子科学与工程', '金融学',
                                       '软件工程', '电子信息工程', '自动化'])
            if cv.get('stability', 3) >= 3.5:
                values_majors.extend(['公费师范生', '免费医学生', '电气工程及其自动化',
                                       '汉语言文学', '法学', '护理学', '会计学'])
            if cv.get('creative', 3) >= 3.5:
                values_majors.extend(['建筑学', '数字媒体技术', '动画', '工业设计',
                                       '新闻传播学', '视觉传达设计'])
            if cv.get('help', 3) >= 3.5:
                values_majors.extend(['临床医学', '教育学', '心理学', '社会工作',
                                       '护理学', '预防医学'])
            for m in values_majors:
                item = _add(m, 'values')
                if item:
                    results.append(item)

        # ── 5. 项目自编偏好问卷方向（补充，限制最多20%）───
        personality_majors = []
        if personality_result and personality_result.recommendations:
            for m in personality_result.recommendations:
                item = _add(m, 'personality')
                if item:
                    personality_majors.append(item)

        # ── 6. 行业趋势加权 ──
        from .industry_trends import boost_major_scores_by_trend
        all_major_names = [m[0] for m in results]
        scored_majors = boost_major_scores_by_trend(all_major_names)
        # 趋势评分>=0.7的机会行业专业优先保留
        trend_boosted_names = {m for m, s, _ in scored_majors if s >= 0.7}

        # 重排：explicit 专业在最前，trend-boosted 其次，personality 最后
        explicit_results = [m for m in results if m[1] == 'explicit']
        non_explicit = [m for m in results if m[1] != 'explicit' and m[0] in trend_boosted_names]
        personality_results = [m for m in personality_majors if m not in results]

        # personality 专业最多占 20%（TOP 10 中最多2个）
        max_personality = 2
        personality_results = personality_results[:max_personality]

        final_results = explicit_results + non_explicit + personality_results

        return final_results[:25]

    def _add_major_recommendations(
        self,
        schools: List,
        recommended_majors: List[str],
        subject_type: str = None,
        user_rank: int = None,
        excluded_majors: List[str] = None,
    ) -> List[SchoolRecommendation]:
        result = []
        excluded_majors = excluded_majors or []
        for school in schools:
            # 专业组模式：查询指定专业组内的专业
            group_code = getattr(school, 'group_code', '') or ''
            majors = self._get_school_majors(
                school.school_name, school.predicted_rank, subject_type,
                group_code=group_code,
                batch=getattr(school, 'batch', '') or None,
            )
            major_prefs = self._score_majors(majors, recommended_majors)

            # 撤销专业过滤：该校近5年已撤销的专业点不再推荐
            revoked_at_school = set()
            for mp in major_prefs[:]:
                risk = get_revocation_risk(mp.major_name, school.school_name)
                if risk['level'] == 3:
                    revoked_at_school.add(mp.major_name)
                    major_prefs.remove(mp)
            if revoked_at_school:
                school.reasons.append(
                    f'已过滤该校已停招专业: {", ".join(revoked_at_school)}'
                )

            # 排除专业过滤（体检限制/用户明确不考虑）
            if excluded_majors:
                filtered_count = 0
                for mp in major_prefs[:]:
                    for excl in excluded_majors:
                        if self.volunteer_recommender._major_matches_excluded(mp.major_name, excl):
                            major_prefs.remove(mp)
                            filtered_count += 1
                            break
                if filtered_count:
                    school.reasons.append(f'已过滤受限专业{filtered_count}个')

            # 从Recommendation对象获取批次，如为空则查数据库
            batch = getattr(school, 'batch_key', '') or ''
            if not batch:
                # AUDIT-P1-016: 传入 subject_type，避免跨科类返回错误批次
                batch = self._lookup_school_batch(school.school_name, subject_type=subject_type)
            rec = SchoolRecommendation(
                school_name=school.school_name,
                category=school.category,
                probability=float(school.probability.replace('%', ''))
                    if isinstance(school.probability, str) else school.probability,
                confidence=school.confidence,
                predicted_rank=school.predicted_rank,
                school_quality=school.school_quality,
                tier_level=getattr(school, 'school_tier', ''),
                tier_name=getattr(school, 'tier_label', ''),
                location=school.location,
                tuition=school.tuition,
                recommended_majors=major_prefs[:5],
                reasons=school.reasons,
                similar_alternatives=[],
                batch=batch,
                group_code=getattr(school, 'group_code', '') or '',
                group_name=getattr(school, 'group_name', '') or '',
                subject_req=getattr(school, 'subject_req', '') or '',
            )
            # 同专业类降档替代方案
            if user_rank:
                for mp in major_prefs[:3]:
                    alts = self._find_similar_alternatives(
                        school.school_name, mp.major_name, user_rank, subject_type)
                    rec.similar_alternatives.extend(alts)
                rec.similar_alternatives = list(dict.fromkeys(rec.similar_alternatives))
            result.append(rec)
        return result

    def _find_similar_alternatives(
        self,
        school_name: str,
        target_major: str,
        student_rank: int,
        subject_type: str = None,
    ) -> List[str]:
        """
        同专业类内找可替代专业（降档方案）

        场景：用户想学A专业，但A专业录取位次高（风险大），
        同一专业类下B专业录取位次低（能上），推荐B作为替代。
        """
        c = self._get_cursor()

        # 1. 查目标专业的major_class_code
        c.execute('''
            SELECT major_class_code FROM major_catalog
            WHERE major_name = ? AND major_class_code IS NOT NULL
            LIMIT 1
        ''', (target_major,))
        row = c.fetchone()
        if not row or not row[0]:
            return []

        class_code = row[0]

        # 2. 查同专业类下的所有专业
        c.execute('''
            SELECT major_name FROM major_catalog
            WHERE major_class_code = ?
        ''', (class_code,))
        siblings = [r[0] for r in c.fetchall()]
        if not siblings:
            return []

        # 3. 查该校各替代专业的录取位次
        placeholders = ','.join('?' * len(siblings))
        params = [school_name] + siblings
        where = f"school_name = ? AND major_name IN ({placeholders})"
        if subject_type:
            from .subject_normalize import aliases_for_sql_param
            aliases = aliases_for_sql_param(subject_type)
            where += f" AND subject_type IN ({', '.join('?' for _ in aliases)})"
            params.extend(aliases)

        # 走规范视图，规避 2020-2022 新旧标签双计（H2）
        c.execute(f'''
            SELECT major_name, AVG(min_rank) as avg_r, MIN(min_rank) as min_r
            FROM v_enroll_detail
            WHERE {where}
            GROUP BY major_name
        ''', params)
        ranks = {}
        for r in c.fetchall():
            if r[1] is not None and r[2] is not None:
                ranks[r[0]] = (int(r[1]), int(r[2]))

        # 4. 找录取位次 >= 学生位次的替代（学生能上），过滤已撤销专业
        alts = []
        for s in siblings:
            if s == target_major:
                continue
            # 该校已撤销的专业不作为替代方案
            risk = get_revocation_risk(s, school_name)
            if risk['level'] == 3:
                continue
            avg_r, min_r = ranks.get(s, (0, 0))
            if min_r >= student_rank * 0.95:  # 最低录取位次 >= 学生位次（含5%容差）
                alts.append(s)

        return alts[:3]

    def _get_school_majors(self, school_name: str, rank: int,
                           subject_type: str = None,
                           group_code: str = None,
                           batch: str = None) -> List[str]:
        """获取学校/专业组内的专业列表

        参数:
            school_name: 学校名称
            rank: 预测位次
            subject_type: 科类
            group_code: 专业组代码（可选，优先使用enroll_plan_2025）
            batch: 批次（可选；同组号跨批次复用时必须传入，否则可能混批 — H4）
        """
        # 优先使用招生计划按专业组查询（表名按年份参数化，2026年改 CURRENT_PLAN_YEAR）
        from .volunteer_recommender import CURRENT_PLAN_YEAR
        plan_table = f'enroll_plan_{CURRENT_PLAN_YEAR}'
        if group_code:
            group_label = f'{group_code}专业组' if not group_code.endswith('专业组') else group_code
            # 科类映射到 enroll_plan_*.category 实际取值（物理类/历史类）
            if subject_type in ('物理', '物理类', '理科'):
                cat_filter = '物理类'
            elif subject_type in ('历史', '历史类', '文科'):
                cat_filter = '历史类'
            else:
                # AUDIT-P2-023: 未知科类显式报错，而非静默返回空列表
                logger.warning(f'_get_school_majors: 未知科类类型 subject_type={subject_type!r}，school={school_name}')
                return []

            conds = ['school_name = ?', 'subject_group = ?']
            params: list = [school_name, group_label]
            if cat_filter:
                conds.append('category = ?')
                params.append(cat_filter)
            if batch:
                # H4: 同组号在多批次复用时必须按 batch 过滤，否则会混入其他批次的专业
                conds.append('batch = ?')
                params.append(batch)
            query = f'SELECT DISTINCT sp_name FROM {plan_table} WHERE ' + ' AND '.join(conds)
            self._get_cursor().execute(query, params)
            rows = [row[0] for row in self._get_cursor().fetchall() if row[0]]
            if rows:
                return rows[:20]

        # Fallback: 查规范视图 v_enroll_detail（防 2020-2022 双标签）
        query = '''
            SELECT DISTINCT major_name
            FROM v_enroll_detail
            WHERE school_name = ? AND min_rank IS NOT NULL
        '''
        params = [school_name]
        if subject_type:
            # 科类过滤（兼容新旧高考标签），统一走 subject_normalize
            from .subject_normalize import aliases_for_sql_param
            aliases = aliases_for_sql_param(subject_type)
            query += f" AND subject_type IN ({', '.join('?' for _ in aliases)})"
            params.extend(aliases)
        query += ' ORDER BY min_rank LIMIT 20'
        self._get_cursor().execute(query, params)
        return [row[0] for row in self._get_cursor().fetchall()]

    def _score_majors(
        self,
        school_majors: List[str],
        recommended_majors: List,
    ) -> List[MajorPreference]:
        # 兼容 tuple(major_name, source) 和 str 两种格式
        major_to_source = {}
        for item in recommended_majors:
            if isinstance(item, tuple):
                major_to_source[item[0]] = item[1]
            else:
                major_to_source[item] = 'unknown'

        major_rank = {m: i for i, m in enumerate(major_to_source.keys())}
        recommended_classes = {}
        for major_name, source in major_to_source.items():
            if major_name.endswith('类'):
                recommended_classes[major_name] = source

        # 加载2026新增专业集合
        new_major_set = self._get_new_major_set()

        prefs = []
        for i, major in enumerate(school_majors):
            bonus, trend_label = self._get_trend_bonus(major)
            is_new = major in new_major_set
            if major in major_to_source:
                idx = major_rank[major]
                score = min(110, 90 + (20 - idx) + bonus)
                source = major_to_source[major]
                reason = self._major_reason(source, idx)
                if trend_label:
                    reason += trend_label
            elif recommended_classes:
                matched_class = self._match_recommended_major_class(major, recommended_classes)
                if matched_class:
                    idx = major_rank[matched_class]
                    score = min(105, 86 + (20 - idx) + bonus)
                    source = recommended_classes[matched_class]
                    reason = self._major_reason(source, idx) + f'，匹配{matched_class}'
                    if trend_label:
                        reason += trend_label
                else:
                    score = max(45, min(85, 80 - i + bonus))
                    reason = '院校优势专业'
                    if trend_label:
                        reason += trend_label
            else:
                score = max(45, min(85, 80 - i + bonus))
                reason = '院校优势专业'
                if trend_label:
                    reason += trend_label
            emp_rate, avg_salary = self._get_employment_stats(major)
            revocation_risk = self._get_revocation_risk_label(major)

            # P1-3: 新专业特殊处理 — 置信度降级 + 补充说明
            final_score = score
            reason_suffix = ''
            if is_new:
                # 新专业无历史数据，参考同类专业估算，置信度上限降级
                similar_info = self._get_similar_major_historical_data(major)
                if similar_info:
                    reason_suffix = f'（2026新增，参考{similar_info["major_class"]}同类专业，就业率{similar_info["employment_rate"]}）'
                else:
                    reason_suffix = '（2026新增，无历史录取数据，仅供参考）'
                final_score = min(final_score, 70)  # 置信度上限降级

            prefs.append(MajorPreference(
                major_name=major, score=final_score, reason=reason + reason_suffix if reason_suffix else reason,
                is_new_major=is_new,
                revocation_risk=revocation_risk,
                employment_rate=emp_rate,
                avg_salary=avg_salary))
        prefs.sort(key=lambda x: x.score, reverse=True)
        return prefs

    def _match_recommended_major_class(self, major_name: str, recommended_classes: Dict[str, str]) -> Optional[str]:
        """推荐项为专业类时，用 major_catalog 将学校具体专业映射回专业类匹配。"""
        major_class = self._get_major_class(major_name)
        if major_class in recommended_classes:
            return major_class
        for rec_class in recommended_classes:
            if rec_class and (rec_class in major_name or major_name in rec_class):
                return rec_class
        return None

    def _major_reason(self, source: str, idx: int) -> str:
        """根据专业来源生成推荐理由"""
        source_labels = {
            'explicit': '您的明确偏好',
            'industry': '目标行业映射',
            'further_study': '深造意向适配',
            'values': '职业价值偏好匹配',
            'personality': '项目自编偏好问卷方向参考',
            'civil_service': '考公意向专业',
        }
        label = source_labels.get(source, '推荐专业')
        return f'{label}（TOP{idx + 1}）'

    # ──────────────────────────────────────────
    # C4/C5: 撤销风险 + 就业薪资数据查询
    # ──────────────────────────────────────────

    def _get_employment_stats(self, major_name: str) -> Tuple[float, float]:
        """查询专业就业率和平均月薪。无数据时返回 (0, 0)"""
        if not hasattr(self, '_emp_cache'):
            self._emp_cache: Dict[str, Tuple[float, float]] = {}
        if major_name in self._emp_cache:
            return self._emp_cache[major_name]
        try:
            row = self._get_cursor().execute(
                'SELECT employment_rate, avg_salary_monthly '
                'FROM major_employment_stats WHERE major_name = ? LIMIT 1',
                (major_name,)
            ).fetchone()
            result = (float(row[0] or 0), float(row[1] or 0)) if row else (0.0, 0.0)
        except Exception as e:
            logging.warning(f'_get_employment_stats({major_name}) failed: {e}')
            result = (0.0, 0.0)
        self._emp_cache[major_name] = result
        return result

    def _get_revocation_risk_label(self, major_name: str) -> str:
        """
        查询专业近5年撤销趋势：rising/stable/declining/none
        - rising: 2023+2024 撤销数 > 2020+2021
        - declining: 2023+2024 撤销数 < 2020+2021
        - stable: 持平
        - none: 无撤销记录
        """
        if not hasattr(self, '_revocation_cache'):
            self._revocation_cache: Dict[str, str] = {}
        if major_name in self._revocation_cache:
            return self._revocation_cache[major_name]
        label = 'none'
        try:
            row = self._get_cursor().execute(
                "SELECT "
                "  COALESCE(SUM(CASE WHEN year IN (2020,2021) THEN revoke_count END), 0), "
                "  COALESCE(SUM(CASE WHEN year IN (2023,2024) THEN revoke_count END), 0) "
                "FROM major_revocation_stats WHERE major_name = ?",
                (major_name,)
            ).fetchone()
            if row:
                early, recent = int(row[0]), int(row[1])
                if early + recent == 0:
                    label = 'none'
                elif recent > early:
                    label = 'rising'
                elif recent < early:
                    label = 'declining'
                else:
                    label = 'stable'
        except Exception as e:
            logging.warning(f'_get_revocation_risk_label({major_name}) failed: {e}')
        self._revocation_cache[major_name] = label
        return label

    # ──────────────────────────────────────────
    # 2026新增专业标记
    # ──────────────────────────────────────────

    def _get_new_major_set(self) -> Set[str]:
        """加载2026新增专业名称集合（remark标记为'2026年教育部新增'的专业）"""
        if not hasattr(self, '_new_major_set'):
            self._new_major_set: Set[str] = set()
            try:
                rows = self._get_cursor().execute(
                    "SELECT major_name FROM major_catalog WHERE remark LIKE '%2026年新增%'"
                ).fetchall()
                self._new_major_set = {r[0] for r in rows if r[0]}
            except Exception as e:
                logging.warning(f"加载2026新增专业失败: {e}")
                pass
        return self._new_major_set

    def _get_similar_major_historical_data(self, major_name: str) -> Optional[Dict[str, Any]]:
        """P1-3: 为新增专业查找同类专业历史数据作为参考"""
        self._get_cursor().execute(
            'SELECT major_class FROM major_catalog WHERE major_name = ? AND major_class IS NOT NULL LIMIT 1',
            (major_name,),
        )
        row = self._get_cursor().fetchone()
        if not row:
            return None
        major_class = row[0]

        # 查询该专业类的平均录取位次和就业率
        cursor = self._get_cursor()
        try:
            cursor.execute(
                'SELECT AVG(min_rank) FROM enroll_major_detail '
                'WHERE major_class = ? AND min_rank IS NOT NULL LIMIT 1',
                (major_class,),
            )
            avg_rank_row = cursor.fetchone()
            avg_rank = int(avg_rank_row[0]) if avg_rank_row and avg_rank_row[0] else None

            # 就业率从 major_employment_stats 取
            cursor.execute(
                'SELECT employment_rate FROM major_employment_stats '
                'WHERE major_class = ? AND employment_rate IS NOT NULL LIMIT 1',
                (major_class,),
            )
            emp_row = cursor.fetchone()
            emp_rate = round(emp_row[0], 1) if emp_row and emp_row[0] else None
        except Exception:
            avg_rank = None
            emp_rate = None

        return {
            'major_class': major_class,
            'avg_rank': avg_rank,
            'employment_rate': f'{emp_rate}%' if emp_rate is not None else '未知',
        }

    # ──────────────────────────────────────────
    # 趋势评分缓存
    # ──────────────────────────────────────────

    def _get_trend_cache(self) -> Dict[str, float]:
        """
        惰性加载热门学科趋势评分缓存
        返回: {major_class: composite_score}
        """
        if not hasattr(self, '_trend_cache'):
            self._trend_cache: Dict[str, float] = {}
            try:
                from .hot_major_analyzer import HotMajorAnalyzer
                analyzer = HotMajorAnalyzer(self._db_path)
                scores = analyzer.analyze(year=2025)
                for s in scores:
                    if s.major_class not in self._trend_cache or s.composite_score > self._trend_cache[s.major_class]:
                        self._trend_cache[s.major_class] = s.composite_score
            except Exception as e:
                logging.warning(f"加载趋势缓存失败: {e}")
                pass
        return self._trend_cache

    def _get_major_class(self, major_name: str) -> Optional[str]:
        """查询专业所属的专业类（如'计算机类'）"""
        if not major_name:
            return None
        self._get_cursor().execute(
            'SELECT major_class FROM major_catalog WHERE major_name = ? AND major_class IS NOT NULL LIMIT 1',
            (major_name,),
        )
        row = self._get_cursor().fetchone()
        return row[0] if row else None

    def _get_trend_bonus(self, major_name: str) -> Tuple[int, str]:
        """
        计算专业趋势加分（基于HotMajorAnalyzer评分）
        返回: (bonus_int, label_str)
        """
        cache = self._get_trend_cache()
        if not cache:
            return 0, ''

        major_class = self._get_major_class(major_name)
        if not major_class or major_class not in cache:
            return 0, ''

        score = cache[major_class]
        if score >= 75:
            return 5, '（热度趋势+）'
        elif score >= 60:
            return 2, ''
        elif score < 30:
            return -3, '（热度趋势-）'
        return 0, ''

    def _lookup_school_batch(self, school_name: str, subject_type: str = None) -> str:
        """查询学校所属批次（2025年新高考）

        AUDIT-P1-016: 增加 subject_type 参数，避免跨科类返回错误批次。
        同一学校在物理类和历史类下批次可能不同（如某校物理一本/历史二本）。
        """
        if not school_name:
            return ''
        sql = (
            "SELECT DISTINCT batch FROM v_enroll_detail "
            "WHERE school_name = ? AND batch IS NOT NULL AND batch != '' "
        )
        params: list = [school_name]
        if subject_type:
            from .subject_normalize import aliases_for_sql_param
            aliases = aliases_for_sql_param(subject_type)
            placeholders = ','.join(['?'] * len(aliases))
            sql += f"AND subject_type IN ({placeholders}) "
            params.extend(aliases)
        sql += (
            "ORDER BY CASE "
            "  WHEN batch LIKE '提前本科批%' THEN 1 "
            "  WHEN batch LIKE '本科批%' THEN 2 "
            "  WHEN batch LIKE '提前专科批%' THEN 3 "
            "  WHEN batch LIKE '高职专科批%' THEN 4 "
            "  ELSE 5 END "
            "LIMIT 1"
        )
        self._get_cursor().execute(sql, params)
        row = self._get_cursor().fetchone()
        return row[0] if row else ''

    # ──────────────────────────────────────────
    # 预算与排除专业
    # ──────────────────────────────────────────

    def _get_budget_range(self, questionnaire: UserQuestionnaire) -> Tuple[float, float]:
        budget_map = {
            '2万元以内': (0, 20000),
            '2-4万元': (20000, 40000),
            '4-6万元': (40000, 60000),
            '6-10万元': (60000, 100000),
            '10-15万元': (100000, 150000),
            '15万元以上': (150000, 9999999),
        }
        budget = self._normalize_budget_label(questionnaire.total_budget)
        if budget in budget_map:
            return budget_map[budget]
        return (0, 100000)

    def _normalize_budget_label(self, budget: str) -> str:
        """兼容历史测试数据的少量缺字写法，内部统一到 JSON 真实选项。"""
        aliases = {
            '2-4万': '2-4万元',
            '4-6万': '4-6万元',
            '6-10万': '6-10万元',
            '10-15万': '10-15万元',
            '15万以上': '15万元以上',
        }
        return aliases.get(budget or '', budget or '')

    def _get_excluded_majors(self, questionnaire: UserQuestionnaire) -> List[str]:
        """获取排除专业列表（意愿 + 体检 + 约束校验，去重）。"""
        return self._merge_excluded_majors(questionnaire)

    def _get_health_restrictions(self, questionnaire: UserQuestionnaire) -> List[str]:
        """根据体检结论返回受限专业（使用归一化色觉值）。"""
        if not questionnaire.health_screening:
            return []
        restrictions = []
        hs = questionnaire.health_screening

        # 色觉归一化：兼容前端多种存储格式
        cv = hs.color_vision or ''
        # 正常选项也包含“色盲/色弱”，必须先排除；不明确值不假设受限。
        if cv.startswith('无') or cv in ('', '正常', '不清楚', '未知'):
            pass
        elif '色盲' in cv:
            restrictions.extend(['化学类', '医学类', '生物类', '美术类'])
        elif '色弱' in cv:
            restrictions.extend(['化学类', '医学类'])
        if hs.smell == '嗅觉迟钝':
            restrictions.append('食品科学类')
        return restrictions

    # ──────────────────────────────────────────
    # 排除专业合并（意愿 + 体检，去重）
    # ──────────────────────────────────────────

    def _merge_excluded_majors(self, questionnaire: UserQuestionnaire) -> List[str]:
        """合并意愿排除、体检限制、约束校验注入的排除专业，去重返回。"""
        excluded = []

        # 意愿排除
        if questionnaire.medical_preference == '绝对不考虑':
            excluded.append('医学类')
        if questionnaire.agriculture_preference == '绝对不考虑':
            excluded.append('农学类')
        if questionnaire.physics_willingness == '绝对不考虑':
            excluded.extend(['物理学', '应用物理学'])
        if questionnaire.chemistry_willingness == '绝对不考虑':
            excluded.extend(['化学', '应用化学'])
        if questionnaire.history_willingness == '绝对不考虑':
            excluded.extend(['历史学'])
        if questionnaire.foreign_language_willingness == '绝对不考虑':
            excluded.extend(['外国语言文学类'])

        # "都不考虑"标记
        if '都不考虑' in (questionnaire.vertical_majors or []):
            excluded.append('垂直类专业')

        # 体检限制（归一化后的色觉值）
        excluded.extend(self._get_health_restrictions(questionnaire))

        # 约束校验注入（色弱/色盲等通过 exam_codes 触发的过滤）
        # 注意：constraint checker 的 filtered_majors 已经通过 questionnaire.excluded_majors 注入
        # 此处合并时去重，避免和 _get_health_restrictions() 产生重复
        constraint_injected = getattr(questionnaire, 'excluded_majors', [])
        for m in constraint_injected:
            if m not in excluded:
                excluded.append(m)

        return excluded

    # ──────────────────────────────────────────
    # 城市与专业偏好提取
    # ──────────────────────────────────────────

    def _extract_preferred_cities(self, questionnaire: UserQuestionnaire) -> List[str]:
        city_map = {
            '一线城市（北上广深）': ['北京', '上海', '广州', '深圳'],
            '新一线城市（成都/杭州/武汉等）': [
                '成都', '杭州', '武汉', '南京', '重庆', '西安', '苏州', '天津',
            ],
            '二线城市': ['昆明', '贵阳', '南宁', '长沙', '郑州', '济南', '福州', '厦门'],
            '家乡所在省': ['昆明'],
        }

        # 优先使用职业地域倾向
        if questionnaire.location_preference in city_map:
            return city_map[questionnaire.location_preference]

        # 其次使用大学就读地域偏好
        province_map = {
            '必须留在云南': ['昆明', '大理', '曲靖', '玉溪'],
            '优先省内，省外也可以': ['昆明', '大理', '曲靖', '玉溪',
                                      '北京', '上海', '广州', '武汉', '成都'],
            '只想去特定地区': [],  # 需额外标注
        }
        if questionnaire.province_preference in province_map:
            return province_map[questionnaire.province_preference]

        return []

    def _extract_preferred_majors(self, questionnaire: UserQuestionnaire) -> List[str]:
        majors = []
        if questionnaire.vertical_majors:
            majors.extend([m for m in questionnaire.vertical_majors if m != '都不考虑'])
        if questionnaire.acceptable_majors:
            majors.extend(questionnaire.acceptable_majors)
        return majors

    # ──────────────────────────────────────────
    # 禁忌项答案构建（从问卷中提取）
    # ──────────────────────────────────────────

    def _build_constraint_answers(self, questionnaire: UserQuestionnaire) -> Dict:
        """从问卷数据构建禁忌项校验输入

        AUDIT-P0-012: 修复前 foreign_language / political_status / criminal_record
        被初始化为空但从不从 questionnaire 填入，导致外语/政审/直系亲属记录三项禁忌
        校验始终读到空值并静默跳过。此次改为直接从 questionnaire 字段拉取，
        并把直系亲属犯罪记录的"有/无"字符串归一化为 boolean。
        """
        # AUDIT-P0-012: criminal_record 在 questionnaire 中为字符串（'有'/'无'/'是'/'否'/'…'）
        _cr_raw = (getattr(questionnaire, 'criminal_record', '') or '').strip()
        _criminal_record_bool = _cr_raw in (
            '有', '是', 'yes', 'Yes', 'True', 'true', '1',
        )

        answers = {
            'gender': questionnaire.gender or '男',
            'birth_date': questionnaire.birth or '',
            'ethnicity': questionnaire.ethnicity or '',
            # AUDIT-P0-012: 三处禁忌字段必须从 questionnaire 真实拉取
            'foreign_language': getattr(questionnaire, 'foreign_language', '') or '',
            'political_status': getattr(questionnaire, 'political_status', '') or '',
            'criminal_record': _criminal_record_bool,
            # 体检相关（下方 health_screening 块继续覆盖）
            'exam_codes': [],
            'left_eye_vision': None,
            'right_eye_vision': None,
            'color_vision': None,
            'height': None,
            'weight': None,
            'tattoo': False,
            'corrected_vision_degree': 0,
            # AUDIT-P0-010 联动：把未成年标识透传，让 check_constraints 补提醒
            'is_minor': getattr(questionnaire, 'is_minor', False),
            'guardian_consent': getattr(questionnaire, 'guardian_consent', False),
            'gaokao_year': getattr(questionnaire, 'gaokao_year', None),
        }

        # 从体检结论提取
        if questionnaire.health_screening:
            hs = questionnaire.health_screening
            cv = hs.color_vision or ''
            # 与体检专业筛选一致：先排除正常/不明确选项。
            if cv.startswith('无') or cv == '正常':
                answers['color_vision'] = '正常'
            elif cv in ('', '不清楚', '未知'):
                pass  # 保留 None，不把不明确值假设为正常或异常
            elif '色盲' in cv:
                answers['color_vision'] = '色盲'
            elif '色弱' in cv:
                answers['color_vision'] = '色弱'
            elif '障碍' in cv or '识别' in cv:
                answers['color_vision'] = '颜色识别障碍'
            elif cv:
                answers['color_vision'] = cv

            # 视力
            if hs.vision:
                try:
                    v = float(hs.vision)
                    answers['left_eye_vision'] = v
                    answers['right_eye_vision'] = v
                except (ValueError, TypeError):
                    pass

            # 身高体重
            if hs.height:
                try:
                    answers['height'] = int(hs.height)
                except (ValueError, TypeError):
                    pass
            if hs.weight:
                try:
                    answers['weight'] = int(hs.weight)
                except (ValueError, TypeError):
                    pass

            # 纹身
            if hs.tattoo and hs.tattoo in ('有', '是', 'yes', 'Yes', 'True', 'true'):
                answers['tattoo'] = True

        # 单科成绩（用于单科门槛校验）
        answers['english_score'] = getattr(questionnaire, 'english_score', None)
        answers['math_score'] = getattr(questionnaire, 'math_score', None)
        answers['chinese_score'] = getattr(questionnaire, 'chinese_score', None)

        return answers

    # ──────────────────────────────────────────
    # 家庭资源答案构建（从问卷中提取）
    # ──────────────────────────────────────────

    def _build_family_answers(self, questionnaire: UserQuestionnaire) -> Optional[Dict]:
        """从问卷数据构建家庭资源评估输入"""
        # 检查是否有足够的家庭背景信息
        if not questionnaire.parent_occupation and not questionnaire.parent_education:
            return None

        answers = {
            'father_occupation': 10,
            'mother_occupation': 10,
            'family_income_group': 5,
            'father_education': questionnaire.parent_education or '',
            'mother_education': questionnaire.parent_education or '',
            'family_industry': '',
            'gov_relative_count': 0,
            'business_contact_count': 0,
            'professional_relative_count': 0,
            'has_internship_opportunity': False,
            'family_support_level': 3,
            'dependency_on_family': 3,
        }

        # 职业类型映射（从问卷q42字符串 → 阶层代码）
        # 问卷只收集一个parent_occupation字段，同时用于父/母
        occ = questionnaire.parent_occupation or ''

        def _occ_code(occ_text: str) -> int:
            if '公务员' in occ_text or '领导' in occ_text:
                return 1
            elif '经理' in occ_text or '管理' in occ_text:
                return 2
            elif '老板' in occ_text or '企业' in occ_text:
                return 3
            elif '教师' in occ_text or '医生' in occ_text or '工程师' in occ_text or '律师' in occ_text:
                return 4
            elif '文员' in occ_text or '办事' in occ_text:
                return 5
            elif '个体' in occ_text:
                return 6
            elif '服务' in occ_text or '销售' in occ_text:
                return 7
            elif '工人' in occ_text:
                return 8
            elif '农民' in occ_text or '农业' in occ_text:
                return 9
            return 10

        occ_code = _occ_code(occ)
        answers['father_occupation'] = occ_code
        answers['mother_occupation'] = occ_code

        # 收入映射（从学费预算推断）
        budget = self._normalize_budget_label(questionnaire.total_budget)
        budget_map = {
            '2万元以内': 5,
            '2-4万元': 4,
            '4-6万元': 3,
            '6-10万元': 2,
            '10-15万元': 1,
            '15万元以上': 1,
        }
        if budget in budget_map:
            answers['family_income_group'] = budget_map[budget]

        resources = set(questionnaire.family_resources or [])
        if '政府机关人脉' in resources:
            answers['gov_relative_count'] = max(answers['gov_relative_count'], 1)
            answers['family_industry'] = '体制内'
        if '企业资源' in resources or '金融资源' in resources:
            answers['business_contact_count'] = max(answers['business_contact_count'], 1)
            if not answers['family_industry']:
                answers['family_industry'] = '企业'
        professional_resources = {'高校/科研院所', '医疗机构', '法律资源'}
        prof_count = len(resources & professional_resources)
        if prof_count:
            answers['professional_relative_count'] = max(
                answers['professional_relative_count'], prof_count
            )
            if not answers['family_industry']:
                answers['family_industry'] = '新兴行业'
        if resources - {'无特殊资源'}:
            answers['has_internship_opportunity'] = True

        return answers

    # ──────────────────────────────────────────
    # 漏斗排除：获取全量学校+专业数据
    # ──────────────────────────────────────────

    def _get_all_schools_with_majors(self, cursor, subject_type: str) -> List[dict]:
        """获取全量学校及其招生专业列表（不限位次，用于漏斗统计）

        注意：enroll_plan_2025.category 实际取值为 '物理类' / '历史类'，
        不是 '物理' / '历史'。此处必须用全称否则匹配 0 行（H1 修复）。
        """
        if subject_type in ('历史', '历史类', '文科'):
            category_filter = '历史类'
        else:
            category_filter = '物理类'
        schools_raw = cursor.execute(
            'SELECT school_id, school_name, school_tier, school_tier_label '
            'FROM school_info WHERE school_tier IS NOT NULL'
        ).fetchall()

        result = []
        for school in schools_raw:
            school_id = school[0]
            school_name = school[1]
            # 获取该校在subject_type下的招生专业（表名按年份参数化）
            from .volunteer_recommender import CURRENT_PLAN_YEAR
            majors_raw = cursor.execute(
                f'SELECT sp_name, subject_req '
                f'FROM enroll_plan_{CURRENT_PLAN_YEAR} WHERE school_name=? AND category=?',
                (school_name, category_filter),
            ).fetchall()
            # P0-A4: 科类隔离 — 严禁回退到不限 category 的查询，
            # 否则会用另一科类的招生计划进入漏斗判断，违反 CLAUDE.md 绝对约束。
            # 查不到时直接跳过本校，让上层标注"该科类招生计划缺失"。

            major_list = [
                {'major_name': m[0], 'major_class': '', 'subject_req': m[1] or ''}
                for m in majors_raw
            ]
            if major_list:
                result.append({
                    'school_id': school_id,
                    'school_name': school[1],
                    'tier_level': str(school[2] or ''),
                    'tier_name': school[3] or '',
                    'major_list': major_list,
                })
        return result

    # ──────────────────────────────────────────
    # 专业宽度预警（脱敏样例场景）
    # ──────────────────────────────────────────

    def _check_major_breadth(self, user_profile: UserProfile) -> List[str]:
        """检测专业偏好是否过窄，可能导致可选学校极少"""
        notes = []
        preferred = user_profile.preferred_majors or []
        excluded = user_profile.excluded_majors or []

        # 仅目标专业 ≤2 个 → 红色预警
        if len(preferred) > 0 and len(preferred) <= 2:
            notes.append(
                f'⚠️ 专业选择较集中（{len(preferred)}个：{"/".join(preferred)}），'
                f'大幅缩小可选学校范围。历史案例显示此类策略易被不理想专业调剂录取。'
            )
        # 3-5 个 → 黄色预警
        elif 3 <= len(preferred) <= 5:
            notes.append(
                f'💡 专业偏好适中（{len(preferred)}个），建议考虑相关专业作为备选，'
                f'以增加可选学校数量。'
            )

        # 排除专业过多 → 进一步缩小范围
        if len(excluded) >= 3:
            notes.append(
                f'⚠️ 排除了{len(excluded)}个专业方向（{"/".join(excluded[:5])}），'
                f'进一步限制了可选学校范围。'
            )

        return notes

    # ──────────────────────────────────────────
    # 摘要生成 V3.0
    # ──────────────────────────────────────────

    def _generate_summary(
        self,
        user_profile: UserProfile,
        questionnaire: UserQuestionnaire,
        personality_result: Optional[TestResult],
        risk_strategy: str,
        recommendations: Dict,
        notes: List[str] = None,
    ) -> str:
        bf_line = '未测试'
        holland_line = '未测试'
        efficacy_line = '未测试'
        values_line = '未测试'
        major_line = '无'

        if personality_result:
            bf = personality_result.big_five
            bf_line = (f"O={bf.get('O', 0)} C={bf.get('C', 0)} "
                       f"E={bf.get('E', 0)} A={bf.get('A', 0)} "
                       f"N={bf.get('N', 0)}")
            holland_line = personality_result.holland_code
            se = personality_result.self_efficacy or {}
            efficacy_line = (f"语文={se.get('chinese', 0)} "
                             f"数学={se.get('math', 0)} "
                             f"英语={se.get('english', 0)}")
            cv = personality_result.career_values or {}
            top3 = sorted(cv.items(), key=lambda x: x[1], reverse=True)[:3]
            values_line = ' / '.join([f'{k}={v}' for k, v in top3]) if top3 else '无'
            major_line = ', '.join(personality_result.recommendations[:10])

        excluded = self._get_excluded_majors(questionnaire)

        summary = f"""
【匹配结果摘要】

【考生信息】
姓名: {questionnaire.name}
科类: {questionnaire.category}
总分: {questionnaire.total_score}
位次: {questionnaire.rank}

【四维偏好问卷（项目自编，非心理诊断）】
大五维度偏好: {bf_line}
RIASEC 风格代码: {holland_line}
学科自我评价: {efficacy_line}
职业价值偏好（TOP3）: {values_line}
专业推荐: {major_line}

【志愿偏好】
核心诉求: {questionnaire.core_demand}
目标行业: {', '.join(questionnaire.target_industries) or '未定'}
可接受专业: {', '.join(questionnaire.acceptable_majors) or '未定'}
排除专业: {', '.join(excluded) or '无'}
就读地域: {questionnaire.province_preference or '未定'}

【风险策略】
推荐策略: {risk_strategy}
学费预算: {questionnaire.total_budget or '未定'}

【推荐方案】
冲: {len(recommendations.get('冲', []))}所
稳: {len(recommendations.get('稳', []))}所
保: {len(recommendations.get('保', []))}所
垫: {len(recommendations.get('垫', []))}所
总计: {sum(len(v) for v in recommendations.values())}所

【冲稳保详情】
"""
        for category in ['冲', '稳', '保', '垫']:
            schools = recommendations.get(category, [])
            summary += f"\n【{category}】({len(schools)}所):\n"
            for i, school in enumerate(schools[:5], 1):
                summary += f"  {i}. {school.school_name} ({school.school_quality})\n"
                summary += f"     录取概率: {school.probability} | 置信度: {school.confidence}\n"
                summary += f"     地点: {school.location} | 学费: {school.tuition:.0f}元/年\n"
                if school.recommended_majors:
                    m = ', '.join([m.major_name for m in school.recommended_majors[:3]])
                    summary += f"     推荐专业: {m}\n"

        # H-05: 添加说明信息
        if notes:
            summary += "\n【注意事项】\n"
            for note in notes:
                summary += f"  - {note}\n"

        return summary

    def close(self):
        self.rank_converter.close()
        self.prob_calculator.close()
        self.volunteer_recommender.close()
        if hasattr(self._local, 'cursor'):
            try:
                self._local.cursor.connection.close()
            except Exception:
                pass


def main():
    """测试用例 V3.0"""
    engine = MatchingEngine()

    print('=' * 70)
    print('匹配引擎 V3.0 测试 - 物理类考生')
    print('=' * 70)

    from .questionnaire_parser import QuestionnaireParser

    parser = QuestionnaireParser.create_by_category('物理类')

    test_data = {
        'q1_name': '张三', 'q2_gender': '男',
        'q5_exam_id': '5301002026000001', 'q6_phone': '13800138000',
        'q9_color_vision': '无色盲色弱', 'q10_vision': '视力正常',
        'q12_total_score': 580, 'q13_rank': 15000,
        'q14_category': '物理类', 'q15_subject_combo': '物理+化学+生物',
        'q17_chinese_score': 120, 'q18_chinese_rank_pct': '前10%',
        'q22_math_score': 140, 'q23_math_rank_pct': '前10%',
        'q27_english_score': 130, 'q28_english_rank_pct': '前10-30%',
        'q32_advantage_1': '数学', 'q33_advantage_2': '物理',
        'q34_competitions': ['数学竞赛', '物理竞赛'],
        'q40_total_budget': '10-20万元',
        'q43_core_demand': '专业实力优先',
        'q45_target_industries': ['信息技术/互联网', '金融/银行'],
        'q49_acceptable_majors': ['工学类', '理学类', '经济学类'],
        'q51_physics_achievement': '物理很好',
        'q52_physics_willingness': '非常愿意',
        'q56_province_preference': '优先出省',
        'q60_stability_preference': 3,
        'q68_stress_tolerance': '中等压力',
        'q74_decision_control': '自己决定，参考家长意见',
    }

    questionnaire = parser.parse(test_data)

    # 模拟项目自编偏好问卷答案（v3.0）
    big_five_answers = {i: 4 for i in range(1, 51)}
    holland_answers = {i: 'A' if i % 2 == 0 else 'B' for i in range(1, 77)}
    efficacy_answers = {
        76: 4, 77: 4, 78: 3, 79: 4, 80: 4,
        81: 5, 82: 4, 83: 4, 84: 5, 85: 4,
        86: 3, 87: 3, 88: 4, 89: 3, 90: 4,
    }
    career_values_answers = {
        91: 3, 92: 3, 93: 3, 94: 3, 95: 4, 96: 4,
        97: 3, 98: 3, 99: 4, 100: 4, 101: 3, 102: 3,
        103: 3, 104: 3, 105: 3, 106: 3, 107: 4, 108: 4,
        109: 4, 110: 4,
    }

    result = engine.match(
        questionnaire, big_five_answers, holland_answers,
        efficacy_answers, career_values_answers, top_n=30,
    )

    print(result.summary)

    engine.close()
    print('\n' + '=' * 70)
    print('测试完成！')


if __name__ == '__main__':
    main()
