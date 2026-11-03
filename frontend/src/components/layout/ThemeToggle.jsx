import { Moon, Sun } from 'lucide-react'
import { useTheme } from '../../app/ThemeProvider'
import { Button, Tooltip } from '../ui'

/** Icon button that switches light/dark. On desktop, hovering (or keyboard-focusing) shows a tooltip below it. */
export default function ThemeToggle({ align = 'center' }) {
  const { theme, toggle } = useTheme()
  const label = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'
  return (
    <Tooltip label={label} align={align}>
      <Button variant="ghost" className="px-2" onClick={toggle} aria-label={label}>
        {theme === 'dark' ? <Sun className="h-[18px] w-[18px]" strokeWidth={1.5} aria-hidden /> : <Moon className="h-[18px] w-[18px]" strokeWidth={1.5} aria-hidden />}
      </Button>
    </Tooltip>
  )
}
