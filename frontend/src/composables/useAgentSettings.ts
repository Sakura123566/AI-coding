// 智能体设置共享状态（模块级单例）。
// 让「智能体设置」抽屉与「语音朗读」共用同一份数据：抽屉保存后，浮标里的自动播放能立刻读到最新开关/音色/语速/音调。
import { reactive } from 'vue'
import { getAgentSettings, putAgentSettings } from '../services/agent'
import type { AgentSettings, AgentSettingsPatch } from '../types/user'

const state = reactive<{ settings: AgentSettings | null }>({ settings: null })

export function useAgentSettings() {
  async function load(token: string): Promise<AgentSettings | null> {
    if (!token) return null
    try {
      const s = await getAgentSettings(token)
      state.settings = s
      return s
    } catch {
      return null
    }
  }

  async function save(token: string, patch: AgentSettingsPatch): Promise<AgentSettings | null> {
    if (!token) return null
    const s = await putAgentSettings(token, patch)
    state.settings = s
    return s
  }

  return { state, load, save }
}
