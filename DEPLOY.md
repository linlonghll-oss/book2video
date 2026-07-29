# book2video 部署指南

## 架构

```
用户 → Nginx (:80) → Web (:3000) → API (:8000) → SQLite
                          ↓                ↓
                    Next.js SSR   FastAPI + FFmpeg + AI服务
```

## 一、服务器初始化

在服务器上执行（Ubuntu/Debian/CentOS 均可）：

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com | bash
sudo usermod -aG docker $USER
# 重新登录使 docker 权限生效

# 2. 拉取项目
git clone <你的仓库地址> /opt/book2video
cd /opt/book2video

# 3. 配置环境变量
cp .env.example .env
vim .env  # 填入 LLM_API_KEY、IMAGE_API_KEY 等
```

## 二、部署方式

### 方式 A：本地构建部署（快速测试）

```bash
cd /opt/book2video
./deploy/deploy.sh --local
```

### 方式 B：GitHub Actions 自动部署（推荐）

**1. 在 GitHub 仓库设置 Secrets：**

| Secret | 说明 |
|--------|------|
| `SERVER_HOST` | 服务器 IP 或域名 |
| `SERVER_USER` | SSH 用户名（如 root） |
| `SERVER_SSH_KEY` | SSH 私钥内容（`cat ~/.ssh/id_ed25519`） |

**2. 推送代码到 main 分支，自动触发部署。**

```bash
git push origin main
```

首次部署需要手动在服务器上创建目录并配置 `.env`：

```bash
ssh user@your-server
sudo mkdir -p /opt/book2video
sudo chown $USER:$USER /opt/book2video
cd /opt/book2video
# 从仓库复�� docker-compose.prod.yml 和 deploy/nginx.conf
# 创建 .env 文件
```

## 三、常用命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f api    # 后端日志
docker compose logs -f web    # 前端日志
docker compose logs -f nginx  # 访问日志

# 重启单个服务
docker compose restart api

# 停止所有服务
docker compose down

# 更新部署（拉取最新镜像）
./deploy/deploy.sh
```

## 四、域名 & HTTPS（可选）

如果需要绑定域名和 HTTPS，推荐用 Caddy 替代 Nginx：

```bash
# 安装 Caddy
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy

# Caddyfile 示例 (/etc/caddy/Caddyfile)
# your-domain.com {
#     reverse_proxy localhost:3000
# }
```

然后从 `docker-compose.yml` 中移除 nginx 服务即可。

## 五、关键文件清单

| 文件 | 用途 |
|------|------|
| `Dockerfile` | 后端 API 镜像 |
| `web/Dockerfile` | 前端 Web 镜像 |
| `web/next.config.js` | Next.js standalone 输出 |
| `docker-compose.yml` | 本地开发/构建编排 |
| `docker-compose.prod.yml` | 生产环境（用预构建镜像）|
| `.github/workflows/deploy.yml` | CI/CD 自动部署 |
| `deploy/deploy.sh` | 服务器端部署脚本 |
| `deploy/nginx.conf` | Nginx 反向代理配置 |
| `.dockerignore` | Docker 构建排除 |
