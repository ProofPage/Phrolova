import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from "react";
import { api, VodTask } from "../api/client";
import { useToast } from "../components/ui/Toast";
import { getErrorMessage } from "../utils/error";

export interface VodContextType {
    tasks: VodTask[];
    activeCount: number;
    addTask: (url: string, quality?: string) => Promise<string>;
    cancelTask: (taskId: string) => Promise<void>;
    pauseTask: (taskId: string) => Promise<void>;
    resumeTask: (taskId: string) => Promise<void>;
    retryTask: (taskId: string) => Promise<string>;
    clearCompleted: () => Promise<void>;
    openFileLocation: (taskId: string) => Promise<void>;
    refreshTasks: () => Promise<void>;
}

const VodContext = createContext<VodContextType | null>(null);

export function VodProvider({ children }: { children: ReactNode }) {
    const toast = useToast();
    const [tasks, setTasks] = useState<VodTask[]>([]);
    const [activeCount, setActiveCount] = useState(0);

    const applyStatus = useCallback((data: { tasks: VodTask[]; active_count: number; queued_count: number; total_count: number }) => {
        setTasks(data.tasks);
        setActiveCount(data.active_count);
    }, []);

    const refreshTasks = useCallback(async () => {
        try {
            const data = await api.getAllVodStatus();
            applyStatus(data);
        } catch (e) {
            console.error("VOD 상태 갱신 실패:", e);
        }
    }, [applyStatus]);

    // 전역 폴링 (컴포넌트 언마운트와 무관하게 지속)
    useEffect(() => {
        refreshTasks();
        const interval = setInterval(refreshTasks, 2000);
        return () => clearInterval(interval);
    }, [refreshTasks]);

    const addTask = async (url: string, quality = "best") => {
        const { task_id } = await api.downloadVod(url, quality);
        await refreshTasks();
        return task_id;
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
        const { new_task_id } = await api.retryVodDownload(taskId);
        await refreshTasks();
        return new_task_id;
    };

    const clearCompleted = async () => {
        await api.clearCompletedVodTasks();
        await refreshTasks();
    };

    const openFileLocation = async (taskId: string) => {
        try {
            await api.openVodFileLocation(taskId);
        } catch (e: unknown) {
            toast.error(getErrorMessage(e, "파일 위치를 열 수 없습니다."));
        }
    };

    return (
        <VodContext.Provider
            value={{
                tasks,
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
