# Docker 运行说明

## Windows 一键启动

在克隆后的项目根目录运行。
安装 Docker Desktop，切换到 Linux 容器后，双击根目录的 `start-docker.cmd`。

脚本会依次：

1. 检查 Docker Compose，必要时启动 Docker Desktop。
2. 复用已有 `backend/.env`；文件不存在时从 `.env.example` 创建。
3. 按锁文件构建后端、前端两个独立镜像。
4. 用同一个 `compose.yaml` 启动前后端，等待健康检查通过。
5. 打开 http://127.0.0.1:8080 。
6. 启动 Ollama，为其下载 `qwen3-embedding:0.6b`，已有模型则复用。

首次启动需要联网下载镜像、依赖和向量模型。Ollama 启动或模型下载失败时，会给出警告；应用仍可使用文字检索。
后续再次运行启动脚本会重试下载。已降级导入的资料，可以在应用中重建向量。

双击 `stop-docker.cmd` 停止服务。停止脚本不删除持久化数据或模型卷。

## 镜像与网络

| 服务 | 镜像/构建 | 作用 |
| --- | --- | --- |
| frontend | `frontend/Dockerfile` → `mianshiagent-frontend:local` | Vue 生产静态资源、Nginx、API 反向代理 |
| backend | `backend/Dockerfile` → `mianshiagent-backend:local` | FastAPI API，单进程、单 worker |
| ollama | `ollama/ollama:0.19.0` | 本地向量模型，默认 CPU 运行 |

项目使用 SQLite，数据库不启动独立服务。数据库文件使用独立的可写挂载，
前后端镜像分别构建，全部服务由同一个 Compose 管理。

仅前端映射本机回环地址 `127.0.0.1:8080`。后端与向量服务通过 Compose 内部网络通信。
前端请求 `/api/...` 和 `/health` 由 Nginx 代理到后端，不需要修改前端 API 地址。

## 聊天模型配置

在 `backend/.env` 中配置 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL_ID`。
配置文件以只读文件挂载，由后端读取；不会复制进镜像，也不会注入前端。
修改配置后运行：

```powershell
docker compose restart backend
```

如果模型服务运行在 Windows 宿主机上，地址使用 `host.docker.internal`，不能在容器中继续使用 `127.0.0.1` 指代宿主机。
后端已有的向量地址会被 Compose 覆盖为 `http://ollama:11434`。

可以在根目录创建 `.env`（Git 忽略）设置非密钥的部署参数，例如：

```dotenv
MIANSHI_PORT=8080
MIANSHI_EMBEDDING_MODEL=qwen3-embedding:0.6b
MIANSHI_EMBEDDING_DIMENSIONS=1024
```

向量模型与维度必须匹配；切换后可能需要重建已有资料的向量。根目录 `.env` 用于 Compose 参数，
与保存聊天模型配置的 `backend/.env` 是不同文件。

## 命令行运行

在项目根目录执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-docker.ps1 -NoBrowser
```

已有向量模型时，可加 `-SkipModelPull`。
暂时只需要文字检索时，可加 `-SkipEmbeddings`，同时跳过 Ollama 镜像与模型准备。

手动启动相当于：

```powershell
docker compose up --build --detach --wait --wait-timeout 180 backend frontend
docker compose up --detach --wait --wait-timeout 180 ollama
docker compose exec -T ollama ollama pull qwen3-embedding:0.6b
```

手动启动前，确认 `backend/.env` 为文件、`data/runtime` 目录存在。
如果修改了向量模型，最后一条命令也应使用对应模型名。

```powershell
docker compose ps
docker compose logs --tail 100
docker compose restart backend
docker compose down
```

不要在共享日志时输出包含密钥的完整配置。检查 Compose 配置可用 `docker compose config --quiet`。

## 原始资料与目录导入

`data/` 挂载到容器的 `/app/data`，原始资料区域只读，不打进镜像。
在界面的目录导入功能中填写 `/app/data/...` 容器路径。
Windows 的 `E:\...` 路径不能直接在 Linux 容器中读取。
已入库的正文仍由数据库保存；原先记录的 Windows 文件路径不会自动转换。

## 数据持久化与备份

| 宿主机位置 | 容器位置 | 用途 |
| --- | --- | --- |
| `backend/.env` | `/app/backend/.env`，只读 | 聊天模型配置与密钥 |
| `data/` | `/app/data`，只读 | 原始资料、输入样本等 |
| `data/runtime/` | `/app/data/runtime`，独立可写挂载 | SQLite 数据库及 WAL/SHM 文件 |
| Compose 卷 `mianshiagent_ollama-models` | `/root/.ollama` | 已下载向量模型 |

现有数据库 `data/runtime/mianshiagent.sqlite3` 直接复用，不自动清空、复制或重建个人档案。
更新或删除应用容器、重建镜像不会删除宿主机的数据库文件。
从旧的 uvicorn 本地运行方式切换前，先停止旧后端，避免两个实例同时操作同一数据库或执行启动恢复。
备份时先停止应用，再复制整个 `data/runtime` 目录，以包含可能尚未合并到主文件的 WAL 数据。
不要执行 `docker compose down -v`，该选项会删除 Ollama 模型卷；普通 `down` 保留模型。

把应用搬到另一台电脑，需要带上源码、`data/` 和单独妥善传递的 `backend/.env`；
密钥和个人资料都不在构建产物中。向量模型可在新机器首次启动时重新下载。

## 挂载额外的资料目录

要导入 `data/` 外的源码或资料，可在 Compose 的 backend 服务增加只读挂载，例如：

```yaml
volumes:
  - type: bind
    source: E:/another-project
    target: /imports/another-project
    read_only: true
```

随后使用 `/imports/another-project` 扫描；仅挂载实际需要导入的目录。

## 排错

- **8080 端口占用**：在根目录 `.env` 设置 `MIANSHI_PORT=8081`，重新启动。
- **Docker 未就绪**：手动打开 Docker Desktop，确认 Linux 引擎正常后重试。
- **聊天生成不可用**：检查 `backend/.env` 的聊天模型配置与服务网络连通性；`/health` 成功只证明应用进程就绪。
- **向量模型下载失败**：重新运行启动脚本，或手动执行 `ollama pull` 命令。
- **Linux 文件权限错误**：持久化目录应允许容器中的 UID 10001 写入。Windows Docker Desktop 的目录共享由 Desktop 管理。

实现参考：[Docker Compose 启动选项](https://docs.docker.com/reference/cli/docker/compose/up/)、
[uv Docker 集成](https://docs.astral.sh/uv/guides/integration/docker/)、
[Ollama Docker](https://docs.ollama.com/docker)。
