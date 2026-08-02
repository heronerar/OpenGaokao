# OpenGaokao 架构文档

## 项目定位

OpenGaokao 是一个开源、透明的高考志愿推荐引擎，支持中国 3+1+2 新高考模式 21 个省份。

**核心差异化**: 每一步推荐都可溯源、可审计、可解释——与竞争对手的黑箱 LLM 方案形成鲜明对比。

## 架构总览

```
┌─────────────────────────────────────────────────────┐
│                     用户界面层                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │  CLI     │  │  Web UI  │  │  REST API│           │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘           │
│       │             │             │                  │
├───────┴─────────────┴─────────────┴──────────────────┤
│                     应用服务层                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Pipeline │  │ Consensus│  │  Risk    │           │
│  │ 审计追踪  │  │ 家庭共识   │  │ 风险评估   │           │
│  └────┬─────┘  └──────────┘  └──────────┘           │
│       │                                              │
├───────┴──────────────────────────────────────────────┤
│                     核心算法层                        │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │Matching  │  │Volunteer │  │Admission │           │
│  │ Engine   │  │Recommender│  │Probability│          │
│  ├──────────┤  ├──────────┤  ├──────────┤           │
│  │Funnel   │  │Personality│  │Intention │           │
│  │Eliminator│  │   Test   │  │Inference │           │
│  └──────────┘  └──────────┘  └──────────┘           │
│       │                                              │
├───────┴──────────────────────────────────────────────┤
│                     数据层                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ Province │  │ Question-│  │ Example  │           │
│  │ Config   │  │  naires  │  │   DB     │           │
│  └──────────┘  └──────────┘  └──────────┘           │
└──────────────────────────────────────────────────────┘
```

## 目录结构

```
OpenGaokao/
├── gaokao/
│   ├── core/           # 核心算法（17个移植模块）
│   │   ├── matching_engine.py        # 匹配引擎V3.0（入口）
│   │   ├── volunteer_recommender.py  # 志愿推荐器
│   │   ├── admission_probability.py  # 录取概率计算
│   │   ├── funnel_eliminator.py      # 漏斗排除（选科→学科→体检→兴趣）
│   │   ├── personality_test.py       # 四维偏好问卷引擎（项目自编，非心理诊断）
│   │   ├── questionnaire_parser.py   # 问卷解析器
│   │   ├── rank_converter.py         # 位次转换器
│   │   ├── intention_inference.py    # 意愿推断引擎
│   │   ├── constraint_checker.py     # 禁忌项校验
│   │   ├── revocation_risk.py        # 专业撤销风险评估
│   │   ├── industry_trends.py        # 行业趋势分析
│   │   ├── industry_strong_schools.py# 行业强校匹配
│   │   ├── hot_major_analyzer.py     # 热门专业分析
│   │   ├── sparse_prior.py           # 贝叶斯先验估计
│   │   ├── subject_normalize.py      # 科类标签标准化
│   │   ├── backtest.py               # 回测验证工具
│   │   ├── refund_engine.py          # 退费引擎（YGCare兼容存根）
│   │   ├── subject_guidance.py       # 选科指导（高一/高二）
│   │   └── family_resource.py        # 家庭资源评估
│   ├── pipeline/       # 决策管道可视化（审计追踪）
│   │   ├── audit_trail.py            # 审计数据模型
│   │   ├── pipeline_renderer.py       # HTML渲染器
│   │   └── matching_auditor.py        # 审计包装器（桥接核心算法↔审计追踪）
│   ├── risk/           # 风险评估引擎
│   │   └── risk_calculator.py        # 滑档/退档/高分低就风险
│   ├── consensus/      # 家庭共识引擎
│   │   ├── consensus_calculator.py   # 共识度算法
│   │   └── parent_survey.py          # 家长15题偏好问卷
│   ├── export/         # 报告导出
│   │   └── document_generator.py     # 简单报告生成
│   ├── config/         # 省份配置系统
│   │   └── registry.py               # 省份注册表
│   └── cli.py          # 命令行入口
├── provinces/          # 省份配置（社区可贡献）
│   ├── _template/      # 省份配置模板
│   └── yunnan/         # 云南省配置
├── questionnaires/     # 问卷定义
├── data/               # 示例数据
├── web/                # 前端界面
├── tests/              # 测试
└── docs/               # 文档
```

## 设计原则

### 1. 不重写，只包装

YGCare 的核心算法已经过验证。OpenGaokao 在核心算法外层加审计包装器，捕获中间状态。

### 2. 省份可配置

所有硬编码的省份参数（批次规则、改革年份、数据库路径）均通过 YAML 配置驱动。新增省份只需写 YAML + 准备数据。

### 3. 科类严格隔离

物理类和历史类数据在查询级别严格分离，绝不混合。2020-2024 旧高考使用"理科/文科"标签，2025+ 新高考使用"物理/历史"标签，通过 subject_normalize 统一映射。

### 4. 可审计的 7 步管道

每个推荐都经过 7 步透明的决策管道，每步的数字都有来源、排除都有原因、计算都有公式。

## 请求流程

```
1. CLI/API 接收考生信息
2. QuestionnaireParser 解析问卷 → UserQuestionnaire
3. MatchingEngine.match() 执行15步内部流程
   - 审计包装器 audit_match() 同时捕获7步中间状态
4. 输出 MatchingResult + AuditTrail
5. 可选：PipelineRenderer 渲染为 HTML
6. 可选：RiskCalculator 评估风险
7. 可选：ConsensusCalculator 计算家庭共识
```

## 关键数据流

**UserQuestionnaire** (问卷解析结果) → **UserProfile** (含位次/科类/偏好) → **MatchingResult** (含推荐列表+漏斗报告+性格结果) → **AuditTrail** (7步审计追踪)
