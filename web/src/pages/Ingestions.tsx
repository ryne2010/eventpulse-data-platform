import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, Link } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, type Ingestion } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Page, Separator } from '../portfolio-ui'

function statusBadge(status: string) {
  const s = (status || '').toLowerCase()
  if (s === 'success' || s === 'loaded') return <Badge variant="success">success</Badge>
  if (s === 'processing') return <Badge variant="warning">processing</Badge>
  if (s === 'received') return <Badge variant="outline">received</Badge>
  if (s.startsWith('failed')) return <Badge variant="destructive">failed</Badge>
  return <Badge variant="secondary">{s || '—'}</Badge>
}

function qualityBadge(passed: boolean | null | undefined, status: string) {
  const s = (status || '').toLowerCase()
  if (passed === true) return <Badge variant="success">quality ok</Badge>
  if (passed === false) return <Badge variant="destructive">quality fail</Badge>
  // If terminal but no report, call it out.
  if (s === 'success' || s === 'loaded' || s.startsWith('failed')) return <Badge variant="outline">quality —</Badge>
  return <Badge variant="secondary">quality n/a</Badge>
}

function fmtTime(iso?: string | null) {
  if (!iso) return '—'
  return iso.replace('T', ' ').replace('Z', 'Z')
}

export function IngestionsPage() {
  const navigate = useNavigate()

  const metaQ = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const dsQ = useQuery({ queryKey: ['datasets', 200], queryFn: () => api.listDatasets(200) })

  const [limit, setLimit] = React.useState(150)
  const [status, setStatus] = React.useState<'all' | 'received' | 'processing' | 'success' | 'failed'>('all')
  const [dataset, setDataset] = React.useState<string>('all')
  const [search, setSearch] = React.useState('')

  const ingQ = useQuery({
    queryKey: ['ingestions', limit, dataset, status],
    queryFn: () => api.listIngestions(limit, dataset, status),
    refetchInterval: 4000,
  })

  const demoEnabled = Boolean(metaQ.data?.runtime?.enable_demo_endpoints)
  const [seedLoading, setSeedLoading] = React.useState(false)
  const [seedMsg, setSeedMsg] = React.useState<string | null>(null)

  async function seedParcels() {
    setSeedLoading(true)
    setSeedMsg(null)
    try {
      const res = await api.seedParcels(60)
      setSeedMsg(`Seeded ${res.rows} rows across ${res.ingestions.length} ingestions (seed_id=${res.seed_id}).`)
    } catch (e) {
      setSeedMsg(`Seed failed: ${(e as Error).message}`)
    } finally {
      setSeedLoading(false)
    }
  }

  const items = ingQ.data?.items ?? []

  const filtered = items.filter((ing) => {
    const q = search.trim().toLowerCase()
    if (!q) return true
    return (
      ing.id.toLowerCase().includes(q) ||
      (ing.filename ?? '').toLowerCase().includes(q) ||
      (ing.source ?? '').toLowerCase().includes(q) ||
      (ing.raw_path ?? '').toLowerCase().includes(q)
    )
  })

  const columns = React.useMemo<ColumnDef<Ingestion>[]>(() => {
    return [
      {
        header: 'dataset',
        accessorKey: 'dataset',
        cell: (info) => <span className="font-mono">{String(info.getValue() ?? '')}</span>,
      },
      {
        header: 'file',
        accessorKey: 'filename',
        cell: (info) => <span className="text-muted-foreground">{String(info.getValue() ?? '—')}</span>,
      },
      {
        header: 'status',
        accessorKey: 'status',
        cell: (info) => statusBadge(String(info.getValue() ?? '')),
      },
      {
        header: 'quality',
        accessorKey: 'quality_passed',
        cell: (info) => qualityBadge(info.getValue() as any, info.row.original.status),
      },
      {
        header: 'received',
        accessorKey: 'received_at',
        cell: (info) => <span className="text-muted-foreground">{fmtTime(String(info.getValue() ?? ''))}</span>,
      },
      {
        header: 'attempts',
        accessorKey: 'processing_attempts',
        cell: (info) => <span className="text-muted-foreground">{String(info.getValue() ?? '—')}</span>,
      },
      {
        header: 'error',
        accessorKey: 'error',
        cell: (info) => (
          <span className="text-destructive">{String(info.getValue() ?? '')}</span>
        ),
      },
    ]
  }, [])

  return (
    <Page
      title="Ingestions"
      description="Browse ingestion events. Click a row to inspect quality, drift, lineage, and curated outputs."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/upload" className="no-underline">
            <Button size="sm">Upload</Button>
          </Link>
          {demoEnabled ? (
            <Button size="sm" variant="outline" onClick={seedParcels} disabled={seedLoading}>
              {seedLoading ? 'Seeding…' : 'Seed demo'}
            </Button>
          ) : null}
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Search by id, file, source, or raw path.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Search</div>
              <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="parcel_id, parcels.xlsx…" />
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Dataset</div>
              <Input
                list="datasets"
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
                placeholder="all"
              />
              <datalist id="datasets">
                <option value="all" />
                {(dsQ.data?.items ?? []).map((d) => (
                  <option key={d.dataset} value={d.dataset} />
                ))}
              </datalist>
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Status</div>
              <div className="flex flex-wrap gap-2">
                {(['all', 'received', 'processing', 'success', 'failed'] as const).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setStatus(s)}
                    className={[
                      'rounded-md border px-3 py-1.5 text-xs',
                      status === s ? 'bg-accent text-accent-foreground' : 'text-muted-foreground hover:bg-accent/60',
                    ].join(' ')}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>

            <Separator />

            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">showing: {filtered.length}</Badge>
              <Badge variant="outline">limit: {limit}</Badge>
            </div>

            <div className="space-y-1">
              <div className="text-xs font-medium text-muted-foreground">Fetch limit</div>
              <Input
                type="number"
                min={25}
                max={500}
                value={limit}
                onChange={(e) => setLimit(parseInt(e.target.value || '150', 10))}
              />
            </div>

            {seedMsg ? <div className="text-xs text-muted-foreground">{seedMsg}</div> : null}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader>
            <CardTitle>Recent ingestions</CardTitle>
            <CardDescription>
              Live refresh every few seconds while new events arrive.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {ingQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
            {ingQ.isError ? <div className="text-sm text-destructive">Error: {(ingQ.error as Error).message}</div> : null}

            <DataTable
              data={filtered}
              columns={columns}
              height={620}
              onRowClick={(row) => navigate({ to: '/ingestions/$id', params: { id: row.id } })}
              columnMinWidth={210}
            />
          </CardContent>
        </Card>
      </div>
    </Page>
  )
}
