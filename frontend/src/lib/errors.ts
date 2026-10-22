/** A readable message from an API error body ({"detail": "..."}) or a thrown error. */
export function errorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'detail' in error && typeof error.detail === 'string') {
    return error.detail;
  }
  if (error instanceof TypeError) return "Can't reach the hub's API.";
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}
