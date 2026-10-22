import type { Rule } from 'antd/es/form'
import type { PasswordPolicy } from '../api/types'

// 与 Python 的 islower/isupper/isdigit/isalnum 对齐，按 Unicode 类别判定
const CATEGORY_RULES = [/\p{Ll}/u, /\p{Lu}/u, /\p{Nd}/u, /[^\p{L}\p{N}]/u]

export function validatePasswordPolicy(value: string, policy: PasswordPolicy): string | null {
  // 按码点计数，避免增补平面字符在 UTF-16 下被算成两个字符
  if ([...value].length < policy.min_length) {
    return `密码至少 ${policy.min_length} 位`
  }
  if (new TextEncoder().encode(value).length > policy.max_bytes) {
    return `密码不能超过 ${policy.max_bytes} 字节`
  }
  const categories = CATEGORY_RULES.filter((rule) => rule.test(value)).length
  if (categories < policy.min_categories) {
    return `密码需包含大写字母、小写字母、数字、符号中的至少 ${policy.min_categories} 类`
  }
  return null
}

/** 策略缺失时跳过前端校验，由后端统一裁决，避免在客户端重复维护一份默认值。 */
export function passwordRule(policy?: PasswordPolicy | null): Rule {
  return {
    validator: (_, value?: string) => {
      if (!value || !policy) return Promise.resolve()
      const message = validatePasswordPolicy(value, policy)
      return message ? Promise.reject(new Error(message)) : Promise.resolve()
    },
  }
}
