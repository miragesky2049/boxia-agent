import { ArrowLeftOutlined } from '@ant-design/icons'
import { Button, Tag, Tooltip } from 'antd'
import type { GraphValidationIssue } from '../../../api/apps'
import { CANVAS_TOKENS } from '../canvas/tokens'

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

// V6：画布左上角返回按钮 + 保存状态小字 + 校验/历史入口
export function SaveStatusBar({
  saveStatus,
  lastSavedAt,
  validating,
  validationIssues,
  onRetry,
  onOpenValidation,
  onOpenHistory,
  onBack,
}: {
  saveStatus: SaveStatus
  lastSavedAt: Date | null
  validating: boolean
  validationIssues: GraphValidationIssue[]
  onRetry: () => void
  onOpenValidation: () => void
  onOpenHistory: () => void
  onBack: () => void
}) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 12,
        left: 16,
        zIndex: 100,
        fontSize: 12,
        color:
          saveStatus === 'error'
            ? CANVAS_TOKENS.dangerDeep
            : saveStatus === 'saving'
              ? CANVAS_TOKENS.info
              : CANVAS_TOKENS.run,
        display: 'flex',
        alignItems: 'center',
        gap: 6,
      }}
    >
      <Tooltip title="返回应用列表">
        <Button
          type="text"
          size="small"
          icon={<ArrowLeftOutlined />}
          onClick={onBack}
          aria-label="返回应用列表"
          style={{ marginRight: 4, color: '#374151' }}
        />
      </Tooltip>
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background:
            saveStatus === 'error'
              ? CANVAS_TOKENS.dangerDot
              : saveStatus === 'saving'
                ? CANVAS_TOKENS.info
                : CANVAS_TOKENS.run,
          animation: saveStatus === 'saving' ? 'boxia-pulse 1.2s ease-in-out infinite' : undefined,
        }}
      />
      {validating && '校验中…'}
      {!validating && saveStatus === 'saving' && '保存中…'}
      {!validating &&
        saveStatus === 'saved' &&
        lastSavedAt &&
        `已保存 ${lastSavedAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`}
      {!validating && saveStatus === 'saved' && !lastSavedAt && '已保存'}
      {!validating && saveStatus === 'error' && (
        <span style={{ cursor: 'pointer' }} onClick={onRetry}>
          保存失败，点击重试
        </span>
      )}
      <span
        style={{
          cursor: 'pointer',
          color: validationIssues.some((i) => i.severity === 'error')
            ? CANVAS_TOKENS.danger
            : '#6b7280',
        }}
        onClick={onOpenValidation}
      >
        · 校验{validationIssues.length > 0 ? ` ${validationIssues.length}` : ''}
      </span>
      <span style={{ cursor: 'pointer', color: '#6b7280' }} onClick={onOpenHistory}>
        · 历史
      </span>
    </div>
  )
}

// 画布右上角发布按钮 + live 版本徽标
export function PublishBar({
  publishedVersion,
  publishing,
  onPublish,
}: {
  publishedVersion: number | null
  publishing: boolean
  onPublish: () => void
}) {
  return (
    <div
      style={{
        position: 'absolute',
        top: 8,
        right: 16,
        zIndex: 100,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}
    >
      {publishedVersion != null && (
        <Tag color="green" style={{ marginRight: 0, fontSize: 12 }}>
          ● live v{publishedVersion}
        </Tag>
      )}
      <Button
        type="primary"
        size="small"
        loading={publishing}
        onClick={onPublish}
        style={{ background: '#7c3aed', borderColor: '#7c3aed' }}
      >
        🚀 发布
      </Button>
    </div>
  )
}
