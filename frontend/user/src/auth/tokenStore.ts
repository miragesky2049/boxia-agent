const REFRESH_TOKEN_KEY = 'boxia_user_refresh'
const CHANNEL_NAME = 'boxia-user-session'

let accessToken: string | null = null

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

export function setAccessToken(token: string | null): void {
  accessToken = token
  if (token) {
    channel?.postMessage({ type: 'access', token } satisfies SessionMessage)
  }
}

/** 刷新令牌持久化，用于页面刷新后恢复会话。 */
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY)
}

export function setRefreshToken(token: string | null): void {
  if (token) {
    localStorage.setItem(REFRESH_TOKEN_KEY, token)
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
  }
}

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

export function onSessionCleared(listener: SessionClearedListener): () => void {
  clearedListeners.add(listener)
  return () => {
    clearedListeners.delete(listener)
  }
}
