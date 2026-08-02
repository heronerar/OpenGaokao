# OpenGaokao 数据接入指南

> 本指南面向**想将 OpenGaokao 适配到你所在省份的开发者**。
> 读完本文后，你应该能：理解引擎需要哪些数据、从何获取、如何清洗对齐、如何校验正确性。

---

## 一、数据总览

推荐引擎的完整路径使用 **8 张数据表 + 1 份配置**：

| # | 表名 | 用途 | 核心程度 |
|---|------|------|---------|
| 1 | `score_line_{year}` | 当年投档线（院校+专业组） | ⭐ 必填 |
| 2 | `enroll_detail` | 历史录取明细（多年，算概率用） | ⭐ 必填 |
| 3 | `enroll_plan_{year}` | 当年招生计划 | ⭐ 必填 |
| 4 | `school_info` | 院校属性（985/211/博士点等） | ⭐ 必填 |
| 5 | `major_catalog` | 专业目录（专业→专业类映射） | ⭐ 必填 |
| 6 | `score_distribution` | 一分一段表（位次换算） | ✅ 推荐 |
| 7 | `major_employment_stats` | 专业就业统计（排序用） | 🔵 可选 |
| 8 | `major_revocation_stats` | 专业点撤销趋势（方向参考） | 🔵 可选 |
| 9 | `province.yaml` | 省份配置（批次/分数线/阈值） | ⭐ 必填 |

完整引用映射见文末附录。

---

## 二、分表说明

### 2.1 score_line_{year} — 当年投档线

**引擎核心数据**。用来判断考生位次能否达到某校某专业组的最低要求。按年分表，年份由 `province.yaml` 的 `years.score_line` 指定。

新高考（3+1+2, 院校专业组模式，8 列）：

```sql
CREATE TABLE score_line_2025 (
    school_name   TEXT,    -- 院校名称（必须与 school_info.school_name 一致）
    group_code    TEXT,    -- 专业组代码（如 '01', '02'）
    subject_type  TEXT,    -- 科类：'物理'/'历史'/'理科'/'文科'/'不限'
    subject_req   TEXT,    -- 选科要求：'物理+化学'/'物理'/'不限'/...
    min_score     INTEGER, -- 最低录取分
    min_rank      INTEGER, -- 最低录取位次（核心字段！）
    batch         TEXT,    -- 批次名称（必须与 province.yaml batches 的 key 一致）
    enroll_count  INTEGER  -- 录取人数
);
```

旧高考（文理分科，5 列）：

```sql
CREATE TABLE score_line_2024 (
    school_name     TEXT,   -- 院校名称
    subject_type    TEXT,   -- '理科'/'文科'
    min_score_orig  INTEGER,-- 原始最低分
    min_rank        INTEGER,-- 最低录取位次
    batch           TEXT    -- '一本'/'二本'/'专科'
);
```

**数据来源**：各省教育考试院公布的"普通高校招生投档线"（通常在每年 7 月发布）。
**关键列**：`min_rank` — 位次是核心匹配依据，分数只是参考。

---

### 2.2 enroll_detail — 历史录取明细

**概率计算核心**。`AdmissionProbability.calculate()` 基于多年数据拟合概率曲线。通过视图 `v_enroll_detail` 访问。

```sql
CREATE TABLE enroll_detail (
    year          INTEGER, -- 录取年份（2023/2024/2025...）
    school_name   TEXT,    -- 院校名称
    major_name    TEXT,    -- 专业名称（必须与 major_catalog.major_name 一致）
    subject_type  TEXT,    -- 科类：'物理'/'历史'/'理科'/'文科'
    min_score     INTEGER, -- 最低录取分
    min_rank      INTEGER, -- 最低录取位次
    enroll_count  INTEGER, -- 录取人数
    batch         TEXT,    -- 批次（如 '本科批B段'/'一本'/'二本'）
    batch_tier    TEXT,    -- 批次层级（'本科'/'专科'）
    tuition       INTEGER  -- 学费（元/年）
);

-- 引擎通过此视图访问：不要删除此视图
CREATE VIEW v_enroll_detail AS SELECT * FROM enroll_detail;
```

