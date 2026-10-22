const REFRESH_TOKEN_KEY = 'boxia_admin_refresh'
const LEGACY_ACCESS_TOKEN_KEY = 'boxia_admin_token'
const CHANNEL_NAME = 'boxia-admin-session'

let accessToken: string | null = null
let legacyCleaned = false

type SessionMessage = { type: 'access'; token: string } | { type: 'logout' }
type SessionClearedListener = () => void

const clearedListeners = new Set<SessionClearedListener>()

const channel: BroadcastChannel | null =
  typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL_NAME)

channel?.addEventListener('message', (event: MessageEvent<SessionMessage>) => {
  const data = event.data
  if (data?.type === 'access') {
    accessToken = data.token
    return
  }
  if (data?.type === 'logout') {
    accessToken = null
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    for (const listener of clearedListeners) listener()
  }
})

/** 访问令牌仅保存在内存，降低 XSS 窃取风险。 */
export function getAccessToken(): string | null {
  return accessToken
}

/** 更新内存访问令牌并同步到其他标签页。 */
export function setAccessToken(token: string | null): void {
  accessToken = token
  if (token) {
    channel?.postMessage({ type: 'access', token } satisfies SessionMessage)
  }
}

function cleanupLegacyToken(): void {
  if (legacyCleaned) return
  legacyCleaned = true
  localStorage.removeItem(LEGACY_ACCESS_TOKEN_KEY)
}

/** 刷新令牌持久化，用于页面刷新后恢复会话。 */
export function getRefreshToken(): string | null {
  cleanupLegacyToken()
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function setRefreshToken(token: string | null): void {
  cleanupLegacyToken()
  if (token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, token)
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  }
}

/** 清理本地会话，并通知其他标签页同步登出。 */
export function clearSession(options: { broadcast?: boolean } = {}): void {
  accessToken = null
  setRefreshToken(null)
  if (options.broadcast !== false) {
    channel?.postMessage({ type: 'logout' } satisfies SessionMessage)
  }
}

export function hasRefreshToken(): boolean {
  return Boolean(getRefreshToken())
}

/** 订阅其他标签页触发的登出事件，返回取消订阅函数。 */
export function onSessionCleared(listener: SessionClearedListener): () => void {
  clearedListeners.add(listener)
  return () => {
    clearedListeners.delete(listener)
  }
}
