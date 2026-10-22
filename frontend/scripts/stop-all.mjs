import { killByPort } from './port-utils.mjs'

const SITES = [
  { name: 'admin', port: 5173 },
  { name: 'user', port: 5174 },
]

for (const site of SITES) {
  const pids = killByPort(site.port)
  if (pids.length > 0) {
    console.log(`已停止 ${site.name}（端口 ${site.port}，PID ${pids.join(', ')}）`)
  } else {
    console.log(`${site.name}（端口 ${site.port}）未在运行`)
  }
}
