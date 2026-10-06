# 知衡 · 买方投研工作台 V0.3

本版把初版扩展为“财务事实—估值假设—研究计划—反向验证—人工核验—持续跟踪”的可操作流程。研究对象为美的集团、格力电器和海尔智家。

## 启动

双击 **启动知衡.cmd**，或运行 `python launch.py`。需要Python 3.10及以上、SQLite FTS5，前端无安装步骤。仅监听本机，默认8765，已占用时选择空闲端口。启动器会核对项目路径，避免误打开旧版本。

核心使用标准库。导入新的文字型PDF需运行 `python -m pip install -r requirements-optional.txt`，本机已验证pypdf 6.10.0。扫描PDF需先提供OCR文本；空白提取不会当作有效证据。既有PDF检索使用已收集文本，不依赖pypdf。

## 体验流程

1. 选择美的集团，截止日2026-10-06。
2. 在“财务与行情”比较三家公司，切换年度/半年/一季度/前三季度趋势。前三季度采用1—9月累计。
3. 在“估值情景”核对TTM桥接及原页，设定PE倍数。股数可不填；FCFE仅在输入并记录依据后计算。
4. 点击“附带情景，开始研究”，选择资料模式或大模型分析，提出扣非利润与现金流核验问题。
5. 查看计划、备忘录、首次与修订后复核；点击E编号回看原文、日期与页码。
6. 在底部追问。Q编号属于追问证据，主备忘录E编号保持原样。
7. 在“跟踪与人审”添加阈值，触发时复核论据，逐条登记支持依据或反证。
8. 导出备忘录/完整记录，或打印保存为PDF。人工核验记录进入导出。
9. 新公告或新闻通过“补充资料”导入，记录真实披露日期。超过研究时点的资料不会参与该次研究。

资料模式整理原文、指标和核验事项，不调用模型，不声称形成完整投资判断。

## 模型连接

默认DeepSeek：地址 `https://api.deepseek.com`、模型 `deepseek-flash`、环境变量 `DEEPSEEK_API_KEY`。

百炼预设：北京地域地址 `https://dashscope.aliyuncs.com/compatible-mode/v1`、模型 `qwen-plus`、环境变量 `DASHSCOPE_API_KEY`。按自己的服务地域与权限修改。点击“测试连接”会发起一次小规模真实调用。

