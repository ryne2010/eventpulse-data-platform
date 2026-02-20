import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, type AuditEvent } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Label, Page, Separator } from '../portfolio-ui'

function truncate(s: string, n = 120) {
  const t = s ?? ''
  if (t.length <= n) return t
  return `${t.slice(0, n - 1)}…`
}

function formatTime(iso?: string | null) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch {
    return iso
  }
}

function jsonPreview(v: any) {
  try {
    const s = JSON.stringify(v)
    return truncate(s, 140)
  } catch {
    return truncate(String(v ?? ''), 140)
  }
}

export function AuditPage() {
  const nav = useNavigate()

  const dsQ = useQuery({ queryKey: ['datasets', 200], queryFn: () => api.listDatasets(200) })

  const [dataset, setDataset] = React.useState('all')
  const [eventType, setEventType] = React.useState('all')
  const [ingestionId, setIngestionId] = React.useState('')
  const [actor, setActor] = React.useState('')
  const [limit, setLimit] = React.useState(200)

  const q = useQuery({
    queryKey: ['audit_events', limit, dataset, eventType, ingestionId, actor],
    queryFn: () =>
      api.auditEvents(
        limit,
        dataset === 'all' ? undefined : dataset,
        ingestionId.trim() ? ingestionId.trim() : undefined,
        eventType === 'all' ? undefined : eventType,
        actor.trim() ? actor.trim() : undefined,
      ),
    refetchInterval: 10_000,
  })

  const items = q.data?.items ?? []

  const columns: ColumnDef<AuditEvent>[] = [
    {
      header: 'time',
      accessorKey: 'created_at',
      cell: (info) => <span className="font-mono text-xs">{formatTime(info.getValue() as string)}</span>,
    },
    {
      header: 'event',
      accessorKey: 'event_type',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'dataset',
      accessorKey: 'dataset',
      cell: (info) => {
        const v = info.getValue() as any
        return v ? <Badge variant="outline">{String(v)}</Badge> : <span className="text-muted-foreground">—</span>
      },
    },
    {
      header: 'actor',
      accessorKey: 'actor',
      cell: (info) => {
        const v = info.getValue() as any
        return v ? <span className="text-muted-foreground">{String(v)}</span> : <span className="text-muted-foreground">—</span>
      },
    },
    {
      header: 'ingestion',
      accessorKey: 'ingestion_id',
      cell: (info) => {
        const v = info.getValue() as any
        if (!v) return <span className="text-muted-foreground">—</span>
        const id = String(v)
        return <span className="font-mono text-xs">{truncate(id, 16)}</span>
      },
    },
    {
      header: 'details',
      accessorKey: 'details',
      cell: (info) => <span className="font-mono text-xs text-muted-foreground">{jsonPreview(info.getValue())}</span>,
    },
  ]

  const eventTypes = Array.from(new Set(items.map((e) => e.event_type))).sort()

  return (
    <Page
      title="Audit log"
      description="Operational governance: a lightweight audit trail for ingestions, contracts, and ops actions."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/trends" className="no-underline">
            <Button size="sm" variant="outline">Trends</Button>
          </Link>
          <Link to="/ingestions" className="no-underline">
            <Button size="sm" variant="outline">Ingestions</Button>
          </Link>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Refine events by dataset, type, or ingestion id.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label>Dataset</Label>
              <Input list="audit-datasets" value={dataset} onChange={(e) => setDataset(e.target.value)} />
              <datalist id="audit-datasets">
                <option value="all" />
                {(dsQ.data?.items ?? []).map((d) => (
                  <option key={d.dataset} value={d.dataset} />
                ))}
              </datalist>
            </div>

            <div className="space-y-1">
              <Label>Event type</Label>
              <Input list="audit-event-types" value={eventType} onChange={(e) => setEventType(e.target.value)} />
              <datalist id="audit-event-types">
                <option value="all" />
                {eventTypes.map((t) => (
                  <option key={t} value={t} />
                ))}
              </datalist>
              <div className="text-xs text-muted-foreground">
                Tip: try <span className="font-mono">ingestion.failed_quality</span> or <span className="font-mono">contract.updated</span>.
              </div>
            </div>

            <div className="space-y-1">
              <Label>Ingestion id</Label>
              <Input value={ingestionId} onChange={(e) => setIngestionId(e.target.value)} placeholder="optional" />
            </div>

            <div className="space-y-1">
              <Label>Actor</Label>
              <Input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="optional (device_id, user…)" />
              <div className="text-xs text-muted-foreground">
                Useful for device triage (e.g. <span className="font-mono">device.enrolled</span> events).
              </div>
            </div>

            <Separator />

            <div className="space-y-1">
              <Label>Limit</Label>
              <Input
                type="number"
                min={1}
                max={1000}
                value={limit}
                onChange={(e) => setLimit(Number(e.target.value))}
              />
              <div className="text-xs text-muted-foreground">Max 1000 events.</div>
            </div>

            <Button variant="outline" onClick={() => q.refetch()}>Refresh</Button>
          </CardContent>
        </Card>

        <div className="space-y-3 md:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">events: {items.length}</Badge>
            {q.isFetching ? <Badge variant="warning">updating…</Badge> : <Badge variant="success">live</Badge>}
            {q.error ? <Badge variant="destructive">error</Badge> : null}
          </div>

          <DataTable
            data={items}
            columns={columns}
            height={620}
            columnMinWidth={220}
            onRowClick={(row) => {
              if (row.ingestion_id) {
                nav({ to: '/ingestions/$id', params: { id: row.ingestion_id } })
              }
            }}
          />

          <div className="text-xs text-muted-foreground">
            Click a row with an ingestion id to open the ingestion detail.
          </div>
        </div>
      </div>
    </Page>
  )
}
