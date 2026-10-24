import {
  CopyOutlined,
  DownloadOutlined,
  PlusOutlined,
  ReloadOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Drawer,
  Input,
  Modal,
  Popconfirm,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { skillPackageApi } from '../../api/skills'
import type { Skill, SkillFileMeta } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { useTenant } from '../../tenant/TenantContext'

interface SkillPackageDrawerProps {
  skill: Skill | null
  open: boolean
  onClose: () => void
  /** 文件或技能发生变化后通知列表刷新。 */
  onChanged: () => Promise<void>
}

interface EditorState {
  mode: 'create' | 'edit'
  path: string
  content: string
  hash?: string
  loading?: boolean
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export default function SkillPackageDrawer({
  skill,
  open,
  onClose,
  onChanged,
}: SkillPackageDrawerProps) {
  const { message, modal } = App.useApp()
  const { hasPermission } = useAuth()
  const canCreate = hasPermission('button:skill:create')
  const canUpdate = hasPermission('button:skill:update')
  const { isPlatform } = useTenant()
  const [files, setFiles] = useState<SkillFileMeta[]>([])
  const [totalBytes, setTotalBytes] = useState(0)
  const [loading, setLoading] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [saving, setSaving] = useState(false)
  const [cloneOpen, setCloneOpen] = useState(false)
  const [cloneName, setCloneName] = useState('')
  const [cloning, setCloning] = useState(false)

  const readonly = !canUpdate || Boolean(skill?.is_platform && !isPlatform)
  const canClone = canCreate && !isPlatform && Boolean(skill?.is_platform)

  const loadFiles = useCallback(async () => {
    if (!skill) return
    setLoading(true)
    try {
      const result = await skillPackageApi.listFiles(skill.id)
      setFiles(result.items)
      setTotalBytes(result.total_bytes)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载技能包失败')
    } finally {
      setLoading(false)
    }
  }, [skill, message])

  useEffect(() => {
    setEditor(null)
    setCloneOpen(false)
    if (!open || !skill) {
      setFiles([])
      setTotalBytes(0)
      return
    }
    setCloneName(`${skill.name}（副本）`)
    void loadFiles()
  }, [open, skill, loadFiles])

  const openCreate = () => {
    setEditor({ mode: 'create', path: '', content: '' })
  }

  const openFile = async (file: SkillFileMeta) => {
    if (!skill) return
    setEditor({
      mode: 'edit',
      path: file.path,
      content: '',
      hash: file.content_hash,
      loading: true,
    })
    try {
      const detail = await skillPackageApi.readFile(skill.id, file.path)
      setEditor((prev) =>
        prev && prev.mode === 'edit' && prev.path === file.path
          ? { ...prev, content: detail.content, hash: detail.content_hash, loading: false }
          : prev,
      )
    } catch (error) {
      message.error(error instanceof Error ? error.message : '读取文件失败')
      setEditor(null)
    }
  }

  const handleSave = async () => {
    if (!skill || !editor) return
    const path = editor.path.trim()
    if (!path) {
      message.error('请输入文件路径')
      return
    }
    setSaving(true)
    try {
      await skillPackageApi.writeFile(skill.id, {
        path,
        content: editor.content,
        expected_hash: editor.mode === 'edit' ? editor.hash : undefined,
      })
      message.success('已保存')
      setEditor(null)
      await loadFiles()
      await onChanged()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (path: string) => {
    if (!skill) return
    try {
      await skillPackageApi.deleteFile(skill.id, path)
      message.success('已删除')
      await loadFiles()
      await onChanged()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '删除失败')
    }
  }

  const handleImport = (file: File) => {
    if (!skill) return false
    modal.confirm({
      title: '确认导入技能包？',
      content: `将使用「${file.name}」全量替换当前技能包的所有文件，原有文件会被删除。`,
      okText: '导入',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          const imported = await skillPackageApi.importZip(skill.id, file)
          message.success(`已导入 ${imported.length} 个文件`)
          await loadFiles()
          await onChanged()
        } catch (error) {
          message.error(error instanceof Error ? error.message : '导入失败')
        }
      },
    })
    return false
  }

  const handleExport = async () => {
    if (!skill) return
    setExporting(true)
    try {
      const blob = await skillPackageApi.exportZip(skill.id)
      downloadBlob(blob, `${skill.name}-技能包.zip`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '导出失败')
    } finally {
      setExporting(false)
    }
  }

  const handleClone = async () => {
    if (!skill) return
    const name = cloneName.trim()
    if (!name) {
      message.error('请输入副本名称')
      return
    }
    if (skill.agent_id === null) {
      message.error('该技能未归属智能体，无法在智能体内克隆')
      return
    }
    setCloning(true)
    try {
      const created = await skillPackageApi.clone(skill.id, name, skill.agent_id)
      message.success(`已克隆为「${created.name}」`)
      setCloneOpen(false)
      onClose()
      await onChanged()
    } catch (error) {
      message.error(error instanceof Error ? error.message : '克隆失败')
    } finally {
      setCloning(false)
    }
  }

  const columns: ColumnsType<SkillFileMeta> = [
    {
      title: '文件路径',
      dataIndex: 'path',
      key: 'path',
      render: (path: string) => (
        <span className="cell-ellipsis" title={path}>
          {path}
        </span>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size_bytes',
      key: 'size_bytes',
      width: 100,
      render: (value: number) => formatBytes(value),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 140,
      render: (value: string) => dayjs(value).format('MM-DD HH:mm'),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_: unknown, file) => (
        <Space size={4}>
          <Button type="link" size="small" onClick={() => void openFile(file)}>
            {readonly ? '查看' : '编辑'}
          </Button>
          {!readonly && (
            <Popconfirm
              title="确认删除该文件？"
              description="删除后不可恢复。"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={() => handleDelete(file.path)}
            >
              <Button type="link" size="small" danger>
                删除
              </Button>
            </Popconfirm>
          )}
        </Space>
      ),
    },
  ]

  const readonlyHint = !canUpdate
    ? '当前账号无技能维护权限，仅可查看技能包。'
    : skill?.is_platform && !isPlatform
      ? '平台级技能对所有租户只读，如需修改请克隆到本租户。'
      : null

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={760}
      title={
        <div>
          <div className="resource-name">
            {skill?.name ?? '技能包'}
            <Tag bordered={false} style={{ marginLeft: 8 }}>
              技能包
            </Tag>
          </div>
          <Typography.Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>
            共 {files.length} 个文件 · {formatBytes(totalBytes)}
          </Typography.Text>
        </div>
      }
      extra={
        canClone ? (
          <Button icon={<CopyOutlined />} onClick={() => setCloneOpen(true)}>
            克隆到本租户
          </Button>
        ) : null
      }
    >
      {readonlyHint && (
        <Alert type="info" showIcon message={readonlyHint} style={{ marginBottom: 12 }} />
      )}

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          gap: 12,
          marginBottom: 12,
          flexWrap: 'wrap',
        }}
      >
        <Space wrap>
          {!readonly && (
            <>
              <Upload
                accept=".zip,application/zip"
                showUploadList={false}
                beforeUpload={handleImport}
              >
                <Button icon={<UploadOutlined />}>导入 zip</Button>
              </Upload>
              <Button icon={<PlusOutlined />} onClick={openCreate}>
                新建文件
              </Button>
            </>
          )}
          <Button icon={<DownloadOutlined />} loading={exporting} onClick={handleExport}>
            导出 zip
          </Button>
        </Space>
        <Button icon={<ReloadOutlined />} onClick={() => void loadFiles()} loading={loading}>
          刷新
        </Button>
      </div>

      <Table<SkillFileMeta>
        rowKey="path"
        size="small"
        columns={columns}
        dataSource={files}
        loading={loading}
        pagination={false}
        locale={{ emptyText: '暂无文件，可导入 zip 或新建文件' }}
      />

      <Modal
        open={editor !== null}
        title={editor?.mode === 'create' ? '新建文件' : readonly ? '查看文件' : '编辑文件'}
        onCancel={() => setEditor(null)}
        onOk={handleSave}
        okText="保存"
        cancelText={readonly ? '关闭' : '取消'}
        confirmLoading={saving}
        okButtonProps={readonly ? { style: { display: 'none' } } : undefined}
        width={760}
        forceRender
      >
        <Spin spinning={Boolean(editor?.loading)}>
          <Space direction="vertical" size={12} style={{ width: '100%' }}>
            <div>
              <Typography.Text type="secondary">
                文件路径（相对技能根目录，如 references/guide.md）
              </Typography.Text>
              <Input
                value={editor?.path ?? ''}
                disabled={readonly || editor?.mode === 'edit'}
                placeholder="SKILL.md"
                onChange={(event) =>
                  setEditor((prev) => (prev ? { ...prev, path: event.target.value } : prev))
                }
              />
            </div>
            <div>
              <Typography.Text type="secondary">文件内容（UTF-8 文本）</Typography.Text>
              <Input.TextArea
                className="code-textarea"
                rows={16}
                value={editor?.content ?? ''}
                readOnly={readonly}
                placeholder="输入文件内容"
                onChange={(event) =>
                  setEditor((prev) => (prev ? { ...prev, content: event.target.value } : prev))
                }
              />
            </div>
          </Space>
        </Spin>
      </Modal>

      <Modal
        open={cloneOpen}
        title="克隆到本租户"
        onCancel={() => setCloneOpen(false)}
        onOk={handleClone}
        okText="克隆"
        cancelText="取消"
        confirmLoading={cloning}
      >
        <Typography.Paragraph type="secondary">
          克隆后生成一份独立副本，修改副本不会影响平台级技能。
        </Typography.Paragraph>
        <Input
          value={cloneName}
          maxLength={100}
          placeholder="副本名称"
          onChange={(event) => setCloneName(event.target.value)}
        />
      </Modal>
    </Drawer>
  )
}
