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
}

export interface NodeMeta {
  type_code: string
  type_key: string
  title: string
  color: string
  category: string
  description: string
  inputs: PortMeta[]
  outputs: PortMeta[]
  config_fields: ConfigFieldMeta[]
}

export interface NodeMetaResponse {
  items: NodeMeta[]
  categories: Record<string, NodeMeta[]>
}

export async function getNodeMeta(): Promise<NodeMetaResponse> {
  return request<NodeMetaResponse>('/admin/node-meta')
}
