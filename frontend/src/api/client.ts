import axios from "axios";

const API_BASE_URL = "/api";

export const client = axios.create({
    baseURL: API_BASE_URL,
    headers: {
        "Content-Type": "application/json",
    },
});

// ── Types ───────────────────────────────────────────────

export type Platform = "chzzk" | "x_spaces" | "youtube";
export type DownloadCondition = "all" | "watchalong" | "exclude_watchalong";
export interface ChannelDownloadOptions {
    auto_record: boolean;
    download_condition: DownloadCondition | null;
    watchalong_tags: string | null;
}

export const PLATFORM_LABELS: Record<Platform, string> = {
    chzzk: "Chzzk",
    x_spaces: "X Spaces",
    youtube: "YouTube",
};

export interface Channel {
    composite_key?: string;
    platform?: Platform;
    channel_id: string;
    auto_record: boolean;
    download_condition?: DownloadCondition | null;
    watchalong_tags?: string | null;
    broadcast_tags?: string[] | null;
    is_watchalong?: boolean | null;
    watchalong_tag?: string | null;
    auto_record_eligible?: boolean;
    download_hold_reason?: string | null;
    is_live: boolean;
    channel_name?: string;
    title?: string;
    category?: string;
    viewer_count?: number;
    thumbnail_url?: string;
    profile_image_url?: string;
    recording?: {
        is_recording: boolean;
        state: string;
        duration_seconds: number;
        output_path: string | null;
        start_time: string | null;
        // 녹화 통계
        file_size_bytes: number;
        download_speed: number;  // MB/s
        bitrate: number;  // kbps
    };
    chat_archiving?: {
        is_running: boolean;
        message_count: number;
        output_path: string;
    };
    tags?: string[];
    last_error?: string;
}

export interface VodTask {
    task_id: string;
    url: string;
    title: string;
    state: "idle" | "downloading" | "paused" | "completed" | "error" | "cancelling";
    progress: number;
    quality: string;
    output_path: string | null;
    error_message?: string;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    // 다운로드 통계
    download_speed: number;  // MB/s
    downloaded_bytes: number;
    total_bytes: number;
    eta_seconds: number;
}

export interface VodImport {
    id: string;
    url: string;
    state: "queued" | "collecting" | "completed" | "error" | "cancelled";
    added_count: number;
    skipped_count: number;
    error: string | null;
}

export interface VodAddResult {
    task_id: string | null;
    task_ids: string[];
    added_count: number;
    import_id?: string;
    message: string;
}

export interface VodStatusResponse {
    imports?: VodImport[];
    tasks: VodTask[];
    active_count: number;
    queued_count: number;
    total_count: number;
}

export interface Settings {
    app_name: string;
    download_dir: string;
    live_download_dir: string;
    vod_download_dir: string;
    ffmpeg_path: string;
    streamlink_version: string | null;
    monitor_interval: number;
    host: string;
    port: number;
    ffmpeg_version: string | null;
    authenticated: boolean;
    discord_bot_configured: boolean;

    keep_download_parts: boolean;
    max_record_retries: number;
    chzzk_time_machine_enabled: boolean;
    chzzk_stream_mode: "standard" | "request-timemachine" | "force-timemachine";
    chzzk_time_machine_shift: number;
    chzzk_time_machine_offset: number;
    save_live_preview: boolean;
    live_filename_template: string;
    vod_filename_template: string;
    live_download_condition: DownloadCondition;
    watchalong_tags: string;

    live_format: string;
    vod_format: string;
    recording_quality: string;

    // VOD 설정
    vod_max_concurrent: number;
    vod_default_quality: string;
    vod_max_speed: number;

    // 채팅 설정
    chat_archive_enabled: boolean;

    // Discord 설정
    discord_notification_channel_id?: string;
    discord_command_user_ids?: string;
    discord_command_channel_id?: string;

    // 알림 설정
    discord_webhook_configured: boolean;
    discord_notify_events: string[];
    discord_mention_events: string[];
    discord_mention_target: string;
    discord_notify_ttl: number;
    notification_kinds: NotificationKindInfo[];

    // 분할 저장 경로
    split_download_dirs: boolean;
    vod_chzzk_dir: string;
    vod_external_dir: string;

    // X Spaces 인증
    x_cookie_file?: string;
}

export interface PlatformStatus {
    chzzk: { enabled: boolean; authenticated: boolean };
    x_spaces: { enabled: boolean; authenticated: boolean; cookie_file_set: boolean };
    youtube: { enabled: boolean; authenticated: boolean };
}


