# 公网演示版：独立访客与 DeepSeek BYOK

公网入口使用 `mianshi_agent.public_demo:app`；本地个人版仍是 `mianshi_agent.main:app`。两者不可互换。公网入口不读取个人版 dotenv，也不会使用服务器上的 `LLM_API_KEY`。

## 体验方式

- 首页提供虚构资料的只读示例，明确标注不是本次实时生成；无需 Key 即可查看。
- 点击“进入我的体验”后，服务器发放 HttpOnly / SameSite=Strict 的访客 Cookie。
- 每位访客使用独立 SQLite 文件和服务实例，资料、面试及后台复盘互不共享。
- 在页面配置自己的 DeepSeek API Key。请求经本站后端转发至官方 `https://api.deepseek.com`，费用由该 Key 的账户承担。
- Key 仅保存在进程内存，默认 30 分钟到期，可主动断开；重启后重新填写。同一体验内只允许续接原 Key 与原模型，更换配置需显式清空并重新开始。
- 后台任务复用该访客的模型客户端。已发往模型的请求可能在断开后完成并计费，断开会阻止后续调用。
- 当前模型选择为 `deepseek-flash` 和 `deepseek-v4-pro`。保存凭据不是官方鉴权验证，实际请求会反馈鉴权、额度和连接错误。

## 资源与保留期限

默认访客记录最多保留 24 小时，清理任务每分钟检查一次；正在处理的请求完成后再清理。服务暂停时清理不会执行，重新启动后继续。Key 到期也由每次调用和定时清理检查。

默认最多 30 个未到期工作区、8 个驻留工作区、全局 2 个聊天调用并发。部署时可用 `DEMO_MAX_ACTIVE=4` 降低驻留资源。每位访客每分钟最多 30 次业务写请求，每次驻留最多 120 个模型调用；这是小范围演示限额，不是正式计费体系或防滥用服务。

每轮最多六题。单文件最大 1.5 MB，整个请求最大 2 MB。资料、岗位、面试、复习及外部复盘分别有记录数上限。公网不提供目录扫描、本机样本导入或管理接口。

SQLite 与后台任务要求 **单实例、单 worker**，不要开启多副本自动伸缩。

## 本机隔离验证

使用独立 Compose，不挂载个人 `data/` 或 `backend/.env`，也不重建原有个人版容器：

```bash
docker compose -f compose.demo.yaml up --build -d --wait
docker compose -f compose.demo.yaml exec -T ollama ollama pull qwen3-embedding:0.6b
```

打开 `http://127.0.0.1:8082`。本机 Compose 显式允许回环 HTTP；正式公网必须设置真实 HTTPS Origin 并关闭该例外。停止测试用普通 `down`，不要删除卷：

```bash
docker compose -f compose.demo.yaml down
```

演示材料首先以文字检索入库，界面真实显示向量未就绪；向量服务和模型就绪后，可在“资料与档案”中重建向量。DeepSeek 聊天 Key 不是 embedding Key，Ollama 资源仍由部署者承担。

## 镜像

GitHub Actions 在公开 `main` 上先运行后端测试、前端构建和导入流程测试，再分别发布：

```text
ghcr.io/fufufu906/interview-agent-backend:demo-<完整提交 SHA>
ghcr.io/fufufu906/interview-agent-frontend:demo-<完整提交 SHA>
```

`demo-latest` 是可变标签；正式部署优先固定提交 SHA 或镜像 digest。后端使用 `backend/Dockerfile.demo`，前端使用 `frontend/Dockerfile`。

GHCR 首次发布包默认私有。首次发布后需要在包设置中设为 Public，并验证不带凭据可以拉取。镜像构建完成不等于已经获得匿名拉取权限。

## Sealos 应用管理配置

Sealos 应用管理分别部署镜像，不能把 GitHub 源码地址当作 Docker 镜像地址。以下服务名是建议名称；内网地址以控制台实际创建的 Service 为准。

| 服务 | 镜像 | 端口 | 初始资源建议 | 公网 |
| --- | --- | --- | --- | --- |
| `interview-agent-ollama` | `ollama/ollama:0.19.0` | 11434 | 0.5 核 / 2 GiB | 关闭 |
| `interview-agent-backend` | 后端 demo 镜像 | 8000 | 0.5 核 / 512 MiB | 关闭 |
| `interview-agent-frontend` | 前端 demo 镜像 | 80 | 0.5 核 / 512 MiB | 开启 HTTPS |

这些是启动测试规格，尚不是平台性能或容量保证。必须观察首次加载向量模型和批量导入时的内存，再决定是否调整。

### 持久化

- Ollama：挂载 `/root/.ollama`，建议先给 3 GiB，并在终端执行 `ollama pull qwen3-embedding:0.6b`。
- 后端：挂载 `/app/data/public-demo`，建议先给 2 GiB；容器用户为 UID 10001。存储卷需要允许该用户写入，可使用平台支持的 `fsGroup: 10001`。不挂载开发电脑的私人目录。
- 前端：无数据卷。

### 后端环境变量

```dotenv
DEMO_PUBLIC_ORIGIN=https://替换为前端实际分配的域名
DEMO_ALLOW_HTTP_LOCAL=false
DEMO_DATA_DIR=/app/data/public-demo
DEMO_MAX_ACTIVE=4
DEMO_MAX_VISITORS=30
DEMO_EMBEDDING_BASE_URL=http://interview-agent-ollama:11434
DEMO_EMBEDDING_MODEL=qwen3-embedding:0.6b
DEMO_EMBEDDING_DIMENSIONS=1024
```

不要配置共享 `LLM_API_KEY`。首次拿到前端域名后，更新 `DEMO_PUBLIC_ORIGIN` 并重启后端；Origin 不匹配时业务写入会被拒绝。

### 前端环境变量

```dotenv
BACKEND_UPSTREAM=interview-agent-backend:8000
```

填实际的后端内网 Service 名称加端口，不加 `http://`。Nginx 启动时只替换这个变量，不替换 Nginx 自身的 `$host` 等变量。

## 验收

1. 不填 Key 能展开示例、建议与引用；界面明确区分预置内容和实际生成。
2. 两个浏览器的材料、会话 ID 和原文互不可读。
3. 实际生成与后台建议都使用当前访客的 Key，断开后不回退到共享 Key。
4. 重启后记录仍在、Key 不在；原 Key 可续接，不同 Key 需新建体验。
5. 检查凭据未出现在数据库、文件、日志、URL 和响应中。
6. 从外部网络访问 HTTPS，完成面试与复盘。只有正式云端流程验收后，才标为已上线。

模型替身测试不代表 DeepSeek 实际质量或可用性；没有调用官方服务时应保留这一限制。
