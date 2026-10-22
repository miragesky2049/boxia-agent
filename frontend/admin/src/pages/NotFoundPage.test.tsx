import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import NotFoundPage from './NotFoundPage'

describe('NotFoundPage', () => {
  it('展示 404 提示与返回入口', () => {
    render(
      <MemoryRouter>
        <NotFoundPage />
      </MemoryRouter>,
    )

    expect(screen.getByText('404')).toBeInTheDocument()
    expect(screen.getByText('页面不存在或已被移除。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '返回智能体管理' })).toBeInTheDocument()
  })
})