export interface GeneralSettingsUpdate {
    download_dir?: string;
    live_download_dir?: string;
    vod_download_dir?: string;
    monitor_interval?: number;
    live_format?: string;
    recording_quality?: string;
    split_download_dirs?: boolean;
    vod_chzzk_dir?: string;
    vod_external_dir?: string;
}

// ── Dir Browser Types ────────────────────────────────
export interface DirEntry {
    name: string;
    path: string;
}

export interface BrowseDirsResponse {
    current: string;
    parent: string | null;
    dirs: DirEntry[];
}

export interface VodSettingsUpdate {
    vod_filename_template?: string;
    vod_max_concurrent?: number;
    vod_default_quality?: string;
    vod_max_speed?: number;
    vod_format?: string;
    keep_download_parts?: boolean;
}

export interface ChatSettingsUpdate {
    chat_archive_enabled: boolean;
}

export interface DiscordSettingsUpdate {
    discord_bot_token?: string;
    discord_notification_channel_id?: string;
    discord_command_user_ids?: string;
    discord_command_channel_id?: string;
    discord_webhook_url?: string;
    discord_notify_events?: string[];
    discord_mention_events?: string[];
    discord_mention_target?: string;
    discord_notify_ttl?: number;
}

/** 설정 화면에 표시할 알림 종류 (백엔드가 목록을 내려준다). */
export interface NotificationKindInfo {
    value: string;
    label: string;
}

/** 알림 전송 채널의 설정/가용 상태. */
export interface NotificationTransportStatus {
    name: string;
    configured: boolean;
    available: boolean;
}

/** 알림 파이프라인 진단 결과. */
export interface NotificationStatus {
    available: boolean;
    reason?: string;
    queued?: number;
    delivered?: number;
    dropped?: number;
    expired?: number;
    pending?: number;
    transports?: NotificationTransportStatus[];
}

// ── Chat Log Types ───────────────────────────────────────

export interface ChatLogFile {
    file_id: string;
    filename: string;
    channel: string;
    size_bytes: number;
    message_count: number;
    created_at: string;
    modified_at: string;
}

export interface ChatMessageItem {
    timestamp: string;
    user_id: string | null;
    nickname: string;
    message: string;
}

export interface MessagesResponse {
    messages: ChatMessageItem[];
    total: number;
    page: number;
    limit: number;
    has_next: boolean;
}

// ── Stats Types ─────────────────────────────────────────

export interface ChannelLiveStat {
    channel_id: string;
    channel_name: string;
    session_count: number;
    total_duration_seconds: number;
    total_size_bytes: number;
    live_detected_count: number;
}

export interface LiveSession {
    channel_id: string;
    channel_name: string;
    started_at: string | null;
    ended_at: string | null;
    duration_seconds: number;
    file_size_bytes: number;
    output_path: string | null;
}

export interface StatsResponse {
    live: {
        total_duration_seconds: number;
        total_size_bytes: number;
        total_sessions: number;
        active_recordings: number;
        by_channel: ChannelLiveStat[];
    };
    vod: {
        total_completed: number;
        total_size_bytes: number;
        by_type: { chzzk: number; external: number };
    };
    storage: {
        download_dir: string;
        used_bytes: number;
        total_bytes: number;
        free_bytes: number;
    };
    recent_sessions: LiveSession[];
}

// ── System / Update Types ───────────────────────────────

export interface UpdateInfo {
    current_version: string;
    latest_version: string;
    has_update: boolean;
    release_notes: string;
    published_at: string;
    download_url: string;
    checked_at: string | null;
    environment: "windows-exe" | "linux-native" | "termux-native" | "termux-proot" | "windows-native" | "macos-native";
}

// ── System Logs Types ───────────────────────────────────

export interface SystemLogFile {
    filename: string;
    size_bytes: number;
    modified_at: string;
}

export interface SystemLogResponse {
    filename: string;
    content: string;
    total_lines: number;
    lines_returned: number;
}

// ── API Functions ───────────────────────────────────────

