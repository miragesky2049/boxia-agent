import { execFileSync } from 'node:child_process'

const isWindows = process.platform === 'win32'

function findPidsByPort(port) {
  try {
    if (isWindows) {
      const output = execFileSync('netstat', ['-ano'], { encoding: 'utf8' })
      const listening = new RegExp(`[:.]${port}\\s+.*LISTENING`, 'i')
      const pids = new Set()
      for (const line of output.split(/\r?\n/)) {
        if (!listening.test(line)) continue
        const pid = line.trim().split(/\s+/).pop()
        if (pid && pid !== '0') pids.add(pid)
      }
      return [...pids]
    }
    const output = execFileSync('lsof', ['-ti', `tcp:${port}`, '-sTCP:LISTEN'], {
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    })
    return output.split('\n').map((line) => line.trim()).filter(Boolean)
  } catch {
    return []
  }
}

function killPid(pid) {
  try {
    if (isWindows) {
      execFileSync('taskkill', ['/PID', String(pid), '/T', '/F'], { stdio: 'ignore' })
    } else {
      process.kill(Number(pid), 'SIGTERM')
    }
  } catch {
    // 进程可能已经退出，忽略
  }
}

/** 杀掉监听指定端口的进程，返回被处理的 PID 列表 */
export function killByPort(port) {
  const pids = findPidsByPort(port)
  for (const pid of pids) killPid(pid)
  return pids
}