> ⚠️ **注意**：引擎通过 `v_enroll_detail` 视图查询，因此必须创建此视图。
> 要保证该视图存在。如果需要修改行为，可考虑使用同名的表来替代视图。

**数据来源**：各省教育考试院每年发布的"普通高校招生录取情况统计"。
**建议数据量**：每校每年 3-10 条专业记录，至少 2-3 年历史数据。

---

### 2.3 enroll_plan_{year} — 当年招生计划

**批次过滤和兜底逻辑**。年份由 `province.yaml` 的 `years.plan` 指定。

```sql
CREATE TABLE enroll_plan_2025 (
    school_name   TEXT,   -- 院校名称
    category      TEXT,   -- 科类：'物理类'/'历史类'（新高考）'理科'/'文科'（旧高考）
    sp_name       TEXT,   -- 招生专业名称
    subject_group TEXT,   -- 专业组名称（如 '01专业组'）
    subject_req   TEXT,   -- 选科要求：'物理+化学'/'物理'/'不限'
    batch         TEXT,   -- 批次名称（必须与 province.yaml 的 batch key 一致）
    num           INTEGER -- 计划招生人数
);
```

**数据来源**：各省教育考试院发布的"普通高校招生计划"（招生计划大本 / 官方 Excel）。

---

### 2.4 school_info — 院校信息

**院校排序、兜底保护、风险判断**。

```sql
CREATE TABLE school_info (
    school_id        INTEGER, -- 学校ID（自增）
    school_name      TEXT,    -- 院校名称（关联键！其他表通过此字段引用学校）
    school_tier      TEXT,    -- 院校层级代码：'L5'/'L8'/'L12'/'L16'/'L18'
    school_tier_label TEXT,   -- 层级标签：'985'/'211'/'省重点'/'公办本科'
    is_985           INTEGER, -- 是否985（1/0）
    is_211           INTEGER, -- 是否211（1/0）
    is_syl           INTEGER, -- 是否双一流（1/0）
    num_phd          INTEGER, -- 博士点数
    num_master       INTEGER, -- 硕士点数
    syl_disciplines  TEXT,    -- 双一流学科（分号分隔）
    location         TEXT,    -- 所在地（城市名）
    province_full    TEXT,    -- 所在省份全称（如 '云南'）
    level            TEXT,    -- 办学层次（'本科'/'专科'）
    school_type      TEXT,    -- 院校类型（'综合'/'理工'/'师范'/...）
    history          TEXT     -- 建校历史（引擎未使用，保留字段）
);
```

**数据来源**：教育部全国高等学校名单 + 各校官网。
**关键字段**：`is_985` / `is_211`（用于兜底保护逻辑）、`school_tier`（用于排序）。

---

### 2.5 major_catalog — 专业目录

**选科要求映射、就业查询、专业评审**。

```sql
CREATE TABLE major_catalog (
    major_name       TEXT, -- 专业名称（关联键）
    major_class      TEXT, -- 专业类名称（如 '计算机类'/'临床医学类'）
    major_class_code TEXT, -- 专业类代码（如 '0809'/'1002'）
    schools          TEXT  -- 开设院校（引擎未使用）
);
```

**数据来源**：教育部《普通高等学校本科专业目录》。

---

### 2.6 score_distribution — 一分一段表

**位次换算**。`CURRENT_SCORE_LINE_YEAR` 的位次 → 当年排位百分比。

```sql
CREATE TABLE score_distribution (
    year              INTEGER, -- 年份
    score             INTEGER, -- 分数（从高到低）
    physics_count     INTEGER, -- 新高考：物理类该分段人数
    physics_cumsum    INTEGER, -- 新高考：物理类累计人数
    history_count     INTEGER, -- 新高考：历史类该分段人数
    history_cumsum    INTEGER, -- 新高考：历史类累计人数
    wenke_count       INTEGER, -- 旧高考：文科该分段人数
    wenke_cumsum      INTEGER, -- 旧高考：文科累计人数
    like_count        INTEGER, -- 旧高考：理科该分段人数
    like_cumsum       INTEGER  -- 旧高考：理科累计人数
);
```

