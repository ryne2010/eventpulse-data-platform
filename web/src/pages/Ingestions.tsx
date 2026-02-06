import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet'
import { api, type Ingestion } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Page } from '../portfolio-ui'

function statusVariant(status: Ingestion['status']): 'success' | 'warning' | 'destructive' | 'secondary' {
  if (status === 'success') return 'success'
  if (status === 'failed') return 'destructive'
  if (status === 'processing') return 'warning'
  return 'secondary'
}

export function IngestionsPage() {
  const queryClient = useQueryClient()
  const [selectedIngestionId, setSelectedIngestionId] = React.useState<string | null>(null)

  const parcels = useQuery({
    queryKey: ['curated', 'parcels', 50],
    queryFn: () => api.curatedSample('parcels', 50),
  })

  const seed = useMutation({
    mutationFn: () => api.seedParcels(50),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['curated', 'parcels', 50] })
      await queryClient.invalidateQueries({ queryKey: ['ingestions'] })
    },
  })

  const q = useQuery({
    queryKey: ['ingestions'],
    queryFn: () => api.listIngestions(250),
  })
  const items = q.data?.items ?? []

  const preview = useQuery({
    queryKey: ['ingestionPreview', selectedIngestionId],
    queryFn: () => api.ingestionPreview(selectedIngestionId!, 12),
    enabled: Boolean(selectedIngestionId),
  })

  const selected = useQuery({
    queryKey: ['ingestion', selectedIngestionId],
    queryFn: () => api.getIngestion(selectedIngestionId!),
    enabled: Boolean(selectedIngestionId),
  })

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
            <Link to="/ingestions/$id" params={{ id }} className="font-mono text-xs" onClick={(e) => e.stopPropagation()}>
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

  const parcelRows = (parcels.data?.rows ?? []) as Record<string, any>[]
  const points = React.useMemo(() => {
    const out: {
      id: string
      parcel_id: string
      situs_address: string
      lat: number
      lon: number
      sale_price: number | null
      sale_date: string | null
      recording_date: string | null
      doc_number: string | null
      deed_type: string | null
      book: string | null
      page: string | null
    }[] = []
    for (const r of parcelRows) {
      const lat = Number(r.lat)
      const lon = Number(r.lon)
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) continue
      const price = r.sale_price ?? r.assessed_value
      out.push({
        id: String(r.parcel_id ?? r._ingestion_id ?? Math.random()),
        parcel_id: String(r.parcel_id ?? ''),
        situs_address: String(r.situs_address ?? ''),
        lat,
        lon,
        sale_price: price == null ? null : Number(price),
        sale_date: r.sale_date ? String(r.sale_date) : null,
        recording_date: r.recording_date ? String(r.recording_date) : null,
        doc_number: r.doc_number ? String(r.doc_number) : null,
        deed_type: r.deed_type ? String(r.deed_type) : null,
        book: r.book ? String(r.book) : null,
        page: r.page ? String(r.page) : null,
      })
    }
    return out
  }, [parcelRows])

  const center = React.useMemo(() => {
    if (!points.length) return { lat: 37.4083, lon: -102.6146 }
    const lat = points.reduce((acc, p) => acc + p.lat, 0) / points.length
    const lon = points.reduce((acc, p) => acc + p.lon, 0) / points.length
    return { lat, lon }
  }, [points])

  const priceStats = React.useMemo(() => {
    const prices = points
      .map((r) => r.sale_price)
      .filter((n) => n != null && Number.isFinite(n)) as number[]
    prices.sort((a, b) => a - b)
    const median = prices.length ? prices[Math.floor(prices.length / 2)] : null
    const p25 = prices.length ? prices[Math.floor(prices.length * 0.25)] : null
    const p75 = prices.length ? prices[Math.floor(prices.length * 0.75)] : null
    return { count: prices.length, median, p25, p75 }
  }, [points])

  const histogram = React.useMemo(() => {
    const prices = points
      .map((r) => r.sale_price)
      .filter((n) => n != null && Number.isFinite(n)) as number[]
    if (!prices.length) return { bins: [] as { x0: number; x1: number; count: number }[], maxCount: 0 }
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const binCount = 10
    const width = Math.max(1, (max - min) / binCount)
    const bins = Array.from({ length: binCount }, (_, i) => ({
      x0: Math.floor(min + i * width),
      x1: Math.ceil(min + (i + 1) * width),
      count: 0,
    }))
    for (const p of prices) {
      const idx = Math.min(binCount - 1, Math.max(0, Math.floor((p - min) / width)))
      bins[idx].count += 1
    }
    const maxCount = Math.max(...bins.map((b) => b.count))
    return { bins, maxCount }
  }, [points])

  const yearly = React.useMemo(() => {
    const byYear = new Map<number, number[]>()
    for (const r of points) {
      const y = new Date(r.sale_date ?? '').getUTCFullYear()
      if (!Number.isFinite(y)) continue
      const price = r.sale_price
      if (price == null || !Number.isFinite(price)) continue
      const arr = byYear.get(y) ?? []
      arr.push(price)
      byYear.set(y, arr)
    }
    const years = Array.from(byYear.keys()).sort((a, b) => a - b)
    const yearPoints = years.map((y) => {
      const arr = (byYear.get(y) ?? []).slice().sort((a, b) => a - b)
      const med = arr.length ? arr[Math.floor(arr.length / 2)] : 0
      return { year: y, median: med }
    })
    const min = yearPoints.length ? Math.min(...yearPoints.map((p) => p.median)) : 0
    const max = yearPoints.length ? Math.max(...yearPoints.map((p) => p.median)) : 1
    return { points: yearPoints, min, max }
  }, [points])

  function fmtUsd(n: number | null) {
    if (n == null) return '—'
    return n.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
  }

  function fmtDate(v: string | null) {
    if (!v) return '—'
    // ISO timestamps are common here; prefer a stable YYYY-MM-DD display.
    if (v.length >= 10) return v.slice(0, 10)
    return v
  }

  const previewRows = preview.data?.rows ?? []
  const previewColumns = React.useMemo<ColumnDef<Record<string, any>>[]>(() => {
    const keys = previewRows.length ? Object.keys(previewRows[0]) : []
    return keys.map((k) => ({
      header: k,
      accessorKey: k,
      cell: (info) => {
        const v = info.getValue()
        return <span className="text-muted-foreground">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
      },
    }))
  }, [previewRows])

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
      {selectedIngestionId ? (
        <div className="fixed inset-0 z-[2000]">
          <div className="absolute inset-0 bg-black/50" onClick={() => setSelectedIngestionId(null)} />
          <div className="absolute left-1/2 top-16 w-[min(1100px,calc(100vw-2rem))] -translate-x-1/2">
            <Card className="shadow-2xl">
              <CardHeader>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <CardTitle>Ingestion preview</CardTitle>
                    <CardDescription className="break-all">
                      {selectedIngestionId} {selected.data?.ingestion?.dataset ? `• dataset: ${selected.data.ingestion.dataset}` : ''}
                    </CardDescription>
                  </div>
                  <Button variant="outline" size="sm" onClick={() => setSelectedIngestionId(null)}>
                    Close
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                {selected.isLoading || preview.isLoading ? (
                  <div className="text-sm text-muted-foreground">Loading…</div>
                ) : null}
                {selected.isError ? <div className="text-sm text-destructive">Error: {(selected.error as Error).message}</div> : null}
                {preview.isError ? <div className="text-sm text-destructive">Error: {(preview.error as Error).message}</div> : null}

                {selected.data ? (
                  <pre className="max-h-[180px] overflow-auto rounded-md border bg-muted/30 p-4 text-xs">
{JSON.stringify(selected.data.ingestion, null, 2)}
                  </pre>
                ) : null}

                <div className="flex items-center gap-2">
                  <Badge variant="outline">curated rows</Badge>
                  <Badge variant="secondary">{previewRows.length}</Badge>
                  {preview.data?.table_exists === false ? <Badge variant="secondary">table missing</Badge> : null}
                </div>
                <DataTable<Record<string, any>> data={previewRows} columns={previewColumns} height={360} />
              </CardContent>
            </Card>
          </div>
        </div>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Parcels (curated recorder sales) — Springfield, CO</CardTitle>
          <CardDescription>
            Synthetic county-recorder-style sales (fake prices and parties) seeded into the <span className="font-mono">parcels</span>{' '}
            ingestion pipeline, then displayed from curated Postgres.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <div className="h-[360px] overflow-hidden rounded-md border">
              <MapContainer
                center={[center.lat, center.lon]}
                zoom={13}
                style={{ height: '100%', width: '100%' }}
                scrollWheelZoom={false}
              >
                <TileLayer
                  attribution="&copy; OpenStreetMap contributors"
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                {points.map((s) => (
                  <CircleMarker
                    key={s.id}
                    center={[s.lat, s.lon]}
                    radius={5}
                    pathOptions={{ color: '#2563eb', fillColor: '#60a5fa', fillOpacity: 0.8, weight: 1 }}
                  >
                    <Tooltip direction="top" offset={[0, -4]} opacity={1}>
                      <div className="max-w-[260px] text-xs">
                        <div className="font-medium">{s.situs_address}</div>
                        <div className="text-muted-foreground">
                          {fmtUsd(s.sale_price)} • sold {fmtDate(s.sale_date)} • recorded {fmtDate(s.recording_date)}
                        </div>
                        <div className="text-muted-foreground">
                          {s.deed_type ?? '—'} • Doc {s.doc_number ?? '—'} • Book {s.book ?? '—'} Page {s.page ?? '—'}
                        </div>
                      </div>
                    </Tooltip>
                  </CircleMarker>
                ))}
              </MapContainer>
            </div>
          </div>

          <div className="space-y-4">
            {parcels.isSuccess && parcels.data.table_exists === false ? (
              <div className="rounded-md border p-3">
                <div className="text-sm font-medium">No curated parcels yet</div>
                <div className="mt-1 text-sm text-muted-foreground">
                  Seed 50 synthetic recorder-sales rows into the ingestion pipeline to populate the curated table.
                </div>
                <div className="mt-3 flex items-center gap-2">
                  <Button onClick={() => seed.mutate()} disabled={seed.isPending}>
                    {seed.isPending ? 'Seeding…' : 'Seed 50 parcels'}
                  </Button>
                  {seed.isError ? <span className="text-sm text-destructive">{(seed.error as Error).message}</span> : null}
                </div>
              </div>
            ) : null}

            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">Sales</div>
                <div className="text-lg font-semibold">{priceStats.count.toLocaleString()}</div>
              </div>
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">Median price</div>
                <div className="text-lg font-semibold">{fmtUsd(priceStats.median)}</div>
              </div>
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">P25</div>
                <div className="text-lg font-semibold">{fmtUsd(priceStats.p25)}</div>
              </div>
              <div className="rounded-md border p-3">
                <div className="text-xs text-muted-foreground">P75</div>
                <div className="text-lg font-semibold">{fmtUsd(priceStats.p75)}</div>
              </div>
            </div>

            <div className="rounded-md border p-3">
              <div className="mb-2 text-sm font-medium">Price distribution</div>
              <svg viewBox="0 0 320 110" className="h-[110px] w-full">
                {histogram.bins.map((b, i) => {
                  const w = 320 / Math.max(1, histogram.bins.length)
                  const h = histogram.maxCount ? (b.count / histogram.maxCount) * 90 : 0
                  return (
                    <g key={i} transform={`translate(${i * w}, 0)`}>
                      <rect x={4} y={100 - h} width={w - 8} height={h} rx={4} fill="#60a5fa" />
                    </g>
                  )
                })}
                <line x1="0" y1="100" x2="320" y2="100" stroke="#e5e7eb" />
              </svg>
              <div className="text-xs text-muted-foreground">
                {histogram.bins.length
                  ? `${fmtUsd(histogram.bins[0].x0)} – ${fmtUsd(histogram.bins[histogram.bins.length - 1].x1)}`
                  : '—'}
              </div>
            </div>

            <div className="rounded-md border p-3">
              <div className="mb-2 text-sm font-medium">Median sale price by year</div>
              <svg viewBox="0 0 320 110" className="h-[110px] w-full">
                {yearly.points.length > 1 ? (
                  <polyline
                    fill="none"
                    stroke="#2563eb"
                    strokeWidth="2"
                    points={yearly.points
                      .map((p, idx) => {
                        const x = (idx / (yearly.points.length - 1)) * 320
                        const y = 100 - ((p.median - yearly.min) / Math.max(1, yearly.max - yearly.min)) * 90
                        return `${x},${y}`
                      })
                      .join(' ')}
                  />
                ) : null}
                <line x1="0" y1="100" x2="320" y2="100" stroke="#e5e7eb" />
              </svg>
              <div className="text-xs text-muted-foreground">
                {yearly.points.length ? `${yearly.points[0].year} – ${yearly.points[yearly.points.length - 1].year}` : '—'}
              </div>
            </div>

            {parcels.isLoading ? <div className="text-sm text-muted-foreground">Loading curated parcels…</div> : null}
            {parcels.isError ? <div className="text-sm text-destructive">Parcels error: {(parcels.error as Error).message}</div> : null}
            {parcels.isSuccess && parcels.data.table_exists === true && parcelRows.length === 0 ? (
              <div className="text-sm text-muted-foreground">Curated parcels table exists, but has no rows yet.</div>
            ) : null}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Pipeline activity</CardTitle>
          <CardDescription>Virtualized list + debounced search (TanStack Virtual + Pacer).</CardDescription>
        </CardHeader>
        <CardContent>
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          <DataTable<Ingestion> data={filtered} columns={cols} onRowClick={(it) => setSelectedIngestionId(it.id)} />
        </CardContent>
      </Card>
    </Page>
  )
}
