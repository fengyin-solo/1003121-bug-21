import { defineStore } from 'pinia'

export type StaffMember = {
  staff_id: string
  name: string
  team: string | null
  roles: string[]
}

/**
 * 演示身份：与后端工花名册（app/identity.py）保持一致。
 * 真实环境这里换成登录态；权限最终以后端判定为准，前端只做按钮置灰与提示。
 */
const DIRECTORY: StaffMember[] = [
  { staff_id: 'U1001', name: '张建国', team: '掘进一队', roles: ['班组长', '施工员'] },
  { staff_id: 'U1002', name: '李掘进', team: '掘进一队', roles: ['施工员'] },
  { staff_id: 'U1003', name: '王验收', team: '掘进一队', roles: ['验收员'] },
  { staff_id: 'U1004', name: '赵验收', team: '掘进一队', roles: ['验收员'] },
  { staff_id: 'U2001', name: '刘开山', team: '掘进二队', roles: ['班组长', '施工员'] },
  { staff_id: 'U2002', name: '陈支护', team: '掘进二队', roles: ['施工员'] },
  { staff_id: 'U2003', name: '孙复核', team: '掘进二队', roles: ['验收员'] },
  { staff_id: 'U2004', name: '周质检', team: '掘进二队', roles: ['验收员'] },
  { staff_id: 'U9001', name: '科室安全员', team: null, roles: [] },
]

export const useSessionStore = defineStore('session', {
  state: () => ({
    operatorId: 'U1003',
    shiftLabel: '白班 08:00-20:00',
    scope: '矿山安全监测管理平台',
    directory: DIRECTORY,
  }),
  getters: {
    staff(state): StaffMember | undefined {
      return state.directory.find((item) => item.staff_id === state.operatorId)
    },
    operator(): string {
      return this.staff?.name ?? '未登录身份'
    },
    team(): string | null {
      return this.staff?.team ?? null
    },
    roles(): string[] {
      return this.staff?.roles ?? []
    },
    isAcceptor(): boolean {
      return this.roles.includes('验收员')
    },
    isConstructor(): boolean {
      return this.roles.includes('施工员') || this.roles.includes('班组长')
    },
    canOperate(): boolean {
      return Boolean(this.staff)
    },
  },
  actions: {
    setOperator(staffId: string) {
      this.operatorId = staffId
    },
    setShift(label: string) {
      this.shiftLabel = label
    },
    /** 是否能看到某条任务的「验收竣工」入口：本队 + 验收员；最终以后端为准。 */
    canAccept(team: string | number | boolean | null | undefined): boolean {
      return Boolean(team) && this.team === team && this.isAcceptor
    },
    /** 是否能看到派发/开工入口：本队 + 施工角色。 */
    canConstruct(team: string | number | boolean | null | undefined): boolean {
      return Boolean(team) && this.team === team && this.isConstructor
    },
  },
})
