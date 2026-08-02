# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 OpenGaokao Contributors
"""
志愿推荐引擎 (Volunteer Recommender)
根据考生位次和云南新高考批次规则，智能推荐完整志愿填报方案。

核心功能：
1. 候选池筛选
2. 冲稳保分类
3. 按批次分组输出（提前批B段、本科批B段、专科批等）
4. 偏好过滤
5. 生成完整方案
"""
import sqlite3
import threading
import logging
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field, replace
from .admission_probability import AdmissionProbability, ProbabilityResult
from .rank_converter import RankConverter

# 当前招生计划年份（从 province.yaml 读取，可被 configure() 覆盖）
CURRENT_PLAN_YEAR = 2025

# 当前投档线年份
CURRENT_SCORE_LINE_YEAR = 2025

# 省份配置缓存（由 configure_with_config() 设置）
_CONFIG = None


def configure(plan_year: int = None, score_line_year: int = None):
    """从省份配置设置年份参数，覆盖模块级默认值。"""
    global CURRENT_PLAN_YEAR, CURRENT_SCORE_LINE_YEAR
    if plan_year is not None:
        CURRENT_PLAN_YEAR = plan_year
    if score_line_year is not None:
        CURRENT_SCORE_LINE_YEAR = score_line_year
    import logging as _lg
    _lg.getLogger(__name__).info(
        f'志愿推荐器年份已配置: plan_year={CURRENT_PLAN_YEAR}, score_line_year={CURRENT_SCORE_LINE_YEAR}'
    )


def configure_with_config(cfg):
    """从 ProvinceConfig 一次性注入全部配置（年份、批次、分数线）。"""
    global CURRENT_PLAN_YEAR, CURRENT_SCORE_LINE_YEAR, _CONFIG
    CURRENT_PLAN_YEAR = cfg.plan_year
    CURRENT_SCORE_LINE_YEAR = cfg.score_line_year
    _CONFIG = cfg


def get_config():
    """获取已注入的省份配置。"""
    return _CONFIG


# ============================================================
# 批次配置（基于 yunnan_batch_rules.md）
# ============================================================

@dataclass
class BatchConfig:
    """批次配置"""
    name: str                          # 批次名称（展示用）
    batch_key: str                     # 批次键（用于输出字典）
    volunteer_count: int               # 总志愿数
    method: str                        # 投档方式: 平行/单志愿
    section: str = ''                  # 段次（A/B/C/D）
    batch_type: str = ''               # 批次类型（提前本科批/本科批/高职专科批）
    chong_ratio: float = 0.375         # 冲档比例（默认15/40）
    wen_ratio: float = 0.375           # 稳档比例（默认15/40）
    bao_ratio: float = 0.250           # 保档比例（默认10/40）
    chong_prob_range: Tuple[int, int] = (20, 45)
    wen_prob_range: Tuple[int, int] = (45, 75)
    bao_prob_range: Tuple[int, int] = (75, 100)
    eligible_condition: str = ''       # 资格条件描述（如"需专项资格"）
    requires_special: bool = False     # 是否需要特殊资格

# 旧批次硬编码回退（仅当 _CONFIG 未设置时使用 — 云南默认值）
_BATCH_FALLBACK_NEW = {}
_BATCH_FALLBACK_OLD = {}

# 冲稳保策略配置（保档门槛≥85%）
STRATEGY_CONFIGS = {
    'aggressive': {
        'chong_ratio': 0.30,
        'wen_ratio': 0.30,
        'bao_ratio': 0.40,
        'chong_prob_range': (15, 35),
        'wen_prob_range': (35, 85),
        'bao_prob_range': (85, 100),
    },
    'balanced': {
        'chong_ratio': 0.15,
        'wen_ratio': 0.55,
        'bao_ratio': 0.30,
        'chong_prob_range': (15, 35),
        'wen_prob_range': (35, 85),
        'bao_prob_range': (85, 100),
    },
    'conservative': {
        'chong_ratio': 0.10,
        'wen_ratio': 0.60,
        'bao_ratio': 0.30,
        'chong_prob_range': (15, 35),
        'wen_prob_range': (35, 85),
        'bao_prob_range': (85, 100),
    },
}


# ============================================================
# 就业质量关键词（综合质量评分用）
# ============================================================

EMPLOYMENT_POSITIVE = [
    '就业率', '供不应求', '人才缺口', '高薪', '体制内', '公务员',
    '国企', '央企', '读研率', '保研', '需求大', '前景广阔',
    '热门', '紧缺', '优势', '稳定', '好就业',
    # 2026战略新兴产业关键词
    '低空', '无人', '具身', '脑机', '碳中和', '碳中', '半导体',
    '数据智能', '智能影像', '智慧农业', '粮食安全', '国家战略',
    '新兴', '紧缺人才', '交叉融合',
]
EMPLOYMENT_NEGATIVE = [
    '饱和', '就业困难', '供过于求', '竞争激烈', '缩招',
    '裁员', '夕阳', '淘汰', '转行', '难度较大', '慎报',
]


# ============================================================
# 分数段差异化策略（基于PPT幻灯片39）
# 按位次判断分数段，不同分数段有不同优先级（院校/专业/城市）
# ============================================================

# 分数线从 _CONFIG（ProvinceConfig）获取，或回退到这些硬编码默认值
# 使用 configure_with_config() 注入省份配置后会自动覆盖
_BENCHMARK_FALLBACK = {
    '物理类': {'本科线': 420, '专科线': 200},
    '历史类': {'本科线': 430, '专科线': 200},
}


def get_score_segment(score: int, category: str) -> str:
    """
    判断考生所处分数段

    返回: '高分段' / '中高分段' / '中分段' / '关键分数段' / '专科段'
    分数线来自 _CONFIG（已通过 configure_with_config 设置），
    未配置时回退到 _BENCHMARK_FALLBACK（云南默认值）。
    """
    if _CONFIG is not None:
        benke_line = _CONFIG.get_score_line(category, '本科线')
        zhuanke_line = _CONFIG.get_score_line(category, '专科线')
    else:
        benchmarks = _BENCHMARK_FALLBACK.get(category, _BENCHMARK_FALLBACK['物理类'])
        benke_line = benchmarks['本科线']
        zhuanke_line = benchmarks['专科线']

    if score is None:
        return '中分段'

    diff_to_benke = score - benke_line
    if diff_to_benke >= 100:
        return '高分段'
    elif diff_to_benke >= 50:
        return '中高分段'
    elif diff_to_benke >= 30:
        return '关键分数段'
    elif diff_to_benke >= 0:
        return '中分段'
    else:
        return '专科段'


# 各分数段的优先级权重（院校/专业/城市）
# 权重用于学校排序：越高优先
SCORE_SEGMENT_WEIGHTS = {
    # 高分段：院校平台最重要
    '高分段': {
        '物理类': {'school_weight': 0.50, 'major_weight': 0.30, 'city_weight': 0.20},
        '历史类': {'school_weight': 0.50, 'major_weight': 0.30, 'city_weight': 0.20},
    },
    # 中高分段：物理看专业，历史看院校
    '中高分段': {
        '物理类': {'school_weight': 0.30, 'major_weight': 0.50, 'city_weight': 0.20},
        '历史类': {'school_weight': 0.50, 'major_weight': 0.30, 'city_weight': 0.20},
    },
    # 中分段：物理看专业技能，历史看专业实用性
    '中分段': {
        '物理类': {'school_weight': 0.20, 'major_weight': 0.50, 'city_weight': 0.30},
        '历史类': {'school_weight': 0.20, 'major_weight': 0.50, 'city_weight': 0.30},
    },
    # 关键分数段：保层次优先
    '关键分数段': {
        '物理类': {'school_weight': 0.50, 'major_weight': 0.30, 'city_weight': 0.20},
        '历史类': {'school_weight': 0.50, 'major_weight': 0.30, 'city_weight': 0.20},
    },
    # 专科段：层次>技能>城市
    '专科段': {
        '物理类': {'school_weight': 0.50, 'major_weight': 0.30, 'city_weight': 0.20},
        '历史类': {'school_weight': 0.50, 'major_weight': 0.30, 'city_weight': 0.20},
    },
}


# ============================================================
# 批次排他关系（基于 yunnan_batch_rules.md）
# ============================================================

# 批次录取顺序（固定顺序，前一录取则后续全部失效）
BATCH_ADMISSION_ORDER = [
    '提前本科批A段', '提前本科批B段', '提前本科批C段', '提前本科批D段',
    '本科批A段', '本科批B段',
    '提前专科批A段', '提前专科批B段', '高职专科批',
]

# 批次类型录取顺序
BATCH_TYPE_ORDER = [
    '提前本科批', '本科批', '提前高职专科批', '高职专科批',
    '一本批', '二本及预科批',  # 旧高考
]

# 硬性互斥批次对（不能同时兼报）
# 格式: (批次A, 批次B, 原因说明)
BATCH_HARD_EXCLUSIONS = [
    # 艺术类 vs 体育类（规则明确不可兼报）
    # 注：当前代码未区分艺术/体育类考生，此条留作未来扩展
    # ('艺术类提前批', '体育类提前批', '艺术类与体育类不可兼报'),
]

# 软性互斥批次对（可同时出现在方案中，但需警告用户）
# 格式: (批次A, 批次B, 原因说明, 建议)
BATCH_SOFT_EXCLUSIONS = [
    # 提前本科批A段（优师专项/免费定向）vs 提前本科批D段（公费师范生）
    # 两者都有≥6年服务期约束，考生最终只会被一所录取
    (
        '提前本科批A段', '提前本科批D段',
        '优师专项/免费定向与公费师范生均有≥6年定向服务期约束，',
        '建议：若确定从教，优先选择部属师范（D段公费师范生）或省属师范（A段优师专项），避免重复填报造成心理负担。'
    ),
    # 提前本科批A段 vs 本科批B段（普通本科）
    (
        '提前本科批A段', '本科批B段',
        '提前批A段若被录取，本科批B段自动失效。',
        '建议：若能接受定向从教，将A段放优选；若更倾向普通本科，慎报A段。'
    ),
    # 提前本科批D段 vs 本科批B段
    (
        '提前本科批D段', '本科批B段',
        '提前批D段若被录取，本科批B段自动失效。',
        '建议：若被公费师范生录取意味着放弃普通本科选择权，请确认是否可接受。'
    ),
    # 本科批A段（高校专项）vs 本科批B段
    (
        '本科批A段', '本科批B段',
        '高校专项为单志愿，若被录取则本科批B段自动失效。',
        '建议：高校专项是进入重点院校的机会，通常应积极利用。'
    ),
    # 提前本科批B段（军警）vs 其他提前批
    (
        '提前本科批B段', '提前本科批C段',
        '军警院校与招飞/消防/北电科等均为单志愿或平行志愿，前序录取后后续失效。',
        '建议：明确优先方向（军警 vs 特殊院校），将更倾向的段次靠前填报。'
    ),
    # 提前本科批B段 vs 提前本科批D段
    (
        '提前本科批B段', '提前本科批D段',
        '军警院校与公费师范生分属不同段次，先录B段再录D段。',
        '建议：若对军警和从教都有意向，B段和D段均可填报，按 preference 排序。'
    ),
    # 提前专科批 vs 高职专科批
    (
        '提前专科批A段', '高职专科批',
        '提前专科批若被录取，高职专科批自动失效。',
        '建议：定向专科通常有就业保障，若能接受定向就业可优先。'
    ),
    (
        '提前专科批B段', '高职专科批',
        '定向军士若被录取，高职专科批自动失效。',
        '建议：定向军士有服役要求，请确认是否愿意至少服役5年。'
    ),
]


