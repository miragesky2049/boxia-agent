import { request } from './client'

export interface PortMeta {
  name: string
  type: string
  label: string
  required: boolean
}

export interface ConfigFieldMeta {
  name: string
  label: string
  field_type: string
  options: Array<{ value: string }>
  default: unknown
  required: boolean
  placeholder: string
  description: string
  group: string
}

export interface NodeCapabilities {
  runnable: boolean
  copyable: boolean
  deletable: boolean
  has_subgraph: boolean
  has_outputs: boolean
}

export interface NodeMeta {
  type_code: string
  type_key: string
  title: string
  color: string
  category: string
  description: string
  icon: string
  subtitle_hint: string
  next_recommendations: string[]
  capabilities: NodeCapabilities
  inputs: PortMeta[]
  outputs: PortMeta[]
  config_fields: ConfigFieldMeta[]
  // 占位节点：available=false 时前端置灰，hover 显示 unavailable_reason
  available?: boolean
  unavailable_reason?: string
}

export interface NodeMetaResponse {
  items: NodeMeta[]
  categories: Record<string, NodeMeta[]>
}

export async function getNodeMeta(): Promise<NodeMetaResponse> {
  return request<NodeMetaResponse>('/admin/node-meta')
}
