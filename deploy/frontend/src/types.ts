export interface User {
  id: string
  email: string
  name: string
  role_id: number
  permissions: Record<string, boolean>
  active: boolean
}

export interface Site {
  id: string
  name: string
  type: string
  address: string | null
}

export interface Camera {
  id: string
  site_id: string
  name: string
  ip: string | null
  status: string
  ptz_enabled: boolean
  rtsp_url: string | null
}

export interface VmsEvent {
  id: string
  type: string
  severity: string
  camera_id: string | null
  acknowledged: boolean
  ts: string
  data: Record<string, unknown>
}

export interface Recording {
  id: string
  camera_id: string
  start_ts: string
  end_ts: string | null
  status: string
  size_bytes: number
}

export interface Stats {
  cameras: { total: number; online: number; offline: number }
  sites: number
  events_24h: number
  recordings_active: number
}
