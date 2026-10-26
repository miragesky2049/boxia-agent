import type { Department } from '../api/types'

export interface DepartmentTreeNode {
  value: string
  title: string
  disabled?: boolean
  children?: DepartmentTreeNode[]
}

/**
 * 后端部门树转为 TreeSelect 数据。
 * @param nodes 后端返回的部门树根
 * @param disableLevelFrom 该层级及更深的节点禁选（创建部门选父级时用于前端拦截 10 级上限）
 * @param disableInactive 停用节点禁选（新建/移动部门的父级选择器使用）
 */
export function buildDepartmentTreeData(
  nodes: Department[],
  disableLevelFrom?: number,
  disableInactive = false,
): DepartmentTreeNode[] {
  return nodes.map((node) => {
    const treeNode: DepartmentTreeNode = {
      value: node.id,
      title: node.is_active ? node.name : `${node.name}（已停用）`,
    }
    if (disableLevelFrom !== undefined && node.level >= disableLevelFrom) {
      treeNode.disabled = true
    }
    if (disableInactive && !node.is_active) {
      treeNode.disabled = true
    }
    if (node.children && node.children.length > 0) {
      treeNode.children = buildDepartmentTreeData(
        node.children,
        disableLevelFrom,
        disableInactive,
      )
    }
    return treeNode
  })
}

/** 扁平化部门树，用于按 id 查找节点。 */
export function flattenDepartments(nodes: Department[]): Department[] {
  return nodes.flatMap((node) => [
    node,
    ...flattenDepartments(node.children ?? []),
  ])
}