**数据来源**：各省教育考试院发布的"一分一段表"。
**说明**：新旧高考兼容 10 列设计。如果只有新高考 4 列数据，将 `wenke_*` 和 `like_*` 留空即可。

---

### 2.7 major_employment_stats — 就业统计（可选）

**用于专业排序**。没有此表引擎仍然工作，但排序质量降低。

```sql
CREATE TABLE major_employment_stats (
    major_name        TEXT,  -- 专业名称
    employment_rate   REAL,  -- 就业率（0.0-1.0）
    avg_salary_monthly REAL -- 平均月薪（元）
);
```

**数据来源**：教育部就业质量报告 / 学信网 / 第三方调研。
**可选**：缺失时引擎回退为无就业排序。

---

### 2.8 major_revocation_stats — 撤销统计（可选）

**用于专业设置趋势参考**。统计专业点撤销情况，不代表考生退档记录。

```sql
CREATE TABLE major_revocation_stats (
    major_name   TEXT,    -- 专业名称
    year         INTEGER, -- 年份
    revoke_count INTEGER, -- 专业点撤销记录数
    note         TEXT     -- 备注
);
```

**可选**：缺失时对应风险项无数据。

---

## 三、配置对齐

数据表决定后，还需要一份 `provinces/{省名}/province.yaml`。关键配置字段和数据表的对齐关系：

| YAML 字段 | 对应数据表字段 | 含义 |
|-----------|--------------|------|
| `years.plan` | `enroll_plan_{plan}` 的年份 | 招生计划表年份 |
| `years.score_line` | `score_line_{score_line}` 的年份 | 投档线表年份 |
| `years.history` | `enroll_detail.year` 的年份列表 | 概率计算用几年历史 |
| `tables.score_line_prefix` | 默认 `score_line_` | 投档线表名前缀 |
| `tables.enroll_plan_prefix` | 默认 `enroll_plan_` | 招生计划表名前缀 |
| `tables.score_distribution` | 默认 `score_distribution` | 一分一段表名 |
| `thresholds.score_lines` | _不直接引用表_ | 本科线/专科线分数 |
| `batches.*.batch_key` | `score_line_{year}.batch` | 批次名称对齐 |
| `category` | `enroll_plan_{year}.category`, `score_line_{year}.subject_type` | 科类名称映射 |

⚠️ **最关键的对齐**：`province.yaml` 中 `batches` 里的 `batch_key` 必须与 `score_line_{year}.batch` 和 `enroll_plan_{year}.batch` 中的数据值完全一致。

---

## 四、接入流程

### 4.1 三步走

```
Step 1: 收集原始数据
    ↓
Step 2: 运行数据清洗工具 → 生成 SQLite
    ↓
Step 3: 编写 province.yaml → 运行 --check-data 验证
```

### 4.2 数据来源汇总

| 数据 | 官方来源 | 发布渠道 | 发布时间 |
|------|---------|---------|---------|
| 投档线 | 省教育考试院→"普通高校招生投档线" | 官网 PDF/Excel | 每年 7-8 月 |
| 录取明细 | 省教育考试院→"录取情况统计" | 官网 PDF | 每年 8-9 月 |
| 招生计划 | 省教育考试院→"普通高校招生计划" | 官网 Excel / 纸质书 | 每年 6 月 |
| 一分一段 | 省教育考试院→"成绩一分一段表" | 官网 PDF | 每年 6 月 23 日 |
| 院校信息 | 教育部→全国高等学校名单 | 官网 | 每年 6 月 |
| 专业目录 | 教育部→本科专业目录 | 官网 | 不定期 |

**典型清洗模式**：PDF → 人工校验 → CSV → `generate_{province}_db.py` → SQLite

