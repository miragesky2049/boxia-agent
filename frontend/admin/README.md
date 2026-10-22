# Boxia Agent 管理端

React 19 + TypeScript + Vite + Ant Design 5 实现的管理后台，默认开发端口 `5173`。

项目整体说明、后端启动、认证模型与生产部署见仓库根目录 [README](../../README.md)。

## 开发

```bash
npm ci
npm run dev
```

开发环境通过 Vite 将 `/api` 代理到 `http://127.0.0.1:8000`，可通过环境变量 `VITE_PROXY_TARGET` 覆盖。

## 常用命令

| 命令                              | 说明                           |
| --------------------------------- | ------------------------------ |
| `npm run dev`                     | 启动开发服务器                 |
| `npm run typecheck`               | TypeScript 严格模式类型检查    |
| `npm run lint`                    | oxlint 静态检查                |
| `npm run format` / `format:check` | Prettier 格式化 / 校验         |
| `npm run test` / `test:coverage`  | Vitest 单元测试 / 覆盖率       |
| `npm run e2e`                     | Playwright 端到端测试          |
| `npm run build`                   | 类型检查 + 生产构建（`dist/`） |
| `npm run preview`                 | 预览构建产物                   |

## 认证与会话

- Access Token 仅保存在内存；Refresh Token 保存在 `localStorage`（键 `boxia_admin_refresh`）。
- 收到 401 时使用 Web Locks 单飞刷新，并重放原请求一次；刷新失败跳转 `/login?next=...`。
- 多标签页通过 `BroadcastChannel` 同步登录态，登出会同时清理其他标签页。

## 端到端测试

前置条件见根 README「9.3 端到端」。测试默认连接 `http://localhost:5173`，并通过 `E2E_USERNAME` / `E2E_PASSWORD` 覆盖管理员账号。

## 生产部署

构建与 Nginx 配置随 `frontend/admin/Dockerfile` 一起发布，由 `ops/docker-compose.yml` 编排。Nginx 负责 SPA 回退、`/api` 反代、限流与安全响应头。
