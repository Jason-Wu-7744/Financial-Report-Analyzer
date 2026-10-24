# 财报筛选与分析系统

[English](README.md) · [技术架构](docs/ARCHITECTURE.md) · [项目开发说明](docs/PROJECT_NOTES.md)

面向 A 股与港股上市公司的双语财报研究工作台。系统将官方财报检索、PDF 证据提取、经营快评、七章研究简报、独立风险核验和文件导出连接起来。

这是使用 AI 辅助编程工具开发的个人项目，关注金融研究需求如何转化为可运行、可测试的软件。公开版本基于 v8.1，署名使用 Jason。

## 无需 API 的阅读入口

- [茅台中文简报](samples/a-600519-2025h1-zh.md)
- [腾讯中文简报](samples/hk-00700-hk-2025h1-zh.md)
- [英文样例及来源记录](samples/manifest.json)

样例是历史生成结果，不能代表当前投资观点或实时生成速度；程序校验不能替代对原始财报的人工核验。

## 主要能力

- CNINFO 与 HKEX 官方财报检索及报告主体、期间、类型检查。
- 保留 PDF 物理页码的证据选择，并优先保留主表及续页。
- 独立显示“已核验未触发”“已核验触发”“证据不足”和“不适用”。
- 检查报告结构、引用页可用性、显式加减算式及部分会计口径问题。
- 后台任务、分公司检查点、失败阶段续跑与研究历史。
- 中英文界面，原文和英文产物分开保存；翻译检查保护数字及引用。

## 本地运行

建议使用 Python 3.12。先安装依赖，将 `.env.example` 复制为 `.env`，修改其中的本地登录密码，再启动：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
# Windows PowerShell: Copy-Item .env.example .env
# macOS/Linux: cp .env.example .env
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8581
```

打开 `http://127.0.0.1:8581/?lang=zh`。使用自己在 `RESEARCH_ACCOUNTS_JSON` 中配置的账号密码登录。API 密钥可以在本地 `.env` 或设置页配置；模型名称和端点应以你实际可用的服务为准。生成新的模型分析需要有效密钥，阅读仓库中的样例不需要。

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

## 使用边界

这是一套研究辅助原型。PDF 抽取、证据选择和模型推理都可能出错；重要数字、引用和结论需要复核。公开仓库不包含原部署密码、真实 API 密钥、私人论文、服务器脚本及完整下载财报语料。当前登录模块适合本地评审，不应直接作为公开多用户服务的身份系统。本项目不构成投资建议。