# ============================================================
# 选科匹配工具函数（新高考 3+1+2）
# ============================================================

# 再选科目集合
RESLECT_SUBJECTS = {'物理', '化学', '生物', '地理', '政治'}


def parse_subject_req(subject_req: str) -> Optional[List[str]]:
    """
    解析数据库 subject_req 字段，返回所需的再选科目列表。

    参数:
        subject_req: 如 '不限', '化学', '化学和生物', '政治和地理'

    返回:
        None 表示不限
        [] 表示无要求（同不限）
        ['化学'] 表示必须选化学
        ['化学', '生物'] 表示必须同时选化学和生物
    """
    if not subject_req:
        return None
    req = subject_req.strip()
    if not req or req == '不限':
        return None
    # 数据库格式: '化学和生物' / '政治和地理'
    parts = req.replace('和', ' ').replace('+', ' ').split()
    subjects = [p.strip() for p in parts if p.strip() in RESLECT_SUBJECTS]
    return subjects if subjects else None


def check_subject_match(user_subjects: List[str], subject_req: str) -> bool:
    """
    检查考生选科是否满足专业的选科要求。

    参数:
        user_subjects: 考生再选科目列表（不含首选科目）
        subject_req: 数据库 subject_req 值（如 '化学', '化学和生物', '不限'）

    返回:
        True 表示满足要求，False 表示不满足
    """
    required = parse_subject_req(subject_req)
    if required is None:
        return True  # 不限 → 全部满足
    if not required:
        return True
    user_set = set(user_subjects)
    return all(s in user_set for s in required)


# ============================================================
# 数据类
# ============================================================

@dataclass
class UserProfile:
    """用户画像"""
    score: int                    # 高考分数
    rank: int                     # 全省位次
    category: str                 # 科类（物理类/历史类/文科/理科）
    gaokao_year: int = 2026       # 高考年份（判断新旧高考）

    # ========== 专项计划资格（本科批B段附加志愿 + 本科批A段） ==========
    has_national_special: bool = False      # 国家专项资格：农村户籍+父/母农村+实施区域88县+连续3年
    has_local_special: bool = False         # 地方专项资格：农村户籍+父/母农村+实施区域53县+连续3年
    has_university_special: bool = False    # 高校专项资格：农村户籍+父/母农村+实施区域100县+连续3年

    # ========== 提前批资格（提前本科批B/C段、提前专科批B段） ==========
    # 这些批次需要政治考核/面试/体检/体能测评等"门坎条件"
    # YGCare无法自动验证，需用户自报是否已通过/计划参加
    wants_military: bool = False            # 考虑军队院校（提前本科批B段）：年龄16-20+未婚+政考+体检+面试
    wants_police: bool = False              # 考虑公安院校（提前本科批B段）：政考+面试+体检+体能测评
    wants_flying: bool = False              # 考虑招飞（提前本科批C段）：选科物化+视力+英语+体检+心理+政治
    wants_fire: bool = False                # 考虑消防学院/北电科技/国际关系等（提前本科批C段）
    wants_navy: bool = False                # 考虑航海类专业（提前本科批C段）
    wants_military_nco: bool = False        # 定向军士（提前专科批B段）：应届+年龄≤20+未婚+政考+体检
    wants_teacher_directed: bool = False    # 优师专项/免费定向（提前本科批A段）：愿意从教+接受定向
    wants_special_directed: bool = False    # 专科免费定向（提前专科批A段）：户籍定向要求

    # ========== 通用偏好 ==========
    has_minority_prep: bool = False         # 少数民族预科资格
    include_early_batch: bool = True        # 是否考虑提前批（默认包含，用户明确排除时为False）
    preferred_cities: List[str] = field(default_factory=list)   # 偏好城市
    preferred_majors: List[str] = field(default_factory=list)   # 偏好专业
    excluded_majors: List[str] = field(default_factory=list)    # 排除专业
    excluded_batches: List[str] = field(default_factory=list)   # 明确排除的批次
    risk_tolerance: str = 'balanced'        # aggressive/balanced/conservative
    budget_min: float = 0                 # 最低学费预算
    budget_max: float = 100000            # 最高学费预算
    career_plan: str = '就业'             # 考研/就业/出国/考公

    # ========== 选科（新高考 3+1+2） ==========
    selected_subjects: List[str] = field(default_factory=list)
    # 再选科目列表，不含首选科目（物理/历史）
    # 示例: ['化学', '生物'] 来自 '物理+化学+生物'

    @property
    def is_new_gaokao(self) -> bool:
        """是否新高考（2025年起）"""
        return self.gaokao_year >= 2025

    @property
    def subject_type(self) -> Optional[str]:
        """获取数据库科类值（物理/历史）"""
        mapping = {'理科': '物理', '物理': '物理', '物理类': '物理',
                   '文科': '历史', '历史': '历史', '历史类': '历史'}
        return mapping.get(self.category)

    def check_batch_conflicts(self, active_batches: List[str]) -> List[Dict]:
        """
        检查批次间的排他/互斥关系

        参数:
            active_batches: 当前激活的批次列表

        返回:
            冲突列表，每项包含: type, batch_a, batch_b, reason, suggestion
        """
        conflicts = []
        active_set = set(active_batches)

        # 硬性互斥检查
        for a, b, reason in BATCH_HARD_EXCLUSIONS:
            if a in active_set and b in active_set:
                conflicts.append({
                    'type': '硬性互斥',
                    'batch_a': a,
                    'batch_b': b,
                    'reason': reason,
                    'suggestion': '请删除其中一个批次。',
                })

        # 软性互斥检查
        for a, b, reason, suggestion in BATCH_SOFT_EXCLUSIONS:
            if a in active_set and b in active_set:
                conflicts.append({
                    'type': '顺序排他',
                    'batch_a': a,
                    'batch_b': b,
                    'reason': reason,
                    'suggestion': suggestion,
                    'admission_note': (
                        f'录取顺序：{a} 早于 {b}。'
                        f'若{a}被录取，{b}自动失效。'
                    ),
                })

        # 录取顺序说明
        if len(active_batches) > 1:
            # P2-fix: 未知批次排序到末尾，并发出警告
            _unknown = [b for b in active_batches if b not in BATCH_ADMISSION_ORDER]
            if _unknown:
                import logging
                logging.warning(f'check_batch_conflicts: 未知批次 {_unknown}，已排到录取顺序末尾')

            sorted_batches = sorted(
                active_batches,
                key=lambda x: BATCH_ADMISSION_ORDER.index(x)
                if x in BATCH_ADMISSION_ORDER else 999
            )
            order_note = ' → '.join(sorted_batches)
            conflicts.append({
                'type': '录取顺序',
                'batch_a': '',
                'batch_b': '',
                'reason': f'各批次按以下顺序依次录取：{order_note}',
                'suggestion': '前面的批次录取后，后续批次自动失效。请按真实意愿排序。',
            })

        return conflicts

    @property
    def total_volunteer_slots(self) -> int:
        """总志愿槽位数"""
        if self.is_new_gaokao:
            base = 40 + 20  # 本科B段40 + 专科20
            if self.has_national_special or self.has_local_special:
                base += 10  # 专项附加
            if self.has_minority_prep:
                base += 10  # 预科附加
            if self.include_early_batch:
                if self.wants_teacher_directed:
                    base += 1   # 提前A段(优师/定向)
                if self.wants_military or self.wants_police:
                    base += 10  # 提前B段(军队/公安)
                if self.wants_flying or self.wants_fire or self.wants_navy:
                    base += 1   # 提前C段
                base += 10  # 提前D段(公费师范/马理论/港澳)
                if self.wants_special_directed:
                    base += 1   # 提前专科A段(定向)
                if self.wants_military_nco:
                    base += 1   # 提前专科B段(定向军士)
            if self.has_university_special:
                base += 1   # 本科A段(高校专项)
            return base
        else:
            slots = 10 + 10 + 10  # 一本10 + 二本10 + 专科10
            return slots




@dataclass
class Recommendation:
    """推荐结果"""
    school_name: str
    category: str          # 冲/稳/保
    probability: float
    confidence: str
    predicted_rank: int
    reasons: List[str]
    school_quality: str = ''
    school_tier: str = ''     # L1-L13
    tier_label: str = ''      # 清北/华五人/C9等
    tuition: float = 0
    location: str = ''
    batch_key: str = ''    # 所属批次键
    safety_warning: List[str] = field(default_factory=list)  # 兜底安全警告
    extra_reasons: List[str] = field(default_factory=list)   # 额外原因（如冲校门槛高）
    group_code: str = ''     # 专业组代码，如 "01"
    group_name: str = ''     # 专业组名称，如 "01专业组"
    subject_req: str = ''    # 选科要求，如 "化学"
    city_preferred: bool = True  # 是否符合用户城市偏好（无偏好时默认True）


# ============================================================
# 推荐引擎
# ============================================================

