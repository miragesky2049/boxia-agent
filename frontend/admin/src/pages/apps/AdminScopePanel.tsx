import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { App, Alert, Button, Select, Space, Spin, Tag, Typography } from 'antd'
import { useEffect, useState } from 'react'
import { mgmtUnitsApi } from '../../api/mgmtUnit'
import type { MgmtUnit } from '../../api/mgmtUnit'
import {
  addAdminScope,
  listAdminScopes,
  removeAdminScope,
  type AdminScope,
} from '../../api/tenantApps'

interface Props {
  appId: string
  canWrite: boolean
}

/** 管理范围（0069 二期）：应用关联的管理单元增删。mgmt_unit 模式下决定谁可管理该应用。 */
export default function AdminScopePanel({ appId, canWrite }: Props) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(true)
  const [scopes, setScopes] = useState<AdminScope[]>([])
  const [units, setUnits] = useState<MgmtUnit[]>([])
  const [selected, setSelected] = useState<string | undefined>(undefined)

  useEffect(() => {
    ;(async () => {
      setLoading(true)
      try {
        const [scopeList, unitList] = await Promise.all([
          listAdminScopes(appId),
          mgmtUnitsApi.active(),
        ])
        setScopes(scopeList)
        setUnits(unitList)
      } catch (error) {
        message.error(error instanceof Error ? error.message : '加载管理范围失败')
      } finally {
        setLoading(false)
      }
    })()
  }, [appId, message])

  const scopedIds = new Set(scopes.map((item) => item.mgmt_unit_id))
  const candidateOptions = units
    .filter((unit) => !scopedIds.has(unit.id))
    .map((unit) => ({ value: unit.id, label: unit.name }))

  const handleAdd = async () => {
    if (!selected) {
      message.warning('请先选择要关联的管理单元')
      return
    }
    try {
      await addAdminScope(appId, selected)
      const scope = units.find((unit) => unit.id === selected)
      setScopes((prev) => [
        ...prev,
        {
          mgmt_unit_id: selected,
          mgmt_unit_name: scope?.name ?? selected,
          mgmt_unit_code: scope?.code ?? null,
        },
      ])
      setSelected(undefined)
      message.success('管理范围已更新')
    } catch (error) {
      message.error(error instanceof Error ? error.message : '新增管理范围失败')
    }
  }

  const handleRemove = async (mgmtUnitId: string) => {
    try {
      await removeAdminScope(appId, mgmtUnitId)
      setScopes((prev) => prev.filter((item) => item.mgmt_unit_id !== mgmtUnitId))
      message.success('已解除关联')
    } catch (error) {
      const detail = error as { status?: number; message?: string }
      if (detail.status === 403) {
        message.error('当前账号不可管理该应用（未获得关联管理单元的授权）')
      } else {
        message.error(error instanceof Error ? error.message : '解除关联失败')
      }
    }
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 32 }}>
        <Spin />
      </div>
    )
  }

  return (
    <div>
      {!canWrite && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="当前角色缺少管理范围编辑权限，仅可查看"
        />
      )}
      <Space direction="vertical" style={{ width: '100%' }} size={8}>
        {scopes.map((scope) => (
          <Space key={scope.mgmt_unit_id} align="center">
            <Tag bordered={false}>{scope.mgmt_unit_name}</Tag>
            {scope.mgmt_unit_code && (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {scope.mgmt_unit_code}
              </Typography.Text>
            )}
            {canWrite && (
              <Button
                size="small"
                type="text"
                danger
                icon={<DeleteOutlined />}
                onClick={() => void handleRemove(scope.mgmt_unit_id)}
              />
            )}
          </Space>
        ))}
        {scopes.length === 0 && (
          <Typography.Text type="secondary">
            暂未关联管理单元；管理范围为「管理单元」模式的应用，仅被授予关联管理单元的账号可管理
          </Typography.Text>
        )}
        {canWrite && (
          <Space>
            <Select
              value={selected}
              style={{ width: 260 }}
              showSearch
              optionFilterProp="label"
              placeholder="选择管理单元"
              options={candidateOptions}
              onChange={(value: string) => setSelected(value)}
            />
            <Button icon={<PlusOutlined />} onClick={() => void handleAdd()}>
              添加关联
            </Button>
          </Space>
        )}
      </Space>
    </div>
  )
}
