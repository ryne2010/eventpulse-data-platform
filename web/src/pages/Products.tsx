import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, type DataProduct } from '../api'
import { Badge, Button, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Input, Label, Page } from '../portfolio-ui'

function truncate(s: string, n = 70) {
  if (s.length <= n) return s
  return `${s.slice(0, n - 1)}…`
}

export function ProductsPage() {
  const nav = useNavigate()

  const [dataset, setDataset] = React.useState('all')

  const q = useQuery({ queryKey: ['data_products'], queryFn: () => api.dataProducts(200), refetchInterval: 30_000 })

  const all = q.data?.items ?? []
  const filtered = dataset === 'all' ? all : all.filter((p) => p.dataset === dataset)

  const datasets = Array.from(new Set(all.map((p) => p.dataset))).sort()

  const columns: ColumnDef<DataProduct>[] = [
    {
      header: 'dataset',
      accessorKey: 'dataset',
      cell: (info) => <Badge variant="outline">{String(info.getValue())}</Badge>,
    },
    {
      header: 'version',
      accessorKey: 'version',
      cell: (info) => (
        <Badge variant="outline" className="font-mono">
          {String(info.getValue() ?? '—')}
        </Badge>
      ),
    },
    {
      header: 'product',
      accessorKey: 'name',
      cell: (info) => <span className="font-mono text-xs">{String(info.getValue())}</span>,
    },
    { header: 'kind', accessorKey: 'kind' },
    {
      header: 'exists',
      accessorKey: 'exists',
      cell: (info) => {
        const v = Boolean(info.getValue())
        return v ? <Badge variant="success">live</Badge> : <Badge variant="warning">not built</Badge>
      },
    },
    {
      header: 'endpoint',
      accessorKey: 'endpoint',
      cell: (info) => <span className="font-mono text-xs">{truncate(String(info.getValue()))}</span>,
    },
    {
      header: 'description',
      accessorKey: 'description',
      cell: (info) => <span className="text-muted-foreground">{truncate(String(info.getValue() ?? ''), 90)}</span>,
    },
  ]

  return (
    <Page
      title="Data products"
      description="A catalog of published marts/views (the consumption layer)."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/datasets" className="no-underline">
            <Button size="sm" variant="outline">Datasets</Button>
          </Link>
          <Link to="/upload" className="no-underline">
            <Button size="sm" variant="outline">Ingest</Button>
          </Link>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle>Filter</CardTitle>
            <CardDescription>Explore available marts by dataset.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label>Dataset</Label>
              <Input list="product-datasets" value={dataset} onChange={(e) => setDataset(e.target.value)} />
              <datalist id="product-datasets">
                <option value="all" />
                {datasets.map((d) => (
                  <option key={d} value={d} />
                ))}
              </datalist>
            </div>

            <div className="flex flex-wrap gap-2">
              <Badge variant="outline">datasets: {datasets.length}</Badge>
              <Badge variant="outline">products: {filtered.length}</Badge>
            </div>

            <div className="text-xs text-muted-foreground">
              Products map to the stable API endpoint:
              <div className="mt-1 font-mono">/api/datasets/&lt;dataset&gt;/marts/&lt;name&gt;</div>
            </div>
          </CardContent>
        </Card>

        <div className="space-y-3 md:col-span-2">
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.error ? <div className="text-sm text-destructive">Failed to load data products.</div> : null}

          <DataTable
            data={filtered}
            columns={columns}
            height={640}
            columnMinWidth={220}
            onRowClick={(row) => {
              nav({ to: '/datasets/$dataset', params: { dataset: row.dataset } })
            }}
          />

          <div className="text-xs text-muted-foreground">Click a row to open the dataset.</div>
        </div>
      </div>
    </Page>
  )
}