### 4.3 两条接入路径

#### 路径 A（推荐·零 Python）：CSV → 通用导入器

把清洗好的数据按表导出为 CSV（文件名即表名，首行列名见本文各表 schema），放到一个目录，跑：

```bash
python scripts/import_province.py --province hunan --src path/to/hunan_csv/
```

导入器会：建库 → 自动重建 `v_enroll_detail` 视图 → 接 `post_import_validation` 质检（科类标签门禁 + 覆盖率，带退出码）。schema 无关（按 CSV 表头建表、按列名推断 min_rank/year 等数值列），多列少列都不丢不炸。然后只需写 `provinces/hunan/province.yaml` 即可。

> 这是"用户自助清洗数据"的官方支持路径——你不必会写 Python，把数据备成 CSV 即可。

#### 路径 B（完全可编程）：手写生成脚本

需要复杂清洗逻辑时，可参照 `data/generate_example_db.py` 的合成最小 schema：
1. 复制 `data/generate_example_db.py` → `data/generate_hunan_db.py`
2. 在本地接入你有权使用的湖南省数据（不要提交真实数据库、原始个人记录或受限文件）
3. 创建 `provinces/hunan/province.yaml`
4. 运行 `python -m gaokao.cli --province hunan --check-data`
5. 运行 `python -m gaokao.cli --province hunan --example`

---

## 五、省份适配速查表

| 高考模式 | 省份示例 | `gaokao_mode` | `volunteer_mode` | 投档线表结构 | 说明 |
|---------|---------|-------------|----------------|------------|------|
| 3+1+2 | 湖南、湖北、江苏、福建、广东、重庆、辽宁、河北 | `3+1+2` | `group` | 8列（含 group_code, subject_req） | 13省，院校专业组 |
| 3+3 | 浙江、上海、北京、天津、山东、海南 | `3+3` | `major` | 待定 | 专业类模式，需适配 |
| 文理分科 | 河南、四川、陕西、山西... | `wenli` | `old` | 5列（含 min_score_orig） | 未改革的 17 省 |

---

## 六、校验命令

### 6.1 --check-data 命令

```bash
python -m gaokao.cli --province yunnan --check-data
```

项目已内置 `--check-data` 命令，它会：

1. 检查数据库文件是否存在
2. 检查所有必需表是否存在
3. 检查每个表是否有数据（空表告警）
4. 校验 `score_line_{year}` 的科类值与 province.yaml 的 category 是否一致
5. 校验 `batch` 值与 province.yaml 的 batch key 是否匹配
6. 校验 `province.yaml` 必需字段完整性
7. 汇总报告

### 6.2 手动检测 SQL

```sql
-- 检查科类断裂（物理/历史分离）
SELECT DISTINCT subject_type FROM score_line_2025;
SELECT DISTINCT category FROM enroll_plan_2025;
SELECT DISTINCT subject_type FROM enroll_detail;

-- 检查批次名对齐
SELECT DISTINCT batch FROM score_line_2025
WHERE batch NOT IN ('本科批B段', '提前本科批A段', ...);  -- 替换为你的批次名

-- 检查院校名称一致性
SELECT DISTINCT e.school_name
FROM enroll_detail e
LEFT JOIN school_info s ON e.school_name = s.school_name
WHERE s.school_name IS NULL;

-- 检查专业名称一致性
SELECT DISTINCT e.major_name
FROM enroll_detail e
LEFT JOIN major_catalog m ON e.major_name = m.major_name
WHERE m.major_name IS NULL;
```

---

## 七、附录：SQL 引用全映射

下表记录了引擎 Python 代码中对每张表的访问模式。如果你在清洗数据时对某列的空值有疑问，可以查到它具体影响哪个功能模块。

