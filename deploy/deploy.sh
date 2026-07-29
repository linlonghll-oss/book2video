#!/bin/bash
# book2video 服务器端部署脚本
#
# 用法:
#   ./deploy.sh             生产模式 — 从 ghcr.io 拉取镜像
#   ./deploy.sh --local     本地模式 — 从源码构建镜像
#
# 环境变量:
#   GITHUB_USER   你的 GitHub 用户名 (生产模式必须)

set -e

PROJECT_DIR="/opt/book2video"
REGISTRY="ghcr.io"

echo "=========================================="
echo "  book2video 部署脚本"
echo "=========================================="

cd "$PROJECT_DIR"

# 确保 .env 文件存在
if [ ! -f .env ]; then
    echo "[错误] .env 文件不存在！请先创建 .env 配置文件。"
    echo "cp .env.example .env && vim .env"
    exit 1
fi

if [ "$1" = "--local" ]; then
    # === 本地构建模式 ===
    echo "[1/2] 本地构建镜像..."
    docker compose build

    echo "[2/2] 启动服务..."
    docker compose up -d --remove-orphans
else
    # === 生产模式：从 Registry 拉取 ===
    GITHUB_USER="${GITHUB_USER:-}"
    if [ -z "$GITHUB_USER" ]; then
        echo "[错误] 请设置 GITHUB_USER 环境变量"
        echo "  export GITHUB_USER=your-github-username"
        echo "  或者用本地构建: ./deploy.sh --local"
        exit 1
    fi

    echo "[1/3] 登录 GitHub Container Registry..."
    if [ -n "$GITHUB_TOKEN" ]; then
        echo "$GITHUB_TOKEN" | docker login "$REGISTRY" -u "$GITHUB_USER" --password-stdin
    else
        echo "[警告] GITHUB_TOKEN 未设置，如果是公开仓库可以匿名拉取"
    fi

    echo "[2/3] 拉取最新镜像..."
    GITHUB_USER="$GITHUB_USER" docker compose -f docker-compose.prod.yml pull

    echo "[3/3] 启动服务..."
    GITHUB_USER="$GITHUB_USER" docker compose -f docker-compose.prod.yml up -d --remove-orphans
fi

# 清理
docker image prune -f

echo ""
echo "=========================================="
echo "  部署完成！✓"
echo "  Web:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost')"
echo "  API:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8000/docs"
echo ""
echo "  查看日志: docker compose logs -f"
echo "  停止服务: docker compose down"
echo "=========================================="
