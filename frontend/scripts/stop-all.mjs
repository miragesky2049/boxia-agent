import { killByPort } from './port-utils.mjs'

const ALL_SITES = [
  { name: 'admin', port: 5173 },
  { name: 'user', port: 5174 },
]

const requested = process.argv
  .slice(2)
  .map((arg) => arg.trim().toLowerCase())
  .filter((arg) => arg !== '--')
const unknown = requested.filter((name) => name !== 'all' && !ALL_SITES.some((site) => site.name === name))
if (unknown.length > 0) {
  console.error(`未知站点：${unknown.join(', ')}。用法：pnpm run stop [admin|user|all]`)
  process.exit(1)
}

const sites = requested.length === 0 || requested.includes('all') ? ALL_SITES : ALL_SITES.filter((site) => requested.includes(site.name))

for (const site of sites) {
  const pids = killByPort(site.port)
  if (pids.length > 0) {
    console.log(`已停止 ${site.name}（端口 ${site.port}，PID ${pids.join(', ')}）`)
  } else {
    console.log(`${site.name}（端口 ${site.port}）未在运行`)
  }
}
