# SPDX-License-Identifier: LicenseRef-OpenGaokao-SAL-1.0
# Copyright (C) 2026 OpenGaokao Contributors
"""
问卷解析引擎 (Questionnaire Parser) V3.1
解析用户填写的调研问卷，提取关键信息用于志愿推荐。

核心功能：
1. 问卷数据验证
2. 用户画像构建
3. 偏好提取
4. 风险策略匹配
5. 新增：身体健康/考试表现/自我效能感/职业价值观解析
"""
import json
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field



@dataclass
class HealthScreening:
    """体检结论"""
    color_vision: str = ''      # 色觉情况
    vision: str = ''            # 视力情况
    hearing: str = ''           # 听力
    smell: str = ''             # 嗅觉
    height: str = ''            # 身高(cm)
    weight: str = ''            # 体重(kg)
    tattoo: str = ''            # 纹身


def _normalize_color_vision(value) -> str:
    """统一公开问卷与 Web 的色觉选项，避免“无色盲”被子串误判为色盲。"""
    text = str(value or '').strip()
    if text in ('正常', '无', '无色盲色弱') or text.startswith('无色盲'):
        return '正常'
    if '色盲' in text:
        return '色盲'
    if '色弱' in text:
        return '色弱'
    if '障碍' in text or '识别' in text:
        return '颜色识别障碍'
    return text


@dataclass
class UserQuestionnaire:
    """用户问卷数据 V3.1"""
    # 基本信息
    name: str
    gender: str
    exam_id: str
    phone: str
    birth: str = ''
    ethnicity: str = ''
    parent_name: str = ''
    parent_phone: str = ''
    # 基本信息新增
    student_type: str = ''              # 应届/复读
    political_status: str = ''          # 政治面貌

    # 身体健康（新增）
    health_screening: Optional[HealthScreening] = None

    # 高考情况
    total_score: int = 0
    rank: int = 0
    category: str = ''  # 物理类/历史类
    subject_combo: str = ''
    foreign_language: str = ''            # 外语科目

    # 学科能力
    chinese_score: Optional[int] = None
    chinese_rank_pct: str = ''
    math_score: Optional[int] = None
    math_rank_pct: str = ''
    english_score: Optional[int] = None
    english_rank_pct: str = ''
    # 历史类特有
    history_score: Optional[int] = None
    politics_score: Optional[int] = None
    geography_score: Optional[int] = None
    advantage_1: str = ''
    advantage_2: str = ''
    competitions: List[str] = field(default_factory=list)
    focus_area: List[str] = field(default_factory=list)

    # 家庭背景
    parent_education: str = ''
    parent_occupation: str = ''
    family_resources: List[str] = field(default_factory=list)
    family_location: str = ''
    annual_tuition: str = ''       # 已被total_budget替代，保留兼容
    total_budget: str = ''         # 年度总费用
    sino_foreign: str = ''         # 是否考虑中外合作
    private_college: str = ''      # 是否考虑民办院校
    political_review: str = ''     # 是否计划报考政审院校
    criminal_record: str = ''      # 直系亲属刑事处罚记录
    special_plan_eligibility: List[str] = field(default_factory=list)  # 专项计划资格

    # 志愿偏好
    special_schools: List[str] = field(default_factory=list)
    core_demand: str = ''
    civil_service: str = ''
    target_industries: List[str] = field(default_factory=list)
    medical_preference: str = ''
    agriculture_preference: str = ''  # 物理类特有
    teacher_preference: str = ''
    acceptable_majors: List[str] = field(default_factory=list)
    vertical_majors: List[str] = field(default_factory=list)  # 垂直类专业
    excluded_majors: List[str] = field(default_factory=list)  # 排除专业（体检限制/用户明确不考虑）
    # 物理类特有
    physics_achievement: str = ''
    physics_willingness: str = ''
    chemistry_achievement: str = ''
    chemistry_willingness: str = ''
    physics_direction: str = ''
    major_adjustment: str = ''     # 服从专业调剂（物理类）
    # 历史类特有
    history_achievement: str = ''
    history_willingness: str = ''
    foreign_language_achievement: str = ''
    foreign_language_willingness: str = ''
    major_adjustment_attitude: str = ''  # 服从专业调剂（历史类）
    # 通用（新增）
    province_preference: str = ''  # 大学就读地域偏好
    strong_base: List[str] = field(default_factory=list)  # 特殊招生路径
    collection_volunteer: str = ''  # 征集志愿
    intention_note: str = ''        # 其他意向说明

    # 职业倾向
    ideal_workday: List[str] = field(default_factory=list)
    unacceptable_work: str = ''
    ethics_dilemma: str = ''
    stability_preference: int = 3  # 1-5
    tech_iteration: str = ''
    location_preference: str = ''

    # 大学生活
    ideal_university: List[str] = field(default_factory=list)
    dormitory_expectation: str = ''
    minor_attitude: str = ''
    further_study: List[str] = field(default_factory=list)
    parent_support: List[str] = field(default_factory=list)

    # 压力评估
    stress_tolerance: str = ''
    exam_state: str = ''
    major_changes: List[str] = field(default_factory=list)
    stress_coping: List[str] = field(default_factory=list)
    change_impact: str = ''

    # 决策分析
    peer_influence: str = ''
    decision_control: str = ''
    conflict_scenario: str = ''

    # 学科自我效能感（新增）
    subject_self_efficacy: Optional[Dict[str, float]] = None

    # 职业价值观（新增）
    career_values: Optional[Dict[str, float]] = None

    # AUDIT-P0-010: 未成年人保护字段
    age: Optional[int] = None              # 由 q3_birth 计算（无法计算时为 None）
    is_minor: bool = False                 # 是否未满18周岁
    guardian_consent: bool = False         # 监护人是否已代为同意
    minor_consent_required: bool = False   # 需监护人同意但尚未提供（拦截信号）
    minor_protection_notes: List[str] = field(default_factory=list)  # 未成年保护提示

    # AUDIT-P0-011: 性格量表答案（供 personality_test 直接消费）
    big_five_answers: Optional[Dict[int, int]] = None      # {题号 1-50 → 1-5 分}
    holland_answers: Optional[Dict[int, str]] = None       # {题号 1-76 → 'A'/'B'}


