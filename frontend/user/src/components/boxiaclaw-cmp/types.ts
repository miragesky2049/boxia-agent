import type { CSSProperties } from 'react'

/**
 * @boxiaclaw-elearning-cmp/upload-material 组件类型定义
 *
 * 用于自由剧本创建流程中引导用户上传业务资料（产品知识 / 示例对话 /
 * 对话方法论 / 评分规则）。上传完成后由后端解析并通过
 * GetSceneRobotDataMdContext 返回四类总结，agent 据此生成剧本。
 */

/** 单文件状态：uploading 上传中 -> parsing 解析中 -> done 完成 / error 失败 */
export type UploadMaterialFileStatus = 'uploading' | 'parsing' | 'done' | 'error'

/** 已上传文件元数据 */
export interface UploadedMaterialFile {
  id: string
  name: string
  size: number
  status: UploadMaterialFileStatus
  /** 失败原因 */
  error?: string
  /** 后端解析后返回的资料 id，用于后续 GetSceneRobotDataMdContext */
  materialId?: string
}

/** 自定义上传请求签名，默认走内置模拟实现，后端就绪后由调用方注入 */
export type UploadMaterialRequest = (
  file: File,
  sceneRobotId?: string,
) => Promise<{ materialId: string }>

export interface UploadMaterialProps {
  /** 剧本 id，随上传请求回传后端 */
  sceneRobotId?: string
  /** 是否禁用交互（生成中/已完成） */
  disabled?: boolean
  /** 全部文件上传并解析完成回调 */
  onUploaded?: (files: UploadedMaterialFile[]) => void
  /** 用户点击"跳过资料" */
  onSkip?: () => void
  /** 自定义上传实现，未提供时使用内置模拟（仅用于前端联调） */
  uploadRequest?: UploadMaterialRequest
  style?: CSSProperties
  className?: string
}

/**
 * @boxiaclaw-elearning-cmp/action-bar 组件类型定义
 *
 * 在剧本生成完成后渲染"保存并进入剧本详情"等动作按钮。
 */

/** 按钮视觉风格 */
export type ActionBarActionType = 'primary' | 'secondary' | 'default' | 'text'

/** 单个动作定义 */
export interface ActionBarAction {
  /** 按钮文案 */
  label: string
  /** 视觉风格，默认 secondary */
  type?: ActionBarActionType
  /** 是否禁用 */
  disabled?: boolean
  /**
   * 动作配置。type 语义由平台约定，目前已知：
   * - goto_free_detail：保存并进入自由剧本详情
   */
  action?: {
    type: string
    [key: string]: unknown
  }
}

export interface ActionBarProps {
  /** 按钮对齐方向，默认 left */
  placement?: 'left' | 'right' | 'center'
  /** 动作列表 */
  actions: ActionBarAction[]
  /**
   * 动作点击回调。未提供时按内置默认行为处理：
   * - goto_free_detail：跳转 /scene-robots/{sceneRobotId}（或 /scene-robots）
   */
  onAction?: (action: ActionBarAction, index: number) => void
  style?: CSSProperties
  className?: string
}
