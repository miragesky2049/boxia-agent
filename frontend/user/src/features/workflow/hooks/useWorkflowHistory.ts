import { useCallback, useEffect, useState } from 'react'
import { listWorkflowApprovals, listWorkflowRuns } from '../../../api/workflow'
import type { RunHistoryItem } from '../types'

interface UseWorkflowHistoryResult {
  runs: RunHistoryItem[]
  approvals: RunHistoryItem[]
  loading: boolean
  error: string | null
  reload: () => Promise<void>
}

/** 运行历史：我的运行 + 待我审批两个列表并行拉取；403（无审批角色）降级为空列表。 */
export function useWorkflowHistory(agentId: string | undefined): UseWorkflowHistoryResult {
  const [runs, setRuns] = useState<RunHistoryItem[]>([])
  const [approvals, setApprovals] = useState<RunHistoryItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    if (!agentId) return
    setLoading(true)
    setError(null)
    try {
      const runsPromise = listWorkflowRuns(agentId)
      const approvalsPromise = listWorkflowApprovals(agentId).catch(() => [] as RunHistoryItem[])
      const [nextRuns, nextApprovals] = await Promise.all([runsPromise, approvalsPromise])
      setRuns(nextRuns)
      setApprovals(nextApprovals)
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载运行历史失败')
    } finally {
      setLoading(false)
    }
  }, [agentId])

  useEffect(() => {
    void reload()
  }, [reload])

  return { runs, approvals, loading, error, reload }
}