class VolunteerRecommender:
    """志愿推荐引擎"""

    # 科类标签处理已统一抽到 algorithms/subject_normalize.py
    # 不要在此处再维护映射表，参见 P0-3 设计原则

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._local = threading.local()
        self.prob_calculator = AdmissionProbability(db_path)
        self._school_info_cache = {}
        # AUDIT-P1-025: 预加载专业类/就业缓存，避免每次推荐 240+ 次 N+1 小查询
        self._major_class_cache: Dict[str, str] = {}
        self._employment_score_cache: Dict[str, float] = {}
        self._load_major_caches()

    def _load_major_caches(self):
        """AUDIT-P1-025: 推荐器初始化时一次性加载 major_class/employment 缓存。

        预加载减少推荐链路中的 N+1 查询：
        - major_catalog 约 750 行 → 一次扫表 < 50ms
        - major_employment_stats 约 200 行 → 一次扫表 < 20ms
        总共 < 100ms，但每个推荐方案可减少 240+ 次小查询。
        """
        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            cur = conn.cursor()
            # 预加载 major_class 映射
            cur.execute('SELECT major_name, major_class FROM major_catalog WHERE major_class IS NOT NULL')
            for name, cls in cur.fetchall():
                self._major_class_cache[name] = cls
            # 预加载就业评分（结构化数据优先）
            cur.execute(
                'SELECT major_name, employment_rate, avg_salary_monthly FROM major_employment_stats '
                'WHERE employment_rate IS NOT NULL AND avg_salary_monthly IS NOT NULL'
            )
            for name, rate, salary in cur.fetchall():
                emp_score = rate * 60 + min(100, salary / 20000) * 40
                self._employment_score_cache[name] = round(emp_score, 1)
            conn.close()
        except Exception as e:
            logging.warning(f'[P1-025] 预加载 major/emp 缓存失败: {e}，回退到逐行查询')

    def _init_local(self):
        if not hasattr(self._local, 'cursor'):
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._local.cursor = conn.cursor()

    def _get_cursor(self):
        if not hasattr(self._local, 'cursor'):
            self._init_local()
        return self._local.cursor

    def _major_matches_excluded(self, major_name: str, excluded: str) -> bool:
        """判断具体专业名是否匹配排除的大类名。

        例如: "化学工程与工艺" 匹配 "化学类"，"生物技术" 匹配 "生物学类"。
        """
        if major_name == excluded:
            return True
        # 大类名通常以"类"结尾，去掉后缀做关键词匹配
        keyword = excluded[:-1] if excluded.endswith('类') else excluded
        if len(keyword) >= 2 and keyword in major_name:
            return True
        # 再退一层: "生物学" → "生物"，以匹配"生物技术"/"生物工程"等
        if keyword.endswith('学') and len(keyword) > 2:
            root = keyword[:-1]
            if len(root) >= 2 and root in major_name:
                return True
        return False

    def check_major_group_clean(self, school_name: str, user_excluded_majors: List[str],
                                subject_type: str = None) -> Tuple[bool, List[str]]:
        """
        检查院校专业组是否"干净"（框框策略）

        专业组干净 = 该校所有专业用户都能接受（无排斥专业）

        AUDIT-P1-009: 必须按 subject_type 过滤，否则另一科类的招生专业
        会污染本科类的"干净度"判断，错误降低冲档比例。

        参数:
            school_name: 学校名称
            user_excluded_majors: 用户排除的专业列表（体检/兴趣等）
            subject_type: 用户科类 '物理'/'历史'（与 enroll_plan.category 对齐）

        返回:
            (is_clean, conflict_majors): 是否干净 + 冲突专业列表
        """
        if not user_excluded_majors:
            return True, []

        try:
            cursor = self._get_cursor()
            # 实测字段为 sp_name（专业名）+ category（科类，'物理类'/'历史类'/'理科'/'文科'）
            # 用 aliases_for_sql_param 展开所有等价别名，覆盖新旧高考标签
            from .subject_normalize import aliases_for_sql_param
            base = f'SELECT sp_name FROM enroll_plan_{CURRENT_PLAN_YEAR} WHERE school_name=?'
            params = [school_name]
            if subject_type:
                aliases = aliases_for_sql_param(subject_type)
                if aliases:
                    placeholders = ','.join(['?'] * len(aliases))
                    base += f' AND category IN ({placeholders})'
                    params.extend(aliases)
            majors = cursor.execute(base, tuple(params)).fetchall()

            conflict = []
            for m in majors:
                major = m[0]
                for excl in user_excluded_majors:
                    if self._major_matches_excluded(major, excl):
                        conflict.append(major)
                        break

            return len(conflict) == 0, conflict
        except Exception:
            return True, []

    def adjust_chong_wen_bao_ratio(self, config: Dict, has_dirty_groups: bool,
                                    excluded_majors_count: int) -> Tuple[Dict, List[str]]:
        """
        根据专业组干净程度动态调整冲稳保比例（框框策略）

        云南 = 新高考院校专业组模式（有调剂）
        - 专业组干净: 使用原配置
        - 专业组不干净: 降低冲的比例，增加稳的比例
          因为冲不干净专业组 = 可能被调剂到排斥专业
        """
        warnings = []
        if not has_dirty_groups:
            return config, warnings

        # 动态调整：冲比例减半，稳比例增加
        orig_chong = config.get('chong_ratio', 0.15)
        orig_wen = config.get('wen_ratio', 0.55)
        orig_bao = config.get('bao_ratio', 0.30)

        new_chong = max(0.05, orig_chong * 0.5)  # 冲减半，最低5%
        diff = orig_chong - new_chong
        new_wen = orig_wen + diff * 0.6  # 大部分给稳
        new_bao = orig_bao + diff * 0.4  # 少部分给保

        # 归一化
        total = new_chong + new_wen + new_bao
        new_chong = round(new_chong / total, 2)
        new_wen = round(new_wen / total, 2)
        new_bao = 1.0 - new_chong - new_wen

        warnings.append(
            f'⚠️ 部分院校专业组含排斥专业（{excluded_majors_count}个），'
            f'系统已自动降低冲刺比例（{orig_chong:.0%}→{new_chong:.0%}），增加稳妥比例，'
            f'避免被调剂到不适宜专业。'
        )

        new_config = dict(config)
        new_config['chong_ratio'] = new_chong
        new_config['wen_ratio'] = new_wen
        new_config['bao_ratio'] = new_bao

        return new_config, warnings

    # ── 综合质量评分（用于志愿排序）──

    def compute_composite_score(self, rec) -> float:
        """
        计算推荐项的综合质量分（0-100）

        维度权重:
        - 学校层级 35%: L1-L21映射
        - 专业热度 25%: HotMajorAnalyzer.composite_score
        - 就业质量 20%: employment_note关键词打分
        - 行业趋势 20%: HotMajorAnalyzer.trend_score
        """
        # 1. 学校层级分 (35%)
        tier = getattr(rec, 'school_tier', '') or ''
        if tier.startswith('L'):
            try:
                tier_num = int(tier[1:])
                school_score = max(0, (22 - tier_num) / 21 * 100)
            except ValueError:
                school_score = 50
        else:
            # 兜底：用旧标签
            quality = getattr(rec, 'school_quality', '') or ''
            if '985' in quality:
                school_score = 85
            elif '211' in quality:
                school_score = 75
            elif '双一流' in quality:
                school_score = 65
            elif '国家示范' in quality or '国家骨干' in quality or '双高计划' in quality:
                school_score = 45  # 优质专科（国家示范/骨干/双高）
            elif '省级示范' in quality or '国家级重点' in quality:
                school_score = 42  # 较优质专科
            else:
                school_score = 40

        # 2-4. 专业维度（取推荐专业的平均值）
        majors = getattr(rec, 'recommended_majors', []) or []
        major_heat_scores = []
        major_trend_scores = []
        employment_scores = []

        for mp in majors[:5]:  # 最多取5个专业
            major_name = mp.major_name if hasattr(mp, 'major_name') else str(mp)

            # 专业热度 + 趋势
            cls_name = self._get_major_class(major_name)
            if cls_name and cls_name in self._trend_cache:
                major_heat_scores.append(self._trend_cache[cls_name])
                # trend_score 需要从 HotMajorAnalyzer 获取
                if hasattr(self, '_trend_detail_cache') and cls_name in self._trend_detail_cache:
                    major_trend_scores.append(self._trend_detail_cache[cls_name])

            # 就业质量
            emp_score = self._score_major_employment(major_name)
            if emp_score is not None:
                employment_scores.append(emp_score)

        # 聚合专业分（trend_cache 已是 0-100 范围，无需再乘 100）
        has_major_data = bool(major_heat_scores)

        if has_major_data:
            major_heat = sum(major_heat_scores) / len(major_heat_scores)
            trend = sum(major_trend_scores) / len(major_trend_scores)
            employment = sum(employment_scores) / len(employment_scores) if employment_scores else 50
        else:
            # 无专业数据时：仅依赖学校层级排序，专业维度用低默认值
            # 确保"有真实数据的差学校"排名 > "无数据默认值的学校"
            major_heat = 10
            trend = 10
            employment = 10

        return round(
            school_score * 0.35 + major_heat * 0.25 + employment * 0.20 + trend * 0.20, 1
        )

    def _load_trend_caches(self):
        """懒加载热度和趋势缓存"""
        if not hasattr(self, '_trend_cache_loaded'):
            self._trend_cache = {}
            self._trend_detail_cache = {}
            try:
                from .hot_major_analyzer import HotMajorAnalyzer
                analyzer = HotMajorAnalyzer(self._db_path)
                scores = analyzer.analyze(year=2025)
                for s in scores:
                    self._trend_cache[s.major_class] = s.composite_score
                    self._trend_detail_cache[s.major_class] = s.trend_score
                analyzer.close()
            except Exception:
                pass
            self._trend_cache_loaded = True

    def _get_major_class(self, major_name: str) -> str:
        """获取专业所属专业类（AUDIT-P1-025: 优先查缓存避免 N+1）"""
        if not major_name:
            return ''
        if major_name in self._major_class_cache:
            return self._major_class_cache[major_name]
        try:
            cursor = self._get_cursor()
            cursor.execute(
                'SELECT major_class FROM major_catalog WHERE major_name=? LIMIT 1',
                (major_name,),
            )
            row = cursor.fetchone()
            result = row[0] if row else ''
            self._major_class_cache[major_name] = result  # 写入缓存
            return result
        except Exception:
            return ''

    def _load_major_caches(self):
        """AUDIT-P1-025: 推荐器初始化时一次性加载 major_class/employment 缓存。

        预加载减少推荐链路中的 N+1 查询：
        - major_catalog 约 750 行 → 一次扫表 < 50ms
        - major_employment_stats 约 200 行 → 一次扫表 < 20ms
        总共 < 100ms，但每个推荐方案可减少 240+ 次小查询。
        """
        try:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            cur = conn.cursor()
            # 预加载 major_class 映射
            cur.execute('SELECT major_name, major_class FROM major_catalog WHERE major_class IS NOT NULL')
            for name, cls in cur.fetchall():
                self._major_class_cache[name] = cls
            # 预加载就业评分（结构化数据优先）
            cur.execute(
                'SELECT major_name, employment_rate, avg_salary_monthly FROM major_employment_stats '
                'WHERE employment_rate IS NOT NULL AND avg_salary_monthly IS NOT NULL'
            )
            for name, rate, salary in cur.fetchall():
                emp_score = rate * 60 + min(100, salary / 20000) * 40
                self._employment_score_cache[name] = round(emp_score, 1)
            conn.close()
        except Exception as e:
            logging.warning(f'[P1-025] 预加载 major/emp 缓存失败: {e}，回退到逐行查询')

    def _score_major_employment(self, major_name: str) -> float:
        """从就业数据提取就业质量分（0-100）

        优先查询结构化就业统计（就业率+起薪），无数据时fallback到关键词打分。
        AUDIT-P1-025: 优先查缓存避免 N+1 查询。
        """
        if not major_name:
            return 50
        # AUDIT-P1-025: 缓存命中直接返回
        if major_name in self._employment_score_cache:
            return self._employment_score_cache[major_name]
        try:
            cursor = self._get_cursor()
            # 1. 优先查询结构化就业数据
            cursor.execute(
                'SELECT employment_rate, avg_salary_monthly FROM major_employment_stats WHERE major_name=? LIMIT 1',
                (major_name,),
            )
            row = cursor.fetchone()
            if row and row[0] is not None and row[1] is not None:
                # P1-fix: 薪资归一化 divisor=20000 覆盖全国月薪范围（3k-20k→0-100分）
                # 原P0修复 /150 单位错误，后改为 /100000 矫枉过正（7800/100000=0.078，仅3.1分）
                # 现用 /20000：7800月薪→39分，15000→75分，20000→100分
                emp_score = row[0] * 60 + min(100, row[1] / 20000) * 40
                return round(emp_score, 1)

            # 2. 无数据时fallback到关键词打分
            cursor.execute(
                'SELECT employment_note FROM major_catalog WHERE major_name=? LIMIT 1',
                (major_name,),
            )
            row = cursor.fetchone()
            if not row or not row[0]:
                return 50
            text = row[0]
            pos_count = sum(1 for kw in EMPLOYMENT_POSITIVE if kw in text)
            neg_count = sum(1 for kw in EMPLOYMENT_NEGATIVE if kw in text)
            score = 50 + pos_count * 8 - neg_count * 10
            return max(10, min(90, score))
        except Exception:
            return 50

    def _subject_type_in_clause(self, subject_type: str):
        """
        生成科类 IN 子句，覆盖旧高考/新高考所有标签
        统一调用 subject_normalize.aliases_for_sql_param

        返回:
            (clause: str, params: tuple) — 用法：
                clause_str, params = obj._subject_type_in_clause(subject_type)
                sql += clause_str
                all_params = (其他参数,) + params
        """
        from .subject_normalize import aliases_for_sql_param
        aliases = aliases_for_sql_param(subject_type)
        if aliases:
            placeholders = ', '.join('?' for _ in aliases)
            return f" AND subject_type IN ({placeholders})", aliases
        return " AND subject_type = ?", (subject_type,)

    def _resolve_school_info(self, school_name: str):
        """解析学校信息，处理括号后缀问题"""
        # 缓存容量上限：超过 3000 后清掉未命中记录（DB更新后自动刷新）
        if len(self._school_info_cache) > 3000:
            stale = [k for k, v in self._school_info_cache.items() if v is None]
            for k in stale:
                del self._school_info_cache[k]

        if school_name in self._school_info_cache:
            return self._school_info_cache[school_name]

        self._get_cursor().execute('''
            SELECT school_tier, school_tier_label, is_985, is_211, is_syl,
                   province_full, level, school_type, history
            FROM school_info WHERE school_name = ?
        ''', (school_name,))
        row = self._get_cursor().fetchone()
        if row:
            self._school_info_cache[school_name] = row
            return row

        base_name = school_name
        for sep in ('(', '（'):
            idx = base_name.find(sep)
            if idx > 0:
                base_name = base_name[:idx]
                break

        if base_name != school_name:
            self._get_cursor().execute('''
                SELECT school_tier, school_tier_label, is_985, is_211, is_syl,
                       province_full, level, school_type, history
                FROM school_info WHERE school_name = ?
            ''', (base_name,))
            row = self._get_cursor().fetchone()
            if row:
                self._school_info_cache[school_name] = row
                return row

        self._school_info_cache[school_name] = None
        return None

    def _match_subject_school(self, school_name: str, user_subjects: List[str]) -> bool:
        """
        检查学校的选科要求是否匹配考生选科。

        学校任一专业（记录）的选科要求满足，即视为通过。

        参数:
            school_name: 学校名称
            user_subjects: 考生再选科目列表

        返回:
            True 表示学校有至少一个专业考生可报
        """
        if not user_subjects:
            return True  # 未提供选科信息 → 不过滤

        self._get_cursor().execute('''
            SELECT DISTINCT subject_req FROM v_enroll_detail
            WHERE school_name = ? AND subject_req IS NOT NULL
              AND subject_req != '' AND subject_req != '不限'
              AND min_rank IS NOT NULL
        ''', (school_name,))

        rows = self._get_cursor().fetchall()
        if not rows:
            return True  # 无特殊选科要求 → 全部满足

        # 检查是否有任何一条记录的 subject_req 被满足
        for (subject_req,) in rows:
            if check_subject_match(user_subjects, subject_req):
                return True

        return False  # 所有专业的选科要求都不满足

    def filter_candidates(self, user_rank: int, tolerance: float = 0.25,
                          subject_type: str = None,
                          user_subjects: List[str] = None,
                          exclude_early_batches: bool = False) -> List[Tuple]:
        """
        根据位次筛选候选院校专业组池

        参数:
            user_rank: 考生位次
            tolerance: 容忍度（默认±25%）
            subject_type: 科类 '物理'/'历史'（可选）
            exclude_early_batches: 排除提前批次（默认False）

        返回:
            [(school_name, group_code, group_name, min_rank), ...]
            每个专业组作为独立候选
        """
        max_rank_normal = int(user_rank * (1 + tolerance))
        if user_rank < 500:
            max_rank_bao = int(user_rank * 10.0)
        elif user_rank < 5000:
            max_rank_bao = int(user_rank * 4.0)
        else:
            max_rank_bao = int(user_rank * 2.0)

        # Step 2: 历史类数据稀疏（2025年仅~1049条），保档安全垫额外扩大1.2x
        # 对应云南考试院建议：保底位次低于自身15%
        # 数据补全后（>2000条）此分支仍生效，作为常规风控（历史类波动放大）
        # P2-fix: 移除'文科'——subject_type经过映射后仅为'物理类'/'历史类'，不可达
        if subject_type in ('历史', '历史类'):
            max_rank_bao = int(max_rank_bao * 1.2)

        # 优先使用 score_line_{CURRENT_SCORE_LINE_YEAR}（有专业组级投档线数据）
        norm_type = self.prob_calculator._normalize_subject_type(subject_type, CURRENT_SCORE_LINE_YEAR) if subject_type else None
        query = f'''
            SELECT school_name, group_code, subject_req, min_rank
            FROM score_line_{CURRENT_SCORE_LINE_YEAR}
            WHERE min_rank IS NOT NULL
              AND min_rank <= ?
        '''
        params: list = [max_rank_bao]
        if norm_type:
            query += ' AND subject_type = ?'
            params.append(norm_type)
        if exclude_early_batches:
            query += " AND batch NOT LIKE '提前%'"
        query += ' ORDER BY min_rank ASC'

        self._get_cursor().execute(query, params)
        rows = self._get_cursor().fetchall()

        if rows:
            # 构建 (school_name, group_code, group_name, min_rank)
            candidates = [(r[0], str(r[1]), f'{r[1]}专业组', r[3]) for r in rows]
        else:
            # Fallback: 无 score_line_{CURRENT_SCORE_LINE_YEAR} 数据时用 enroll_detail 按学校聚合
            query2 = '''
                SELECT DISTINCT school_name
                FROM v_enroll_detail
                WHERE min_rank IS NOT NULL
                  AND min_rank <= ?
            '''
            params2: list = [max_rank_bao]
            if subject_type:
                subj_clause, subj_params = self._subject_type_in_clause(subject_type)
                query2 += subj_clause
                params2.extend(subj_params)
            if exclude_early_batches:
                query2 += " AND batch NOT LIKE '提前%'"
            query2 += ' ORDER BY school_name'
            self._get_cursor().execute(query2, params2)
            candidates = [(row[0], '', '', 0) for row in self._get_cursor().fetchall()]

        if len(candidates) > 2000:
            # 候选池过大，按正常范围截断
            params[0] = max_rank_normal
            self._get_cursor().execute(query, params)
            rows = self._get_cursor().fetchall()
            if rows:
                candidates = [(r[0], str(r[1]), f'{r[1]}专业组', r[3]) for r in rows]

        # 选科过滤
        if user_subjects and candidates:
            filtered = []
            for school_name, group_code, group_name, min_rank in candidates:
                if group_code:
                    subject_req = self._get_group_subject_req(
                        school_name, group_code, norm_type
                    )
                    if subject_req and check_subject_match(user_subjects, subject_req):
                        filtered.append((school_name, group_code, group_name, min_rank))
                else:
                    # 无选科要求或 fallback 模式，按学校级过滤
                    if self._match_subject_school(school_name, user_subjects):
                        filtered.append((school_name, group_code, group_name, min_rank))
            candidates = filtered

        return candidates

    def _get_group_subject_req(self, school_name: str, group_code: str,
                                subject_type: str = None) -> Optional[str]:
        """查询指定专业组的选科要求（必须按科类过滤，防止物理/历史混用）"""
        if subject_type:
            self._get_cursor().execute(f'''
                SELECT subject_req FROM score_line_{CURRENT_SCORE_LINE_YEAR}
                WHERE school_name = ? AND group_code = ? AND subject_type = ?
                LIMIT 1
            ''', (school_name, group_code, subject_type))
        else:
            self._get_cursor().execute(f'''
                SELECT subject_req FROM score_line_{CURRENT_SCORE_LINE_YEAR}
                WHERE school_name = ? AND group_code = ?
                LIMIT 1
            ''', (school_name, group_code))
        row = self._get_cursor().fetchone()
        return row[0] if row and row[0] else None

    def filter_candidates_with_major(self, user_rank: int, target_major: str,
                                      subject_type: str = None,
                                      rank_tolerance: float = 0.40,
                                      user_subjects: List[str] = None,
                                      exclude_early_batches: bool = False) -> List[str]:
        """
        按位次筛选候选池 + 补充目标专业匹配的学校

        参数:
            user_rank: 考生位次
            target_major: 目标专业名称
            subject_type: 科类 '物理'/'历史'
            rank_tolerance: 位次容忍度
            user_subjects: 考生再选科目列表
            exclude_early_batches: 排除提前批次（默认False）

        返回:
            候选院校名称列表
        """
        # filter_candidates 返回 List[Tuple]，提取学校名
        raw_candidates = self.filter_candidates(
            user_rank, rank_tolerance, subject_type, user_subjects,
            exclude_early_batches=exclude_early_batches)
        candidates = set()
        for c in raw_candidates:
            candidates.add(c[0] if isinstance(c, tuple) else c)

        aliases = self._get_major_aliases(target_major)
        wide_rank = int(user_rank * 2.0)  # 与filter_candidates保持一致
        early_clause = "AND batch NOT LIKE '提前%' " if exclude_early_batches else ""
        # AUDIT-P1-008: 目标专业候选必须按用户科类过滤，避免另一科类的专业被错误纳入
        subject_clause, subject_params = self._subject_type_in_clause(subject_type) if subject_type else ("", ())

        for alias in aliases:
            self._get_cursor().execute(f'''
                SELECT DISTINCT school_name FROM v_enroll_detail
                WHERE min_rank IS NOT NULL AND min_rank <= ?
                  AND major_name LIKE ? {subject_clause} {early_clause}
            ''', (wide_rank, f'%{alias}%') + subject_params)
            for row in self._get_cursor().fetchall():
                candidates.add(row[0])

        if subject_type:
            filtered = set()
            subject_clause2, subject_params2 = self._subject_type_in_clause(subject_type)
            early_filter = "AND batch NOT LIKE '提前%' " if exclude_early_batches else ""
            for school in candidates:
                self._get_cursor().execute(f'''
                    SELECT COUNT(DISTINCT year) FROM v_enroll_detail
                    WHERE school_name = ? {subject_clause2} {early_filter}AND min_rank IS NOT NULL
                ''', (school,) + subject_params2)
                row = self._get_cursor().fetchone()
                if row and row[0] >= 2:
                    filtered.add(school)
            candidates = filtered

        return sorted(candidates)

    def calculate_probability(self, user_rank: int, school_name: str,
                              subject_type: str = None) -> Optional[ProbabilityResult]:
        """计算单所院校的录取概率"""
        return self.prob_calculator.calculate(user_rank, school_name,
                                              subject_type=subject_type)

    def classify_schools(self, candidates, user_rank: int,
                         prob_ranges: Dict, subject_type: str = None,
                         target_major: str = None,
                         score_segment: str = None,
                         prob_ranges_source: str = 'STRATEGY') -> Tuple[List, List, List]:
        """
        按冲稳保分类

        参数:
            candidates: 候选项
                - 新高考模式: [(school_name, group_code, group_name, min_rank), ...]
                - 旧高考/Fallback: [school_name, ...]
            user_rank: 考生位次
            prob_ranges: 概率范围配置 {'chong_prob_range': (min,max), ...}
            subject_type: 科类
            target_major: 目标专业
            score_segment: 分数段（'高分段'/'中高分段'/'中分段'/'关键分数段'/'专科段'）
            prob_ranges_source: 配置来源 'STRATEGY' / 'BATCH' / 'CUSTOM'（便于追溯/审计）
        """
        chong_list = []
        wen_list = []
        bao_list = []

        chong_min, chong_max = prob_ranges['chong_prob_range']
        wen_min, wen_max = prob_ranges['wen_prob_range']
        bao_min = prob_ranges['bao_prob_range'][0]

        # 专科段说明：不再降低保底阈值（历史bug：曾将保档降至25%）
        # 即使用户处于专科段，保档仍需≥85%才算"保"
        # 专科段考生在高职专科批的推荐会因公式限制概率偏低，
        # 此时通过扩大候选池和"不够保"警告来处理，而非降低"保"的定义

        # 判断输入格式：tuple 还是 str
        is_tuple_mode = bool(candidates and isinstance(candidates[0], tuple))

        for item in candidates:
            if is_tuple_mode:
                school_name, group_code, group_name, _min_rank = item
            else:
                school_name = item
                group_code = ''
                group_name = ''

            result = None
            if is_tuple_mode and group_code:
                # 专业组模式：优先使用专业组级投档线
                result = self.prob_calculator.calculate_group(
                    user_rank, school_name, group_code, subject_type=subject_type
                )
            if result is None and target_major:
                result = self.prob_calculator.calculate(
                    user_rank, school_name, target_major, subject_type=subject_type
                )
                if result and result.confidence == 'none':
                    result = None
            if result is None:
                result = self.calculate_probability(
                    user_rank, school_name, subject_type=subject_type
                )
                # 共享陷阱3：学校级 fallback 同样可能返回 confidence='none'
                # （如"无位次数据"分支返回 prob=50/none）。若不拦，会穿过下方
                # prob<15 过滤、被当 50% 稳档虚假推荐。与上面 1187 专业级守卫
                # 一致：confidence='none' 不进冲稳保分类（NEVER 用无法评估的数据出推荐）。
                if result and result.confidence == 'none':
                    result = None
            if result is None:
                continue

            prob = result.probability

            # CAT-03 运行时校验: 添加分类标签
            # 概率<15%的极险学校直接跳过（浪费志愿名额，含完全不可达的清北等）
            if prob < 15:
                continue

            category_label = None
            extra_reasons = []

            # 先检查保档 → 稳档 → 冲档（顺序很重要，避免范围重叠时被前面的条件捕获）
            if prob >= bao_min:
                category_label = '保'
                # 保档但概率不足85%标记为"不够保"
                if prob < 85:
                    extra_reasons.append('⚠️ 该档作为保底不够保险（概率<85%），建议增加更稳妥的保底校')
            elif wen_min <= prob < wen_max:
                category_label = '稳'
            elif prob < chong_max:
                category_label = '冲'
                if prob < chong_min:
                    extra_reasons.append('该校门槛高于考生位次，属于极限冲刺，建议谨慎填报')
            elif prob > 0:
                category_label = '冲'
                extra_reasons.append('该校门槛高于考生位次，建议谨慎填报')

            if category_label:
                reasons = result.reasons + extra_reasons
                rec = Recommendation(
                    school_name=school_name, category=category_label, probability=prob,
                    confidence=result.confidence, predicted_rank=result.predicted_rank,
                    reasons=reasons,
                    group_code=group_code,
                    group_name=group_name,
                    subject_req=self._get_group_subject_req(school_name, group_code, subject_type) or '',
                )
                if category_label == '冲':
                    chong_list.append(rec)
                elif category_label == '稳':
                    wen_list.append(rec)
                else:
                    bao_list.append(rec)

        return chong_list, wen_list, bao_list

    def apply_preferences(self, schools: List[Recommendation],
                         user_profile: UserProfile) -> List[Recommendation]:
        """
        应用用户偏好过滤（学费等）
        """
        filtered = []

        for school in schools:
            row = self._resolve_school_info(school.school_name)
            if row:
                school_tier, tier_label, is_985, is_211, is_syl, province, level, school_type, history = row
                school.school_quality = '/'.join(filter(None, [
                    '985' if is_985 == '1' else '',
                    '211' if is_211 == '1' else '',
                    '双一流' if is_syl == '1' else '',
                ])) or '普通'
                school.school_tier = f"L{school_tier}" if school_tier else ""
                school.tier_label = tier_label or ""
                school.location = province or ''

                # 专科层次增强：识别国家示范性/双高/骨干等优质专科
                if school_tier == '18' and history:
                    zhuanke_tags = []
                    if '国家示范' in history or '全国示范' in history:
                        zhuanke_tags.append('国家示范')
                    elif '省级示范' in history or '省示范' in history:
                        zhuanke_tags.append('省级示范')
                    if '骨干' in history:
                        zhuanke_tags.append('国家骨干')
                    if '双高' in history:
                        zhuanke_tags.append('双高计划')
                    if '国家示范性高职' in history:
                        zhuanke_tags.append('国家示范')
                    if '国家级重点' in history or '国家高水平' in history:
                        zhuanke_tags.append('国家级重点')
                    if zhuanke_tags:
                        school.school_quality = '/'.join(zhuanke_tags)

            # AUDIT-P1-009: 学费均值按用户科类计算，避免另一科类的学费混入
            _subj_clause, _subj_params = self._subject_type_in_clause(
                getattr(user_profile, 'subject_type', None)
            ) if getattr(user_profile, 'subject_type', None) else ("", ())
            self._get_cursor().execute(f'''
                SELECT AVG(tuition)
                FROM v_enroll_detail
                WHERE school_name = ? AND tuition IS NOT NULL AND tuition != ''
                  {_subj_clause}
            ''', (school.school_name,) + _subj_params)

            tuition_row = self._get_cursor().fetchone()
            if tuition_row and tuition_row[0]:
                school.tuition = float(tuition_row[0])
                # 预算只限制上限（学生能承担的最高学费），不设下限
                if school.tuition > user_profile.budget_max:
                    continue

            # 城市偏好匹配标记（软过滤：不硬排除，只影响后续排序权重）
            if user_profile.preferred_cities:
                school_province = (school.location or '').strip()
                school.city_preferred = any(
                    c in school_province or school_province in c
                    for c in user_profile.preferred_cities
                )
            else:
                school.city_preferred = True  # 无偏好=全匹配

            filtered.append(school)

        return filtered

    def check_safety_net(self, bao_list: List[Recommendation],
                         user_profile: UserProfile,
                         user_rank: int,
                         subject_type: str = None) -> List[Recommendation]:
        """
        兜底志愿安全检查（框框策略）

        检查规则:
        1. 招生计划过少（<10人）→ 标记"招生计划少"
        2. 上一年断档（位次异常低）→ 标记"曾断档"
        3. 中外合作办学 → 标记"中外合作"
        4. 非本省 → 标记"非本省，兜底优先本省"

        兜底不够安全的学校不作为最后3个保底志愿。
        确保保底志愿列表至少有5所满足全部安全条件的学校。
        """
        warnings = []
        safe_list = []
        unsafe_list = []

        for rec in bao_list:
            issues = []

            # 1. 检查招生计划人数
            plan_count = self._get_enrollment_plan(rec.school_name, subject_type)
            if plan_count and plan_count < 10:
                issues.append(f'招生计划仅{plan_count}人（建议≥10人）')

            # 2. 检查上一年是否断档
            if self._is_catch_cutoff(rec.school_name, user_rank, subject_type):
                issues.append('上一年曾出现断档，录取位次波动大')

            # 3. 检查中外合作办学
            if self._is_joint_venture(rec.school_name):
                issues.append(
                    '中外合作办学：①学费3-8万/年（4年总学费12-32万）；'
                    '②学籍单独编码，几乎不能转入该校普通类专业（教育部及多数高校规定）；'
                    '③部分项目需赴海外完成2年学业（额外生活成本）'
                )

            # 4. 检查是否本省（用户有明确外省城市偏好时跳过此警告）
            user_wants_outside = bool(
                user_profile.preferred_cities and
                not any('云南' in c or '昆明' in c for c in user_profile.preferred_cities)
            )
            if not user_wants_outside and not self._is_local_province(rec.school_name, user_profile):
                issues.append('非本省高校，兜底优先选择本省院校')

            # 5. 分段计费检查（软件工程/集成电路类常见大三大四学费上涨）
            _EXPENSIVE_MAJOR_KEYWORDS = ('软件工程', '集成电路', '微电子', '示范性软件学院')
            recommended_majors = getattr(rec, 'recommended_majors', []) or []
            major_text = ' '.join(getattr(m, 'major_name', '') for m in recommended_majors)
            if any(kw in major_text for kw in _EXPENSIVE_MAJOR_KEYWORDS):
                issues.append(
                    '⚠️ 软件/集成电路类专业部分院校采用"分阶段收费"（前2年公办标准、'
                    '后2年涨至1.6万+/年），请查阅招生章程"学费收取办法"条款'
                )

            # 6. 异地校区检查（区别于本部，学籍/师资/毕业证可能不同）
            _REMOTE_CAMPUS_TOKENS = ('威海', '珠海', '深圳', '苏州', '青岛', '无锡', '北戴河', '荣成', '海宁', '宁波')
            school_full = rec.school_name
            has_campus_suffix = '(' in school_full or '（' in school_full
            if has_campus_suffix and any(tok in school_full for tok in _REMOTE_CAMPUS_TOKENS):
                issues.append(
                    '⚠️ 异地校区：与本部存在管理、师资、毕业证标注差异，'
                    '请核查《招生章程》校区说明及毕业证书是否标注校区名称'
                )

            if issues:
                rec.extra_reasons = getattr(rec, 'extra_reasons', []) + issues
                rec.safety_warning = issues
                unsafe_list.append(rec)
            else:
                safe_list.append(rec)

        # 确保至少5所安全兜底
        if len(safe_list) < 5 and unsafe_list:
            # 不足5所时，从unsafe中取问题最少的补齐
            unsafe_list.sort(key=lambda x: len(x.safety_warning))
            needed = 5 - len(safe_list)
            safe_list.extend(unsafe_list[:needed])
            unsafe_list = unsafe_list[needed:]

        return safe_list, unsafe_list

    def _get_enrollment_plan(self, school_name: str, subject_type: str = None) -> Optional[int]:
        """获取学校在某科类的招生计划人数

        实测 enroll_plan_2025 字段：category('物理类'/'历史类') + num（不是 subject_type/enroll_count）
        """
        try:
            cursor = self._get_cursor()
            # 科类映射到 DB 实际取值：物理类 / 历史类
            if subject_type in ('物理', '物理类', '理科'):
                cat = '物理类'
            elif subject_type in ('历史', '历史类', '文科'):
                cat = '历史类'
            else:
                cat = None

            if cat:
                cursor.execute(
                    f'SELECT SUM(num) FROM enroll_plan_{CURRENT_PLAN_YEAR}'
                    ' WHERE school_name=? AND category=?',
                    (school_name, cat),
                )
            else:
                cursor.execute(
                    f'SELECT SUM(num) FROM enroll_plan_{CURRENT_PLAN_YEAR}'
                    ' WHERE school_name=?',
                    (school_name,),
                )
            row = cursor.fetchone()
            if row and row[0]:
                return int(row[0])
        except Exception:
            pass
        return None

    def _is_catch_cutoff(self, school_name: str, user_rank: int,
                         subject_type: str = None) -> bool:
        """检查上一年是否断档（录取位次相比往年异常低，波动>50%）

        AUDIT-P1-009: 必须按 subject_type 过滤，否则用对方科类的位次比对，
        会得出错误的"断档"标记，影响兜底志愿的安全警告。
        """
        try:
            cursor = self._get_cursor()
            # 历史 enroll_school_ext 无 year/min_rank/school_name 列，改用 v_enroll_detail 聚合
            base = '''
                SELECT year, MIN(min_rank) AS min_rank FROM v_enroll_detail
                WHERE school_name=? AND year IN (2024, 2023) AND min_rank IS NOT NULL
            '''
            params: list = [school_name]
            if subject_type:
                subj_clause, subj_params = self._subject_type_in_clause(subject_type)
                base += subj_clause
                params.extend(subj_params)
            base += ' GROUP BY year ORDER BY year DESC'
            cursor.execute(base, tuple(params))
            rows = cursor.fetchall()
            if len(rows) >= 2:
                recent_rank = rows[0][1]  # 2024年最低位次
                prev_rank = rows[1][1]    # 2023年最低位次
                if recent_rank and prev_rank and prev_rank > 0:
                    # 位次上升幅度>50%视为断档（位次值越小越好，变大=录取分降低）
                    ratio = recent_rank / prev_rank if prev_rank > 0 else 1
                    if ratio > 1.5:  # 位次要求降低50%以上
                        return True
        except Exception:
            pass
        return False

    def _is_joint_venture(self, school_name: str) -> bool:
        """检查是否为中外合作办学"""
        try:
            cursor = self._get_cursor()
            cursor.execute('''
                SELECT school_type FROM school_info WHERE school_name=? LIMIT 1
            ''', (school_name,))
            row = cursor.fetchone()
            if row and row[0] and '中外合作' in row[0]:
                return True
        except Exception:
            pass
        return False

    def _is_local_province(self, school_name: str, user_profile: UserProfile) -> bool:
        """检查是否为考生本省高校（云南）"""
        try:
            cursor = self._get_cursor()
            cursor.execute('''
                SELECT province_full FROM school_info WHERE school_name=? LIMIT 1
            ''', (school_name,))
            row = cursor.fetchone()
            if row and row[0] and '云南' in row[0]:
                return True
        except Exception:
            pass
        return False

    # ============================================================
    # 新方法：按批次生成完整方案
    # ============================================================

    def _get_batch_configs(self, user_profile: UserProfile) -> Dict[str, BatchConfig]:
        """根据考生信息获取适用的批次配置

        各批次入选/排除逻辑：
        - 提前本科批A段: 需wants_teacher_directed=True（自愿从教+接受定向）
        - 提前本科批B段: 需wants_military或wants_police=True（已参加/计划参加军检/警考）
        - 提前本科批C段: 需wants_flying/wants_fire/wants_navy=True（已参加/计划参加招飞体检等）
        - 提前本科批D段: 默认包含（公费师范生/马理论/港澳，无特殊门坎）
        - 本科批A段: 需has_university_special=True（农村户籍+实施区域+连续3年，已审核）
        - 本科批B段: 默认包含（普通本科）；专项附加志愿由has_national/has_local控制
        - 提前专科批A段: 需wants_special_directed=True（户籍定向要求）
        - 提前专科批B段: 需wants_military_nco=True（已参加/计划参加定向军士政考体检）
        - 高职专科批: 默认包含（无特殊条件）
        """
        if _CONFIG is not None and _CONFIG.batches:
            # 从配置加载批次
            raw = _CONFIG.batches
            batches = {k: BatchConfig(
                name=v.name, batch_key=v.batch_key,
                volunteer_count=v.volunteer_count, method=v.method,
                section=v.section, batch_type=v.batch_type or v.batch_key,
                chong_ratio=v.chong_ratio, wen_ratio=v.wen_ratio,
                bao_ratio=v.bao_ratio,
                chong_prob_range=tuple(v.chong_prob_range),
                wen_prob_range=tuple(v.wen_prob_range),
                bao_prob_range=tuple(v.bao_prob_range),
                requires_special=v.requires_special,
                eligible_condition=v.eligible_condition,
            ) for k, v in raw.items()}
        elif user_profile.is_new_gaokao:
            batches = {k: replace(v) for k, v in _BATCH_FALLBACK_NEW.items()}
        else:
            batches = {k: replace(v) for k, v in _BATCH_FALLBACK_OLD.items()}

        # 调整本科B段志愿数（有专项/预科资格可增加）
        if '本科批B段' in batches:
            extra = 0
            if user_profile.has_national_special or user_profile.has_local_special:
                extra += 10
            if user_profile.has_minority_prep:
                extra += 10
            if extra > 0:
                cfg = batches['本科批B段']
                cfg.volunteer_count = 40 + extra

        if not user_profile.is_new_gaokao:
            return batches  # 旧高考不需要复杂过滤

        # --- 以下仅新高考 ---

        # 提前批：根据用户是否考虑各方向动态过滤
        if user_profile.include_early_batch:
            # A段: 优师专项/免费定向 → 自愿从教
            if '提前本科批A段' in batches and not user_profile.wants_teacher_directed:
                del batches['提前本科批A段']
            # B段: 军队/公安 → 已参加军检/警考
            if '提前本科批B段' in batches:
                if not (user_profile.wants_military or user_profile.wants_police):
                    del batches['提前本科批B段']
            # C段: 招飞/消防/航海 → 已参加相应检查
            if '提前本科批C段' in batches:
                if not (user_profile.wants_flying or user_profile.wants_fire or user_profile.wants_navy):
                    del batches['提前本科批C段']
            # D段: 公费师范生/马理论/港澳 → 默认包含（无特殊门坎）
            # 提前专科A段: 定向 → 户籍定向要求
            if '提前专科批A段' in batches and not user_profile.wants_special_directed:
                del batches['提前专科批A段']
            # 提前专科B段: 定向军士 → 已参加军士政考体检
            if '提前专科批B段' in batches and not user_profile.wants_military_nco:
                del batches['提前专科批B段']
        else:
            # 完全排除提前批
            for key in list(batches.keys()):
                if batches[key].batch_type in ('提前本科批', '提前高职专科批'):
                    del batches[key]

        # 高校专项需要资格（农村户籍+实施区域+连续3年）
        if '本科批A段' in batches and not user_profile.has_university_special:
            del batches['本科批A段']

        # 排除用户指定排除的批次
        for excluded in user_profile.excluded_batches:
            if excluded in batches:
                del batches[excluded]

        return batches

    def _fill_batch(self, batch_cfg: BatchConfig, user_rank: int,
                    all_chong: List[Recommendation],
                    all_wen: List[Recommendation],
                    all_bao: List[Recommendation],
                    risk_tolerance: str,
                    all_batches: Dict[str, BatchConfig] = None) -> List[Recommendation]:
        """
        按批次配置填充冲稳保学校

        改进策略（按比例分配）：
        - 根据该批次志愿数占总志愿数的比例，按比例分配冲/稳/保
        - 避免前序批次耗尽所有名额
        """
        result = []

        # 计算各批次志愿数比例
        if all_batches:
            total_slots = sum(
                b.volunteer_count for b in all_batches.values()
            )
            batch_ratio = max(0.05, batch_cfg.volunteer_count / total_slots)

            # 按比例从各池分配
            n_chong_pool = max(1, int(len(all_chong) * batch_ratio))
            n_wen_pool = max(1, int(len(all_wen) * batch_ratio))
            n_bao_pool = max(1, int(len(all_bao) * batch_ratio))
        else:
            n_chong_pool = max(1, int(batch_cfg.volunteer_count * batch_cfg.chong_ratio))
            n_wen_pool = max(1, int(batch_cfg.volunteer_count * batch_cfg.wen_ratio))
            n_bao_pool = max(1, batch_cfg.volunteer_count - n_chong_pool - n_wen_pool)

        # 从可用池中选取
        chong_available = list(all_chong[:n_chong_pool])
        wen_available = list(all_wen[:n_wen_pool])
        bao_available = list(all_bao[:n_bao_pool])

        # 调整：如果某个档位不够，从相邻档位补充
        # 使用固定偏移量（原始池大小），避免动态 len() 导致索引断片
        orig_wen_len = len(wen_available)
        orig_bao_len = len(bao_available)

        # 冲不足 → 从稳池补充
        if len(chong_available) < n_chong_pool:
            deficit = n_chong_pool - len(chong_available)
            # 从稳池已选部分之后的位置取（即稳池的后续学校）
            start = min(orig_wen_len, len(wen_available))
            take = min(deficit, max(0, len(all_wen) - start))
            for r in all_wen[start:start + take]:
                r.category = '冲'
                chong_available.append(r)

        # 稳不足 → 从冲池剩余 + 保池补充
        if len(wen_available) < n_wen_pool:
            deficit = n_wen_pool - len(wen_available)
            taken_from_chong = 0
            # 从冲池剩余部分取（冲池前 n_chong_pool 已用，取后面的）
            chong_start = n_chong_pool
            chong_end = min(chong_start + deficit, len(all_chong))
            if chong_end > chong_start:
                for r in all_chong[chong_start:chong_end]:
                    r.category = '稳'
                    wen_available.append(r)
                taken_from_chong = chong_end - chong_start
            # 还不足则从保池补
            if len(wen_available) < n_wen_pool:
                deficit2 = n_wen_pool - len(wen_available)
                take = min(deficit2, orig_bao_len)
                # 从保池已有部分的后续取
                bao_start = min(orig_bao_len, len(bao_available))
                # 直接用 all_bao 中未用的部分
                for r in all_bao[bao_start:bao_start + take]:
                    r.category = '稳'
                    wen_available.append(r)

        # 保不足 → 从稳池补充
        if len(bao_available) < n_bao_pool:
            deficit = n_bao_pool - len(bao_available)
            # 从稳池已选部分之后取
            start = min(orig_wen_len, len(wen_available))
            # 需要重新看 all_wen 中尚未被分配到稳池的
            take = min(deficit, max(0, len(all_wen) - start))
            for r in all_wen[start:start + take]:
                r.category = '保'
                bao_available.append(r)

        # 取数
        result.extend(chong_available)
        result.extend(wen_available)
        result.extend(bao_available)

        # 标注批次
        for r in result:
            r.batch_key = batch_cfg.batch_key

        return result

    def generate_plan(self, user_profile: UserProfile, top_n: int = 30,
                      use_batch_mode: bool = False) -> Dict:
        """
        生成志愿推荐方案

        参数:
            user_profile: 用户画像
            top_n: 旧模式推荐数量（兼容参数，batch_mode=True时忽略）
            use_batch_mode: 是否使用批次模式（新结构）

        返回:
            旧模式: {'冲': [...], '稳': [...], '保': [...], 'total': N}
            批次模式: {
                'user': {...},
                'batches': {
                    '本科批B段': {'config': {...}, 'chong': [...], 'wen': [...], 'bao': [...]},
                    ...
                },
                'total_volunteers': N,
            }
        """
        # 安全检查
        if top_n > 200:
            top_n = 200

        subject_type = user_profile.subject_type
        target_major = user_profile.preferred_majors[0] if user_profile.preferred_majors else None
        user_subjects = user_profile.selected_subjects if user_profile.is_new_gaokao else None

        # 第一步：筛选候选池
        exclude_early = not user_profile.include_early_batch
        if target_major:
            candidates = self.filter_candidates_with_major(
                user_profile.rank, target_major, subject_type=subject_type,
                rank_tolerance=0.40, user_subjects=user_subjects,
                exclude_early_batches=exclude_early,
            )
        else:
            candidates = self.filter_candidates(user_profile.rank, tolerance=0.30,
                                                subject_type=subject_type,
                                                user_subjects=user_subjects,
                                                exclude_early_batches=exclude_early)

        if not candidates:
            empty_plan = {'冲': [], '稳': [], '保': [],
                          'message': '未找到匹配的院校，请调整位次或容忍度'}
            if use_batch_mode:
                empty_plan['batches'] = {}
            return empty_plan

        # 第二步：计算概率并分类（统一走 STRATEGY_CONFIGS，保档下限严格 ≥85%）
        score_segment = get_score_segment(user_profile.score, user_profile.category)
        config = STRATEGY_CONFIGS.get(user_profile.risk_tolerance, STRATEGY_CONFIGS['balanced'])
        prob_ranges = config
        # 运行时检查：保档下限必须 ≥85%（python -O 不跳过）
        bao_min = prob_ranges['bao_prob_range'][0]
        if bao_min < 85:
            import logging
            logging.error(
                f'[P1] generate_plan 保档下限 {bao_min} < 85，自动修正为85'
            )
            prob_ranges = dict(prob_ranges)
            prob_ranges['bao_prob_range'] = (85, prob_ranges['bao_prob_range'][1])

        chong_list, wen_list, bao_list = self.classify_schools(
            candidates, user_profile.rank, prob_ranges,
            subject_type=subject_type, target_major=target_major,
            score_segment=score_segment,
        )

        # 第三步：应用偏好过滤
        chong_list = self.apply_preferences(chong_list, user_profile)
        wen_list = self.apply_preferences(wen_list, user_profile)
        bao_list = self.apply_preferences(bao_list, user_profile)

        # 第四步：专业优先排序
        if target_major:
            # AUDIT-P1-008: 传入科类避免跨科类专业被误匹配
            _st = getattr(user_profile, 'subject_type', None)
            chong_list = self._prioritize_major_matches(chong_list, target_major, subject_type=_st)
            wen_list = self._prioritize_major_matches(wen_list, target_major, subject_type=_st)
            bao_list = self._prioritize_major_matches(bao_list, target_major, subject_type=_st)

        # 第五步：输出
        if use_batch_mode:
            return self._generate_batch_plan(
                user_profile, chong_list, wen_list, bao_list, target_major
            )
        else:
            return self._generate_legacy_plan(
                user_profile, top_n, chong_list, wen_list, bao_list, target_major
            )

    def _generate_batch_plan(self, user_profile: UserProfile,
                             chong_list: List[Recommendation],
                             wen_list: List[Recommendation],
                             bao_list: List[Recommendation],
                             target_major: str = None) -> Dict:
        """按批次生成完整方案（新结构）"""
        batch_configs = self._get_batch_configs(user_profile)
        batches = {}
        total_volunteers = 0

        # 跨批次去重：同一院校专业组只能出现在一个批次中
        assigned_keys = set()

        # 按录取顺序处理批次（先录取的批次先分配学校）
        sorted_batch_keys = sorted(
            batch_configs.keys(),
            key=lambda k: BATCH_ADMISSION_ORDER.index(k)
            if k in BATCH_ADMISSION_ORDER else 999
        )

        for batch_key in sorted_batch_keys:
            cfg = batch_configs[batch_key]

            # 过滤掉已分配的院校专业组
            def _group_key(s):
                return (s.school_name, s.group_code) if s.group_code else (s.school_name, '')

            available_chong = [s for s in chong_list
                               if _group_key(s) not in assigned_keys]
            available_wen = [s for s in wen_list
                             if _group_key(s) not in assigned_keys]
            available_bao = [s for s in bao_list
                             if _group_key(s) not in assigned_keys]

            schools = self._fill_batch(
                cfg, user_profile.rank, available_chong, available_wen, available_bao,
                user_profile.risk_tolerance,
                all_batches=batch_configs,
            )

            # 记录已分配的院校专业组
            for s in schools:
                assigned_keys.add(_group_key(s))

            # 专业优先：有目标专业时，把含目标专业的学校排在前面
            if target_major:
                # AUDIT-P1-008: 传入科类避免跨科类专业被误匹配
                schools = self._prioritize_major_matches(
                    schools, target_major,
                    subject_type=getattr(user_profile, 'subject_type', None),
                )

            # 按概率排序（冲档从低到高，稳档从高到低，保档从高到低）
            chong = sorted([s for s in schools if s.category == '冲'],
                           key=lambda x: x.probability)
            wen = sorted([s for s in schools if s.category == '稳'],
                         key=lambda x: x.probability, reverse=True)
            bao = sorted([s for s in schools if s.category == '保'],
                         key=lambda x: x.probability, reverse=True)

            batch_data = {
                'name': cfg.name,
                'batch_type': cfg.batch_type,
                'section': cfg.section,
                'method': cfg.method,
                'volunteer_count': cfg.volunteer_count,
                'chong': [self._format_recommendation(s) for s in chong],
                'wen': [self._format_recommendation(s) for s in wen],
                'bao': [self._format_recommendation(s) for s in bao],
                'chong_count': len(chong),
                'wen_count': len(wen),
                'bao_count': len(bao),
            }
            # 中文键别名（报告渲染用）
            cat_chinese_map = {
                'chong': '冲', 'wen': '稳', 'bao': '保',
                'chong_count': '冲_count', 'wen_count': '稳_count', 'bao_count': '保_count',
            }
            for pinyin_key, chinese_key in cat_chinese_map.items():
                batch_data[chinese_key] = batch_data[pinyin_key]
            batch_data['total'] = batch_data['chong_count'] + batch_data['wen_count'] + batch_data['bao_count']

            batches[batch_key] = batch_data
            total_volunteers += len(schools)

        active_batch_keys = list(batch_configs.keys())
        conflicts = user_profile.check_batch_conflicts(active_batch_keys)

        return {
            'user': {
                'name': '',
                'score': user_profile.score,
                'rank': user_profile.rank,
                'category': user_profile.category,
                'risk_tolerance': user_profile.risk_tolerance,
                'is_new_gaokao': user_profile.is_new_gaokao,
            },
            'batches': batches,
            'total_volunteers': total_volunteers,
            'batch_summary': {
                k: {
                    'chong': v['chong_count'],
                    'wen': v['wen_count'],
                    'bao': v['bao_count'],
                    '总': v['total'],
                    '冲': v['chong_count'],
                    '稳': v['wen_count'],
                    '保': v['bao_count'],
                    'total': v['chong_count'] + v['wen_count'] + v['bao_count'],
                }
                for k, v in batches.items()
            },
            'admission_order': BATCH_ADMISSION_ORDER,
            'batch_exclusions': {
                'hard': [
                    {'batch_a': c['batch_a'], 'batch_b': c['batch_b'],
                     'reason': c['reason'], 'suggestion': c['suggestion']}
                    for c in conflicts if c['type'] == '硬性互斥'
                ],
                'soft': [
                    {'batch_a': c['batch_a'], 'batch_b': c['batch_b'],
                     'reason': c['reason'], 'suggestion': c['suggestion'],
                     'admission_note': c.get('admission_note', '')}
                    for c in conflicts if c['type'] == '顺序排他'
                ],
                'admission_sequence_note': (
                    next(
                        (c['reason'] for c in conflicts if c['type'] == '录取顺序'),
                        ''
                    )
                ),
                'filling_order_suggestion': (
                    next(
                        (c['suggestion'] for c in conflicts if c['type'] == '录取顺序'),
                        ''
                    )
                ),
            } if conflicts else None,
        }

    def _generate_legacy_plan(self, user_profile: UserProfile,
                              top_n: int,
                              chong_list: List[Recommendation],
                              wen_list: List[Recommendation],
                              bao_list: List[Recommendation],
                              target_major: str = None) -> Dict:
        """旧模式生成方案（保持向后兼容）"""
        config = STRATEGY_CONFIGS.get(user_profile.risk_tolerance, STRATEGY_CONFIGS['balanced'])

        n_chong = int(top_n * config['chong_ratio'])
        n_wen = int(top_n * config['wen_ratio'])
        n_bao = top_n - n_chong - n_wen

        # 冲档：概率从低到高（先录取的排前面）
        chong_list = sorted(chong_list, key=lambda x: x.probability)[:n_chong]

        # 稳档：按概率从高到低（安全的稳档优先）
        wen_list = sorted(wen_list, key=lambda x: x.probability, reverse=True)[:n_wen]

        # 保档：概率从高到低（最安全的排前面）
        bao_list = sorted(bao_list, key=lambda x: x.probability, reverse=True)[:n_bao]

        # 档位不足时从相邻档补充
        # 保不足 → 仅从高概率稳档补充（≥保档下限），否则留空
        if len(bao_list) < n_bao and wen_list:
            bao_min_threshold = config['bao_prob_range'][0]
            wen_high = [s for s in wen_list if s.probability >= bao_min_threshold]
            wen_high.sort(key=lambda x: x.probability, reverse=True)
            for s in wen_high:
                if len(bao_list) >= n_bao:
                    break
                s.category = '保'
                bao_list.append(s)
            wen_list = [s for s in wen_list if s not in bao_list]
            # 补满n_wen
            remaining = sorted(wen_list, key=lambda x: x.probability, reverse=True)
            wen_list = remaining[:n_wen]

        # 冲不足 → 从高概率冲档不足的稳档补充
        if len(chong_list) < n_chong and wen_list:
            wen_extra = sorted(wen_list, key=lambda x: x.probability)
            for s in wen_extra:
                if len(chong_list) >= n_chong:
                    break
                s.category = '冲'
                chong_list.append(s)
            wen_list = [s for s in wen_list if s not in chong_list]

        return {
            '冲': [self._format_recommendation(r) for r in chong_list],
            '稳': [self._format_recommendation(r) for r in wen_list],
            '保': [self._format_recommendation(r) for r in bao_list],
            'strategy': user_profile.risk_tolerance,
            'total': len(chong_list) + len(wen_list) + len(bao_list),
        }

    # ============================================================
    # 辅助方法
    # ============================================================

    def _major_matches(self, major_name: str, target: str) -> bool:
        """判断专业名是否匹配目标专业"""
        if not major_name or not target:
            return False
        m = major_name.lower().replace(' ', '').replace('·', '')
        t = target.lower().replace(' ', '').replace('·', '')
        if m == t:
            return True
        if t in m or m in t:
            return True
        for suffix in ('类', '方向', '专业', '班'):
            kt = t.rstrip(suffix)
            if len(kt) >= 2 and kt in m:
                return True
        return False

    def _get_major_aliases(self, target: str) -> List[str]:
        """获取目标专业的别名列表"""
        aliases = [target]
        t = target.replace(' ', '')

        major_suffixes = ('工程', '学', '类', '方向', '专业', '班')
        for suffix in major_suffixes:
            if t.endswith(suffix):
                base = t[:-len(suffix)]
                if len(base) >= 2:
                    aliases.append(base)
                    aliases.append(base + '类')

        filler_patterns = ('科学与技术', '及科学', '与科学')
        for pat in filler_patterns:
            if pat in t:
                keyword = t.split(pat)[0]
                if len(keyword) >= 2:
                    aliases.append(keyword)
                    aliases.append(keyword + '类')

        return list(dict.fromkeys(aliases))

    def _prioritize_major_matches(self, schools: List[Recommendation],
                                   target_major: str,
                                   subject_type: str = None) -> List[Recommendation]:
        """优先保留提供目标专业的学校（单次 SQL 批量查询替代 N*M 逐条查询）

        AUDIT-P1-008: 目标专业匹配必须按 subject_type 过滤，
        避免另一科类的"同名专业"被错误识别为匹配。
        """
        aliases = self._get_major_aliases(target_major)
        if not schools or not aliases:
            unmatched = sorted(schools, key=lambda x: x.probability, reverse=True)
            return unmatched

        # AUDIT-P1-008: 科类过滤子句
        subject_clause, subject_params = self._subject_type_in_clause(subject_type) if subject_type else ("", ())

        # 分块执行：学校名数量受 SQLite 变量上限约束
        school_names = [s.school_name for s in schools]
        max_vars = 32000 // max(len(aliases), 1)
        chunk_size = min(max_vars, len(school_names), 900)

        matched_names = set()
        for i in range(0, len(school_names), chunk_size):
            chunk = school_names[i:i + chunk_size]
            placeholders = ','.join('?' * len(chunk))
            alias_clause = ' OR '.join('major_name LIKE ?' for _ in aliases)
            query = f'''
                SELECT DISTINCT school_name FROM v_enroll_detail
                WHERE min_rank IS NOT NULL AND school_name IN ({placeholders})
                  AND ({alias_clause}) {subject_clause}
            '''
            params = list(chunk)
            for alias in aliases:
                params.append(f'%{alias}%')
            params.extend(subject_params)
            self._get_cursor().execute(query, params)
            for row in self._get_cursor().fetchall():
                matched_names.add(row[0])

        matched = [s for s in schools if s.school_name in matched_names]
        unmatched = [s for s in schools if s.school_name not in matched_names]

        matched.sort(key=lambda x: x.probability, reverse=True)
        unmatched.sort(key=lambda x: x.probability, reverse=True)
        return matched + unmatched

    def _format_recommendation(self, rec: Recommendation) -> Dict:
        """格式化推荐结果"""
        return {
            'school_name': rec.school_name,
            'category': rec.category,
            'probability': f"{rec.probability:.1f}%",
            'probability_raw': rec.probability,
            'confidence': rec.confidence,
            'predicted_rank': rec.predicted_rank,
            'school_quality': rec.school_quality,
            'tier_level': rec.school_tier,
            'tier_name': rec.tier_label,
            'location': rec.location,
            'tuition': f"¥{rec.tuition:.0f}/年" if rec.tuition > 0 else '未知',
            'reasons': rec.reasons,
            'batch_key': rec.batch_key,
            'school_type': self._detect_school_type(rec.school_name),
        }

    @staticmethod
    def _detect_school_type(school_name: str) -> str:
        """检测学校类型标签（本部/分校/中外合作）"""
        is_campus = any(kw in school_name for kw in [
            '威海', '宁波', '香港理工', '深圳', '苏州',
            '昆山', '杜克', '西浦', '北理珠', '西交利物浦',
        ])
        return '分校' if is_campus else '本部'

    def generate_collection_plan(self, user_profile: UserProfile,
                                  top_n: int = 20) -> Dict:
        """
        征集志愿补录模式（保底优先 + 3方案并行）

        适用场景：正常录取后未进入任何推荐院校，进入征集志愿阶段。

        返回:
            {
                'mode': 'collection',
                'conservative': {...},  # 保守方案（概率>85%）
                'balanced': {...},      # 均衡方案（概率70-85%）
                'aggressive': {...},    # 激进方案（概率50-75%）
            }
        """
        results = {}

        # 三套方案：不同概率区间
        configs = [
            ('conservative', '保守方案', 85, 100, '只选保底校，求稳'),
            ('balanced', '均衡方案', 70, 85, '兼顾稳妥和冲一下'),
            ('aggressive', '激进方案', 50, 75, '争取更好学校'),
        ]

        for key, label, prob_min, prob_max, desc in configs:
            # 使用不同容忍度重新筛选
            tolerance = {
                'conservative': 0.15,  # 保守：小范围
                'balanced': 0.25,      # 均衡：标准范围
                'aggressive': 0.40,    # 激进：大范围
            }[key]

            candidates = self.filter_candidates(
                user_profile.rank, tolerance=tolerance,
                subject_type=user_profile.subject_type,
                user_subjects=(user_profile.selected_subjects
                               if user_profile.is_new_gaokao else None),
            )

            schools = []
            for school in candidates[:top_n * 2]:
                prob = self._get_probability(
                    user_profile.rank, school,
                    subject_type=user_profile.subject_type,
                )
                if prob and prob_min <= prob.probability <= prob_max:
                    rec = Recommendation(
                        school_name=school,
                        probability=prob.probability,
                        confidence=prob.confidence,
                        predicted_rank=prob.predicted_rank,
                        school_quality='',
                        location='',
                        tuition=0,
                        reasons=prob.reasons,
                        batch_key='征集志愿',
                    )
                    schools.append(rec)

            schools.sort(key=lambda r: r.probability, reverse=True)
            schools = schools[:top_n]

            results[key] = {
                'label': label,
                'description': desc,
                'probability_range': f'{prob_min}-{prob_max}%',
                'school_count': len(schools),
                'schools': [self._format_recommendation(s) for s in schools],
            }

        # 方案对比
        comparison = []
        for key in ['conservative', 'balanced', 'aggressive']:
            r = results[key]
            comparison.append({
                '方案': r['label'],
                '概率区间': r['probability_range'],
                '学校数': r['school_count'],
                '说明': r['description'],
            })

        return {
            'mode': 'collection',
            'conservative': results['conservative'],
            'balanced': results['balanced'],
            'aggressive': results['aggressive'],
            'comparison': comparison,
            'note': '征集志愿补录模式，建议优先采用均衡方案。',
        }

    def close(self):
        self.prob_calculator.close()
        if hasattr(self._local, 'cursor'):
            try:
                self._local.cursor.connection.close()
            except Exception:
                pass


