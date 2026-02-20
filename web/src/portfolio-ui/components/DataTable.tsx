import * as React from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from '@tanstack/react-table'
import { cn } from '../lib/utils'

export type DataTableProps<T> = {
  data: T[]
  columns: ColumnDef<T, any>[]
  height?: number
  className?: string
  onRowClick?: (row: T) => void
  columnMinWidth?: number
}

export function DataTable<T>(props: DataTableProps<T>) {
  const parentRef = React.useRef<HTMLDivElement>(null)
  const columnMinWidth = props.columnMinWidth ?? 220

  const table = useReactTable({
    data: props.data,
    columns: props.columns,
    getCoreRowModel: getCoreRowModel(),
  })

  const rows = table.getRowModel().rows
  const headerGroup = table.getHeaderGroups().slice(-1)[0]
  const leafColumnCount = headerGroup?.headers.length ?? 0
  const gridTemplateColumns =
    leafColumnCount > 0 ? `repeat(${leafColumnCount}, ${columnMinWidth}px)` : `repeat(1, ${columnMinWidth}px)`

  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 44,
    overscan: 10,
  })

  return (
    <div
      ref={parentRef}
      className={cn(
        'rounded-md border bg-card text-card-foreground',
        'overflow-auto',
        props.className,
      )}
      style={{ height: props.height ?? 520 }}
    >
      <div
        role="table"
        className="text-sm"
        style={{
          width: Math.max(1, leafColumnCount) * columnMinWidth,
          minWidth: '100%',
        }}
      >
        <div role="rowgroup" className="sticky top-0 z-10 bg-card">
          <div
            role="row"
            className="grid border-b"
            style={{
              gridTemplateColumns,
            }}
          >
            {headerGroup?.headers.map((header) => (
              <div
                role="columnheader"
                key={header.id}
                className="min-w-0 px-4 py-2 text-left font-medium text-muted-foreground"
              >
                <div className="overflow-hidden text-ellipsis whitespace-nowrap">
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div role="rowgroup" className="relative" style={{ height: rowVirtualizer.getTotalSize() }}>
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const row = rows[virtualRow.index]
            return (
              <div
                role="row"
                key={row.id}
                className={cn('absolute left-0 right-0 border-b last:border-b-0 hover:bg-accent/50', props.onRowClick ? 'cursor-pointer' : '')}
                style={{
                  transform: `translateY(${virtualRow.start}px)`,
                  display: 'grid',
                  gridTemplateColumns,
                }}
                onClick={(e) => {
                  if (!props.onRowClick) return
                  const target = e.target as HTMLElement | null
                  // Avoid row navigation when the user clicks interactive controls.
                  if (
                    target?.closest(
                      'button, a, input, textarea, select, option, [role="button"], [data-no-row-click]',
                    )
                  ) {
                    return
                  }
                  props.onRowClick(row.original)
                }}
              >
                {row.getVisibleCells().map((cell) => (
                  <div
                    role="cell"
                    key={cell.id}
                    className="min-w-0 px-4 py-2 align-middle"
                  >
                    <div className="overflow-hidden text-ellipsis whitespace-nowrap">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </div>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
