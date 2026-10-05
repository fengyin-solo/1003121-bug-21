/**
 * 统一请求封装：拼后端地址、带操作者身份头、抛网络错误、给页脚留一句可读的说明。
 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

function authHeaders(init?: RequestInit): HeadersInit {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  // 巷道维修的队伍归属与验收授权以后端人员目录为准；身份由页面顶部选择并持久化。
  const operatorId = localStorage.getItem('roadway-operator-id')
  if (operatorId) {
    headers.set('X-Operator-Id', operatorId)
  }
  return headers
}

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    ...init,
    headers: authHeaders(init),
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
