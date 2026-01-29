import React from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, Page } from '../portfolio-ui'

export function MetaPage() {
  const q = useQuery({ queryKey: ['meta'], queryFn: api.meta })

  return (
    <Page title="Meta" description="Runtime configuration for the local-first ingestion pipeline.">
      <Card>
        <CardHeader>
          <CardTitle>API meta</CardTitle>
          <CardDescription>Safe diagnostic endpoint (version, runtime paths, health).</CardDescription>
        </CardHeader>
        <CardContent>
          {q.isLoading ? <div className="text-sm text-muted-foreground">Loading…</div> : null}
          {q.isError ? <div className="text-sm text-destructive">Error: {(q.error as Error).message}</div> : null}
          {q.data ? (
            <pre className="overflow-x-auto rounded-md border bg-muted/30 p-4 text-xs">
{JSON.stringify(q.data, null, 2)}
            </pre>
          ) : null}
        </CardContent>
      </Card>
    </Page>
  )
}
