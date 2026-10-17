/** Retry only unsuccessful initial reads; successful editable data stays local. */
export function initialResourceLoader(tasks: Array<() => Promise<boolean>>) {
  const pending = new Set(tasks);
  let running = false;
  return async () => {
    if (running || !pending.size) return;
    running = true;
    try {
      await Promise.all(
        [...pending].map(async (task) => {
          try {
            if (await task()) pending.delete(task);
          } catch {
            // A failed read remains pending until the next retry.
          }
        }),
      );
    } finally {
      running = false;
    }
  };
}
