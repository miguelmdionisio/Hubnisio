const WIDTH = 400;
const HEIGHT = 300;
const PAD = 16;

type Point = [number, number];

/** The route's points as SVG coordinates that keep its shape (longitude shrunk by latitude). */
export function projectRoute(route: Point[]): { points: [number, number][]; path: string } {
  const lat0 = route.reduce((sum, [lat]) => sum + lat, 0) / route.length;
  const scale = Math.cos((lat0 * Math.PI) / 180);
  const flat = route.map(([lat, lon]) => [lon * scale, -lat] as [number, number]);
  const xs = flat.map(([x]) => x);
  const ys = flat.map(([, y]) => y);
  const minX = Math.min(...xs);
  const minY = Math.min(...ys);
  const spanX = Math.max(...xs) - minX || 1e-9;
  const spanY = Math.max(...ys) - minY || 1e-9;
  const fit = Math.min((WIDTH - 2 * PAD) / spanX, (HEIGHT - 2 * PAD) / spanY);
  const offsetX = (WIDTH - spanX * fit) / 2;
  const offsetY = (HEIGHT - spanY * fit) / 2;
  const points = flat.map(
    ([x, y]) =>
      [
        Number((offsetX + (x - minX) * fit).toFixed(1)),
        Number((offsetY + (y - minY) * fit).toFixed(1)),
      ] as [number, number],
  );
  return { points, path: points.map(([x, y], i) => `${i ? 'L' : 'M'}${x} ${y}`).join(' ') };
}

/** The route as a line, no map: a green dot where it starts, a red one where it ends. */
export function RouteMap({ route }: { route: Point[] }) {
  const { points, path } = projectRoute(route);
  const [start, end] = [points[0], points.at(-1)];
  const first = route[0];
  const last = route.at(-1);
  return (
    <figure>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="h-auto w-full max-h-[340px] rounded-[14px] bg-surface-2"
        role="img"
        aria-label="Route"
      >
        <path
          d={path}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={2.5}
          strokeLinejoin="round"
          strokeLinecap="round"
          vectorEffect="non-scaling-stroke"
        />
        {start && <circle cx={start[0]} cy={start[1]} r={5} fill="var(--good)" />}
        {end && <circle cx={end[0]} cy={end[1]} r={5} fill="var(--destructive)" />}
      </svg>
      <figcaption className="sr-only">
        Route of {route.length} points
        {first && `, starting at ${first[0].toFixed(4)}, ${first[1].toFixed(4)}`}
        {last && `, ending at ${last[0].toFixed(4)}, ${last[1].toFixed(4)}`}
      </figcaption>
    </figure>
  );
}
