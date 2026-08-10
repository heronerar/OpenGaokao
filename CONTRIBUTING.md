# 参与 OpenGaokao

> 当前发行适用 `LicenseRef-OpenGaokao-SAL-1.0`，是“源码可见、商业受限”模式，不是
> OSI 开源。在独立贡献协议启用前暂停合并外部代码贡献；仅接受 issue、复现材料和不包含
> 第三方代码的讨论。详情见 [LICENSING.md](LICENSING.md)。

感谢你改进 OpenGaokao。当前支持的开发方式是在仓库根目录直接运行源码；项目尚未
提供可独立运行的 wheel / PyPI 安装包。

## 本地验证

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
python data/generate_example_db.py
python -m pytest tests/ -q --tb=short
python scripts/verify_release.py --ci
```

`example.db` 由脚本现场生成，只包含显式标记的合成数据。演示路径通过不代表真实省份
数据、录取准确率或真实填报效果已经验收。
合成标记保存在数据库内容中；复制或改名文件不能把示例库变成真实省份数据。

## 数据、隐私与授权

- 不要提交真实考生、家长、客户或员工的姓名、联系方式、证件号、成绩、位次、录取去向，
  也不要提交可通过“精确成绩 + 位次 + 学校/专业”等组合重新识别个人的记录。
- 不要提交真实 SQLite 数据库、WAL/SHM/journal、导出报表、日志或内部分析材料；即使表
  当前为空，SQLite 未清理页也可能保留历史内容。
- 示例必须完全合成，并在院校名、页面、CLI 和 API 响应中持续标明“示例”，不得静默
  冒充真实推荐。
- 数据处理代码可以贡献；真实数据文件不进入本仓库。新增数据来源时须在文档中写明来源
  URL、年份、许可或使用条款，以及你拥有再分发权的依据。
- 不要复制、翻译或改编未经许可的商业测评题目。项目现有偏好问卷为项目自编题面，未经
  心理测量验证，不作诊断。

## 提交要求

- 改动保持最小，并为行为变化补回归测试。
- 推荐算法、科类映射、概率阈值或数据导入发生变化时，除 pytest 外还要运行对应省份的
  `scripts/post_import_validation.py` 和真实入口验收。
- 发版门禁失败时不得宣告完成，也不得用 example/mock 结果替代真实数据验收。
- 未经维护者提供并签署独立贡献协议，请不要通过 PR 提交代码、文档或配置。YGCare 的商业
  运营及第三方集成模块不属于本项目贡献范围。

维护者在公开发布前还必须运行：

```bash
python scripts/verify_release.py --ci --public-release \
  --pii-denylist <不进入 Git 的私有文件> \
  --rights-bom <仓库外最终逐文件权属清单> \
  --release-approval <仓库外许可人批准JSON>
```

私有 denylist 应包含已知真实姓名和其他高风险字面量；门禁会检查待发布文件及所有 Git
引用。该文件本身不得被 Git 跟踪。

`--ci` 在这里仅验收不携带私有省份数据库的源码与合成演示包。真实数据验收是另一个私有
证据范围，不能用合成示例冒充，也不应把真实数据库放入发行工作树。

缺少仓库外 Rights BOM、许可人批准回执或 SSH 签名固定 Tag 时，正式公开命令会失败。这是
有意的发布阻断，不能通过仓库内自填状态、占位凭据或使用 `--skip-fulltest` 放行。