class QuestionnaireParser:
    """问卷解析器 V3.1"""

    # v3.1 物理类题号 → dataclass字段映射（以 volunteer_survey_physics.json 为唯一真源）
    PHYSICS_FIELD_MAP = {
        'q1_name': 'name', 'q2_gender': 'gender', 'q3_birth': 'birth',
        'q4_ethnicity': 'ethnicity', 'q5_exam_id': 'exam_id',
        'q6_phone': 'phone', 'q7_parent_name': 'parent_name',
        'q8_parent_phone': 'parent_phone',
        'q8b_student_type': 'student_type',
        'q8c_political_status': 'political_status',
        # 健康
        'q9_color_vision': ('health', 'color_vision'),
        'q10_vision': ('health', 'vision'),
        'q11_hearing': ('health', 'hearing'),
        'q11b_smell': ('health', 'smell'),
        'q11c_height': ('health', 'height'),
        'q11d_weight': ('health', 'weight'),
        'q11e_tattoo': ('health', 'tattoo'),
        # 高考
        'q12_total_score': 'total_score', 'q13_rank': 'rank',
        'q14_category': 'category', 'q15_subject_combo': 'subject_combo',
        'q16_foreign_language': 'foreign_language',
        # 学科能力（物理类 q17~q35，真实 JSON 无 q19~q21/q24~q26/q29~q31 数值字段，直接跳）
        'q17_chinese_score': 'chinese_score',
        'q18_chinese_rank_pct': 'chinese_rank_pct',
        'q22_math_score': 'math_score',
        'q23_math_rank_pct': 'math_rank_pct',
        'q27_english_score': 'english_score',
        'q28_english_rank_pct': 'english_rank_pct',
        'q32_advantage_1': 'advantage_1',
        'q33_advantage_2': 'advantage_2',
        'q34_competitions': 'competitions',
        'q35_focus_area': 'focus_area',
        # 家庭背景（物理类 q36~q41b）
        'q36_parent_education': 'parent_education',
        'q37_parent_occupation': 'parent_occupation',
        'q38_family_resources': 'family_resources',
        'q39_family_location': 'family_location',
        'q40_total_budget': 'total_budget',
        'q40b_sino_foreign': 'sino_foreign',
        'q40c_private_college': 'private_college',
        'q41_political_review': 'political_review',
        'q41a_criminal_record': 'criminal_record',
        'q41b_special_plan_eligibility': 'special_plan_eligibility',
        # 志愿偏好（物理类 q42~q56e）
        'q42_special_schools': 'special_schools',
        'q43_core_demand': 'core_demand',
        'q44_civil_service': 'civil_service',
        'q45_target_industries': 'target_industries',
        'q46_medical_preference': 'medical_preference',
        'q47_agriculture_preference': 'agriculture_preference',
        'q48_teacher_preference': 'teacher_preference',
        'q49_acceptable_majors': 'acceptable_majors',
        'q50_vertical_majors': 'vertical_majors',
        'q51_physics_achievement': 'physics_achievement',
        'q52_physics_willingness': 'physics_willingness',
        'q53_chemistry_achievement': 'chemistry_achievement',
        'q54_chemistry_willingness': 'chemistry_willingness',
        'q55_physics_direction': 'physics_direction',
        'q56_province_preference': 'province_preference',
        'q56b_major_adjustment': 'major_adjustment',
        'q56c_strong_base': 'strong_base',
        'q56d_collection_volunteer': 'collection_volunteer',
        'q56e_intention_note': 'intention_note',
        # 职业倾向（物理类 q57~q62）
        'q57_ideal_workday': 'ideal_workday',
        'q58_unacceptable_work': 'unacceptable_work',
        'q59_ethics_dilemma': 'ethics_dilemma',
        'q60_stability_preference': 'stability_preference',
        'q61_tech_iteration': 'tech_iteration',
        'q62_location_preference': 'location_preference',
        # 大学生活（物理类 q63~q67）
        'q63_ideal_university': 'ideal_university',
        'q64_dormitory_expectation': 'dormitory_expectation',
        'q65_minor_attitude': 'minor_attitude',
        'q66_further_study': 'further_study',
        'q67_parent_support': 'parent_support',
        # 压力评估（物理类 q68~q72）
        'q68_stress_tolerance': 'stress_tolerance',
        'q69_exam_state': 'exam_state',
        'q70_major_changes': 'major_changes',
        'q71_stress_coping': 'stress_coping',
        'q72_change_impact': 'change_impact',
        # 决策分析（物理类 q73~q75）
        'q73_peer_influence': 'peer_influence',
        'q74_decision_control': 'decision_control',
        'q75_conflict_scenario': 'conflict_scenario',
        # 自我效能感（物理类 q76~q90）
        'q76_se_cn1': 'q76_se_cn1', 'q77_se_cn2': 'q77_se_cn2',
        'q78_se_cn3': 'q78_se_cn3', 'q79_se_cn4': 'q79_se_cn4',
        'q80_se_cn5': 'q80_se_cn5',
        'q81_se_mt1': 'q81_se_mt1', 'q82_se_mt2': 'q82_se_mt2',
        'q83_se_mt3': 'q83_se_mt3', 'q84_se_mt4': 'q84_se_mt4',
        'q85_se_mt5': 'q85_se_mt5',
        'q86_se_en1': 'q86_se_en1', 'q87_se_en2': 'q87_se_en2',
        'q88_se_en3': 'q88_se_en3', 'q89_se_en4': 'q89_se_en4',
        'q90_se_en5': 'q90_se_en5',
        # 职业价值观（物理类 q91~q110）
        'q91_cv_income1': 'q91_cv_income1', 'q92_cv_income2': 'q92_cv_income2',
        'q93_cv_stability1': 'q93_cv_stability1', 'q94_cv_stability2': 'q94_cv_stability2',
        'q95_cv_achievement1': 'q95_cv_achievement1', 'q96_cv_achievement2': 'q96_cv_achievement2',
        'q97_cv_help1': 'q97_cv_help1', 'q98_cv_help2': 'q98_cv_help2',
        'q99_cv_creative1': 'q99_cv_creative1', 'q100_cv_creative2': 'q100_cv_creative2',
        'q101_cv_balance1': 'q101_cv_balance1', 'q102_cv_balance2': 'q102_cv_balance2',
        'q103_cv_leadership1': 'q103_cv_leadership1', 'q104_cv_leadership2': 'q104_cv_leadership2',
        'q105_cv_autonomy1': 'q105_cv_autonomy1', 'q106_cv_autonomy2': 'q106_cv_autonomy2',
        'q107_cv_location1': 'q107_cv_location1', 'q108_cv_location2': 'q108_cv_location2',
        'q109_cv_learning1': 'q109_cv_learning1', 'q110_cv_learning2': 'q110_cv_learning2',
    }

    # v3.1 历史类题号差异映射（物理类键 → 历史类键，以 volunteer_survey_history.json 为唯一真源）
    HISTORY_ID_MAP = {
        # 基本信息/健康/高考 — 与物理类相同，无需映射
        # 学科能力 — 历史类新增 q32/q33/q34 史政地，advantage/focus_area 偏移 -3
        'q32_advantage_1': 'q35_advantage_1',
        'q33_advantage_2': 'q36_advantage_2',
        'q34_competitions': 'q37_competitions',
        'q35_focus_area': 'q38_focus_area',
        # 家庭背景 — 历史类偏移 +3（相对物理类 q36~q41b → 历史类 q39~q44b）
        'q36_parent_education': 'q39_parent_education',
        'q37_parent_occupation': 'q40_parent_occupation',
        'q38_family_resources': 'q41_family_resources',
        'q39_family_location': 'q42_family_location',
        'q40_total_budget': 'q43_total_budget',
        'q40b_sino_foreign': 'q43b_sino_foreign',
        'q40c_private_college': 'q43c_private_college',
        'q41_political_review': 'q44_political_review',
        'q41a_criminal_record': 'q44a_criminal_record',
        'q41b_special_plan_eligibility': 'q44b_special_plan_eligibility',
        # 志愿偏好 — 历史类偏移 +3（物理类 q42~q50 → 历史类 q45~q52）
        # 注：历史类特有 q50b_agriculture_preference（物理类 q47 对应位置不同）
        'q42_special_schools': 'q45_special_schools',
        'q43_core_demand': 'q46_core_demand',
        'q44_civil_service': 'q47_civil_service',
        'q45_target_industries': 'q48_target_industries',
        'q46_medical_preference': 'q49_medical_preference',
        'q47_agriculture_preference': 'q50b_agriculture_preference',
        'q48_teacher_preference': 'q50_teacher_preference',
        'q49_acceptable_majors': 'q51_acceptable_majors',
        'q50_vertical_majors': 'q52_vertical_majors',
        # 学科特有字段（物理类 → 历史类对应字段）
        'q51_physics_achievement': 'q53_history_achievement',
        'q52_physics_willingness': 'q54_history_willingness',
        'q53_chemistry_achievement': 'q55_foreign_language_achievement',
        'q54_chemistry_willingness': 'q56_foreign_language_willingness',
        'q55_physics_direction': None,  # 历史类无此字段
        'q56_province_preference': 'q57_province_preference',
        'q56b_major_adjustment': 'q56b_major_adjustment_attitude',
        'q56c_strong_base': 'q57b_strong_base',
        'q56d_collection_volunteer': 'q57c_collection_volunteer',
        'q56e_intention_note': 'q57d_intention_note',
        # 职业倾向（物理类 q57~q62 → 历史类 q58~q63）
        'q57_ideal_workday': 'q58_ideal_workday',
        'q58_unacceptable_work': 'q59_unacceptable_work',
        'q59_ethics_dilemma': 'q60_ethics_dilemma',
        'q60_stability_preference': 'q61_stability_preference',
        'q61_tech_iteration': 'q62_tech_iteration',
        'q62_location_preference': 'q63_location_preference',
        # 大学生活（物理类 q63~q67 → 历史类 q64~q68）
        'q63_ideal_university': 'q64_ideal_university',
        'q64_dormitory_expectation': 'q65_dormitory_expectation',
        'q65_minor_attitude': 'q66_minor_attitude',
        'q66_further_study': 'q67_further_study',
        'q67_parent_support': 'q68_parent_support',
        # 压力评估（物理类 q68~q72 → 历史类 q69~q73）
        'q68_stress_tolerance': 'q69_stress_tolerance',
        'q69_exam_state': 'q70_exam_state',
        'q70_major_changes': 'q71_major_changes',
        'q71_stress_coping': 'q72_stress_coping',
        'q72_change_impact': 'q73_change_impact',
        # 决策分析（物理类 q73~q75 → 历史类 q74~q76）
        'q73_peer_influence': 'q74_peer_influence',
        'q74_decision_control': 'q75_decision_control',
        'q75_conflict_scenario': 'q76_conflict_scenario',
        # 自我效能感（物理类 q76~q90 → 历史类 q77~q91）
        'q76_se_cn1': 'q77_se_cn1', 'q77_se_cn2': 'q78_se_cn2',
        'q78_se_cn3': 'q79_se_cn3', 'q79_se_cn4': 'q80_se_cn4',
        'q80_se_cn5': 'q81_se_cn5',
        'q81_se_mt1': 'q82_se_mt1', 'q82_se_mt2': 'q83_se_mt2',
        'q83_se_mt3': 'q84_se_mt3', 'q84_se_mt4': 'q85_se_mt4',
        'q85_se_mt5': 'q86_se_mt5',
        'q86_se_en1': 'q87_se_en1', 'q87_se_en2': 'q88_se_en2',
        'q88_se_en3': 'q89_se_en3', 'q89_se_en4': 'q90_se_en4',
        'q90_se_en5': 'q91_se_en5',
        # 职业价值观（物理类 q91~q110 → 历史类 q92~q111）
        'q91_cv_income1': 'q92_cv_income1', 'q92_cv_income2': 'q93_cv_income2',
        'q93_cv_stability1': 'q94_cv_stability1', 'q94_cv_stability2': 'q95_cv_stability2',
        'q95_cv_achievement1': 'q96_cv_achievement1', 'q96_cv_achievement2': 'q97_cv_achievement2',
        'q97_cv_help1': 'q98_cv_help1', 'q98_cv_help2': 'q99_cv_help2',
        'q99_cv_creative1': 'q100_cv_creative1', 'q100_cv_creative2': 'q101_cv_creative2',
        'q101_cv_balance1': 'q102_cv_balance1', 'q102_cv_balance2': 'q103_cv_balance2',
        'q103_cv_leadership1': 'q104_cv_leadership1', 'q104_cv_leadership2': 'q105_cv_leadership2',
        'q105_cv_autonomy1': 'q106_cv_autonomy1', 'q106_cv_autonomy2': 'q107_cv_autonomy2',
        'q107_cv_location1': 'q108_cv_location1', 'q108_cv_location2': 'q109_cv_location2',
        'q109_cv_learning1': 'q110_cv_learning1', 'q110_cv_learning2': 'q111_cv_learning2',
    }

    def __init__(self, survey_json_path: str = None):
        if survey_json_path:
            with open(survey_json_path, 'r', encoding='utf-8') as f:
                self.survey_template = json.load(f)
        else:
            self.survey_template = None
        self.question_map = self._build_question_map()

    def _build_question_map(self) -> Dict[str, Dict]:
        if not self.survey_template:
            return {}
        q_map = {}
        for section in self.survey_template['sections']:
            for q in section['questions']:
                q_map[q['id']] = q
        return q_map

    @classmethod
    def create_by_category(cls, category: str):
        # Resolve path relative to project root
        import os
        _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if category == '物理类':
            path = os.path.join(_root, 'questionnaires', 'volunteer_survey_physics.json')
        elif category == '历史类':
            path = os.path.join(_root, 'questionnaires', 'volunteer_survey_history.json')
        else:
            raise ValueError(f"不支持的科类: {category}")
        return cls(survey_json_path=path)

    def parse(self, raw_data: Dict) -> UserQuestionnaire:
        """解析原始问卷数据（v3.1）"""
        self._validate(raw_data)
        is_history = '历史' in raw_data.get('q14_category', raw_data.get('q11_category', ''))
        id_map = self.HISTORY_ID_MAP if is_history else {}

        def get_phys(phys_id, default=None):
            """根据题号映射获取值"""
            if is_history and phys_id in id_map:
                hist_id = id_map[phys_id]
                if hist_id is None:
                    return default
                if hist_id in raw_data:
                    return raw_data[hist_id]
            if phys_id in raw_data:
                return raw_data[phys_id]
            return default

        # 体检结论
        health = HealthScreening(
            color_vision=_normalize_color_vision(get_phys('q9_color_vision', '')),
            vision=get_phys('q10_vision', ''),
            hearing=get_phys('q11_hearing', ''),
            smell=get_phys('q11b_smell', ''),
            height=get_phys('q11c_height', ''),
            weight=get_phys('q11d_weight', ''),
            tattoo=get_phys('q11e_tattoo', ''),
        )

        questionnaire = UserQuestionnaire(
            name=raw_data.get('q1_name', ''),
            gender=raw_data.get('q2_gender', ''),
            birth=raw_data.get('q3_birth', ''),
            ethnicity=raw_data.get('q4_ethnicity', ''),
            exam_id=raw_data.get('q5_exam_id', ''),
            phone=raw_data.get('q6_phone', ''),
            parent_name=raw_data.get('q7_parent_name', ''),
            parent_phone=raw_data.get('q8_parent_phone', ''),
            # 基本信息新增
            student_type=get_phys('q8b_student_type', ''),
            political_status=get_phys('q8c_political_status', ''),
            health_screening=health,
            total_score=self._safe_int(get_phys('q12_total_score')) or 0,
            rank=self._safe_int(get_phys('q13_rank')) or 0,
            category=get_phys('q14_category', ''),
            subject_combo=get_phys('q15_subject_combo', ''),
            foreign_language=get_phys('q16_foreign_language', ''),
            chinese_score=self._safe_int(get_phys('q17_chinese_score')),
            chinese_rank_pct=get_phys('q18_chinese_rank_pct', ''),
            math_score=self._safe_int(get_phys('q22_math_score')),
            math_rank_pct=get_phys('q23_math_rank_pct', ''),
            english_score=self._safe_int(get_phys('q27_english_score')),
            english_rank_pct=get_phys('q28_english_rank_pct', ''),
            # 历史类史地政分数（物理类为None）
            history_score=self._safe_int(raw_data.get('q32_history_score')) if is_history else None,
            politics_score=self._safe_int(raw_data.get('q33_politics_score')) if is_history else None,
            geography_score=self._safe_int(raw_data.get('q34_geography_score')) if is_history else None,
            advantage_1=get_phys('q32_advantage_1', ''),
            advantage_2=get_phys('q33_advantage_2', ''),
            competitions=self._to_list(get_phys('q34_competitions', [])),
            focus_area=self._to_list(get_phys('q35_focus_area', [])),
            parent_education=get_phys('q36_parent_education', ''),
            parent_occupation=get_phys('q37_parent_occupation', ''),
            family_resources=self._to_list(get_phys('q38_family_resources', [])),
            family_location=get_phys('q39_family_location', ''),
            total_budget=get_phys('q40_total_budget', ''),
            sino_foreign=get_phys('q40b_sino_foreign', ''),
            private_college=get_phys('q40c_private_college', ''),
            political_review=get_phys('q41_political_review', ''),
            criminal_record=get_phys('q41a_criminal_record', ''),
            special_plan_eligibility=self._to_list(get_phys('q41b_special_plan_eligibility', [])),
            special_schools=self._to_list(get_phys('q42_special_schools', [])),
            core_demand=get_phys('q43_core_demand', ''),
            civil_service=get_phys('q44_civil_service', ''),
            target_industries=self._to_list(get_phys('q45_target_industries', [])),
            medical_preference=get_phys('q46_medical_preference', ''),
            agriculture_preference=get_phys('q47_agriculture_preference', ''),
            teacher_preference=get_phys('q48_teacher_preference', ''),
            acceptable_majors=self._to_list(get_phys('q49_acceptable_majors', [])),
            vertical_majors=self._to_list(get_phys('q50_vertical_majors', [])),
            # 物理类特有（H-9 fix: 历史类考生不应设置物理专属字段）
            physics_achievement=get_phys('q51_physics_achievement', '') if not is_history else '',
            physics_willingness=get_phys('q52_physics_willingness', '') if not is_history else '',
            chemistry_achievement=get_phys('q53_chemistry_achievement', '') if not is_history else '',
            chemistry_willingness=get_phys('q54_chemistry_willingness', '') if not is_history else '',
            physics_direction=get_phys('q55_physics_direction', '') if not is_history else '',
            major_adjustment=get_phys('q56b_major_adjustment', '') if not is_history else '',
            # 历史类特有（通过 get_phys 走 HISTORY_ID_MAP）
            history_achievement=get_phys('q51_physics_achievement', '') if is_history else '',
            history_willingness=get_phys('q52_physics_willingness', '') if is_history else '',
            foreign_language_achievement=get_phys('q53_chemistry_achievement', '') if is_history else '',
            foreign_language_willingness=get_phys('q54_chemistry_willingness', '') if is_history else '',
            major_adjustment_attitude=get_phys('q56b_major_adjustment', '') if is_history else '',
            # 通用
            province_preference=get_phys('q56_province_preference', ''),
            strong_base=self._to_list(get_phys('q56c_strong_base', [])),
            collection_volunteer=get_phys('q56d_collection_volunteer', ''),
            intention_note=get_phys('q56e_intention_note', ''),
            ideal_workday=self._to_list(get_phys('q57_ideal_workday', [])),
            unacceptable_work=get_phys('q58_unacceptable_work', ''),
            ethics_dilemma=get_phys('q59_ethics_dilemma', ''),
            stability_preference=self._parse_stability_preference(get_phys('q60_stability_preference', 3)),
            tech_iteration=get_phys('q61_tech_iteration', ''),
            location_preference=get_phys('q62_location_preference', ''),
            ideal_university=self._to_list(get_phys('q63_ideal_university', [])),
            dormitory_expectation=get_phys('q64_dormitory_expectation', ''),
            minor_attitude=get_phys('q65_minor_attitude', ''),
            further_study=self._to_list(get_phys('q66_further_study', [])),
            parent_support=self._to_list(get_phys('q67_parent_support', [])),
            stress_tolerance=get_phys('q68_stress_tolerance', ''),
            exam_state=get_phys('q69_exam_state', ''),
            major_changes=self._to_list(get_phys('q70_major_changes', [])),
            stress_coping=self._to_list(get_phys('q71_stress_coping', [])),
            change_impact=get_phys('q72_change_impact', ''),
            peer_influence=get_phys('q73_peer_influence', ''),
            decision_control=get_phys('q74_decision_control', ''),
            conflict_scenario=get_phys('q75_conflict_scenario', ''),
        )

        # P1: 把 se/cv 解析结果写回 questionnaire 对象（多维采集完整进入画像）
        questionnaire.subject_self_efficacy = self.parse_self_efficacy(raw_data)
        questionnaire.career_values = self.parse_career_values(raw_data)

        # AUDIT-P0-010: 未成年人保护（年龄判定 + 监护人同意 + 敏感信息提示）
        # reference_year 取实际高考年；可由 raw_data 显式覆盖，否则用 CURRENT_PLAN_YEAR+1
        try:
            from .volunteer_recommender import CURRENT_PLAN_YEAR
            default_gaokao_year = CURRENT_PLAN_YEAR + 1
        except Exception:
            default_gaokao_year = 2026
        reference_year = self._safe_int(raw_data.get('gaokao_year')) or default_gaokao_year
        self._apply_minor_protection(questionnaire, raw_data, reference_year)

        # AUDIT-P0-011: 解析大五人格 + 霍兰德答案
        questionnaire.big_five_answers = self.parse_big_five(raw_data)
        questionnaire.holland_answers = self.parse_holland(raw_data)

        return questionnaire

    # 物理类/历史类 se/cv 字符串题号前缀（与 JSON 真实键对应）
    _SE_KEYS = {
        'physics': {
            'chinese': [f'q{76+i}_se_cn{i+1}' for i in range(5)],
            'math':    [f'q{81+i}_se_mt{i+1}' for i in range(5)],
            'english': [f'q{86+i}_se_en{i+1}' for i in range(5)],
        },
        'history': {
            'chinese': [f'q{77+i}_se_cn{i+1}' for i in range(5)],
            'math':    [f'q{82+i}_se_mt{i+1}' for i in range(5)],
            'english': [f'q{87+i}_se_en{i+1}' for i in range(5)],
        },
    }
    _CV_DIMS = ['income', 'stability', 'achievement', 'help', 'creative',
                'balance', 'leadership', 'autonomy', 'location', 'learning']
    _CV_SUFFIXES = {
        'income': ('income1', 'income2'), 'stability': ('stability1', 'stability2'),
        'achievement': ('achievement1', 'achievement2'), 'help': ('help1', 'help2'),
        'creative': ('creative1', 'creative2'), 'balance': ('balance1', 'balance2'),
        'leadership': ('leadership1', 'leadership2'), 'autonomy': ('autonomy1', 'autonomy2'),
        'location': ('location1', 'location2'), 'learning': ('learning1', 'learning2'),
    }
    _CV_BASES = {'physics': 91, 'history': 92}

    def parse_self_efficacy(self, raw_data: Dict) -> Dict[str, float]:
        """解析学科自我效能感（从字符串键读取，以 JSON 题号为准）"""
        is_history = '历史' in raw_data.get('q14_category', raw_data.get('q11_category', ''))
        cat_key = 'history' if is_history else 'physics'
        se_keys = self._SE_KEYS[cat_key]
        web_keys = self._SE_KEYS['physics']

        efficacy = {}
        for subject, keys in se_keys.items():
            vals = []
            for index, key in enumerate(keys):
                candidates = (key, web_keys[subject][index]) if is_history else (key,)
                for candidate in candidates:
                    if candidate not in raw_data:
                        continue
                    score = self._parse_likert_score(raw_data[candidate])
                    if score is not None:
                        vals.append(score)
                        break
            efficacy[subject] = round(sum(vals) / len(vals), 1) if vals else 0.0
        return efficacy

    def parse_career_values(self, raw_data: Dict) -> Dict[str, float]:
        """解析职业价值观（从字符串键读取，以 JSON 题号为准）"""
        is_history = '历史' in raw_data.get('q14_category', raw_data.get('q11_category', ''))
        base = self._CV_BASES['history' if is_history else 'physics']
        web_base = self._CV_BASES['physics']

        values = {}
        for idx, dim in enumerate(self._CV_DIMS):
            s1, s2 = self._CV_SUFFIXES[dim]
            k1 = f'q{base + idx*2}_cv_{s1}'
            k2 = f'q{base + idx*2 + 1}_cv_{s2}'
            vals = []
            for key, web_key in (
                (k1, f'q{web_base + idx*2}_cv_{s1}'),
                (k2, f'q{web_base + idx*2 + 1}_cv_{s2}'),
            ):
                candidates = (key, web_key) if is_history else (key,)
                for candidate in candidates:
                    if candidate not in raw_data:
                        continue
                    score = self._parse_likert_score(raw_data[candidate])
                    if score is not None:
                        vals.append(score)
                        break
            values[dim] = round(sum(vals) / len(vals), 1) if vals else 0.0
        return values

    # AUDIT-P0-011: 大五人格 + 霍兰德答案解析
    def parse_big_five(self, raw_data: Dict) -> Optional[Dict[int, int]]:
        """从问卷答案中提取大五人格答案 {题号 1-50 → 1-5}。

        题号由 personality_items.big_five_question_id 决定（bf01..bf50）。
        无任何 bf 题作答时返回 None，让上层判断"未做"。
        """
        from .personality_items import (
            BIG_FIVE_ITEMS, big_five_question_id,
        )
        answers: Dict[int, int] = {}
        for no in BIG_FIVE_ITEMS.keys():
            key = big_five_question_id(no)
            if key not in raw_data:
                continue
            score = self._parse_likert_score(raw_data[key])
            if score is not None:
                answers[no] = score
        return answers if answers else None

    def parse_holland(self, raw_data: Dict) -> Optional[Dict[int, str]]:
        """从问卷答案中提取霍兰德答案 {题号 1-76 → 'A'/'B'}。

        题号由 personality_items.holland_question_id 决定（h01..h76）。
        作答值兼容多种格式：
            - 'A' / 'B'
            - 'A. 动手维修...' （JSON 选项原文）
            - 选项索引 0 / 1
        """
        from .personality_items import (
            HOLLAND_ITEMS, holland_question_id,
        )
        answers: Dict[int, str] = {}
        for no in HOLLAND_ITEMS.keys():
            key = holland_question_id(no)
            if key not in raw_data:
                continue
            val = raw_data[key]
            choice = self._normalize_holland_choice(val)
            if choice in ('A', 'B'):
                answers[no] = choice
        return answers if answers else None

    @staticmethod
    def _normalize_holland_choice(value) -> Optional[str]:
        """归一化霍兰德选项：兼容 'A'/'B'、'A. xxx'、整数索引等。"""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return 'A' if int(value) == 0 else 'B'
        if isinstance(value, str):
            s = value.strip().upper()
            if s.startswith('A'):
                return 'A'
            if s.startswith('B'):
                return 'B'
        return None

    def _validate(self, raw_data: Dict):
        required_fields = ['q1_name', 'q12_total_score', 'q13_rank', 'q14_category']
        missing = [f for f in required_fields if f not in raw_data or not raw_data[f]]
        if missing:
            raise ValueError(f"缺少必填项: {', '.join(missing)}")
        # OG-F-40: 总分/位次必须为正整数。否则 `_safe_int(...) or 0` 会把非数字（如"不知道"）
        # 静默归零，下游 rank=0 被当全省第一并产出空推荐却无任何解释。在此显式拦截给明确错误。
        for f, label in (('q12_total_score', '高考总分'), ('q13_rank', '位次')):
            v = self._safe_int(raw_data.get(f))
            if v is None or v <= 0:
                raise ValueError(f"{label}（{f}）必须是有效的正整数，无法解析当前值: {raw_data.get(f)!r}")

    # ── AUDIT-P0-010: 未成年人保护 ──
    # 高考报考关键日：用高考首日（6月7日）作为年龄基准，而非系统当前时间，
    # 既保证可测试（结果不随运行日期漂移），又符合"报考时是否成年"的法律语义。
    GAOKAO_EXAM_MONTH = 6
    GAOKAO_EXAM_DAY = 7

    # 高度敏感字段：未成年人采集需监护人知情，记录提示
    _MINOR_SENSITIVE_FIELDS = {
        'q41a_criminal_record': '直系亲属刑事处罚记录',
        'q4_ethnicity': '民族',
        'q8c_political_status': '政治面貌',
    }

    def _compute_age(self, birth: str, reference_year: int) -> Optional[int]:
        """根据出生日期计算高考当年的周岁年龄。

        参数:
            birth: 出生日期字符串，支持 'YYYY-MM-DD' / 'YYYY/MM/DD' / 'YYYYMMDD'
            reference_year: 高考年份（基准日为该年6月7日）
        返回:
            周岁年龄；无法解析时返回 None
        """
        if not birth or not isinstance(birth, str):
            return None
        s = birth.strip().replace('/', '-')
        # 兼容纯数字 YYYYMMDD
        if s.isdigit() and len(s) == 8:
            s = f'{s[:4]}-{s[4:6]}-{s[6:8]}'
        parts = s.split('-')
        try:
            by = int(parts[0])
            bm = int(parts[1]) if len(parts) > 1 else 1
            bd = int(parts[2]) if len(parts) > 2 else 1
        except (ValueError, IndexError):
            return None
        # 合理性校验：出生年应在 reference_year-25 ~ reference_year-14 之间
        if by < reference_year - 30 or by > reference_year - 10:
            return None
        if not (1 <= bm <= 12) or not (1 <= bd <= 31):
            return None
        # 周岁 = 基准年 - 出生年，若基准日(6/7)未到生日则减1
        age = reference_year - by
        if (self.GAOKAO_EXAM_MONTH, self.GAOKAO_EXAM_DAY) < (bm, bd):
            age -= 1
        return age

    def _apply_minor_protection(self, questionnaire: 'UserQuestionnaire',
                                raw_data: Dict, reference_year: int):
        """对解析后的问卷应用未成年人保护逻辑（隐私政策第7节）。

        - 计算年龄，<18 标记为未成年
        - 未成年且无监护人同意 → minor_consent_required=True（上层据此拦截）
        - 未成年时对高敏字段记录提示
        """
        age = self._compute_age(questionnaire.birth, reference_year)
        questionnaire.age = age

        if age is not None and age < 18:
            questionnaire.is_minor = True
            # 监护人同意：接受多种字段名（前端/飞书可能命名不同）
            consent_raw = (
                raw_data.get('guardian_consent')
                or raw_data.get('q_guardian_consent')
                or raw_data.get('parent_consent')
                or raw_data.get('监护人同意')
            )
            questionnaire.guardian_consent = self._parse_consent(consent_raw)

            if not questionnaire.guardian_consent:
                questionnaire.minor_consent_required = True
                questionnaire.minor_protection_notes.append(
                    f'⚠️ 检测到考生为未成年人（{age}岁），根据隐私政策需监护人代为同意方可继续。'
                    f'请补充监护人同意确认（guardian_consent=true）及监护人姓名/联系方式。'
                )

            # 高敏字段最小化提示
            collected_sensitive = [
                label for key, label in self._MINOR_SENSITIVE_FIELDS.items()
                if raw_data.get(key)
            ]
            if collected_sensitive:
                questionnaire.minor_protection_notes.append(
                    f'ℹ️ 未成年人敏感信息提示：本次采集了{", ".join(collected_sensitive)}，'
                    f'依据最小化原则，请确认监护人知情且这些信息为志愿推荐所必需。'
                )
        elif age is None:
            # 无法判定年龄：不阻断，但提示后续人工核对
            questionnaire.minor_protection_notes.append(
                'ℹ️ 未能从出生日期判定年龄，若考生为未成年人请确保已获监护人同意。'
            )

    @staticmethod
    def _parse_consent(value) -> bool:
        """解析监护人同意标记（兼容 bool / 字符串 / 中文）"""
        if value is True:
            return True
        if isinstance(value, str):
            return value.strip().lower() in ('true', '1', 'yes', '是', '同意', '已同意')
        if isinstance(value, (int, float)):
            return value == 1
        return False

    def _safe_int(self, value) -> Optional[int]:
        if value is None or value == '':
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _parse_stability_preference(self, value) -> int:
        """解析铁饭碗偏好：真实问卷提交中文选项，测试/旧数据可能提交数字。"""
        if value is None or value == '':
            return 3
        if isinstance(value, str):
            value = value.strip()
        option_map = {
            '完全不想': 1,
            '不太想': 2,
            '无所谓': 3,
            '比较渴望': 4,
            '非常渴望': 5,
        }
        if value in option_map:
            return option_map[value]
        parsed = self._safe_int(value)
        return parsed if parsed is not None else 3

    def _parse_likert_score(self, value) -> Optional[int]:
        """解析 1-5 Likert 量表：兼容真实问卷中文选项和旧数字输入。"""
        if value is None or value == '':
            return None
        if isinstance(value, str):
            value = value.strip()
        option_map = {
            '非常不符合': 1,
            '不太符合': 2,
            '不确定': 3,
            '比较符合': 4,
            '非常符合': 5,
        }
        if value in option_map:
            return option_map[value]
        return self._safe_int(value)

    def _to_list(self, value) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [v.strip() for v in value.split(',') if v.strip()]
        if isinstance(value, list):
            return value
        return []

    def get_risk_strategy(self, questionnaire: UserQuestionnaire) -> str:
        """推断风险策略"""
        score = 0
        score += questionnaire.stability_preference

        stress_map = {
            '能适应很高强度的压力': 1, '能适应较高压力': 2,
            '能适应中等压力': 3, '只能适应较低压力': 4,
            '偏好低压稳定环境': 5
        }
        if questionnaire.stress_tolerance in stress_map:
            score += stress_map[questionnaire.stress_tolerance]

        if '学校名气优先' in questionnaire.core_demand:
            score += 2
        if '就业率优先' in questionnaire.core_demand:
            score += 1

        if '完全家长决定' in questionnaire.decision_control:
            score += 1

        if score <= 5:
            return 'aggressive'
        elif score <= 10:
            return 'balanced'
        else:
            return 'conservative'

    def get_budget_range(self, questionnaire: UserQuestionnaire) -> Tuple[float, float]:
        """提取学费预算范围"""
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
        aliases = {
            '2-4万': '2-4万元',
            '4-6万': '4-6万元',
            '6-10万': '6-10万元',
            '10-15万': '10-15万元',
            '15万以上': '15万元以上',
        }
        return aliases.get(budget or '', budget or '')

    def generate_summary(self, questionnaire: UserQuestionnaire) -> str:
        """生成问卷摘要"""
        health_str = '正常'
        if questionnaire.health_screening:
            hs = questionnaire.health_screening
            parts = []
            if hs.color_vision: parts.append(f'色觉:{hs.color_vision}')
            if hs.vision: parts.append(f'视力:{hs.vision}')
            if hs.hearing: parts.append(f'听力:{hs.hearing}')
            if hs.smell: parts.append(f'嗅觉:{hs.smell}')
            if hs.height: parts.append(f'身高:{hs.height}cm')
            if hs.weight: parts.append(f'体重:{hs.weight}kg')
            if hs.tattoo: parts.append(f'纹身:{hs.tattoo}')
            health_str = '; '.join(parts) if parts else '正常'

        summary = f"""
【考生信息】
姓名: {questionnaire.name}
科类: {questionnaire.category}
总分: {questionnaire.total_score}
位次: {questionnaire.rank}
外语科目: {questionnaire.foreign_language or '未填'}
身体健康: {health_str}

【学科优势】
第一优势: {questionnaire.advantage_1}
第二优势: {questionnaire.advantage_2}
竞赛经历: {', '.join(questionnaire.competitions) or '无'}

【家庭背景】
年度预算: {questionnaire.total_budget or '未定'}
中外合作: {questionnaire.sino_foreign or '未填'}
民办院校: {questionnaire.private_college or '未填'}
专项计划: {', '.join(questionnaire.special_plan_eligibility) or '无'}

【志愿偏好】
核心诉求: {questionnaire.core_demand}
目标行业: {', '.join(questionnaire.target_industries) or '未定'}
可接受专业: {', '.join(questionnaire.acceptable_majors) or '未定'}
就读地域: {questionnaire.province_preference or '未定'}
服从调剂: {questionnaire.major_adjustment or questionnaire.major_adjustment_attitude or '未填'}
特殊招生: {', '.join(questionnaire.strong_base) or '无'}
征集志愿: {questionnaire.collection_volunteer or '未填'}

【职业倾向】
稳定性偏好: {questionnaire.stability_preference}/5
地域倾向: {questionnaire.location_preference or '未定'}
深造意向: {', '.join(questionnaire.further_study) or '未定'}

【风险策略】
推荐策略: {self.get_risk_strategy(questionnaire)}
学费预算: {questionnaire.total_budget or '未定'}
"""
        return summary


