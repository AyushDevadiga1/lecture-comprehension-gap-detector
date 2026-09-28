import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import App from './App'

describe('App Component', () => {
  it('renders brand and navigation links', () => {
    render(<App />)
    expect(screen.getByText('LecGap')).toBeInTheDocument()
    expect(screen.getByText('Student Portal')).toBeInTheDocument()
    expect(screen.getByText('Faculty Insights')).toBeInTheDocument()
  })
})
