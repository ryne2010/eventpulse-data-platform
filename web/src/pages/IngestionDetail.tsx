import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from '@tanstack/react-router'
import { api } from '../api'
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Page } from '../portfolio-ui'

export function IngestionDetailPage() {
  const { id } = useParams({ from: '/ingestions/$id' })

  const q = useQuery({
    queryKey: ['ingestion', id],
    queryFn: () => api.getIngestion(id),
  })

  return (
    <Page
      title="Ingestion detail"
      description="Record + quality report. In production, this is where lineage + contract versioning is surfaced."
      actions={
        <Link to="/">
          <Button variant="outline" size="sm">
            ← Back
          </Button>
        </Link>
      }
    >
      <Card>
        <CardHeader>
          <CardTitle>Record</CardTitle>
          <CardDescription>Raw ingestion metadata.</CardDescription>
        </CardHeader>
        <CardContent>
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          {q.data ? (
            <pre className="overflow-x-auto rounded-md border bg-muted/30 p-4 text-xs">
{JSON.stringify(q.data.ingestion, null, 2)}
            </pre>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Quality report</CardTitle>
          <CardDescription>Example of warehouse readiness checks (schema, nullability, drift, etc.).</CardDescription>
        </CardHeader>
        <CardContent>
          {q.data ? (
            <pre className="overflow-x-auto rounded-md border bg-muted/30 p-4 text-xs">
{JSON.stringify(q.data.quality_report, null, 2)}
            </pre>
          ) : (
            <div className="text-sm text-muted-foreground">—</div>
          )}
        </CardContent>
      </Card>
    </Page>
  )
}
