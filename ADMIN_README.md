# 具身项目雷达管理员系统

## 本地启动

在仓库根目录使用 Python 3.13。管理员服务只需要 python-dotenv 和 jsonschema。

```powershell
python -m pip install python-dotenv jsonschema
Copy-Item .env.admin.example .env
python -m src.admin.server
```

启动前编辑本地 .env，设置 ADMIN_PASSWORD、OPENROUTER_MODEL 和由组员持有的 OPENROUTER_API_KEY。模型填写允许使用的 OpenRouter 模型 ID（provider/model）。在浏览器访问 http://127.0.0.1:8012/，用自己的名字和管理员口令登录，名字用于编辑记录。使用没有密钥的本地环境可查看公司库及规则预览。

## 演示流程

1. 在抽取页刷新 36 氪或输入一条新闻 URL。文章网页无法读取时可粘贴正文并保留原链接。
2. 开始抽取。核对公司卡片、字段原文和事件时间。点开原文证据，逐字段勾选或编辑。模型调用失败时可手动切换到规则预览。
3. 用待复核保存草稿。确认后到公司库查找记录和事件。重启后可在同一个 SQLite 文件中继续查看。
4. 下载公司快照。它包含公开应用原有加载器可读取的 matching_data。审核后可由项目负责人发布该快照，或将公开服务的 MATCH_DATA_DIR 指向解压后的 matching_data 路径并重启。新增管理员事件同时保存在 admin_events.json 和 SQLite 中，公开雷达新闻页继续用现有新闻数据源。

## Render

为管理员端单独创建服务。Build Command 为 pip install python-dotenv jsonschema，Start Command 为 python -m src.admin.server，健康检查路径为 /healthz。设置 ADMIN_HOST=0.0.0.0，配置模型与口令环境变量。使用持久磁盘时将 ADMIN_DB_PATH 设成挂载目录内的绝对路径，如 /var/data/admin.sqlite3。组员自行在 Render 后台配置换发的密钥。

## 验收状态

已通过模拟模型和模拟 URL 正文的路由测试，覆盖口令检查、三类结果、多主体、重复 URL、复核草稿、确认入库、重启及公开快照加载器校验。浏览器端脚本已通过语法检查。实际新闻抓取、真实模型、页面交互和 Render 持久磁盘待现场验收。建议按 PRD 用完全符合、部分符合、不相关各两条，另用两条多主体新闻，记录结果、字段准确性、耗时和 token 用量。
