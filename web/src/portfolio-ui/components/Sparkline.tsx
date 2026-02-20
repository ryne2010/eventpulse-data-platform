import React from 'react'

import { cn } from '../lib/utils'

type SparklineProps = {
  values: Array<number | null | undefined>
  width?: number
  height?: number
  strokeWidth?: number
  className?: string
  title?: string
}

/**
 * Tiny, dependency-free sparkline.
 *
 * Intended for dashboards / “at a glance” trends.
 * Uses currentColor so theme can control styling.
 */
export function Sparkline(props: SparklineProps) {
  const width = props.width ?? 160
  const height = props.height ?? 32
  const strokeWidth = props.strokeWidth ?? 1.5

  const clean = React.useMemo(
    () => props.values.filter((v): v is number => typeof v === 'number' && Number.isFinite(v)),
    [props.values],
  )

  // Not enough data for a meaningful line.
  if (clean.length < 2) {
    return <div className={cn('h-8', props.className)} />
  }

  const min = Math.min(...clean)
  const max = Math.max(...clean)
  const range = max - min || 1
  const pad = 1
  const n = clean.length
  const w = Math.max(8, width)
  const h = Math.max(8, height)

  const points = clean
    .map((v, i) => {
      const x = pad + (i / (n - 1)) * (w - 2 * pad)
      const y = h - pad - ((v - min) / range) * (h - 2 * pad)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label={props.title ?? 'trend'}
      className={cn('block', props.className)}
    >
      {props.title ? <title>{props.title}</title> : null}
      <polyline
        fill="none"
        stroke="currentColor"
        strokeWidth={strokeWidth}
        vectorEffect="non-scaling-stroke"
        points={points}
      />
    </svg>
  )
}
