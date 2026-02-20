import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ColumnDef } from '@tanstack/react-table'
import { api, getTaskTokenForUi, type DeviceMediaItem } from '../api'
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  CopyButton,
  DataTable,
  Input,
  Label,
  Page,
  Separator,
} from '../portfolio-ui'

function formatTime(iso?: string | null) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString()
  } catch {
    return iso
  }
}

function humanBytes(n?: number | null) {
  if (!n || n <= 0) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

function truncate(s: string, n = 90) {
  const t = s ?? ''
  if (t.length <= n) return t
  return `${t.slice(0, n - 1)}…`
}

export function MediaPage() {
  const [deviceId, setDeviceId] = React.useState('')
  const [limit, setLimit] = React.useState(200)
  const [opening, setOpening] = React.useState<string | null>(null)

  const q = useQuery({
    queryKey: ['media', limit, deviceId],
    queryFn: () => api.listMedia(limit, deviceId.trim() ? deviceId.trim() : undefined),
    refetchInterval: 15_000,
  })

  const items = q.data?.items ?? []

  const openItem = async (item: DeviceMediaItem) => {
    setOpening(item.id)
    try {
      const r = await api.mediaReadSignedUrl(item.gcs_uri, 900)
      window.open(r.download_url, '_blank', 'noopener,noreferrer')
    } catch (e: any) {
      console.error(e)
      alert(String(e?.message ?? e ?? 'Failed to open media'))
    } finally {
      setOpening(null)
    }
  }

  const columns: ColumnDef<DeviceMediaItem>[] = [
    {
      header: 'created',
      accessorKey: 'created_at',
      cell: (info) => <span className="font-mono text-xs">{formatTime(info.getValue() as string)}</span>,
    },
    {
      header: 'device',
      accessorKey: 'device_id',
      cell: (info) => {
        const id = String(info.getValue() ?? '')
        return (
          <Link to="/devices/$deviceId" params={{ deviceId: id }} className="font-mono text-xs">
            {truncate(id, 18)}
          </Link>
        )
      },
    },
    {
      header: 'type',
      accessorKey: 'media_type',
      cell: (info) => <Badge variant="outline">{String(info.getValue() ?? '—')}</Badge>,
    },
    {
      header: 'captured',
      accessorKey: 'captured_at',
      cell: (info) => <span className="text-xs text-muted-foreground">{formatTime(info.getValue() as any)}</span>,
    },
    {
      header: 'size',
      accessorKey: 'bytes',
      cell: (info) => <span className="text-xs text-muted-foreground">{humanBytes(info.getValue() as any)}</span>,
    },
    {
      header: 'notes',
      accessorKey: 'notes',
      cell: (info) => {
        const v = info.getValue() as any
        if (!v) return <span className="text-xs text-muted-foreground">—</span>
        return <span className="text-xs text-muted-foreground">{truncate(String(v), 120)}</span>
      },
    },
    {
      header: 'actions',
      id: 'actions',
      cell: (info) => {
        const row = info.row.original
        return (
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => openItem(row)}
              disabled={opening === row.id}
            >
              {opening === row.id ? 'Opening…' : 'Open'}
            </Button>
            <CopyButton text={row.gcs_uri} label="Copy gs:// URI" size="sm" />
          </div>
        )
      },
    },
  ]

  const token = getTaskTokenForUi()
  const needsToken = !token && (q.error ? String((q.error as any)?.message ?? q.error).includes('401') : false)

  return (
    <Page
      title="Media"
      description="Field ops artifacts: photos/videos uploaded by edge devices (optional)."
      actions={
        <div className="flex items-center gap-2">
          <Link to="/devices" className="no-underline">
            <Button size="sm" variant="outline">
              Devices
            </Button>
          </Link>
          <Link to="/audit" className="no-underline">
            <Button size="sm" variant="outline">
              Audit
            </Button>
          </Link>
        </div>
      }
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-1">
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Media listing is protected by internal auth.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-1">
              <Label>Device id</Label>
              <Input value={deviceId} onChange={(e) => setDeviceId(e.target.value)} placeholder="optional" />
              <div className="text-xs text-muted-foreground">Filter by a single device for fast triage.</div>
            </div>

            <div className="space-y-1">
              <Label>Limit</Label>
              <Input type="number" min={1} max={1000} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
            </div>

            <Separator />

            <div className="space-y-2">
              <div className="text-xs text-muted-foreground">
                If <span className="font-mono">TASK_AUTH_MODE=token</span>, set your task token on the Ops page.
              </div>
              {needsToken ? (
                <Badge variant="warning">Task token required</Badge>
              ) : token ? (
                <Badge variant="success">Task token set</Badge>
              ) : (
                <Badge variant="outline">No task token</Badge>
              )}
              <Link to="/meta" className="no-underline">
                <Button size="sm" variant="outline">Go to Ops</Button>
              </Link>
            </div>

            <Button variant="outline" onClick={() => q.refetch()}>
              Refresh
            </Button>
          </CardContent>
        </Card>

        <div className="space-y-3 md:col-span-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">items: {items.length}</Badge>
            {q.isFetching ? <Badge variant="warning">updating…</Badge> : <Badge variant="success">live</Badge>}
            {q.error ? <Badge variant="destructive">error</Badge> : null}
          </div>

          <DataTable data={items} columns={columns} height={640} columnMinWidth={220} />

          <div className="text-xs text-muted-foreground">
            Enable edge media uploads with <span className="font-mono">ENABLE_EDGE_MEDIA=true</span>.
          </div>
        </div>
      </div>
    </Page>
  )
}
