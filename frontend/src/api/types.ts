export type MediaType = "manga" | "comic";

export type RequestStatus =
  | "pending"
  | "denied"
  | "processing"
  | "partially_available"
  | "available"
  | "failed";

export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  created_at: string;
  request_count: number;
  sso_only: boolean;
}

export interface AuthStatus {
  setup_required: boolean;
  registration_enabled: boolean;
  sso_enabled: boolean;
  local_login_enabled: boolean;
}

export interface SearchResult {
  media_type: MediaType;
  provider: string;
  provider_id: number;
  title: string;
  english_title: string;
  alt_titles: string[];
  description: string;
  status: string;
  publisher: string;
  year: number | null;
  cover_url: string;
  total_count: number | null;
  in_library: boolean;
  request_id: number | null;
  request_status: RequestStatus | null;
}

export interface SearchResponse {
  results: SearchResult[];
  errors: Record<string, string>;
}

export interface MediaRequest {
  id: number;
  media_type: MediaType;
  provider: string;
  provider_id: number;
  title: string;
  english_title: string;
  year: number | null;
  cover_url: string;
  description: string;
  status: RequestStatus;
  note: string;
  remote_series_id: number | null;
  downloaded_count: number;
  total_count: number;
  created_at: string;
  updated_at: string;
  username: string;
  decided_by_username: string;
}

export type Settings = Record<string, string>;

export interface RootFolder {
  id: number;
  path: string;
}

export interface ConnectionTest {
  ok: boolean;
  version: string;
  message: string;
}

export interface DiscoverItem {
  media_type: MediaType;
  provider: string;
  provider_id: number;
  title: string;
  english_title: string;
  description: string;
  status: string;
  year: number | null;
  cover_url: string;
  score: number | null;
  subtitle: string;
  genres: string[];
  in_library: boolean;
  library_series_id: number | null;
  request_id: number | null;
  request_status: RequestStatus | null;
}

export interface Chapter {
  number: number | null;
  label: string;
  title: string;
  volume: number | null;
  downloaded: boolean;
  monitored: boolean;
}

export interface TitleDetail {
  media_type: MediaType;
  provider: string;
  provider_id: number;
  title: string;
  english_title: string;
  native_title: string;
  description: string;
  status: string;
  format: string;
  year: number | null;
  end_year: number | null;
  cover_url: string;
  banner_url: string;
  genres: string[];
  score: number | null;
  publisher: string;
  country: string;
  staff: { name: string; role: string }[];
  total_count: number | null;
  volumes: number | null;
  downloaded_count: number;
  chapters: Chapter[];
  chapters_available: boolean;
  in_library: boolean;
  library_series_id: number | null;
  request_id: number | null;
  request_status: RequestStatus | null;
}

export interface DiscoverSection {
  key: string;
  title: string;
  items: DiscoverItem[];
}

export interface DiscoverResponse {
  sections: DiscoverSection[];
  errors: Record<string, string>;
}
