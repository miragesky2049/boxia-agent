import { ArrowLeftOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Input,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { rolesApi } from '../../api/access'
import type { Role, RoleGrantResource, ResourceType } from '../../api/types'

const RESOURCE_TABS: { key: ResourceType; label: string }[] = [
  { key: 'agent', label: '智能体' },
  { key: 'skill', label: '技能' },
  { key: 'tool', label: '工具' },
  { key: 'component', label: '组件' },
  { key: 'prompt', label: '提示词' },
]

const SYSTEM_ROLE_META: Record<string, { label: string; color: string }> = {
  superadmin: { label: '超级管理员', color: 'red' },
  admin: { label: '管理员', color: 'blue' },
  viewer: { label: '只读', color: 'default' },
}

export default function RoleDetailPage() {
  const { id } = useParams()
  const roleId = Number(id)
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [role, setRole] = useState<Role | null>(null)
  const [roleLoading, setRoleLoading] = useState(false)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [resourceType, setResourceType] = useState<ResourceType>('agent')
  const [items, setItems] = useState<RoleGrantResource[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(10)
  const [keyword, setKeyword] = useState('')
  const [grantedOnly, setGrantedOnly] = useState(false)
  const [loading, setLoading] = useState(false)
  const [pendingIds, setPendingIds] = useState<number[]>([])

  const readonly = role?.system_role === 'superadmin'
  const isPlatformRole = role?.tenant_id === null

  const loadRole = useCallback(async () => {
    if (!Number.isFinite(roleId)) {
      message.error('角色不存在')
      navigate('/roles', { replace: true })
      return
    }
    setRoleLoading(true)
    try {
      const [detail, summary] = await Promise.all([
        rolesApi.get(roleId),
        rolesApi.grantSummary(roleId),
      ])
      setRole(detail)
      setCounts(summary.counts)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载角色失败')
    } finally {
      setRoleLoading(false)
    }
  }, [roleId, message, navigate])

  const loadGrants = useCallback(async () => {
    if (!Number.isFinite(roleId)) return
    setLoading(true)
    try {
      const result = await rolesApi.listGrants(roleId, {
        resource_type: resourceType,
        page,
        page_size: pageSize,
        keyword: keyword || undefined,
        granted_only: grantedOnly,
      })
      setItems(result.items)
      setTotal(result.total)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载授权失败')
    } finally {
      setLoading(false)
    }
  }, [roleId, resourceType, page, pageSize, keyword, grantedOnly, message])

  const refreshSummary = useCallback(async () => {
    if (!Number.isFinite(roleId)) return
    try {
      const summary = await rolesApi.grantSummary(roleId)
      setCounts(summary.counts)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '加载授权汇总失败')
    }
  }, [roleId, message])

  useEffect(() => {
    void loadRole()
  }, [loadRole])

  useEffect(() => {
    void loadGrants()
  }, [loadGrants])

  const handleToggle = async (record: RoleGrantResource, checked: boolean) => {
    setPendingIds((prev) => [...prev, record.resource_id])
    try {
      if (checked) {
        await rolesApi.addGrants(roleId, resourceType, [record.resource_id])
      } else {
        await rolesApi.removeGrant(roleId, resourceType, record.resource_id)
      }
      message.success(checked ? '已授权' : '已取消授权')
      await Promise.all([loadGrants(), refreshSummary()])
    } catch (error) {
      message.error(error instanceof Error ? error.message : '授权失败')
    } finally {
      setPendingIds((prev) => prev.filter((item) => item !== record.resource_id))
    }
  }

  const columns: ColumnsType<RoleGrantResource> = [
    {
      title: '名称',
      key: 'name',
      render: (_: unknown, record: RoleGrantResource) => (
        <div>
          <div className="resource-name">
            {record.name}
            {record.is_platform && (
              <Tag color="geekblue" bordered={false} style={{ marginLeft: 8 }}>
                平台级
              </Tag>
            )}
          </div>
          {record.description && <div className="resource-desc">{record.description}</div>}
        </div>
      ),
    },
    {
      title: '状态',
      dataIndex: 'is_enabled',
      key: 'is_enabled',
      width: 90,
      render: (enabled: boolean) => (enabled ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>),
    },
    {
      title: '更新时间',
      dataIndex: 'updated_at',
      key: 'updated_at',
      width: 170,
      render: (value: string) => dayjs(value).format('YYYY-MM-DD HH:mm'),
    },
    {
      title: '授权',
      key: 'granted',
      width: 90,
      align: 'center',
      render: (_: unknown, record: RoleGrantResource) => (
        <Checkbox
          checked={record.is_granted}
          disabled={readonly || pendingIds.includes(record.resource_id)}
          onChange={(event) => void handleToggle(record, event.target.checked)}
        >
          {record.is_granted ? '已授权' : '未授权'}
        </Checkbox>
      ),
    },
  ]

  const systemRoleMeta = role ? SYSTEM_ROLE_META[role.system_role] : null

  return (
    <div className="page-card">
      <div className="page-header">
        <div>
          <Space size={8}>
            <Button
              type="text"
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate('/roles')}
            />
            <h2 className="page-header__title">{role?.name ?? '角色授权'}</h2>
          </Space>
          <p className="page-header__desc">
            {isPlatformRole
              ? '按资源类型勾选该平台角色可访问的平台级智能体、技能、工具、组件与提示词；未勾选的资源对绑定该角色的平台账号不可见。'
              : '按资源类型勾选该角色可访问的智能体、技能、工具、组件与提示词；未勾选的资源不可见。'}
          </p>
        </div>
      </div>

      {role && (
        <Card size="small" loading={roleLoading} style={{ marginBottom: 16 }}>
          <Descriptions column={3} size="small">
            <Descriptions.Item label="角色编码">{role.code}</Descriptions.Item>
            <Descriptions.Item label="基础权限">
              {systemRoleMeta ? (
                <Tag color={systemRoleMeta.color}>{systemRoleMeta.label}</Tag>
              ) : (
                role.system_role
              )}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              {role.is_active ? <Tag color="success">启用</Tag> : <Tag>停用</Tag>}
            </Descriptions.Item>
            <Descriptions.Item label="描述" span={3}>
              {role.description || '-'}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}

      {readonly && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={
            isPlatformRole
              ? '超级管理员角色默认拥有全部平台级资源，授权页只读。'
              : '超级管理员角色默认拥有本租户全部资源，授权页只读。'
          }
        />
      )}

      <Tabs
        activeKey={resourceType}
        items={RESOURCE_TABS.map((tab) => ({
          key: tab.key,
          label: (
            <span>
              {tab.label}
              <Tag bordered={false} style={{ marginLeft: 6 }}>
                {counts[tab.key] ?? 0}
              </Tag>
            </span>
          ),
        }))}
        onChange={(key) => {
          setResourceType(key as ResourceType)
          setPage(1)
          setKeyword('')
          setGrantedOnly(false)
        }}
      />

      <div className="page-toolbar">
        <Input.Search
          key={resourceType}
          allowClear
          placeholder="搜索名称或描述"
          style={{ width: 260 }}
          onSearch={(value) => {
            setKeyword(value.trim())
            setPage(1)
          }}
        />
        <Space size={8}>
          <Switch
            size="small"
            checked={grantedOnly}
            onChange={(checked) => {
              setGrantedOnly(checked)
              setPage(1)
            }}
          />
          <span>仅看已授权</span>
        </Space>
        <Tag color="blue" bordered={false}>
          共 {total} 个
        </Tag>
      </div>

      <Table<RoleGrantResource>
        rowKey="resource_id"
        columns={columns}
        dataSource={items}
        loading={loading}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: ['10', '20', '50'],
          showTotal: (count) => `共 ${count} 条`,
          onChange: (nextPage, nextSize) => {
            setPage(nextSize !== pageSize ? 1 : nextPage)
            setPageSize(nextSize)
          },
        }}
      />
    </div>
  )
}
