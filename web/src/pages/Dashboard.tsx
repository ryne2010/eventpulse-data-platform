import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { api } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Page, Separator } from '../portfolio-ui'

type AnalyticsSaleRow = Record<string, any>

function fmtPct(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function fmtInt(v: number | null | undefined) {
  if (v === null || v === undefined) return '—'
  return Intl.NumberFormat().format(v)
}

function fmtUsd(v: number | null | undefined, fractionDigits = 0) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: fractionDigits,
  }).format(v)
}

function fmtDate(v: string | null | undefined) {
  if (!v) return '—'
  try {
    return new Date(v).toLocaleDateString()
  } catch {
    return v
  }
}

function isMartMissingError(err: unknown) {
  const msg = String((err as Error | undefined)?.message ?? '').toLowerCase()
  return msg.includes('mart view not available yet') || msg.includes('mart not found')
}

async function fetchParcelsMartRows(mart: string, limit: number) {
  try {
    const res = await api.getMart('parcels', mart, limit)
    return res.rows ?? []
  } catch (err) {
    if (isMartMissingError(err)) return []
    throw err
  }
}

function analyticsSalesColumns(metricKey: 'price_per_acre' | 'price_per_sf'): ColumnDef<Record<string, any>>[] {
  const metricLabel = metricKey === 'price_per_acre' ? '$/acre' : '$/sf'
  const metricDigits = metricKey === 'price_per_acre' ? 0 : 2
  return [
    { header: 'parcel_id', accessorKey: 'parcel_id' },
    {
      header: 'sale_date',
      accessorKey: 'sale_date',
      cell: (info) => <span className="text-xs">{fmtDate(String(info.getValue() ?? ''))}</span>,
    },
    {
      header: 'sale_price',
      accessorKey: 'sale_price',
      cell: (info) => <span className="font-mono text-xs">{fmtUsd(Number(info.getValue() ?? 0), 0)}</span>,
    },
    {
      header: metricLabel,
      accessorKey: metricKey,
      cell: (info) => <span className="font-mono text-xs">{fmtUsd(Number(info.getValue() ?? 0), metricDigits)}</span>,
    },
    {
      header: 'year_built',
      accessorKey: 'year_built',
      cell: (info) => <span className="text-xs">{String(info.getValue() ?? '—')}</span>,
    },
    {
      header: 'acres',
      accessorKey: 'lot_sqft',
      cell: (info) => {
        const lotSqft = Number(info.getValue() ?? 0)
        if (!Number.isFinite(lotSqft) || lotSqft <= 0) return <span className="text-xs text-muted-foreground">—</span>
        return <span className="font-mono text-xs">{(lotSqft / 43560).toFixed(1)}</span>
      },
    },
    {
      header: 'land_type',
      accessorKey: 'land_type',
      cell: (info) => <span className="text-xs">{String(info.getValue() ?? '—')}</span>,
    },
  ]
}

function StatusKpi(props: { label: string; value: string; hint?: string; badge?: React.ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
          {props.label}
          {props.badge}
        </CardTitle>
        {props.hint ? <CardDescription>{props.hint}</CardDescription> : null}
      </CardHeader>
      <CardContent>
        <div className="text-3xl font-semibold tracking-tight">{props.value}</div>
      </CardContent>
    </Card>
  )
}

