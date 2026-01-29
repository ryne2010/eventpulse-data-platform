import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { api, type Ingestion } from '../api'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Page } from '../portfolio-ui'

function statusVariant(status: Ingestion['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'destructive'
  if (status === 'processing') return 'warning'
  return 'secondary'
}

export function IngestionsPage() {
  const q = useQuery({
    queryKey: ['ingestions'],
    queryFn: () => api.listIngestions(250),
  })
  const items = q.data?.items ?? []

  const [searchRaw, setSearchRaw] = React.useState('')
  const [search] = useDebouncedValue(searchRaw, { wait: 200 })

  const filtered = React.useMemo(() => {
    const s = search.trim().toLowerCase()
    if (!s) return items
    return items.filter((it) => `${it.dataset} ${it.filename ?? ''} ${it.id}`.toLowerCase().includes(s))
  }, [items, search])

  const cols = React.useMemo<ColumnDef<Ingestion>[]>(() => {
    return [
      {
        header: 'ID',
        accessorKey: 'id',
        cell: (info) => {
          const id = String(info.getValue())
          return (
            <Link to="/ingestions/$id" params={{ id }} className="font-mono text-xs">
              {id}
            </Link>
          )
        },
      },
      { header: 'Dataset', accessorKey: 'dataset' },
      {
        header: 'File',
        accessorKey: 'filename',
        cell: (info) => <span className="text-muted-foreground">{String(info.getValue() ?? '')}</span>,
      },
      {
        header: 'Status',
        accessorKey: 'status',
        cell: (info) => <Badge variant={statusVariant(info.getValue() as any)}>{String(info.getValue())}</Badge>,
      },
      {
        header: 'Received',
        accessorKey: 'received_at',
        cell: (info) => <span className="text-muted-foreground">{new Date(String(info.getValue())).toLocaleString()}</span>,
      },
      {
        header: 'Processed',
        accessorKey: 'processed_at',
        cell: (info) =>
          info.getValue() ? (
            <span className="text-muted-foreground">{new Date(String(info.getValue())).toLocaleString()}</span>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
      },
    ]
  }, [])

  return (
    <Page
      title="Ingestions"
      description={
        <span>
          Event-driven ingestion records. Designed for idempotency, replay/backfills, and governance-friendly artifacts.
        </span>
      }
      actions={
        <div className="flex items-center gap-2">
          <Badge variant="outline">{filtered.length} items</Badge>
          <Input value={searchRaw} onChange={(e) => setSearchRaw(e.target.value)} placeholder="Search dataset/file/id…" />
        </div>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Pipeline activity</CardTitle>
          <CardDescription>Virtualized list + debounced search (TanStack Virtual + Pacer).</CardDescription>
        </CardHeader>
        <CardContent>
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          <DataTable<Ingestion> data={filtered} columns={cols} />
        </CardContent>
      </Card>
    </Page>
  )
}
