import React from 'react'
import { useQuery } from '@tanstack/react-query'
import type { ColumnDef } from '@tanstack/react-table'
import { Link } from '@tanstack/react-router'
import { api, type QualityTrendPoint } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Label, Page, Separator } from '../portfolio-ui'

function formatBucket(iso: string) {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

function round1(n: number) {
  return Math.round(n * 10) / 10
}

function QualityBars({ series }: { series: QualityTrendPoint[] }) {
  const heightPx = 120
  const maxTotal = Math.max(1, ...series.map((p) => p.total))

  return (
    <div className="w-full overflow-x-auto">
      <div className="flex items-end gap-[2px]" style={{ height: `${heightPx}px` }}>
        {series.map((p) => {
          const totalPx = Math.round((p.total / maxTotal) * heightPx)
          const failedPx = p.total > 0 ? Math.round((p.failed / p.total) * totalPx) : 0
          const passedPx = Math.max(0, totalPx - failedPx)
          const title = `${formatBucket(p.bucket)}\nTotal: ${p.total}  Passed: ${p.passed}  Failed: ${p.failed}  Avg rows: ${round1(p.avg_rows)}`
          return (
            <div key={p.bucket} className="flex w-[4px] flex-col justify-end" title={title}>
              <div className="w-full rounded-t-sm bg-emerald-500/70" style={{ height: `${passedPx}px` }} />
              <div className="w-full bg-rose-500/70" style={{ height: `${failedPx}px` }} />
            </div>
          )
        })}
      </div>
    </div>
  )
}

export function TrendsPage() {
  const dsQ = useQuery({ queryKey: ['datasets', 200], queryFn: () => api.listDatasets(200) })

  const [dataset, setDataset] = React.useState('all')
  const [hours, setHours] = React.useState(168)
  const [bucket, setBucket] = React.useState(60)

  const trendQ = useQuery({
    queryKey: ['quality_trend', dataset, hours, bucket],
    queryFn: () => api.qualityTrend(hours, bucket, dataset === 'all' ? undefined : dataset),
    refetchInterval: 15_000,
  })

  const series = trendQ.data?.series ?? []
  const totals = series.reduce(
    (acc, p) => {
      acc.total += p.total
      acc.passed += p.passed
      acc.failed += p.failed
      return acc
    },
    { total: 0, passed: 0, failed: 0 },
  )

  const passRate = totals.total > 0 ? Math.round((totals.passed / totals.total) * 1000) / 10 : 0

  const columns: ColumnDef<QualityTrendPoint>[] = [
    {
      header: 'bucket',
      accessorKey: 'bucket',
      cell: (info) => <span className="font-mono text-xs">{formatBucket(String(info.getValue()))}</span>,
    },
    { header: 'total', accessorKey: 'total' },
    { header: 'passed', accessorKey: 'passed' },
    { header: 'failed', accessorKey: 'failed' },
    {
      header: 'avg rows',
      accessorKey: 'avg_rows',
      cell: (info) => <span className="font-mono text-xs">{round1(Number(info.getValue()))}</span>,
    },
  ]

  return (
    <Page
      title="Trends"
      description="Quality pass/fail trends from recent ingestions. Great for spotting regressions and freshness issues."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/audit" className="no-underline">
            <Button size="sm" variant="outline">Audit log</Button>
          </Link>
          <Link to="/datasets" className="no-underline">
            <Button size="sm" variant="outline">Datasets</Button>
          </Link>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle>Controls</CardTitle>
            <CardDescription>Pick dataset + timeframe for quality trends.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label>Dataset</Label>
              <Input list="trend-datasets" value={dataset} onChange={(e) => setDataset(e.target.value)} />
              <datalist id="trend-datasets">
                <option value="all" />
                {(dsQ.data?.items ?? []).map((d) => (
                  <option key={d.dataset} value={d.dataset} />
                ))}
              </datalist>
            </div>

            <div className="space-y-1">
              <Label>Lookback hours</Label>
              <Input type="number" min={24} max={336} step={24} value={hours} onChange={(e) => setHours(Number(e.target.value))} />
              <div className="text-xs text-muted-foreground">24–336 hours (1–14 days).</div>
            </div>

            <div className="space-y-1">
              <Label>Bucket minutes</Label>
              <select
                className="h-9 w-full rounded-md border border-input bg-background px-3 py-1 text-sm shadow-sm"
                value={bucket}
                onChange={(e) => setBucket(Number(e.target.value))}
              >
                <option value={60}>60 (hourly)</option>
                <option value={1440}>1440 (daily)</option>
              </select>
              <div className="text-xs text-muted-foreground">Use daily buckets for longer lookbacks.</div>
            </div>

            <Separator />

            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">total: {totals.total}</Badge>
              <Badge variant="success">passed: {totals.passed}</Badge>
              <Badge variant={totals.failed > 0 ? 'destructive' : 'outline'}>failed: {totals.failed}</Badge>
              <Badge variant="outline">pass rate: {passRate}%</Badge>
            </div>

            <Button variant="outline" onClick={() => trendQ.refetch()}>Refresh</Button>
          </CardContent>
        </Card>

        <div className="space-y-4 md:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle>Quality trend</CardTitle>
              <CardDescription>Stacked bars: passed vs failed ingestions per time bucket.</CardDescription>
            </CardHeader>
            <CardContent>
              {trendQ.isLoading ? (
                <div className="text-sm text-muted-foreground">Loading trend…</div>
              ) : trendQ.error ? (
                <div className="text-sm text-destructive">Failed to load trend.</div>
              ) : series.length === 0 ? (
                <div className="text-sm text-muted-foreground">No quality reports yet (run a few ingestions).</div>
              ) : (
                <QualityBars series={series} />
              )}
              <div className="mt-2 text-xs text-muted-foreground">Hover bars for details.</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Raw series</CardTitle>
              <CardDescription>Helpful for debugging gaps and spikes.</CardDescription>
            </CardHeader>
            <CardContent>
              <DataTable data={series} columns={columns} height={420} columnMinWidth={200} />
            </CardContent>
          </Card>
        </div>
      </div>
    </Page>
  )
}
