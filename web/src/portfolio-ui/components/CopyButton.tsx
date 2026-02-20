import * as React from 'react'
import { Button } from '../ui/button'

export type CopyButtonProps = {
  text: string
  label?: string
  copiedLabel?: string
  variant?: 'default' | 'outline' | 'secondary' | 'destructive' | 'ghost' | 'link'
  size?: 'default' | 'sm' | 'lg' | 'icon'
  className?: string
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // fall through to legacy path
  }

  try {
    const el = document.createElement('textarea')
    el.value = text
    el.setAttribute('readonly', 'true')
    el.style.position = 'absolute'
    el.style.left = '-9999px'
    document.body.appendChild(el)
    el.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(el)
    return ok
  } catch {
    return false
  }
}

export function CopyButton(props: CopyButtonProps) {
  const {
    text,
    label = 'Copy',
    copiedLabel = 'Copied',
    variant = 'outline',
    size = 'sm',
    className,
  } = props

  const [copied, setCopied] = React.useState(false)

  async function onCopy() {
    const ok = await copyToClipboard(text)
    if (ok) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    }
  }

  return (
    <Button variant={variant} size={size} onClick={onCopy} className={className}>
      {copied ? copiedLabel : label}
    </Button>
  )
}