def main():
    """测试用例"""
    recommender = VolunteerRecommender()

    print('=' * 70)
    print('志愿推荐引擎测试 — 新旧高考双模式')
    print('=' * 70)

    # 测试1：旧高考模式
    print('\n【测试1】旧高考模式（2024年，理科，rank=15000）')
    user1 = UserProfile(
        score=580, rank=15000, category='理科', gaokao_year=2024,
        preferred_cities=['昆明', '成都', '重庆'],
        risk_tolerance='balanced',
    )
    plan1 = recommender.generate_plan(user1, top_n=30)
    print(f'  冲: {len(plan1["冲"])}所 | 稳: {len(plan1["稳"])}所 | 保: {len(plan1["保"])}所 | 共: {plan1["total"]}所')
    for cat in ['冲', '稳', '保']:
        schools = plan1[cat][:3]
        for i, s in enumerate(schools, 1):
            print(f'    {i}. {s["school_name"]} ({s["probability"]})')

    # 测试2：新高考模式（批次输出）
    print('\n【测试2】新高考批次模式（2026年，物理类，rank=15000）')
    user2 = UserProfile(
        score=580, rank=15000, category='物理类', gaokao_year=2026,
        preferred_cities=['昆明', '成都', '重庆'],
        risk_tolerance='balanced',
    )
    plan2 = recommender.generate_plan(user2, use_batch_mode=True)
    print(f'  总志愿数: {plan2["total_volunteers"]}')
    for batch_key, batch_data in plan2['batches'].items():
        print(f'\n  【{batch_data["name"]}】 ({batch_data["method"]}, 最多{batch_data["volunteer_count"]}个)')
        print(f'    冲: {batch_data["chong_count"]}所 | 稳: {batch_data["wen_count"]}所 | 保: {batch_data["bao_count"]}所')
        for cat in ['chong', 'wen', 'bao']:
            schools = batch_data[cat][:3]
            label = {'chong': '冲', 'wen': '稳', 'bao': '保'}[cat]
            for i, s in enumerate(schools, 1):
                print(f'      {i}. {s["school_name"]} ({s["probability"]})')

    recommender.close()
    print('\n' + '=' * 70)
    print('测试完成！')

if __name__ == '__main__':
    main()
