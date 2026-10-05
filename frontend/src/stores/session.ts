import { defineStore } from 'pinia'

export interface OperatorInfo {
  id: string
  name: string
  role: string
  team: string | null
}

const STORAGE_KEY = 'roadway-operator-id'

export const useSessionStore = defineStore('session', {
  state: () => ({
    // 巷道维修的操作者身份（id 与后端目录一致）；其他模块仍用 name 兜底展示。
    operatorId: localStorage.getItem(STORAGE_KEY) ?? 'U1004',
    operatorName: '',
    operatorRole: '',
    operatorTeam: null as string | null,
    shiftLabel: '白班 08:00-20:00',
    scope: '矿山安全监测管理平台',
  }),
  getters: {
    operator(state): string {
      return state.operatorName || '值班管理员'
    },
    canOperate: (state) => state.operatorId.length > 0,
  },
  actions: {
    setShift(label: string) {
      this.shiftLabel = label
    },
    setOperator(info: OperatorInfo) {
      this.operatorId = info.id
      this.operatorName = info.name
      this.operatorRole = info.role
      this.operatorTeam = info.team
      localStorage.setItem(STORAGE_KEY, info.id)
    },
  },
})
