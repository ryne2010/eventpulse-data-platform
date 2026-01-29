import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { useDebouncedValue } from '@tanstack/react-pacer/debouncer'
import { api } from '../api'
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle, DataTable, Page, RangeSlider } from '../portfolio-ui'

export function DatasetPage() {
  const { dataset } = useParams({ from: '/datasets/$dataset' })

  const [limit, setLimit] = React.useState(25)
  const [debouncedLimit] = useDebouncedValue(limit, { wait: 150 })

  const q = useQuery({
    queryKey: ['curated', dataset, debouncedLimit],
    queryFn: () => api.curatedSample(dataset, debouncedLimit),
  })

  const rows = q.data?.rows ?? []

  const columns = React.useMemo<ColumnDef<Record<string, any>>[]>(() => {
    const keys = rows.length ? Object.keys(rows[0]) : []
    return keys.map((k) => ({
      header: k,
      accessorKey: k,
      cell: (info) => {
        const v = info.getValue()
        return <span className="text-muted-foreground">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
      },
    }))
  }, [rows])

  return (
    <Page
      title="Curated sample"
      description={
        <span>
          Read-model sample (curated schema). Slider uses TanStack Ranger; debounce uses TanStack Pacer.
        </span>
      }
      actions={
        <div className="flex items-center gap-2">
          <Badge variant="outline">dataset: {dataset}</Badge>
          <Badge variant="secondary">limit: {debouncedLimit}</Badge>
        </div>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Sample rows</CardTitle>
          <CardDescription>In production, these rows are served from a governed warehouse/curated schema.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <RangeSlider min={10} max={200} step={5} value={limit} onChange={setLimit} label="Row limit" />
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          <DataTable data={rows} columns={columns} />
        </CardContent>
      </Card>
    </Page>
  )
}
