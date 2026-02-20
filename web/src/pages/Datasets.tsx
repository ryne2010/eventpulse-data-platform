import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Input, Page } from '../portfolio-ui'

function shortHash(h?: string | null) {
  if (!h) return '—'
  return `${h.slice(0, 8)}…${h.slice(-6)}`
}

export function DatasetsPage() {
  const q = useQuery({ queryKey: ['datasets', 200], queryFn: () => api.listDatasets(200) })
  const [filter, setFilter] = React.useState('')

  const items = q.data?.items ?? []
  const filtered = items.filter((d) => {
    const f = filter.trim().toLowerCase()
    if (!f) return true
    return (
      d.dataset.toLowerCase().includes(f) ||
      (d.contract_description ?? '').toLowerCase().includes(f) ||
      (d.primary_key ?? '').toLowerCase().includes(f)
    )
  })

  return (
    <Page
      title="Datasets"
      description="Explore contract-backed datasets, schema history, curated outputs, and marts."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/upload" className="no-underline">
            <Button size="sm">Upload</Button>
          </Link>
        </div>
      }
    >
      <div className="flex flex-wrap items-center gap-3 mb-4">
        <div className="w-72">
          <Input placeholder="Filter datasets (name, description…)" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
        <Badge variant="outline">count: {filtered.length}</Badge>
      </div>

      {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
      {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}

      <div className="grid gap-4 md:grid-cols-2">
        {filtered.map((d) => (
          <Card key={d.dataset}>
            <CardHeader>
              <CardTitle className="flex items-center justify-between gap-2">
                <Link to="/datasets/$dataset" params={{ dataset: d.dataset }} className="hover:underline">
                  {d.dataset}
                </Link>
                <div className="flex items-center gap-2">
                  {d.curated_table_exists ? <Badge variant="secondary">curated</Badge> : <Badge variant="outline">no curated</Badge>}
                  {d.has_contract ? <Badge variant="outline">contract</Badge> : <Badge variant="warning">no contract</Badge>}
                </div>
              </CardTitle>
              <CardDescription>{d.contract_description ?? '—'}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">ingestions: {d.ingestion_count}</Badge>
                <Badge variant="outline">drift: {d.drift_policy ?? '—'}</Badge>
                <Badge variant="outline">pk: {d.primary_key ?? '—'}</Badge>
              </div>

              <div className="text-xs text-muted-foreground space-y-1">
                <div>latest schema: <span className="font-mono">{shortHash(d.latest_schema_hash)}</span></div>
                <div>schema last seen: {d.schema_last_seen_at ?? '—'}</div>
                <div>last received: {d.last_received_at ?? '—'}</div>
              </div>

              <div className="flex items-center gap-2">
                <Link to="/datasets/$dataset" params={{ dataset: d.dataset }} className="no-underline">
                  <Button size="sm" variant="outline">Open</Button>
                </Link>
                <Link to="/upload" className="no-underline">
                  <Button size="sm">Upload</Button>
                </Link>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </Page>
  )
}
