import * as React from 'react'
import { cn } from '../lib/utils'

export type TabItem = {
  value: string
  label: string
  disabled?: boolean
}

export type TabsProps = {
  items: TabItem[]
  value: string
  onValueChange: (value: string) => void
  className?: string
}

/**
 * A tiny tabs/segmented-control component.
 *
 * We keep this local to avoid pulling in a heavier headless UI dependency.
 */
export function Tabs(props: TabsProps) {
  return (
    <div className={cn('flex flex-wrap gap-2', props.className)}>
      {props.items.map((it) => {
        const active = it.value === props.value
        return (
          <button
            key={it.value}
            type="button"
            disabled={it.disabled}
            onClick={() => props.onValueChange(it.value)}
            className={cn(
              'rounded-md border px-3 py-1.5 text-sm transition-colors',
              active ? 'bg-accent text-accent-foreground' : 'bg-background text-muted-foreground hover:bg-accent/60',
              it.disabled ? 'opacity-50 cursor-not-allowed' : '',
            )}
          >
            {it.label}
          </button>
        )
      })}
    </div>
  )
}
