export type Source = {
  id: number; name: string; display_name: string; kind: 'mount' | 'upload'
  enabled: boolean; present: boolean; ts_order: string[]; filename_pattern: string
  last_scan_at: number | null; image_count: number; first_ms: number | null; last_ms: number | null
}

export type ScanRow = {
  source_id: number; display_name: string; status: string; started_at: number | null; finished_at: number | null
  found: number; new: number; changed: number; removed: number; errors: number; message: string | null
}

export type ScanStatus = {
  scans: ScanRow[]
  thumbs: { total: number; pending: number; done: number; errors: number; rate: number; eta_s: number | null }
  now: number
}
