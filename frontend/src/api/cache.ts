import type { QueryClient } from "@tanstack/react-query";

export function invalidateRequestViews(queryClient: QueryClient): void {
  for (const key of ["requests", "discover", "search", "detail"]) {
    void queryClient.invalidateQueries({ queryKey: [key] });
  }
}
