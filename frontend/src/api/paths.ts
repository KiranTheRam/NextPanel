export function titleHref(
  item: { media_type: string; provider: string; provider_id: number; title: string },
): string {
  // The title hint lets providers without a by-id lookup resolve cold links.
  return `/title/${encodeURIComponent(item.media_type)}/${encodeURIComponent(item.provider)}/${item.provider_id}` +
    `?title=${encodeURIComponent(item.title)}`;
}

/** "1 chapter", "12 chapters", "1 issue"… */
export function countOf(count: number, mediaType: string): string {
  const unit = mediaType === "manga" ? "chapter" : "issue";
  return `${count} ${unit}${count === 1 ? "" : "s"}`;
}
