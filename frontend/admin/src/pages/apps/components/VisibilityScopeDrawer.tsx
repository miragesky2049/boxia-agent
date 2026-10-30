import { App, Button, Drawer, Empty, Radio, Select, Space, Spin, Tree, Typography } from 'antd'
import { useEffect, useMemo, useState } from 'react'

import {
  getAppVisibility,
  replaceAppVisibility,
  type AppVisibility,
} from '../../../api/apps'
import { departmentsApi } from '../../../api/department'
import { usersApi } from '../../../api/users'
import type { Department, UserOption } from '../../../api/types'

interface VisibilityScopeDrawerProps {
  open: boolean
  applicationId: string
  onClose: () => void
  onSaved?: () => void
}

interface TreeNode {
  key: string
  title: string
  children?: TreeNode[]
}

/** 把扁平 Department[]（带 children）转成 antd Tree 需要的 {key, title, children} 结构。 */
function toTreeNodes(depts: Department[]): TreeNode[] {
  return depts.map((d) => ({
    key: d.id,
    title: d.name,
    children: d.children && d.children.length > 0 ? toTreeNodes(d.children) : undefined,
  }))
}

export function VisibilityScopeDrawer({
  open,
  applicationId,
  onClose,
  onSaved,
}: VisibilityScopeDrawerProps) {
  const { message } = App.useApp()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [mode, setMode] = useState<'all' | 'custom'>('all')
  const [treeData, setTreeData] = useState<TreeNode[]>([])
  // include_subtree=true 的部门（含其全部后代）
  const [checkedWithSub, setCheckedWithSub] = useState<string[]>([])
  // include_subtree=false 的部门（仅本部门）
  const [checkedOnly, setCheckedOnly] = useState<string[]>([])
  const [userOptions, setUserOptions] = useState<UserOption[]>([])
  const [selectedUsers, setSelectedUsers] = useState<string[]>([])

  // 打开时加载现有设置与候选数据
  useEffect(() => {
    if (!open || !applicationId) return
    setLoading(true)
    Promise.all([
      getAppVisibility(applicationId),
      departmentsApi.tree(),
      usersApi.options(),
    ])
      .then(([vis, depts, users]) => {
        setMode(vis.mode)
        setTreeData(toTreeNodes(depts))
        setUserOptions(users)
        // 拆分部门到 withSub / only 两个集合
        const withSub: string[] = []
        const only: string[] = []
        for (const d of vis.departments) {
          if (d.include_subtree) withSub.push(d.department_id)
          else only.push(d.department_id)
        }
        setCheckedWithSub(withSub)
        setCheckedOnly(only)
        setSelectedUsers(vis.users)
      })
      .catch((err: unknown) => {
        message.error(err instanceof Error ? err.message : '加载可见范围失败')
      })
      .finally(() => setLoading(false))
  }, [open, applicationId, message])

  // 两个 Tree 的 checkedKeys 互斥：withSub 变化时从 only 中移除相同 key，反之亦然
  const handleWithSubChange = (keys: React.Key[]) => {
    const next = keys as string[]
    setCheckedWithSub(next)
    setCheckedOnly((prev) => prev.filter((k) => !next.includes(k)))
  }
  const handleOnlyChange = (keys: React.Key[]) => {
    const next = keys as string[]
    setCheckedOnly(next)
    setCheckedWithSub((prev) => prev.filter((k) => !next.includes(k)))
  }

  const handleSave = async () => {
    if (mode === 'custom' && checkedWithSub.length === 0 && checkedOnly.length === 0 && selectedUsers.length === 0) {
      message.warning('自定义可见范围至少需要指定一个部门或用户')
      return
    }
    setSaving(true)
    const payload: AppVisibility = {
      mode,
      departments: [
        ...checkedWithSub.map((id) => ({ department_id: id, include_subtree: true })),
        ...checkedOnly.map((id) => ({ department_id: id, include_subtree: false })),
      ],
      users: selectedUsers,
    }
    try {
      await replaceAppVisibility(applicationId, payload)
      message.success('可见范围已保存')
      onSaved?.()
      onClose()
    } catch (err) {
      message.error(err instanceof Error ? err.message : '保存失败')
    } finally {
      setSaving(false)
    }
  }

  // 部门选项 label 渲染：显示名称 + 用户名
  const userSelectOptions = useMemo(
    () =>
      userOptions.map((u) => ({
        value: u.id,
        label: `${u.display_name}（${u.username}）`,
      })),
    [userOptions],
  )

  // 当 mode=all 时，底部不需要保存按钮的禁用条件
  const saveDisabled = loading || saving

  return (
    <Drawer
      title="数据可见范围"
      open={open}
      onClose={onClose}
      width={520}
      footer={
        <Space style={{ float: 'right' }}>
          <Button onClick={onClose}>取消</Button>
          <Button type="primary" loading={saving} disabled={saveDisabled} onClick={handleSave}>
            保存
          </Button>
        </Space>
      }
    >
      <Spin spinning={loading}>
        <Radio.Group
          value={mode}
          onChange={(e) => setMode(e.target.value as 'all' | 'custom')}
          style={{ marginBottom: 16 }}
        >
          <Radio value="all">全员可见（同租户所有用户可在用户端看到该应用）</Radio>
          <Radio value="custom">指定部门和用户可见（白名单模式）</Radio>
        </Radio.Group>

        {mode === 'custom' && (
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <div>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                部门（含子部门）
              </Typography.Title>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                勾选后，该部门及其所有子部门下的用户都能看到该应用。
              </Typography.Paragraph>
              {treeData.length === 0 ? (
                <Empty description="暂无部门" />
              ) : (
                <Tree
                  checkable
                  checkedKeys={checkedWithSub}
                  onCheck={(keys) => handleWithSubChange(keys as React.Key[])}
                  treeData={treeData}
                />
              )}
            </div>

            <div>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                部门（仅本部门）
              </Typography.Title>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                勾选后，仅该部门直属用户能看到该应用（不含子部门）。
              </Typography.Paragraph>
              {treeData.length === 0 ? (
                <Empty description="暂无部门" />
              ) : (
                <Tree
                  checkable
                  checkedKeys={checkedOnly}
                  onCheck={(keys) => handleOnlyChange(keys as React.Key[])}
                  treeData={treeData}
                />
              )}
            </div>

            <div>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                指定用户
              </Typography.Title>
              <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
                直接勾选的用户，无论所属部门都能看到该应用。
              </Typography.Paragraph>
              <Select
                mode="multiple"
                showSearch
                placeholder="搜索并选择用户"
                value={selectedUsers}
                onChange={setSelectedUsers}
                options={userSelectOptions}
                style={{ width: '100%' }}
                optionFilterProp="label"
              />
            </div>
          </Space>
        )}
      </Spin>
    </Drawer>
  )
}