function ActivityChart(props: { activity: { hour: string; received: number; processing: number; success: number; failed: number; other: number }[] }) {
  const max = Math.max(
    1,
    ...props.activity.map((a) => a.received + a.processing + a.success + a.failed + a.other),
  )

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>Ingestion activity (last {props.activity.length} hours)</span>
        <span>Higher bar = more ingestions received</span>
      </div>

      <div className="flex items-end gap-1 rounded-md border bg-muted/20 p-3 overflow-x-auto">
        {props.activity.map((a) => {
          const total = a.received + a.processing + a.success + a.failed + a.other
          const h = Math.max(2, Math.round((total / max) * 72))
          return (
            <div key={a.hour} className="flex flex-col items-center gap-1">
              <div
                className="w-3 rounded-sm bg-muted-foreground/40"
                title={`${a.hour}\nreceived=${a.received} processing=${a.processing} success=${a.success} failed=${a.failed}`}
                style={{ height: h }}
              />
            </div>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <span className="inline-block h-2 w-2 rounded-sm bg-muted-foreground/40" /> total per hour
        </span>
      </div>
    </div>
  )
}

function PriceBarList(props: {
  rows: Record<string, any>[]
  labelKey: string
  valueKey: string
  countKey?: string
  valueSuffix: string
  valueFractionDigits?: number
  maxRows?: number
  selectedLabel?: string | null
  onSelect?: (label: string) => void
}) {
  const maxRows = props.maxRows ?? 12
  const valueFractionDigits = props.valueFractionDigits ?? 0
  const countKey = props.countKey ?? 'sales_count'

  const rows = (props.rows ?? [])
    .map((r) => {
      const labelRaw = r?.[props.labelKey]
      const valueRaw = Number(r?.[props.valueKey])
      const countRaw = Number(r?.[countKey])
      return {
        label: String(labelRaw ?? '—'),
        value: Number.isFinite(valueRaw) ? valueRaw : null,
        count: Number.isFinite(countRaw) ? countRaw : null,
      }
    })
    .filter((r) => r.value !== null)
    .slice(0, maxRows)

  if (!rows.length) {
    return <div className="text-sm text-muted-foreground">No analytic rows yet. Seed parcels or ingest parcel sales data.</div>
  }

  const max = Math.max(1, ...rows.map((r) => Number(r.value ?? 0)))

  return (
    <div className="space-y-2">
      {rows.map((r) => {
        const selected = props.selectedLabel === r.label
        return (
          <button
            key={r.label}
            type="button"
            onClick={() => props.onSelect?.(r.label)}
            className={`w-full rounded-md border p-2 text-left transition ${selected ? 'border-blue-500 bg-blue-50/40' : 'border-transparent hover:border-border'}`}
          >
            <div className="space-y-1">
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="font-medium">{r.label}</span>
                <span className="text-muted-foreground">
                  {fmtUsd(r.value, valueFractionDigits)}
                  {props.valueSuffix}
                  {r.count !== null ? ` • ${fmtInt(r.count)} sales` : ''}
                </span>
              </div>
              <div className="h-2 rounded bg-muted/50">
                <div className="h-2 rounded bg-blue-500/80" style={{ width: `${Math.max(2, Math.round((Number(r.value) / max) * 100))}%` }} />
              </div>
            </div>
          </button>
        )
      })}
    </div>
  )
}

function DetailItem(props: { label: string; value: React.ReactNode }) {
  return (
    <div className="space-y-1 rounded-md border bg-muted/20 p-3">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{props.label}</div>
      <div className="text-sm">{props.value}</div>
    </div>
  )
}

function SaleDetailDialog(props: {
  open: boolean
  title: string
  subtitle?: string
  row: AnalyticsSaleRow | null
  onClose: () => void
}) {
  React.useEffect(() => {
    if (!props.open) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') props.onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [props.open, props.onClose])

  if (!props.open || !props.row) return null

  const row = props.row
  const salePrice = Number(row?.sale_price)
  const pricePerAcre = Number(row?.price_per_acre)
  const pricePerSf = Number(row?.price_per_sf)
  const saleYear = Number(row?.sale_year)
  const yearBuilt = Number(row?.year_built)
  const lotSqft = Number(row?.lot_sqft)
  const acres = Number.isFinite(lotSqft) && lotSqft > 0 ? lotSqft / 43560 : null
  const buildingSqft = Number(row?.building_sqft)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/55 p-4" onClick={props.onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Sale detail"
        className="w-full max-w-3xl rounded-lg border bg-background shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4 border-b p-4">
          <div className="space-y-1">
            <h2 className="text-lg font-semibold">{props.title}</h2>
            {props.subtitle ? <p className="text-sm text-muted-foreground">{props.subtitle}</p> : null}
          </div>
          <Button type="button" variant="outline" size="sm" onClick={props.onClose}>
            Close
          </Button>
        </div>

        <div className="grid gap-3 p-4 md:grid-cols-2">
          <DetailItem label="Parcel ID" value={String(row?.parcel_id ?? '—')} />
          <DetailItem label="Land Type" value={String(row?.land_type ?? '—')} />
          <DetailItem label="Sale Date" value={fmtDate(String(row?.sale_date ?? ''))} />
          <DetailItem label="Sale Year" value={Number.isFinite(saleYear) && saleYear > 0 ? fmtInt(saleYear) : '—'} />
          <DetailItem label="Sale Price" value={<span className="font-mono">{Number.isFinite(salePrice) && salePrice > 0 ? fmtUsd(salePrice, 0) : '—'}</span>} />
          <DetailItem label="$/Acre" value={<span className="font-mono">{Number.isFinite(pricePerAcre) && pricePerAcre > 0 ? fmtUsd(pricePerAcre, 0) : '—'}</span>} />
          <DetailItem label="$/SF" value={<span className="font-mono">{Number.isFinite(pricePerSf) && pricePerSf > 0 ? fmtUsd(pricePerSf, 2) : '—'}</span>} />
          <DetailItem label="Year Built" value={Number.isFinite(yearBuilt) && yearBuilt > 0 ? fmtInt(yearBuilt) : '—'} />
          <DetailItem label="Building SF" value={Number.isFinite(buildingSqft) && buildingSqft > 0 ? fmtInt(buildingSqft) : '—'} />
          <DetailItem label="Lot SF" value={Number.isFinite(lotSqft) && lotSqft > 0 ? fmtInt(lotSqft) : '—'} />
          <DetailItem label="Lot Acres" value={acres === null ? '—' : acres.toFixed(2)} />
        </div>
      </div>
    </div>
  )
}

export function DashboardPage() {
  const metaQ = useQuery({ queryKey: ['meta'], queryFn: api.meta })
  const statsQ = useQuery({ queryKey: ['stats', 24], queryFn: () => api.stats(24), refetchInterval: 5000 })
  const dsQ = useQuery({ queryKey: ['datasets', 50], queryFn: () => api.listDatasets(50) })
  const pricePerAcreQ = useQuery({
    queryKey: ['mart', 'parcels', 'price_per_acre_by_land_type', 20],
    queryFn: () => fetchParcelsMartRows('price_per_acre_by_land_type', 20),
    refetchInterval: 30_000,
    retry: false,
  })
  const pricePerSfByYearBuiltQ = useQuery({
    queryKey: ['mart', 'parcels', 'price_per_sf_by_year_built', 60],
    queryFn: () => fetchParcelsMartRows('price_per_sf_by_year_built', 60),
    refetchInterval: 30_000,
    retry: false,
  })
  const pricePerSfBySaleYearQ = useQuery({
    queryKey: ['mart', 'parcels', 'price_per_sf_by_sale_year', 20],
    queryFn: () => fetchParcelsMartRows('price_per_sf_by_sale_year', 20),
    refetchInterval: 30_000,
    retry: false,
  })

  const [selectedLandType, setSelectedLandType] = React.useState<string | null>(null)
  const [selectedYearBuilt, setSelectedYearBuilt] = React.useState<string | null>(null)
  const [selectedSaleYear, setSelectedSaleYear] = React.useState<string | null>(null)
  const [selectedSaleRow, setSelectedSaleRow] = React.useState<{
    title: string
    subtitle?: string
    row: AnalyticsSaleRow
  } | null>(null)

  const landTypeSalesQ = useQuery({
    queryKey: ['analytics-sales', 'parcels', 'land_type', selectedLandType, 80],
    queryFn: () => api.parcelsAnalyticsSales('land_type', selectedLandType ?? '', 80),
    enabled: Boolean(selectedLandType),
    retry: false,
  })
  const yearBuiltSalesQ = useQuery({
    queryKey: ['analytics-sales', 'parcels', 'year_built', selectedYearBuilt, 80],
    queryFn: () => api.parcelsAnalyticsSales('year_built', selectedYearBuilt ?? '', 80),
    enabled: Boolean(selectedYearBuilt),
    retry: false,
  })
  const saleYearSalesQ = useQuery({
    queryKey: ['analytics-sales', 'parcels', 'sale_year', selectedSaleYear, 80],
    queryFn: () => api.parcelsAnalyticsSales('sale_year', selectedSaleYear ?? '', 80),
    enabled: Boolean(selectedSaleYear),
    retry: false,
  })

  const [seedLoading, setSeedLoading] = React.useState(false)
  const [seedResult, setSeedResult] = React.useState<string | null>(null)
  const demoEnabled = Boolean(metaQ.data?.runtime?.enable_demo_endpoints)

  async function seedParcels() {
    setSeedLoading(true)
    setSeedResult(null)
    try {
      const res = await api.seedParcels(60)
      setSeedResult(`Seeded ${res.rows} rows across ${res.ingestions.length} ingestions (seed_id=${res.seed_id}).`)
    } catch (e) {
      setSeedResult(`Seed failed: ${(e as Error).message}`)
    } finally {
      setSeedLoading(false)
    }
  }

  const totals = statsQ.data?.totals ?? {}
  const activity = statsQ.data?.activity ?? []
  const storage = metaQ.data?.runtime?.storage_backend
  const queue = metaQ.data?.runtime?.queue

  const pricePerAcreColumns = React.useMemo(() => analyticsSalesColumns('price_per_acre'), [])
  const pricePerSfColumns = React.useMemo(() => analyticsSalesColumns('price_per_sf'), [])

  return (
    <Page
      title="Dashboard"
      description="Operational overview for the event-driven ingestion pipeline."
      actions={
        <div className="flex items-center gap-2">
          {storage ? <Badge variant="outline">storage: {storage}</Badge> : null}
          {queue ? <Badge variant="outline">queue: {queue}</Badge> : null}
          <Link to="/upload" className="no-underline">
            <Button size="sm" variant="outline">Ingest</Button>
          </Link>
          <Link to="/products" className="no-underline">
            <Button size="sm" variant="outline">Products</Button>
          </Link>
          <Link to="/trends" className="no-underline">
            <Button size="sm" variant="outline">Trends</Button>
          </Link>
          <Link to="/audit" className="no-underline">
            <Button size="sm" variant="outline">Audit</Button>
          </Link>
          <Link to="/ingestions" className="no-underline">
            <Button size="sm">Ingestions</Button>
          </Link>
        </div>
      }
    >
      {metaQ.isLoading || statsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
      {(metaQ.isError || statsQ.isError) ? (
        <div className="text-sm text-destructive">
          Error: {((metaQ.error || statsQ.error) as Error).message}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        <StatusKpi label="Total ingestions" value={fmtInt(statsQ.data?.total_ingestions)} />
        <StatusKpi label="Backlog" value={fmtInt(statsQ.data?.backlog)} hint="received + processing" />
        <StatusKpi label="Success rate" value={fmtPct(statsQ.data?.success_rate)} hint="success / (success + failed)" />
        <StatusKpi
          label="Stuck processing"
          value={fmtInt(statsQ.data?.stuck_processing)}
          hint="processing older than TTL"
          badge={statsQ.data?.stuck_processing ? <Badge variant="warning">check</Badge> : undefined}
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2 mt-6">
        <Card>
          <CardHeader>
            <CardTitle>Status totals</CardTitle>
            <CardDescription>Grouped status counts from the metadata DB.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">received: {fmtInt(totals.received)}</Badge>
              <Badge variant="warning">processing: {fmtInt(totals.processing)}</Badge>
              <Badge variant="success">success: {fmtInt(totals.success)}</Badge>
              <Badge variant="destructive">failed: {fmtInt(totals.failed)}</Badge>
            </div>
            <Separator />
            {activity.length ? <ActivityChart activity={activity} /> : <div className="text-sm text-muted-foreground">No recent activity.</div>}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Datasets</CardTitle>
            <CardDescription>Contract-backed datasets available in this environment.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {dsQ.isLoading ? <div className="text-sm text-muted-foreground">Loading datasets…</div> : null}
            {dsQ.isError ? <div className="text-sm text-destructive">Error: {(dsQ.error as Error).message}</div> : null}
            {dsQ.data?.items?.length ? (
              <div className="space-y-2">
                {dsQ.data.items.slice(0, 8).map((d) => (
                  <div key={d.dataset} className="flex items-center justify-between rounded-md border p-3">
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Link to="/datasets/$dataset" params={{ dataset: d.dataset }} className="font-medium">
                          {d.dataset}
                        </Link>
                        {d.curated_table_exists ? <Badge variant="secondary">curated</Badge> : <Badge variant="outline">no curated</Badge>}
                        {d.has_contract ? <Badge variant="outline">contract</Badge> : <Badge variant="warning">no contract</Badge>}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        ingestions: {fmtInt(d.ingestion_count)} • last: {d.last_received_at ?? '—'}
                      </div>
                    </div>
                    <Link to="/datasets/$dataset" params={{ dataset: d.dataset }} className="no-underline">
                      <Button size="sm" variant="outline">Open</Button>
                    </Link>
                  </div>
                ))}
                <Link to="/datasets" className="text-sm text-muted-foreground hover:text-foreground">
                  View all datasets →
                </Link>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">No datasets found yet. Add a contract or ingest data.</div>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3 mt-6">
        <Card>
          <CardHeader>
            <CardTitle>$/acre by land type</CardTitle>
            <CardDescription>Median price-per-acre by land type. Click a bar to see underlying sales.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {pricePerAcreQ.isLoading ? <div className="text-sm text-muted-foreground">Loading analytics…</div> : null}
            {pricePerAcreQ.isError ? <div className="text-sm text-destructive">Error: {(pricePerAcreQ.error as Error).message}</div> : null}
            {!pricePerAcreQ.isLoading && !pricePerAcreQ.isError ? (
              <PriceBarList
                rows={pricePerAcreQ.data ?? []}
                labelKey="land_type"
                valueKey="median_price_per_acre"
                valueSuffix="/acre"
                selectedLabel={selectedLandType}
                onSelect={setSelectedLandType}
              />
            ) : null}
            {selectedLandType ? <div className="text-xs text-muted-foreground">Showing recent sales for: {selectedLandType}</div> : null}
            {selectedLandType && landTypeSalesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading sales…</div> : null}
            {selectedLandType && landTypeSalesQ.isError ? <div className="text-sm text-destructive">Failed to load sales.</div> : null}
            {selectedLandType && !landTypeSalesQ.isLoading && !landTypeSalesQ.isError ? (
              (landTypeSalesQ.data?.rows?.length ?? 0) > 0 ? (
                <DataTable
                  data={landTypeSalesQ.data?.rows ?? []}
                  columns={pricePerAcreColumns}
                  height={260}
                  columnMinWidth={140}
                  onRowClick={(row) =>
                    setSelectedSaleRow({
                      title: `Parcel ${String(row?.parcel_id ?? 'sale')}`,
                      subtitle: selectedLandType ? `Land type: ${selectedLandType}` : undefined,
                      row,
                    })
                  }
                />
              ) : (
                <div className="text-sm text-muted-foreground">No matching sales for this bucket yet.</div>
              )
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>$/sf by year built</CardTitle>
            <CardDescription>Median price-per-square-foot by year built. Click a bar to see underlying sales.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {pricePerSfByYearBuiltQ.isLoading ? <div className="text-sm text-muted-foreground">Loading analytics…</div> : null}
            {pricePerSfByYearBuiltQ.isError ? <div className="text-sm text-destructive">Error: {(pricePerSfByYearBuiltQ.error as Error).message}</div> : null}
            {!pricePerSfByYearBuiltQ.isLoading && !pricePerSfByYearBuiltQ.isError ? (
              <PriceBarList
                rows={pricePerSfByYearBuiltQ.data ?? []}
                labelKey="year_built"
                valueKey="median_price_per_sf"
                valueSuffix="/sf"
                valueFractionDigits={2}
                maxRows={14}
                selectedLabel={selectedYearBuilt}
                onSelect={setSelectedYearBuilt}
              />
            ) : null}
            {selectedYearBuilt ? <div className="text-xs text-muted-foreground">Showing recent sales for year built: {selectedYearBuilt}</div> : null}
            {selectedYearBuilt && yearBuiltSalesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading sales…</div> : null}
            {selectedYearBuilt && yearBuiltSalesQ.isError ? <div className="text-sm text-destructive">Failed to load sales.</div> : null}
            {selectedYearBuilt && !yearBuiltSalesQ.isLoading && !yearBuiltSalesQ.isError ? (
              (yearBuiltSalesQ.data?.rows?.length ?? 0) > 0 ? (
                <DataTable
                  data={yearBuiltSalesQ.data?.rows ?? []}
                  columns={pricePerSfColumns}
                  height={260}
                  columnMinWidth={140}
                  onRowClick={(row) =>
                    setSelectedSaleRow({
                      title: `Parcel ${String(row?.parcel_id ?? 'sale')}`,
                      subtitle: selectedYearBuilt ? `Year built: ${selectedYearBuilt}` : undefined,
                      row,
                    })
                  }
                />
              ) : (
                <div className="text-sm text-muted-foreground">No matching sales for this bucket yet.</div>
              )
            ) : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>$/sf by sale year</CardTitle>
            <CardDescription>Median price-per-square-foot by sale year. Click a bar to see underlying sales.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {pricePerSfBySaleYearQ.isLoading ? <div className="text-sm text-muted-foreground">Loading analytics…</div> : null}
            {pricePerSfBySaleYearQ.isError ? <div className="text-sm text-destructive">Error: {(pricePerSfBySaleYearQ.error as Error).message}</div> : null}
            {!pricePerSfBySaleYearQ.isLoading && !pricePerSfBySaleYearQ.isError ? (
              <PriceBarList
                rows={pricePerSfBySaleYearQ.data ?? []}
                labelKey="sale_year"
                valueKey="median_price_per_sf"
                valueSuffix="/sf"
                valueFractionDigits={2}
                selectedLabel={selectedSaleYear}
                onSelect={setSelectedSaleYear}
              />
            ) : null}
            {selectedSaleYear ? <div className="text-xs text-muted-foreground">Showing recent sales for sale year: {selectedSaleYear}</div> : null}
            {selectedSaleYear && saleYearSalesQ.isLoading ? <div className="text-sm text-muted-foreground">Loading sales…</div> : null}
            {selectedSaleYear && saleYearSalesQ.isError ? <div className="text-sm text-destructive">Failed to load sales.</div> : null}
            {selectedSaleYear && !saleYearSalesQ.isLoading && !saleYearSalesQ.isError ? (
              (saleYearSalesQ.data?.rows?.length ?? 0) > 0 ? (
                <DataTable
                  data={saleYearSalesQ.data?.rows ?? []}
                  columns={pricePerSfColumns}
                  height={260}
                  columnMinWidth={140}
                  onRowClick={(row) =>
                    setSelectedSaleRow({
                      title: `Parcel ${String(row?.parcel_id ?? 'sale')}`,
                      subtitle: selectedSaleYear ? `Sale year: ${selectedSaleYear}` : undefined,
                      row,
                    })
                  }
                />
              ) : (
                <div className="text-sm text-muted-foreground">No matching sales for this bucket yet.</div>
              )
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="mt-6">
        <Card>
          <CardHeader>
            <CardTitle>Quick actions</CardTitle>
            <CardDescription>Helpful shortcuts for exploring the demo.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-3">
            <Link to="/upload" className="no-underline">
              <Button variant="outline">Upload a file</Button>
            </Link>
            <Link to="/products" className="no-underline">
              <Button variant="outline">Browse data products</Button>
            </Link>
            <Link to="/trends" className="no-underline">
              <Button variant="outline">View trends</Button>
            </Link>
            <Link to="/audit" className="no-underline">
              <Button variant="outline">Open audit log</Button>
            </Link>
            <Link to="/datasets/$dataset" params={{ dataset: 'parcels' }} className="no-underline">
              <Button variant="outline">Open parcels dataset</Button>
            </Link>
            {demoEnabled ? (
              <>
                <Button onClick={seedParcels} disabled={seedLoading}>
                  {seedLoading ? 'Seeding…' : 'Seed parcels'}
                </Button>
              </>
            ) : (
              <Badge variant="outline">Demo endpoints disabled</Badge>
            )}
            {seedResult ? <span className="text-sm text-muted-foreground">{seedResult}</span> : null}
          </CardContent>
        </Card>
      </div>

      <SaleDetailDialog
        open={Boolean(selectedSaleRow)}
        title={selectedSaleRow?.title ?? ''}
        subtitle={selectedSaleRow?.subtitle}
        row={selectedSaleRow?.row ?? null}
        onClose={() => setSelectedSaleRow(null)}
      />
    </Page>
  )
}
