import { createContext, useContext, useState, useEffect, ReactNode, useCallback, useRef } from "react";
import { api, VodTask, VodImport, VodAddResult, VodStatusResponse } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { getErrorMessage } from "../utils/error";

export interface VodContextType {
    loading: boolean;
    loadError: boolean;
    tasks: VodTask[];
    imports: VodImport[];
    activeCount: number;
    addTask: (url: string, quality?: string) => Promise<VodAddResult>;
    cancelTask: (taskId: string) => Promise<void>;
    pauseTask: (taskId: string) => Promise<void>;
    resumeTask: (taskId: string) => Promise<void>;
    retryTask: (taskId: string) => Promise<string>;
    clearCompleted: (completedOnly?: boolean) => Promise<{ deleted_count: number; remaining_count: number }>;
    openFileLocation: (taskId: string) => Promise<void>;
    refreshTasks: () => Promise<void>;
}

const VodContext = createContext<VodContextType | null>(null);

export function VodProvider({ children }: { children: ReactNode }) {
    const toast = useToast();
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);
    const [tasks, setTasks] = useState<VodTask[]>([]);
    const [imports, setImports] = useState<VodImport[]>([]);
    const [activeCount, setActiveCount] = useState(0);

    const applyStatus = useCallback((data: VodStatusResponse) => {
        setLoadError(false);
        setTasks(previous => {
            const byId = new Map(previous.map(task => [task.task_id, task]));
            const next = data.tasks.map(task => {
                const prior = byId.get(task.task_id);
                return prior && JSON.stringify(prior) === JSON.stringify(task) ? prior : task;
            });
            return previous.length === next.length && previous.every((task, index) => task === next[index]) ? previous : next;
        });
        setImports(previous => JSON.stringify(previous) === JSON.stringify(data.imports ?? []) ? previous : data.imports ?? []);
        setActiveCount(data.active_count);
    }, []);

    const inFlight = useRef<Promise<void> | null>(null);
    const refreshTasks = useCallback((): Promise<void> => {
        // 폴링과 버튼 갱신이 겹쳐도 응답 순서가 뒤집히거나 요청이 누적되지 않게 한다.
        if (inFlight.current) return inFlight.current;
        const request = (async () => {
            try {
                applyStatus(await api.getAllVodStatus());
            } catch (e) {
                setLoadError(true);
                console.error("다시보기 상태 갱신 실패:", e);
            } finally {
                setLoading(false);
                inFlight.current = null;
            }
        })();
        inFlight.current = request;
        return request;
    }, [applyStatus]);

    // 전역 폴링 (컴포넌트 언마운트와 무관하게 지속)
    useEffect(() => {
        refreshTasks();
        const interval = setInterval(refreshTasks, 2000);
        return () => clearInterval(interval);
    }, [refreshTasks]);

    const addTask = async (url: string, quality?: string) => {
        const settings = await api.getSettings();
        const result = await api.downloadVod(url, quality ?? settings.vod_default_quality ?? 'best', undefined, settings.chzzk_vod_cdn ?? "default");
        await refreshTasks();
        return result;
    };

    const cancelTask = async (taskId: string) => {
        await api.cancelVodDownload(taskId);
        await refreshTasks();
    };

    const pauseTask = async (taskId: string) => {
        await api.pauseVodDownload(taskId);
        await refreshTasks();
    };

    const resumeTask = async (taskId: string) => {
        await api.resumeVodDownload(taskId);
        await refreshTasks();
    };

    const retryTask = async (taskId: string) => {
        const settings = await api.getSettings();
        const { new_task_id } = await api.retryVodDownload(taskId, settings.chzzk_vod_cdn ?? "default");
        await refreshTasks();
        return new_task_id;
    };

    const clearCompleted = async (completedOnly = false) => {
        const result = await api.clearCompletedVodTasks(completedOnly);
        await refreshTasks();
        return result;
    };

    const openFileLocation = async (taskId: string) => {
        try {
            const result = await api.openVodFileLocation(taskId);
            toast.success(result.message);
        } catch (e: unknown) {
            toast.error(getErrorMessage(e, "파일 위치를 열 수 없습니다."));
        }
    };

    return (
        <VodContext.Provider
            value={{
                loading,
                loadError,
                tasks,
                imports,
                activeCount,
                addTask,
                cancelTask,
                pauseTask,
                resumeTask,
                retryTask,
                clearCompleted,
                openFileLocation,
                refreshTasks,
            }}
        >
            {children}
        </VodContext.Provider>
    );
}

export function useVod() {
    const context = useContext(VodContext);
    if (!context) {
        throw new Error("useVod는 VodProvider 내부에서만 사용할 수 있습니다.");
    }
    return context;
}
