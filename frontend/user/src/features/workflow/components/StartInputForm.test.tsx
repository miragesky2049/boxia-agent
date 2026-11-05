import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { WorkflowSchema } from '../types'
import StartInputForm from './StartInputForm'

function schemaWith(...names: (keyof typeof PARAMS)[]): WorkflowSchema {
  return {
    application_id: 'app-1',
    name: '测试工作流',
    description: '',
    flow_type: 'workflow',
    inputs: names.map((n) => PARAMS[n]),
    has_human_approval: false,
  }
}

const PARAMS = {
  text: { name: 'query', type: 'string', required: true, description: '查询词', default_value: null },
  count: { name: 'count', type: 'number', required: false, description: '', default_value: null },
  flag: { name: 'flag', type: 'boolean', required: false, description: '', default_value: null },
  obj: { name: 'obj', type: 'object', required: false, description: '', default_value: null },
} as const

function submit() {
  fireEvent.click(screen.getByRole('button', { name: '开始运行' }))
}

describe('StartInputForm 校验与提交', () => {
  it('必填项为空时不提交并提示', () => {
    const onSubmit = vi.fn()
    render(<StartInputForm schema={schemaWith('text')} running={false} onSubmit={onSubmit} />)
    submit()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('请填写查询词')).toBeInTheDocument()
  })

  it('合法输入按类型转换后提交', () => {
    const onSubmit = vi.fn()
    render(<StartInputForm schema={schemaWith('text', 'count', 'flag')} running={false} onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText(/query/), { target: { value: '市场' } })
    fireEvent.change(screen.getByLabelText(/count/), { target: { value: '7' } })
    fireEvent.change(screen.getByLabelText(/flag/), { target: { value: 'true' } })
    submit()
    expect(onSubmit).toHaveBeenCalledWith({ query: '市场', count: 7, flag: true })
  })

  it('非法 JSON 对象提示解析失败且不提交', () => {
    const onSubmit = vi.fn()
    render(<StartInputForm schema={schemaWith('obj')} running={false} onSubmit={onSubmit} />)
    fireEvent.change(screen.getByLabelText(/obj/), { target: { value: '{bad json' } })
    submit()
    expect(onSubmit).not.toHaveBeenCalled()
    expect(screen.getByText('JSON 解析失败')).toBeInTheDocument()
  })

  it('校验错误修复后空 notice 键不再阻塞提交', () => {
    const onSubmit = vi.fn()
    render(<StartInputForm schema={schemaWith('text')} running={false} onSubmit={onSubmit} />)
    submit()
    fireEvent.change(screen.getByLabelText(/query/), { target: { value: '补上' } })
    submit()
    expect(onSubmit).toHaveBeenCalledWith({ query: '补上' })
  })
})
