import type { ThemeConfig } from 'antd'

// 与 src/styles/tokens.css 保持一致的 JS 侧变量（antd 需要数值，CSS 需要字符串）。
export const tokens = {
  brand: {
    50: '#eef4ff',
    100: '#dbe7ff',
    200: '#c2d6ff',
    300: '#9dbdff',
    500: '#2f6bff',
    600: '#1f57e0',
  },
  bg: {
    page: '#f7f8fc',
    surface: '#ffffff',
    subtle: '#f2f4f9',
    hover: '#f1f4fa',
    sidebar: '#fbfcfe',
    userBubble: '#e8f1ff',
  },
  text: {
    primary: '#14161a',
    secondary: '#5b6472',
    tertiary: '#8a93a3',
    disabled: '#aeb5c2',
    userBubble: '#14428f',
  },
  border: {
    subtle: '#eef0f4',
    default: '#e3e7ee',
    strong: '#d3d9e3',
  },
  radius: {
    sm: 8,
    md: 12,
    lg: 16,
    xl: 20,
    pill: 999,
  },
  fontFamily: `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Microsoft YaHei', sans-serif`,
  status: {
    success: '#16a34a',
    warning: '#d97706',
    danger: '#dc2626',
  },
} as const

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: tokens.brand[500],
    colorLink: tokens.brand[500],
    colorError: tokens.status.danger,
    colorSuccess: tokens.status.success,
    colorWarning: tokens.status.warning,
    colorText: tokens.text.primary,
    colorTextSecondary: tokens.text.secondary,
    colorTextTertiary: tokens.text.tertiary,
    colorBgLayout: tokens.bg.page,
    colorBorder: tokens.border.default,
    colorBorderSecondary: tokens.border.subtle,
    borderRadius: tokens.radius.md,
    borderRadiusLG: tokens.radius.lg,
    borderRadiusSM: tokens.radius.sm,
    fontFamily: tokens.fontFamily,
  },
  components: {
    Button: {
      primaryShadow: 'none',
      fontWeight: 600,
    },
    Card: {
      borderRadiusLG: tokens.radius.lg,
    },
    Input: {
      borderRadius: tokens.radius.md,
    },
  },
}
