import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { killByPort } from './port-utils.mjs'

const rootDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const isWindows = process.platform === 'win32'

const SITES = [
  { name: 'admin', dir: 'admin', port: 5173 },
  { name: 'user', dir: 'user', port: 5174 },
]

const children = []
let stopping = false

function prefixLines(stream, prefix, target) {
  let buffer = ''
  stream.setEncoding('utf8')
  stream.on('data', (chunk) => {
    buffer += chunk
    const lines = buffer.split(/\r?\n/)
    buffer = lines.pop() ?? ''
    for (const line of lines) target.write(`${prefix}${line}\n`)
  })
}

function shutdown(code) {
  if (stopping) return
  stopping = true
  for (const site of SITES) killByPort(site.port)
  for (const child of children) {
    if (child.exitCode === null) child.kill()
  }
  setTimeout(() => process.exit(code), 300)
}

process.on('SIGINT', () => shutdown(0))
process.on('SIGTERM', () => shutdown(0))

for (const site of SITES) {
  const command = isWindows ? 'pnpm run --silent dev' : 'pnpm'
  const args = isWindows ? [] : ['run', '--silent', 'dev']
  const child = spawn(command, args, {
    cwd: path.join(rootDir, site.dir),
    shell: isWindows,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const prefix = `[${site.name}] `.padEnd(9)

  prefixLines(child.stdout, prefix, process.stdout)
  prefixLines(child.stderr, prefix, process.stderr)

  child.on('exit', (code) => {
    if (!stopping) {
      console.log(`${prefix}进程退出（code=${code}），正在停止其余站点...`)
      shutdown(code ?? 0)
    }
  })

  children.push(child)
  console.log(`${prefix}启动中 http://localhost:${site.port}`)
}
