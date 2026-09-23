import { storeToRefs } from 'pinia'
import { useKpStore } from '../stores/knowledgeParty'

// 薄封装：用 storeToRefs 取出响应式 state（保持 ref 身份），
// 所有组件通过它读取同一份 store 中的检索状态，避免多实例不同步。
export function useResearch() {
  const store = useKpStore()
  const { topic, loading, error, papers, report } = storeToRefs(store)
  return {
    topic,
    loading,
    error,
    papers,
    report,
    submit: store.doSearch
  }
}
