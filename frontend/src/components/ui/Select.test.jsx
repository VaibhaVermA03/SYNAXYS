import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Select from './Select'

const OPTIONS = [{ value: 'a', label: 'Apple' }, { value: 'b', label: 'Banana' }, { value: 'c', label: 'Cherry' }]
function Harness({ initial = 'a', onChange = () => {}, ...rest }) {
  const [v, setV] = useState(initial)
  return <Select ariaLabel="Fruit" value={v} onChange={(x) => { setV(x); onChange(x) }} options={OPTIONS} {...rest} />
}
const trigger = () => screen.getByRole('combobox', { name: 'Fruit' })
const gone = () => waitFor(() => expect(screen.queryByRole('listbox')).not.toBeInTheDocument())

afterEach(() => vi.restoreAllMocks())

describe('Select', () => {
  it('shows the selected label, closed by default, with correct ARIA state', () => {
    render(<Harness initial="b" />)
    expect(trigger()).toHaveTextContent('Banana')
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('opens on click, marks the current option, selects with the mouse and closes', async () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await userEvent.click(trigger())
    expect(trigger()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('option', { name: 'Apple' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getAllByRole('option')).toHaveLength(3)
    await userEvent.click(screen.getByRole('option', { name: 'Cherry' }))
    expect(onChange).toHaveBeenCalledWith('c')
    expect(trigger()).toHaveTextContent('Cherry')
    await gone()
  })

  it('renders trigger and options inside ONE rounded container that is exactly as wide as the trigger', async () => {
    render(<Harness />)
    await userEvent.click(trigger())
    const shell = screen.getByRole('listbox').parentElement
    const wrapper = trigger().parentElement
    expect(wrapper).toContainElement(shell)                                // same parent container as the trigger
    expect(shell).toHaveClass('rounded-xl', 'inset-x-0')                   // one rounded shell spanning the wrapper's full width
    expect(wrapper).toHaveClass('w-full')                                  // width is whatever the parent gives it
    expect(trigger()).toHaveClass('rounded-xl')                            // trigger uses the same corner radius
    expect(trigger()).toHaveClass('z-[6]')                                 // stays BELOW header (z-20), drawer overlay (z-30) and sidebar (z-40)
  })

  it('supports the keyboard: arrows move, Enter selects, Home/End jump, focus stays on the trigger', async () => {
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await userEvent.tab()
    expect(trigger()).toHaveFocus()
    await userEvent.keyboard('{ArrowDown}')                                // opens with the current option active
    expect(trigger()).toHaveAttribute('aria-expanded', 'true')
    await userEvent.keyboard('{ArrowDown}')
    expect(trigger()).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: 'Banana' }).id)
    await userEvent.keyboard('{End}')
    expect(trigger()).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: 'Cherry' }).id)
    await userEvent.keyboard('{Home}')
    expect(trigger()).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: 'Apple' }).id)
    await userEvent.keyboard('{ArrowDown}{Enter}')
    expect(onChange).toHaveBeenCalledWith('b')
    expect(trigger()).toHaveFocus()
    await gone()
  })

  it('opens with Space and jumps with type-ahead', async () => {
    render(<Harness />)
    await userEvent.tab()
    await userEvent.keyboard('c')
    expect(trigger()).toHaveAttribute('aria-expanded', 'true')
    expect(trigger()).toHaveAttribute('aria-activedescendant', screen.getByRole('option', { name: 'Cherry' }).id)
    await userEvent.keyboard('{Escape}')
    await gone()
    await userEvent.keyboard(' ')
    expect(trigger()).toHaveAttribute('aria-expanded', 'true')
  })

  it('Escape closes only the dropdown (not a surrounding dialog) and returns focus', async () => {
    const outer = vi.fn()
    document.addEventListener('keydown', outer)
    const onChange = vi.fn()
    render(<Harness onChange={onChange} />)
    await userEvent.click(trigger())
    await userEvent.keyboard('{Escape}')
    expect(outer).not.toHaveBeenCalled()                                   // a dialog listening on document never sees this Escape
    expect(onChange).not.toHaveBeenCalled()
    expect(trigger()).toHaveFocus()
    await gone()
    await userEvent.keyboard('{Escape}')                                   // closed: Escape is not swallowed
    expect(outer).toHaveBeenCalled()
    document.removeEventListener('keydown', outer)
  })

  it('closes when clicking outside', async () => {
    render(<div><Harness /><button>elsewhere</button></div>)
    await userEvent.click(trigger())
    await userEvent.click(screen.getByRole('button', { name: 'elsewhere' }))
    await gone()
    expect(trigger()).toHaveAttribute('aria-expanded', 'false')
  })

  it('does nothing when disabled and shows a placeholder / empty state when needed', async () => {
    const { unmount } = render(<Harness disabled />)
    await userEvent.click(trigger())
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    unmount()
    render(<Select ariaLabel="Fruit" value="" onChange={() => {}} options={[]} placeholder="Pick one" />)
    expect(trigger()).toHaveTextContent('Pick one')
    await userEvent.click(trigger())
    expect(screen.getByText('No options')).toBeInTheDocument()
  })

  it('compact size keeps the same single-container structure', async () => {
    render(<Harness size="sm" />)
    expect(trigger().parentElement).toHaveClass('h-8')
    await userEvent.click(trigger())
    expect(trigger().parentElement).toContainElement(screen.getByRole('listbox'))
  })
})
