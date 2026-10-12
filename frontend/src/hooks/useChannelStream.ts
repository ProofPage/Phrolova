import { useCallback, useEffect, useRef, useState } from "react";
import { client, PLATFORM_LABELS, type Channel } from "../api/client";

const supportedChannels = (channels: Channel[]) => channels.filter(channel =>
    !channel.platform || Object.hasOwn(PLATFORM_LABELS, channel.platform));

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

    const alive = useRef(true);
    const revision = useRef(0);
    const inFlight = useRef<Promise<void> | null>(null);
    const requestController = useRef<AbortController | null>(null);
    const fetchChannels = useCallback((): Promise<void> => {
        if (inFlight.current) return inFlight.current;
        const controller = new AbortController();
        requestController.current = controller;
        const startedAt = revision.current;
        const request = (async () => {
            try {
                const response = await client.get<Channel[]>("/platforms/channels", {signal: controller.signal});
                if (!alive.current || controller.signal.aborted || revision.current !== startedAt) return;
                if (!Array.isArray(response.data)) throw new Error("Invalid channel response");
                setChannels(supportedChannels(response.data));
                setConnectionError(false);
            } catch {
                if (alive.current && !controller.signal.aborted && revision.current === startedAt) setConnectionError(true);
            } finally {
                if (requestController.current === controller) {
                    requestController.current = null;
                    inFlight.current = null;
                }
            }
        })();
        inFlight.current = request;
        return request;
    }, []);

    useEffect(() => {
        let eventSource: EventSource | null = null;
        let reconnectTimeout: ReturnType<typeof setTimeout> | undefined;
        let disposed = false;
        alive.current = true;

        const connect = () => {
            if (disposed) return;
            const baseUrl = client.defaults.baseURL || "/api";
            const source = new EventSource(`${baseUrl}/events`);
            eventSource = source;

            source.onmessage = (event) => {
                if (disposed || source !== eventSource) return;
                if (!event.data || event.data === "ping") return;
                try {
                    const message = JSON.parse(event.data) as { type?: string; data?: Channel[] };
                    if (message.type === "status_update" && Array.isArray(message.data)) {
                        revision.current++;
                        setChannels(supportedChannels(message.data));
                        setConnectionError(false);
                        setInitialLoading(false);
                    }
                } catch (error) {
                    console.error("SSE 메시지 파싱 실패:", error);
                }
            };

            source.onerror = () => {
                if (disposed || source !== eventSource) return;
                setConnectionError(true);
                source.close();
                eventSource = null;
                clearTimeout(reconnectTimeout);
                // 재연결 전에도 목록을 갱신해 SSE 장애가 화면 공백으로 이어지지 않게 한다.
                fetchChannels().finally(() => {
                    if (!disposed) setConnectionError(true);
                });
                reconnectTimeout = setTimeout(connect, 5000);
            };
        };

        connect();
        // 최초 이벤트가 늦거나 실패해도 목록을 바로 보여주기 위해 직접 한 번 조회한다.
        fetchChannels().finally(() => { if (!disposed) setInitialLoading(false); });

        return () => {
            disposed = true;
            alive.current = false;
            requestController.current?.abort();
            requestController.current = null;
            inFlight.current = null;
            eventSource?.close();
            if (reconnectTimeout) clearTimeout(reconnectTimeout);
        };
    }, [fetchChannels]);

    return { channels, initialLoading, connectionError, fetchChannels };
}
