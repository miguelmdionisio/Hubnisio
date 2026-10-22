import { useQuery } from '@tanstack/react-query';
import { getHealthOptions } from '../api/@tanstack/react-query.gen';

export function HomePage() {
  const health = useQuery(getHealthOptions());

  return (
    <section className="max-w-md rounded-lg border border-neutral-200 bg-white p-4">
      <h2 className="font-medium">System status</h2>
      <p className="mt-2 text-sm text-neutral-600">
        {health.isPending && 'Checking the API…'}
        {health.isError && 'The API is unreachable.'}
        {health.data && `API ${health.data.status}, database ${health.data.database}.`}
      </p>
    </section>
  );
}
