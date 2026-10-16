# Interview Agent

基于个人资料和目标岗位的面试练习与复习助手。支持资料导入、逐题模拟、结束复盘，以及带引用依据和待补信息的建议回答。

技术栈：Python / FastAPI / Vue 3 / TypeScript / SQLite / Ollama / Docker Compose。

## 功能

- 个人档案与岗位 JD：按档案保存资料，面试绑定岗位快照。
- 资料导入：支持文本 PDF、Markdown、TXT、代码及目录扫描，保留来源位置和版本信息。
- 混合检索：向量 + TF-IDF + 有界图扩展；向量服务不可用时回退文字检索。
- 严格模拟：逐题回答、追问、补充和跳过，结束后统一复盘。
- 建议回答：新面试结束后自动生成，历史面试手动生成；展示参考答案、引用依据和待补信息。
- 持久化与恢复：SQLite 保存会话与生成任务，支持回答幂等提交、失败重试和中断恢复。
- 深度复习：问题拆解、资料检索、分层解释及引用校验。

原始回答与生成内容分别保存，历史回答和复盘不自动成为长期个人事实。引用校验只能确认来源归属，不能保证每项模型推断正确。

## 环境变量

仓库只提供不含真实配置的示例文件：

| 文件 | 用途 |
| --- | --- |
| `backend/.env.example` | 后端、聊天模型、向量模型及检索参数 |
| `.env.example` | 可选的 Docker Compose 端口和向量模型参数 |

复制示例后，在本机填写自己的配置：

```powershell
Copy-Item backend/.env.example backend/.env
```

必须填写聊天模型的 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_ID`。地址指向兼容 `/chat/completions` 的 API 根路径，例如供应商的 `/v1` 根路径；模板中的 `api.example.com` 和 `your-chat-model` 只是占位符。

可选：复制根目录 `.env.example` 为 `.env`，调整 Docker 前端端口等参数。根目录 `.env` 与 `backend/.env` 用途不同，聊天密钥仅放后端配置。

真实 `.env`、API 密钥、简历、资料、会话数据库、向量索引及本地日志不进入版本库。密钥不传到前端，也不复制进镜像。

## Docker 一键启动

安装 Docker Desktop，使用 Linux 容器。完成后端配置后，在 Windows 上双击：

```text
start-docker.cmd
```

脚本启动前端、后端和 Ollama，首次下载向量模型；打开 <http://127.0.0.1:8080>。

停止服务：双击 `stop-docker.cmd`。数据库保存在 `data/runtime/`，模型保存在 Docker 卷中。

其他平台可以手动启动：

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your own provider settings.
mkdir -p data/runtime
docker compose up --build --detach --wait backend frontend ollama
docker compose exec -T ollama ollama pull qwen3-embedding:0.6b
```

详细说明见 [Docker 运行说明](docs/docker.md)。

## 源码运行

需要 Python 3.11+、uv、Node.js 24、npm，以及用于向量检索的 Ollama。

后端：

```bash
cd backend
uv sync --all-groups
uv run uvicorn mianshi_agent.main:app --host 127.0.0.1 --port 8000
```

另开终端启动向量模型：

```bash
ollama serve
# In another terminal:
ollama pull qwen3-embedding:0.6b
```

前端：

```bash
cd frontend
npm ci
npm run dev
```

打开 <http://127.0.0.1:5173>，创建自己的档案，添加岗位和资料。应用不预装个人简历或面试内容。

## 验证

```bash
cd backend
uv run ruff check src tests
uv run pytest -q
```

```bash
cd frontend
npm ci
npm run build
node --test tests/folderImport.test.cjs
```

测试使用模拟模型与独立临时数据；真实外部模型调用质量需要使用者单独验证。

## 运行边界

当前面向本机个人使用，后端按单进程、单 worker 运行。尚未接入账户登录和身份认证，不能把档案 ID 当作访问权限凭据。默认只将前端端口映射到本机回环地址。

尚未实现扫描 PDF OCR、自动联网核验、流式生成和多实例任务协调。模型服务会接收生成所需的问答与资料片段，请自行选择适合资料范围的供应商。

架构和记忆边界见 [架构说明](docs/architecture.md)。

## 目录

```text
backend/       API、检索、资料导入、状态机与测试
frontend/      Vue 页面、API 交互与组件
scripts/       Docker 启停脚本
config/        项目证据导入的空白示例
templates/     个人档案填写模板
docs/          运行和架构说明
data/          本地生成，Git 忽略
```

项目由 AutoDeepSearch 的部分设计思路衍生，面试业务、数据模型及交互单独实现；公开仓库不附带私人研究资料、面试记录或本地开发历史。
