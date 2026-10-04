import { useCallback, useEffect, useState } from "react";
import { client, type Channel } from "../api/client";

interface ChannelStreamState {
    channels: Channel[];
    initialLoading: boolean;
    connectionError: boolean;
    fetchChannels: () => Promise<void>;
}

/** SSE가 끊겨도 직접 조회한 마지막 채널 목록을 유지한다. */
export function useChannelStream(): ChannelStreamState {
    const [channels, setChannels] = useState<Channel[]>([]);
    const [initialLoading, setInitialLoading] = useState(true);
    const [connectionError, setConnectionError] = useState(false);

    const fetchChannels = useCallback(async () => {
        try {
            const response = await client.get<Channel[]>("/platforms/channels");
            setChannels(response.data);
            setConnectionError(false);
        } catch {
            setConnectionError(true);
        }
    }, []);

    useEffect(() => {
        let eventSource: EventSource | null = null;
        let reconnectTimeout: ReturnType<typeof setTimeout> | undefined;
        let disposed = false;

        const connect = () => {
            if (disposed) return;
            const baseUrl = client.defaults.baseURL || "/api";
            eventSource = new EventSource(`${baseUrl}/events`);

            eventSource.onmessage = (event) => {
                if (!event.data || event.data === "ping") return;
                try {
                    const message = JSON.parse(event.data) as { type?: string; data?: Channel[] };
                    if (message.type === "status_update" && message.data) {
                        setChannels(message.data);
                        setConnectionError(false);
                        setInitialLoading(false);
                    }
                } catch (error) {
                    console.error("SSE 메시지 파싱 실패:", error);
                }
            };

            eventSource.onerror = () => {
                setConnectionError(true);
                eventSource?.close();
                // 재연결 전에도 목록을 갱신해 SSE 장애가 화면 공백으로 이어지지 않게 한다.
                fetchChannels().finally(() => {
                    if (!disposed) setConnectionError(true);
                });
                reconnectTimeout = setTimeout(connect, 5000);
            };
        };

        connect();
        // 최초 이벤트가 늦거나 실패해도 목록을 바로 보여주기 위해 직접 한 번 조회한다.
        fetchChannels().finally(() => setInitialLoading(false));

        return () => {
            disposed = true;
            eventSource?.close();
            if (reconnectTimeout) clearTimeout(reconnectTimeout);
        };
    }, [fetchChannels]);

    return { channels, initialLoading, connectionError, fetchChannels };
}
