import { useState } from "react";

// Per-browser display preferences; the app works the same without storage.
function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* not persisted */
  }
}

/** Hide titles that are already in the library from discovery listings. */
export function useHideInLibrary(): [boolean, (hide: boolean) => void] {
  const key = "nextpanel.hideInLibrary";
  const [hide, setHide] = useState(() => read(key) === "true");
  return [
    hide,
    (next: boolean) => {
      write(key, String(next));
      setHide(next);
    },
  ];
}
