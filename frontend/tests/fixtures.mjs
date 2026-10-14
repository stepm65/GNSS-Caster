export const now = Math.floor(Date.now() / 1000);
export const station = {
  id: 1,
  name: "DIY-GNSS-MINI-88",
  connection_type: "bluetooth",
  bt_mac: "AA:BB:CC:DD:EE:88",
  channel: 1,
  baudrate: 115200,
  status: "connected",
  bytes_received: 18342720,
  bytes_sent: 47120,
  receiver_brand: "unicore",
  data_type: "RTCM3",
  output_interval: 1,
  position_mode: "manual",
  operation_mode: "base",
  position_accuracy: 1,
  manual_lat: 55.0281,
  manual_lon: 82.9212,
  manual_alt: 143.21,
  survey_duration_sec: 30,
  antenna_height: 2,
  add_antenna_height: true,
  command_strategy: "generated",
  data_bits: 8,
  stop_bits: 1,
  parity: "N",
  startup_commands: "",
  shutdown_commands: "",
  receiver_model: "UM980",
  firmware_version: "R4.10",
};
export const backup = {
  filename: "backup_20261013_120000.tar.gz",
  size_bytes: 541872,
  modified_at: now - 3600,
};
const setting = (value, description = "") => ({
  value: String(value),
  description,
  is_secret: false,
});
export const settings = {
  system_name: setting("Field caster"),
  bluetooth_name: setting("GNSS-Caster"),
  max_connections: setting(50),
  log_retention: setting(30),
  data_retention: setting(365),
  gnss_time_sync: setting(false),
  ntrip_enabled: setting(true),
  bluetooth_enabled: setting(true),
  bluetooth_discoverable: setting(false),
  auto_backup: setting(true),
  backup_interval: setting(86400),
  backup_external_path: setting("/media/backup"),
  backup_encryption_enabled: setting(true),
  backup_encryption_passphrase: { value: "", is_secret: true, is_set: true },
  telegram_bot_token: { value: "", is_secret: true, is_set: true },
  telegram_chat_id: setting("-10012345678"),
  telegram_admin_id: setting("12345678"),
  telegram_enabled: setting(true),
  telegram_commands_enabled: setting(false),
  telegram_send_backup: setting(true),
  notify_station_up: setting(true),
  notify_station_down: setting(true),
  notify_station_error: setting(true),
  notify_rover_connect: setting(false),
  notify_rover_disconnect: setting(false),
  notify_backup: setting(true),
  notify_service: setting(true),
};
export function fixture(pathname) {
  const path = pathname.split("?")[0];
  const fixed = {
    "/api/diagnostics": {
      status: "ok",
      components: {
        web: { status: "ok", message: "Web application responds" },
        database: {
          status: "ok",
          message: "Database responds to a read query",
        },
        ntrip: { status: "ok", message: "NTRIP server is running" },
        receivers: { status: "ok", message: "1/1 receivers connected" },
        rtcm: { status: "ok", message: "1/1 receivers provide fresh RTCM" },
      },
      stations: [
        {
          id: 1,
          name: station.name,
          receiver: "ok",
          rtcm: "ok",
          message: "Valid RTCM frames are arriving",
          last_frame_age_seconds: 0.6,
          frames_parsed: 58432,
          crc_failures: 0,
        },
      ],
    },
    "/api/status": {
      status: "ok",
      system: {
        hostname: "caster.local",
        platform: "Linux",
        version: "3.1.0",
        uptime: "2h 18m",
      },
      resources: {
        cpu_percent: 12.8,
        memory_percent: 27,
        disk_percent: 18,
        cpu_temp_c: 44.2,
        fan_status: "ON",
        wifi: { signal_dbm: -48, ssid: "Field network" },
      },
      database: {
        base_stations: 1,
        active_bases: 1,
        mountpoints: 2,
        rovers: 3,
        active_rovers: 1,
      },
    },
    "/api/base_stations": [station],
    "/api/bluetooth/status": {
      connected: 1,
      total_stations: 1,
      stations: [
        {
          ...station,
          connected: true,
          rover_clients: 1,
          rssi: -52,
          reconnect_count: 0,
          last_error: null,
          telemetry: {
            satellites_used: 28,
            satellites_visible: 36,
            fix_quality: "RTK fixed",
            hdop: 0.7,
            latitude: station.manual_lat,
            longitude: station.manual_lon,
            altitude_m: station.manual_alt,
            utc_time: "08:42:19",
          },
          stream: {
            frames_parsed: 58432,
            crc_failures: 0,
            bytes_received: 18342720,
          },
        },
      ],
    },
    "/api/ntrip/status": {
      running: true,
      port: 2101,
      connections: [
        {
          rover: "rover1",
          rover_id: 1,
          mountpoint: "BASE88",
          address: "10.0.0.23:50221",
          duration: 2515,
        },
      ],
      stats: { authenticated_connections: 1 },
    },
    "/api/rovers": [
      {
        id: 1,
        username: "rover1",
        email: "",
        mountpoints: ["BASE88"],
        max_conn: 1,
        active_conn: 1,
        expires: 0,
        last_connection: now - 2500,
        total_connections: 12,
        is_active: true,
      },
    ],
    "/api/mountpoints": [
      {
        id: 1,
        name: "BASE88",
        base_id: 1,
        description: "Main correction stream",
        is_active: true,
        rtcm_settings: {},
      },
      {
        id: 2,
        name: "BASE88_MSM",
        base_id: 1,
        description: "MSM corrections",
        is_active: true,
        rtcm_settings: { 1077: true },
      },
    ],
    "/api/logs": [
      {
        id: 1,
        timestamp: now - 20,
        level: "INFO",
        module: "ntrip",
        message: "Rover rover1 started receiving corrections",
      },
      {
        id: 2,
        timestamp: now - 40,
        level: "INFO",
        module: "bluetooth",
        message: "Base DIY-GNSS-MINI-88 connected",
      },
      {
        id: 3,
        timestamp: now - 3600,
        level: "WARNING",
        module: "maintenance",
        message: "External backup storage is not mounted",
      },
    ],
    "/api/rtcm/messages": {
      GPS: [
        { type: 1077, description: "GPS MSM7 observations", enabled: true },
        { type: 1019, description: "GPS ephemerides", enabled: true },
      ],
      GLONASS: [
        { type: 1087, description: "GLONASS MSM7 observations", enabled: true },
      ],
      Station: [
        {
          type: 1006,
          description: "Station coordinates and antenna height",
          enabled: true,
        },
      ],
    },
    "/api/rtcm/settings": [
      { msg_type: 1077, enabled: true },
      { msg_type: 1019, enabled: false },
    ],
    "/api/rtcm/presets": {
      presets: [{ name: "Field MSM7", enabled_count: 4, total_count: 4 }],
    },
    "/api/system/settings": settings,
    "/api/system/tls": {
      https_enabled: true,
      domain: "caster.example.com",
      issuer: "Let’s Encrypt",
      days_remaining: 65,
      mode: "letsencrypt",
    },
    "/api/system/backups": {
      items: [backup],
      count: 1,
      total_size_bytes: backup.size_bytes,
    },
    "/api/system/backups/storage": {
      local: {
        path: "/opt/gnss-caster/backups",
        writable: true,
        free_bytes: 5838478336,
      },
      external: {
        path: "/media/backup",
        writable: true,
        configured: true,
        mounted: true,
      },
      warnings: [],
    },
    "/api/system/readiness": {
      ready: true,
      stations: [
        {
          id: 1,
          name: station.name,
          ready: true,
          issues: [],
          satellites: 28,
          rovers: 1,
        },
      ],
      issues: [],
    },
    "/api/admins": [
      {
        id: 1,
        username: "admin",
        role: "admin",
        email: "",
        last_login: now - 4000,
        is_builtin: true,
      },
    ],
    "/api/tokens": [
      {
        id: 1,
        name: "Status monitor",
        token_prefix: "gnss_dem",
        scope: "read",
        is_active: true,
        expires: now + 86400,
        last_used: now - 15,
      },
    ],
    "/api/2fa/status": { enabled: false, backup_codes_remaining: 0 },
    "/api/base_stations/1/command_log": [
      {
        id: 1,
        ts: now - 4000,
        phase: "startup",
        command: "mode base",
        response: "OK",
      },
    ],
    "/api/base_stations/1/config_versions": [
      {
        id: 1,
        version: 2,
        source: "edit",
        note: "Known position saved",
        created_by: "admin",
        created_at: now - 4000,
      },
    ],
    "/api/base_stations/1/config_versions/1": {
      version: 2,
      config: { position_mode: "manual", manual_lat: station.manual_lat },
      diff_vs_current: {},
    },
    "/api/base_stations/1/position_history": {
      max_offset_m: 0.014,
      mean_offset_m: 0.006,
      samples: Array.from({ length: 20 }, (_, i) => ({
        ts: now - (20 - i) * 60,
        latitude: station.manual_lat,
        longitude: station.manual_lon,
        altitude: station.manual_alt,
        offset_m: 0.004 + Math.sin(i) * 0.003,
        satellites: 28,
        hdop: 0.7,
      })),
    },
    "/api/site_points": [
      {
        id: 1,
        name: "Survey marker 01",
        latitude: station.manual_lat,
        longitude: station.manual_lon,
        altitude: station.manual_alt,
        antenna_height: 2,
        add_antenna_height: true,
      },
    ],
    "/api/bluetooth/scan": [
      {
        mac: station.bt_mac,
        name: station.name,
        rssi: -52,
        paired: false,
        is_registered: true,
      },
    ],
    "/api/base_stations/serial_ports": {
      ports: [
        {
          device: "/dev/ttyACM0",
          by_id: "/dev/serial/by-id/receiver",
          label: "GNSS receiver",
        },
      ],
    },
  };
  if (path.startsWith("/api/system/jobs/"))
    return {
      status: "completed",
      is_finished: true,
      message: "Maintenance job completed successfully",
    };
  if (path.startsWith("/api/system/privileged_jobs/"))
    return { status: "done", kind: "Settings update" };
  return fixed[path];
}