def main():
    """测试用例"""
    print('=' * 70)
    print('问卷解析引擎 V3.1 测试 - 物理类 vs 历史类')
    print('=' * 70)

    # ── 测试1：物理类 ──
    print('\n【测试1】物理类问卷解析')
    parser_physics = QuestionnaireParser.create_by_category('物理类')

    test_data_physics = {
        'q1_name': '张三', 'q2_gender': '男',
        'q5_exam_id': '5301002026000001', 'q6_phone': '13800138000',
        'q9_color_vision': '无色盲色弱', 'q10_vision': '视力正常',
        'q11_hearing': '听力正常', 'q11b_smell': '嗅觉正常',
        'q11c_height': '175', 'q11d_weight': '65', 'q11e_tattoo': '无',
        'q12_total_score': 580, 'q13_rank': 15000,
        'q14_category': '物理类', 'q15_subject_combo': '物理+化学+生物',
        'q16_foreign_language': '英语',
        'q17_chinese_score': 120, 'q18_chinese_rank_pct': '前10%',
        'q22_math_score': 140, 'q23_math_rank_pct': '前10%',
        'q27_english_score': 130, 'q28_english_rank_pct': '前10-30%',
        'q37_advantage_1': '数学', 'q38_advantage_2': '物理',
        'q39_competitions': ['数学竞赛', '物理竞赛'],
        'q45_total_budget': '6-10万',
        'q48_core_demand': '专业实力优先',
        'q50_target_industries': ['信息技术/互联网', '金融/银行'],
        'q54_acceptable_majors': ['工学类', '理学类', '经济学类'],
        'q56_physics_achievement': '物理很好', 'q57_physics_willingness': '非常愿意',
        'q61_province_preference': '优先出省',
        'q65_stability_preference': 3,
        'q73_stress_tolerance': '能适应中等压力',
        'q79_decision_control': '自己决定，参考家长意见',
    }

    q_physics = parser_physics.parse(test_data_physics)
    print(parser_physics.generate_summary(q_physics))
    print(f'推荐风险策略: {parser_physics.get_risk_strategy(q_physics)}')

    # ── 测试2：历史类 ──
    print('\n【测试2】历史类问卷解析')
    parser_history = QuestionnaireParser.create_by_category('历史类')

    test_data_history = {
        'q1_name': '李四', 'q2_gender': '女',
        'q5_exam_id': '5301002026000002', 'q6_phone': '13800138001',
        'q9_color_vision': '无色盲色弱', 'q10_vision': '近视但矫正后达标',
        'q11_hearing': '听力正常', 'q11b_smell': '嗅觉正常',
        'q12_total_score': 560, 'q13_rank': 18000,
        'q14_category': '历史类', 'q15_subject_combo': '历史+政治+地理',
        'q16_foreign_language': '英语',
        'q17_chinese_score': 130, 'q18_chinese_rank_pct': '前10%',
        'q22_math_score': 110, 'q23_math_rank_pct': '前30-50%',
        'q27_english_score': 125, 'q28_english_rank_pct': '前10-30%',
        'q32_history_score': 85, 'q33_politics_score': 80, 'q34_geography_score': 78,
        'q40_advantage_1': '语文', 'q41_advantage_2': '英语',
        'q42_competitions': ['作文竞赛', '英语竞赛'],
        'q48_total_budget': '4-6万',
        'q51_core_demand': '学校名气优先（985/211/双一流）',
        'q53_target_industries': ['教育/培训', '法律/政务'],
        'q59_acceptable_majors': ['文学类', '历史学类', '法学类'],
        'q61_history_achievement': '历史很好', 'q62_history_willingness': '非常愿意',
        'q65_province_preference': '优先省内，省外也可以',
        'q82_stability_preference': 4,
        'q90_stress_tolerance': '只能适应较低压力',
        'q96_decision_control': '家长和自己共同决定',
    }

    q_history = parser_history.parse(test_data_history)
    print(parser_history.generate_summary(q_history))
    print(f'推荐风险策略: {parser_history.get_risk_strategy(q_history)}')

    # ── 对比分析 ──
    print('\n【对比分析】')
    print(f'物理类: {q_physics.name} | 位次: {q_physics.rank} | 策略: {parser_physics.get_risk_strategy(q_physics)}')
    print(f'历史类: {q_history.name} | 位次: {q_history.rank} | 策略: {parser_history.get_risk_strategy(q_history)}')

    print('\n' + '=' * 70)
    print('测试完成！')


if __name__ == '__main__':
    main()