export const api = {
    getLivePreview: async (key: string, signal: AbortSignal): Promise<{ url: string }> =>
        (await client.get(`/stream/preview/${encodeURIComponent(key)}`, { signal })).data,
    // Channels
    addChannel: async (channel_id: string, auto_record: boolean = true, options?: ChannelDownloadOptions) => {
        const res = await client.post("/stream/channels", {
            channel_id,
            auto_record,
            ...options,
        });
        return res.data;
    },
    removeChannel: async (channel_id: string) => {
        const res = await client.delete(`/stream/channels/${encodeURIComponent(channel_id)}`);
        return res.data;
    },
    toggleAutoRecord: async (channel_id: string) => {
        const res = await client.patch(`/stream/channels/${encodeURIComponent(channel_id)}/auto-record`);
        return res.data;
    },

    // Recording
    startRecording: async (channel_id: string) => {
        const res = await client.post(`/stream/record/${encodeURIComponent(channel_id)}/start`);
        return res.data;
    },
    stopRecording: async (channel_id: string) => {
        const res = await client.post(`/stream/record/${encodeURIComponent(channel_id)}/stop`);
        return res.data;
    },
    stopAllRecordings: async () => {
        const res = await client.post<{ stopped_count: number; message: string }>("/stream/record/stop-all");
        return res.data;
    },

    // Monitor

    // VOD
    downloadVod: async (url: string, quality: string = "best", output_dir?: string) => {
        const res = await client.post<VodAddResult>("/vod/download", {
            url,
            quality,
            output_dir,
        });
        return res.data;
    },
    getAllVodStatus: async () => {
        const res = await client.get<VodStatusResponse>("/vod/status", { timeout: 10000 });
        return res.data;
    },
    cancelVodImport: async (id: string) => {
        await client.post(`/vod/imports/${id}/cancel`);
    },
    cancelVodDownload: async (task_id: string) => {
        const res = await client.post(`/vod/${task_id}/cancel`);
        return res.data;
    },
    pauseVodDownload: async (task_id: string) => {
        const res = await client.post(`/vod/${task_id}/pause`);
        return res.data;
    },
    resumeVodDownload: async (task_id: string) => {
        const res = await client.post(`/vod/${task_id}/resume`);
        return res.data;
    },
    retryVodDownload: async (task_id: string) => {
        const res = await client.post<{ message: string; old_task_id: string; new_task_id: string }>(`/vod/${task_id}/retry`);
        return res.data;
    },
    reorderVodTasks: async (task_ids: string[]) => {
        const res = await client.post("/vod/reorder", { task_ids });
        return res.data;
    },
    clearCompletedVodTasks: async () => {
        const res = await client.post<{ message: string; deleted_count: number; remaining_count: number }>("/vod/clear-completed");
        return res.data;
    },
    openVodFileLocation: async (task_id: string) => {
        const res = await client.post<{ message: string; path: string }>(`/vod/${task_id}/open-location`);
        return res.data;
    },

    // Settings
    updateLiveCondition: async (live_download_condition: DownloadCondition, watchalong_tags: string) => {
        const res = await client.put("/settings/live-condition", { live_download_condition, watchalong_tags });
        return res.data;
    },
    updateChannelDownloadOptions: async (channel: Channel, options: ChannelDownloadOptions) => {
        const path = (channel.platform || "chzzk") === "chzzk"
            ? `/stream/channels/${encodeURIComponent(channel.channel_id)}/download-options`
            : `/platforms/channels/${channel.platform}/${encodeURIComponent(channel.channel_id)}/download-options`;
        const res = await client.put(path, options);
        return res.data;
    },
    getSettings: async () => {
        const res = await client.get<Settings>("/settings");
        return res.data;
    },
    updateCookies: async (nid_aut: string, nid_ses: string) => {
        const res = await client.put("/settings/cookies", { nid_aut, nid_ses });
        return res.data;
    },
    updateDownloadSettings: async (
        max_record_retries: number,
        chzzk_stream_mode: "standard" | "request-timemachine" | "force-timemachine",
        chzzk_time_machine_offset: number,
        save_live_preview: boolean,
        live_filename_template: string,
        recording_quality: string,
    ) => {
        const res = await client.put("/settings/live", {
            max_record_retries,
            chzzk_stream_mode,
            chzzk_time_machine_offset,
            save_live_preview,
            live_filename_template,
            recording_quality,
        });
        return res.data;
    },
    updateGeneralSettings: async (data: GeneralSettingsUpdate) => {
        const res = await client.put("/settings/general", data);
        return res.data;
    },
    updateVodSettings: async (data: VodSettingsUpdate) => {
        const res = await client.put("/settings/vod", data);
        return res.data;
    },
    updateChatSettings: async (data: ChatSettingsUpdate) => {
        const res = await client.put("/settings/chat", data);
        return res.data;
    },
    updateDiscordSettings: async (data: DiscordSettingsUpdate) => {
        const res = await client.put("/settings/discord", data);
        return res.data;
    },
    getNotificationStatus: async (): Promise<NotificationStatus> => {
        const res = await client.get<NotificationStatus>("/settings/discord/status");
        return res.data;
    },
    sendTestNotification: async (): Promise<{ message: string }> => {
        const res = await client.post<{ message: string }>("/settings/discord/test");
        return res.data;
    },
    testCookies: async () => {
        const res = await client.post("/settings/cookies/test");
        return res.data;
    },
    browseDirs: async (path?: string): Promise<BrowseDirsResponse> => {
        const res = await client.get<BrowseDirsResponse>("/settings/browse-dirs", {
            params: path !== undefined ? { path } : {},
        });
        return res.data;
    },

    // Platform Channels (멀티 플랫폼)
    addPlatformChannel: async (platform: Platform, channel_id: string, auto_record: boolean = true) => {
        const res = await client.post("/platforms/channels", { platform, channel_id, auto_record });
        return res.data;
    },
    removePlatformChannel: async (platform: Platform, channel_id: string) => {
        const res = await client.delete(`/platforms/channels/${platform}/${encodeURIComponent(channel_id)}`);
        return res.data;
    },
    togglePlatformAutoRecord: async (platform: Platform, channel_id: string) => {
        const res = await client.patch(`/platforms/channels/${platform}/${encodeURIComponent(channel_id)}/auto-record`);
        return res.data;
    },
    scanNow: async (compositeKey?: string) => {
        const params = compositeKey ? { composite_key: compositeKey } : {};
        const res = await client.post("/platforms/scan-now", null, { params });
        return res.data;
    },
    getPlatformStatus: async (): Promise<PlatformStatus> => {
        const res = await client.get<PlatformStatus>("/platforms/status");
        return res.data;
    },
    uploadXCookie: async (file: File) => {
        const form = new FormData();
        form.append("file", file);
        const res = await client.post("/platforms/x/cookie", form, {
            headers: { "Content-Type": "multipart/form-data" },
        });
        return res.data;
    },
    deleteXCookie: async () => {
        const res = await client.delete("/platforms/x/cookie");
        return res.data;
    },

    // Stats
    getStats: async (): Promise<StatsResponse> => {
        const res = await client.get<StatsResponse>("/stats/");
        return res.data;
    },

    // Tags
    getTags: async () => {
        const res = await client.get<{ tags: string[] }>("/tags");
        return res.data;
    },
    createTag: async (name: string) => {
        const res = await client.post<{ tags: string[] }>("/tags", { name });
        return res.data;
    },
    /** 태그를 전역에서 지운다. 백엔드가 모든 채널에서도 함께 떼어낸다. */
    deleteTag: async (name: string) => {
        const res = await client.delete<{ status: string; deleted: string }>(`/tags/${encodeURIComponent(name)}`);
        return res.data;
    },
    updateChannelTags: async (channel_id: string, tags: string[]) => {
        const res = await client.patch<{ status: string; tags: string[] }>(`/tags/channel/${encodeURIComponent(channel_id)}`, { tags });
        return res.data;
    },

    // System & Update
    getUpdateStatus: async (): Promise<UpdateInfo> => {
        const res = await client.get<UpdateInfo>("/system/update");
        return res.data;
    },
    checkUpdateNow: async (): Promise<UpdateInfo> => {
        const res = await client.post<UpdateInfo>("/system/update/check");
        return res.data;
    },

    // Chat Logs
    getChatFiles: async () => {
        const res = await client.get<ChatLogFile[]>("/chat/files");
        return res.data;
    },
    getChatMessages: async (
        file_id: string,
        params: { page?: number; limit?: number; search?: string; nickname?: string }
    ) => {
        const res = await client.get<MessagesResponse>(`/chat/files/${file_id}/messages`, {
            params,
        });
        return res.data;
    },
    getChatDownloadUrl: (file_id: string): string =>
        `${API_BASE_URL}/chat/files/${file_id}/download`,

    // System Logs
    getSystemLogFiles: async (): Promise<SystemLogFile[]> => {
        const res = await client.get<SystemLogFile[]>("/system/logs");
        return res.data;
    },
    getSystemLogContent: async (filename: string, lines?: number): Promise<SystemLogResponse> => {
        const res = await client.get<SystemLogResponse>(`/system/logs/${filename}`, {
            params: { ...(lines !== undefined ? { lines } : {}), _refresh: Date.now() },
            headers: { "Cache-Control": "no-cache" },
        });
        return res.data;
    },
    clearSystemLogs: async (): Promise<{ message: string; cleared_files: number }> => {
        const res = await client.delete<{ message: string; cleared_files: number }>("/system/logs");
        return res.data;
    },
};