| 表名 | 查询模式 | 引用的列 | 使用模块 | 影响的功能 |
|------|---------|---------|---------|-----------|
| `score_line_{Y}` | DISTINCT batch | school_name, batch | matching_engine | 批次过滤 |
| | WHERE subject_type IN (...) | subject_type, min_rank, enroll_count | matching_engine | 科类检查 |
| | WHERE school_name=? | school_name | matching_engine | 学校级查询 |
| | WHERE subject_req LIKE | subject_req, batch | volunteer_recommender:filter_candidates | 选科过滤 |
| `v_enroll_detail` | AVG(min_rank) | min_rank | sparse_prior | 稀疏数据校准 |
| | DISTINCT school_name, year | school_name, year | volunteer_recommender | 候选池生成 |
| | GROUP BY year, MIN(min_rank) | year, min_rank, school_name | volunteer_recommender | 概率计算 |
| | DISTINCT subject_req | subject_req | volunteer_recommender | 选科要求汇总 |
| `enroll_plan_{Y}` | SELECT sp_name WHERE school_name=? | sp_name, school_name | volunteer_recommender | 招生计划查询 |
| | SUM(num) WHERE ... | num, batch, category | volunteer_recommender | 兜底安全 |
| `school_info` | SELECT is_985, is_211 | is_985, is_211 | revocation_risk | 退档风险评估 |
| | SELECT num_phd, num_master, is_985, is_211, syl_disciplines | num_phd, num_master, is_985, is_211, syl_disciplines | matching_engine | 综合排序 |
| | SELECT school_type | school_type | volunteer_recommender | 院校分类 |
| | SELECT province_full | province_full | volunteer_recommender | 地域偏好 |
| `major_catalog` | SELECT major_name, major_class | major_name, major_class | funnel_eliminator, volunteer_recommender | 选科过滤 + 就业查询 |
| | SELECT major_class_code | major_class_code | matching_engine | 专业评审分 |
| | WHERE remark LIKE '%新增%' | major_name, remark | matching_engine | 新增专业标记 |
| `major_employment_stats` | SELECT employment_rate, avg_salary_monthly | employment_rate, avg_salary_monthly | volunteer_recommender | 专业排序 |
| `major_revocation_stats` | SELECT year, revoke_count | year, revoke_count | revocation_risk | 专业点撤销趋势参考 |
| `score_distribution` | 按年份和分数查询 | year, score, *count, *cumsum | (引擎内部位次换算) | 位次转百分比 |

---

## 八、示例：从零适配湖南省

> 这是一个假设场景，展示具体操作流程。

### 目录结构

```
provinces/hunan/
├── province.yaml           # 湖南配置
└── data/
    └── generate_hunan_db.py # 数据清洗脚本（可选）
```

### province.yaml 核心差异

```yaml
name: "湖南省"
slug: "hunan"
gaokao_mode: "3+1+2"
volunteer_mode: "group"
reform_year: 2021  # 湖南 2021 年首届新高考

years:
  plan: 2025
  score_line: 2025
  history: [2022, 2023, 2024]

# 湖南批次（2025 年）：本科批、专科提前批、高职专科批
batches:
  "本科批":
    name: "本科批（普通类）"
    batch_key: "本科批"
    volunteer_count: 45
    method: "平行志愿"
    chong_ratio: 0.20
    wen_ratio: 0.50
    bao_ratio: 0.30
    chong_prob_range: [20, 35]
    wen_prob_range: [35, 85]
    bao_prob_range: [85, 100]
  # ... 其他批次
```

### 常见问题

**Q：为什么推荐结果为空？**
A：最常见的原因是 `score_line_{year}` 中的 `batch` 值与 `province.yaml` 的 batch key 不匹配。运行 `--check-data` 即可发现。

**Q：概率算出来全是 0？**
A：通常是 `enroll_detail` 数据太少。概率计算需要某校某专业至少 2 年的历史录取位次。

**Q：旧高考（文理分科）的省份怎么配？**
A：设置 `gaokao_mode: "wenli"`, `volunteer_mode: "old"`。`score_line` 表用 5 列版本，`enroll_detail` 的 `subject_type` 用 `'理科'/'文科'`。
