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

export type Rule = { id?: number; type: string; enabled: boolean; params: Record<string, any> }

export type VideoParams = {
  mode: 'fps' | 'length'; fps: number; target_length_s: number; hold_first_s: number; hold_last_s: number
  resolution: string; custom_w: number; custom_h: number; aspect: string
  crop: { x: number; y: number; w: number; h: number } | null
  rotate: number; flip_h: boolean; flip_v: boolean; codec: 'h264' | 'h265' | 'av1'; quality: string
  expert: { enabled: boolean; crf: number; preset: string; bitrate_kbps: number }
  deflicker: { enabled: boolean; size: number }
  blend: { enabled: boolean; frames: number }
  overlay: { enabled: boolean; format: string; position: string; size: number; box: boolean }
  title: { text: string; duration_s: number }
  credits: { text: string; duration_s: number }
  fade_in_s: number; fade_out_s: number
  audio: { file: string | null; name: string | null; fade_out_s: number }
}

export type Project = {
  id: number; name: string; created_at: number; updated_at: number; params: VideoParams; rules?: Rule[]; renders?: number
}

export type Suggestion = {
  kind: 'fps' | 'nth' | 'limit' | 'info'; label: string; fps: number; frames: number; total_s: number
  n: number | null; limit: number | null; exact: boolean; notes: string[]
}

export type Evaluation = {
  count: number; total: number; key: string; elapsed_ms: number
  steps: { rule_id: number | null; type: string; count: number | null; error: string | null }[]
  first_ms: number | null; last_ms: number | null; days: number
  distribution: [number, number][]
  marks: { include: number; exclude: number }
  video: {
    frames: number; fps: number; body_s: number; extra_s: number; total_s: number; warnings: string[]
    source_size: { w: number; h: number }
    geometry: { crop: { x: number; y: number; w: number; h: number }; rotated: { w: number; h: number }; out: { w: number; h: number } }
    estimate: { size_bytes: number; render_s: number; render_fps: number | null }
    suggestions: Suggestion[]; base_frames?: number
  }
}

export type Job = {
  id: number; project_id: number | null; project_name: string; kind: 'render' | 'preview'
  status: 'queued' | 'preparing' | 'rendering' | 'done' | 'failed' | 'cancelled' | 'interrupted'
  phase: string | null; priority: number; summary: string; frames_total: number; frames_done: number; percent: number
  fps_current: number | null; speed: number | null; eta_s: number | null; elapsed_s: number | null
  created_at: number; started_at: number | null; finished_at: number | null
  output_name: string | null; output_size: number | null; output_exists: boolean; error: string | null
  cancel_requested: boolean; remote_user: string | null
  estimate: { size_bytes: number; render_s: number } | null; range: { start: number; end: number | null } | null
  out_w: number | null; out_h: number | null; fps: number | null; codec: string | null
}

export type JobsSnapshot = { active: number; jobs: Job[]; render_window: string; window_open: boolean }
