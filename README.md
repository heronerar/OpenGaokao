# OpenGaokao — 高考志愿推荐引擎（许可迁移中）

> 🔒 **许可迁移中：当前仓库必须保持 PRIVATE。** 项目所有者已确定未来目标为
> “源码可见、商业受限”，但定制许可证、YGCare 权属链和律师审定尚未完成。
> 在 [LICENSING.md](LICENSING.md) 列出的硬门禁全部通过前，不得恢复公开，也不得宣称
> 新商业限制已经生效。历史 AGPL 版本的既有权利不受未来变更影响。

[![AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-green)]()
[![CI](https://github.com/heronerar/OpenGaokao/actions/workflows/ci.yml/badge.svg)](https://github.com/heronerar/OpenGaokao/actions/workflows/ci.yml)

**源码透明 · 每一步可解释 · 本地隐私保护**

OpenGaokao 是一个高考志愿推荐引擎，面向 3+1+2 新高考模式设计。仓库当前包含**云南**配置；真实云南数据库不随代码分发。同为院校专业组模式的省份可按 YAML + 数据处理代码适配（见 docs/data-guide.md），其他志愿模式仍可能需要代码适配。
基于历史录取数据、项目自编偏好问卷和规则引擎，生成透明、可追溯、可审计的志愿推荐方案。

本项目于 2026-06-08 从 **YGCare** 移植核心推荐代码后独立演进；商业运营与第三方集成模块不在本仓库。衍生与修改声明见 [NOTICE](NOTICE)。当前迁移候选仍保留历史 `AGPL-3.0-or-later` 许可；未来以商业受限条款重新公开，必须先取得相关权利人的重许可确认和律师审定。

> ⚠️ **使用边界：** 当前为 Beta 阶段的本地决策辅助工具，不是教育考试机构官方系统，也不构成录取承诺。真实填报前必须核对当年考试院政策、招生计划和数据时效。

## 为什么公开源码？

高考志愿是**一次性、高赌注、不可逆**的决策。家长需要的不只是推荐结果，更需要知道**为什么推荐**。

OpenGaokao 的核心理念：**"别信我，你来看代码。"**

## 核心特性

- 🔍 **透明推荐**：每条推荐都有完整的计算链条——从分数到位次到概率到排序，每一步可追溯
- 🧠 **多维偏好辅助**：项目自编大五维度、RIASEC 风格、学科自我评价和职业价值偏好问卷，用于专业匹配参考，不作心理诊断
- 🏠 **本地运行**：数据不出你的电脑，隐私安全
- ⚙️ **省份可配**：同模式省份可复用 YAML 配置与数据导入工具
- 🎯 **冲稳保分层**：基于指数衰减概率模型和公开阈值划分冲/稳/保

## 当前能力边界

| 能力 | 当前状态 |
|------|---------|
| 推荐逻辑 | 源码可审查的规则与固定算法，可在本地复现 |
| 数据 | 仓库只生成合成示例库；真实省份数据由使用者合法准备 |
| Web/API | Flask 本地开发入口，进程退出后即停止 |
| 偏好问卷 | 项目自编、未经心理测量验证，仅作方向参考 |
| 省份支持 | 仓库含云南配置；其他省份尚未验收 |

## 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/heronerar/OpenGaokao.git
cd OpenGaokao

# 2. 安装依赖
pip install -r requirements.txt

# 3. 生成可复现的合成示例库（真实数据库不随代码仓库分发）
python data/generate_example_db.py

# 4. 跑通示例数据（只用于演示，不是实际填报推荐）
python -m gaokao.cli --province yunnan --example

# 5. 启动本地服务（真实云南推荐需要 data/yunnan_gaokao.db）
python -m gaokao.api.server --province yunnan
# 访问 http://localhost:5000
```

当前支持的分发方式是**在克隆后的仓库根目录运行源码**。普通 wheel / PyPI 安装包尚未发布；不要把 `pip install .` 视为受支持的 Web/CLI 安装路径。

本项目当前是开发/开源本地工具，不是常驻系统服务。上述命令运行期间，
Web 与 API 才可访问；关闭终端、按 `Ctrl+C`、退出进程或重启电脑后服务会停止，
再次执行同一条命令即可恢复。项目不默认配置开机自启动。

若 `data/yunnan_gaokao.db` 不存在，服务会降级到 `data/example.db`，页面将持续显示
红色“演示数据”警示；这类结果不可用于实际填报，也不能作为真实数据验收通过。
示例库同时写入内容级 `synthetic_example` 标记；即使复制或改名为
`yunnan_gaokao.db`，API、Web 与发版门禁仍会把它识别为演示数据。

## 运行验收与完成口径

真实入口验收会实际启动一个临时 Flask 进程，检查首页、核心推荐、数据源标识与
进程退出语义；任一项失败均以非零退出码结束：

```bash
# 要求使用真实云南数据库，example.db 降级会失败
python tests/test_e2e_api.py --province yunnan

# 发版单一门禁：语法、pytest、真实入口、数据、隐私与 AGPL
python scripts/verify_release.py --province yunnan
```

只有明确验收演示路径时，才可显式使用
`--expect-data-source example`；它不等于真实推荐验收通过。

正式公开发布还要执行维护者门禁；该门禁要求提供不进入 Git 的私有 PII denylist，并扫描待发布树与全部 Git refs：

```bash
python scripts/verify_release.py --ci --public-release \
  --pii-denylist <私有文件路径>
```

这里的 `--ci` 表示验收不含私有省份数据库的“代码公开包”；真实云南数据仍须另行执行
不带 `--ci` 的本地发版门禁，二者不能相互替代。

当前 `licensing/publication-policy.json` 的状态为 `LEGAL_REVIEW_REQUIRED`，所以上述
正式公开命令必须非零退出。该状态不能在仓库内自我改成 `APPROVED`：未来必须先实现受
保护的仓库外签名审批验证，再由独立变更开放发布路径。完成条件见
[LICENSING.md](LICENSING.md)。

## 目录结构

```
OpenGaokao/
├── gaokao/           # 核心引擎
│   ├── core/         # 算法（省份无关）
│   ├── pipeline/     # 决策管道可视化
│   ├── consensus/    # 家庭共识引擎
│   ├── risk/         # 风险评估引擎
│   ├── export/       # PDF/Excel/HTML生成
│   ├── api/          # Flask REST API
│   └── config/       # 配置系统
├── provinces/        # 省份配置（社区可贡献）
├── questionnaires/   # 问卷定义
├── docs/             # 文档
├── web/              # 前端
└── tests/            # 测试
```

## 数据边界

代码公开不等于招生数据可以再分发。本仓库不提供、销售或承诺交付任何真实省份数据库；
使用者须从合法来源自行准备数据，并遵守来源许可、考试院条款和个人信息保护要求。

## 许可证

- 当前私有迁移候选中的代码、文档与生成脚本仍为历史
  [`AGPL-3.0-or-later`](LICENSE)；这不表示未来商业受限许可证已经生效
- `data/example.db` 不进入 Git，由 `data/generate_example_db.py` 现场生成

真实省份数据库、商业数据包和任何考生记录均不随本代码仓库分发。贡献数据前请阅读 [贡献指南](CONTRIBUTING.md) 的来源、授权与隐私要求。

## 参与贡献

许可迁移期间暂停合并外部代码贡献；当前只接受 issue、复现材料和不包含第三方代码的
讨论。详情见 [CONTRIBUTING.md](CONTRIBUTING.md)，并确保发布门禁失败时不宣告完成。