其他服务需兼容Chat Completions和JSON对象输出。参考[百炼兼容说明](https://docs.bailian.console.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope)、[DeepSeek文档](https://api-docs.deepseek.com/)与[OpenAI接口文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。真实验收使用DeepSeek，其他服务需自行测试。

连接设置和临时密钥仅在本次服务进程中有效。密钥不返回页面、不进入文件。研究、追问和连接测试会发送问题、选取原文与计算包到所选服务，包含用户导入并启用的资料。研究进行中不能切换模型设置。

## 财务与估值

51份财报覆盖三家公司FY2021—2025、H1 2022—2026、Q1 2023—2026、Q3 2023—2025，共17个期间。四项流量为营收、归母利润、扣非利润和经营现金流。7份采用人工登记并复算，其余为规则提取，均保留原值、单位、基期、同比和逐项页码。

调整前/后数据按表头列序处理。部分三季报未披露上年累计金额，仅显示报告同比，不倒推基期。跨页指标引用实际页码；提取状态与人工核验状态分开。

TTM采用“上年度全年 + 当期累计 − 上年同期间累计”，优先使用当期报告可比基期。跨报告口径仍需核对附注。PE使用未四舍五入的原值；FCFE折现直接得到股权价值，不再次加现金或减净债务。

股数需独立核对，EPS加权平均股数不等于期末股本，参见[IAS 33](https://www.ifrs.org/issued-standards/list-of-standards/ias-33-earnings-per-share.html/)。A/H/D股、库存股与稀释未完整建模，每股情景只对应所填分母。情景值不形成目标价或买卖评级。

## 编排与留痕

大模型先规划、写作和复核，共3次调用；中高风险且勾选自动修订时增加修订与再次复核，共最多5次。勾选语义重排时增加问题改写与排序，完整成功时共5次或7次；检索格式或服务异常时保留关键词候选并明确提示降级。使用同一服务、不同提示词，仍需人工审阅。格式/引用无效时拒绝保存不完整备忘录。追问格式可自动重试一次，最多2次调用，均留存。

记录保存研究时点、计划、检索词/过滤条件/输出位置、证据原文、公式、估值假设、提示词、模型输出与用量、数据及日期版本摘要。人工核验独立保存，导出附带最新备注。

结构分衡量章节、编号、时点、计算和复核过程是否齐全。即使100分，也可能有高风险问题，不证明事实或投资判断正确。阈值是用户假设，未触发不证明论据成立。

## 代码与接口

- `core.py`：索引、检索、时点过滤、原件与研究存储。
- `financials.py`、`metrics.json`、`metrics_supplement.json`：规则提取及人工登记。
- `source_overrides.json`：4份历史财报日期更正，保留旧值与核验网址；启动自动更新索引。
- `valuation.py`：TTM、PE、FCFE与敏感性分析。
- `research.py`、`model.py`：计划、检索工具、提示词、模型复核与修订。
- `questions.py`：追问与独立引用空间。
- `retrieval.py`：问题改写、多路关键词召回、倒数排名融合、候选编号校验与语义排序；独立检索记录。
- `announcements.py`：巨潮/上交所公告查询、元数据规范化、候选去重、选择导入与另一官方文件交叉核对。
- `knowledge.py`：补充资料、物理页码与片段索引、网址读取、启停。
- `workbench.py`：情景保存、人工核验、结构分与跟踪规则。
- `exporting.py`：Markdown、JSON、HTML打印页与CSV。
- `server.py`、`static/`：本地服务与界面。
- `data/`、`exports/`：本机数据和导出，均不进入Git。

读取接口包括 `/api/financial/history`、`/api/valuation/context`、`/api/watchlist`、`/api/knowledge`、`/api/questions`、`/api/runs/{id}/quality`。写入接口包括 `/api/research`、`/api/valuation`、`/api/knowledge/import`、`/api/questions`、`/api/watchlist`、`/api/runs/{id}/annotations`。长任务返回编号，查询 `/api/jobs/{id}`。

保持本目录与旁边资料目录的相对位置，可用 `ZHIHENG_DATASET` 更改资料位置。更正日期前的快照不自动改写，涉及4份报告的旧研究应重新运行。

## 验证与后续

运行 `python -m unittest discover -p "test_*.py" -v` 检查38项场景；启动后运行 `python check_http.py` 检查引用、原件、导出与本机访问限制，写入 `data/http-check.json`。

## V0.3新增操作

在“研究工作台”选择“大模型分析”，勾选“理解问题并语义重排证据”。“检索证据”只进行最多2次检索调用；“生成备忘录”将这些证据接入计划、写作、反向核验及可选修订。检索详情和排序理由可回看；资料模式始终不调用模型。

在“官方公告”设定公司、日期和关键词，点击检查。每家公司最多读取5页、每页30条，日期跨度最长366天；达到上限或接口异常会标记不完整。选择1至5份加入资料库，不自动下载整个列表。源文件摘要重复时复用已有原件，暂停资料可以重新启用。官方列表登记的日期不是正文的自动核验结论；新原件仍需回看。

海尔以交易所列表发现公告。若上交所文件返回访问提示，则在巨潮查询同公司、同日、同标题的唯一公开副本，保留两处元数据和响应摘要。不运行访问验证脚本；无唯一匹配时保留失败原因，改由用户手动提供原件。

新增接口：`POST /api/retrieval`、`GET /api/retrieval/{id}`；`GET /api/announcements`、`POST /api/announcements/check`、`POST /api/announcements/import`。长任务使用同一任务编号查询方式。

`python check_stage3_live.py --live` 会调用已配置模型，测试6个固定检索问题，并读取公开公告列表，写入本机 `data/stage3_live.json`。这会产生最多12次模型调用。来源及页码标注见 `retrieval_cases.json`，不是独立盲测。官方资料实测导入后，`python check_stage3_http.py --live` 验证日期过滤、去重状态，并生成一份语义研究（最多7次调用）；不加 `--live` 则不生成模型研究。

本版为比赛研究原型。向量召回、扫描资料自动OCR、资产负债/分部/股本结构化核验、无人值守网络监测和推送是后续增强项，见 `功能进度.md`。
