# OpenGaokao — 开源透明的高考志愿推荐引擎
#
# 基于 YGCare 核心算法，支持 3+1+2 新高考模式 21 省份。
# 许可证: AGPL-3.0

## 架构

```text
OpenGaokao/
├── gaokao/core/      # 核心算法（省份无关）
├── gaokao/pipeline/  # 决策管道可视化（审计追踪）
├── gaokao/consensus/ # 家庭共识引擎
├── gaokao/risk/      # 风险评估引擎
├── gaokao/export/    # PDF/Excel/HTML 生成
├── gaokao/api/       # Flask REST API
├── gaokao/config/    # 省份配置 + 注册表
├── provinces/        # 省份配置（社区可贡献）
├── questionnaires/   # 问卷定义（开源）
├── tests/            # 测试
└── web/              # 前端
```

## 绝对约束（NEVER 违反）

### 1. 科类隔离 — NEVER 混合物理/历史数据
- 物理类和历史类数据严格分离查询
- NEVER 把物理类位次推荐给历史类考生（反之亦然）
- 旧高考(2020-2024): 文科/理科 → 新高考(2025+): 物理类/历史类

### 2. 概率边界 — MUST 校验区间
- 冲: 录取概率 < 35% | 稳: 35%-85% | 保: ≥85%
- "保"档门槛固定≥85%，NEVER降低此阈值

### 2.5 服从专业调剂 — MUST 提示
- 云南"院校专业组"模式：投档后若不服从调剂，退档后本批次后续志愿失效
- 推荐结果含冲档志愿时 MUST 提示"建议在冲档志愿中勾选服从专业调剂"
- NEVER 建议用户不服从调剂
- 已实现（防回归）：`gaokao/core/matching_engine.py:277-292`（F4 风险提示）、`gaokao/core/volunteer_recommender.py:640-668`。改这两处时 NEVER 删除/弱化提示

### 3. 数据质量 — MUST 标注风险
- 数据覆盖不足时 MUST 标注风险（NEVER 隐瞒）
- 中外合作办学/分校/不同校区 MUST 分别标注

### 4. 推荐输出 — MUST 附带免责声明
- 所有推荐结果 MUST 附带免责声明
- 概率仅基于历史数据统计，不代表未来结果

## 已知致命 Bug（P0 级，已修复但需防回归）

与 YGCare 同源（2026-06-08 移植）。以下 5 个 P0 在本仓库已修复，改对应文件时 MUST 对照检查是否引入回归：

1. **历史→文科映射错**（旧高考转新高考时把"历史"误映射到"理科/文科"）— 已修：`gaokao/core/rank_converter.py:197` 正确映射表（文科→历史类、理科→物理类）+ `:58` 未知科类抛错（NEVER 静默回退到文科）
2. **趋势方向反了**（位次数字变大=门槛降低，旧代码显示"上升"）— 已修：`gaokao/core/admission_probability.py:341` 注释方向已校正；CAT-01 禁止跨新旧高考体系混算趋势
3. **学校级 fallback 混科类**（fallback 到不区分科类的查询）— 已修：`gaokao/core/admission_probability.py:112` P0-A1 科类隔离，学校级 fallback 也带 subject_type + 别名展开。NEVER 让任何回退路径丢掉科类过滤
4. **2020-2022 科类标签**（enroll_detail 旧高考文科/理科与新标签并存、存在双标签重复行）— 写 subject_type 过滤前先 `SELECT DISTINCT`，依赖 `subject_normalize` 别名展开；导入后 MUST 跑 `scripts/post_import_validation.py`（科类标签门禁会拦截集合外标签）
5. **Flask debug/对外监听**（远程代码执行 + 数据外泄风险）— `gaokao/api/server.py:749-768` 默认 `debug=False`、`host=127.0.0.1`。NEVER 把默认改成 `debug=True` 或 `0.0.0.0`（违背"本地隐私"承诺）

数据导入/更新后 MUST 跑：`python scripts/post_import_validation.py --province <省>`（科类标签门禁 + P0 回归带退出码，失败不放行）。

## 开发规范
- 注释/输出用中文，标识符用英文
- 算法保持简单透明优先，不做不必要的大模型/深度学习调用
- 新增省份不需要改代码，只需写 YAML + 准备数据

## 常用命令
```bash
# 命令行运行
python -m gaokao.cli --province yunnan --example

# 启动 API
python -m gaokao.api.server --province yunnan

# 测试
pytest tests/ -v
```
