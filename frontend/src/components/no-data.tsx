import { Card, CardHeader, CardTitle } from '@/components/ui/card';

/** An honest gap: the page has no data yet. Later slices replace it with the page's content. */
export function NoData() {
  return (
    <Card size="sm" className="max-w-xl">
      <CardHeader>
        <CardTitle>No data yet</CardTitle>
      </CardHeader>
    </Card>
  );
}
