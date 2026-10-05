/** 统一请求封装：拼后端地址、带上当前操作人、抛网络错误、给页脚留一句可读的说明。 */
import { useSessionStore } from '@/stores/session'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function buildHeaders(init?: RequestInit): HeadersInit {
  const headers = new Headers(init?.headers ?? { 'Content-Type': 'application/json' })
  if (!headers.has('Content-Type') && init?.body) {
    headers.set('Content-Type', 'application/json')
  }
  // 把当前操作人传给后端做归属与角色判定；没有登录态时后端会拒绝写操作
  try {
    const session = useSessionStore()
    if (session.operatorId) {
      headers.set('X-Operator-Id', session.operatorId)
      headers.set('X-Operator-Name', session.operator)
    }
  } catch {
    // Pinia 尚未挂载（如模块初始化阶段）时不阻塞请求
  }
  return headers
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, { ...init, headers: buildHeaders(init) }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

/** 读取后端结构化错误：403 的 detail 里带缺哪项授权，409 带首次结论说明。 */
export async function readError(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown }
    const detail = payload.detail
    if (detail && typeof detail === 'object' && 'message' in detail) {
      return String((detail as { message: string }).message)
    }
    if (typeof detail === 'string') {
      return detail
    }
  } catch {
    // 非 JSON 响应时退回通用提示
  }
  return `接口返回 ${response.status}，操作未生效`
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  return (await response.json()) as T
}
