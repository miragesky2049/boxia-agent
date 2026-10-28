/**
 * @senclaw-elearning-cmp 组件库
 *
 * boxia AI 陪练自由剧本创建流程中使用的前端组件，对应 skill free-script-creation-v8
 * 中声明的两个 uicomponents：
 *
 * - UploadMaterial：资料上传入口（阶段一 P1）
 * - ActionBar：完成动作按钮（阶段三 P3）
 *
 * 用法：
 * ```tsx
 * import { UploadMaterial, ActionBar } from './components/senclaw-cmp'
 * ```
 */
export { default as UploadMaterial } from './UploadMaterial'
export { default as ActionBar } from './ActionBar'
export type {
  UploadedMaterialFile,
  UploadMaterialFileStatus,
  UploadMaterialProps,
  UploadMaterialRequest,
} from './types'
export type {
  ActionBarAction,
  ActionBarActionType,
  ActionBarProps,
} from './types'
