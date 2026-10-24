import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import type { Channel } from "../api/client";
import { getChannelKey } from "../utils/channel";
import { sortChannels, type ChannelSortMode } from "../utils/channelSort";

const STORAGE_KEY = "dashboardChannelOrder";
const SORT_MODE_STORAGE_KEY = "dashboardChannelSortMode";

/** 채널 카드·행에 그대로 펼쳐 넣는 재정렬 props. 훅과 컴포넌트가 이 타입 하나를 공유한다. */
export interface ReorderProps {
    canMoveUp: boolean;
    canMoveDown: boolean;
    manualOrder: boolean;
    onMoveChannel: (direction: number) => void;
    isDragging: boolean;
    isDropTarget: boolean;
    onReorderPointerDown: (event: PointerEvent<HTMLElement>) => void;
    onReorderPointerMove: (event: PointerEvent<HTMLElement>) => void;
    onReorderPointerUp: (event: PointerEvent<HTMLElement>) => void;
    onReorderMouseMove: (event: MouseEvent<HTMLElement>) => void;
    onReorderMouseUp: (event: MouseEvent<HTMLElement>) => void;
    onReorderKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
}

function readStoredOrder(): string[] {
    try {
        const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        return Array.isArray(value) && value.every((item) => typeof item === "string") ? value : [];
    } catch {
        return [];
    }
}

function writeStoredOrder(order: string[]): void {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(order));
}

function readStoredSortMode(): ChannelSortMode {
    try {
        const value = localStorage.getItem(SORT_MODE_STORAGE_KEY);
        if (value === "name" || value === "manual" || value === "live-first-name") {
            return value;
        }
    } catch {
        /* ignore */
    }
    return "live-first-name";
}

function writeStoredSortMode(mode: ChannelSortMode): void {
    try {
        localStorage.setItem(SORT_MODE_STORAGE_KEY, mode);
    } catch {
        /* ignore */
    }
}

/**
 * 대시보드 채널의 표시 순서를 관리한다.
 *
 * 기본 모드는 라이브 우선 · 이름순('live-first-name')이며,
 * 라이브가 켜진 채널이 상단에 이름순으로 먼저 배치되고 오프라인 채널도 이름순으로 정렬된다.
 * 수동 정렬 모드('manual')에서는 사용자가 드래그 또는 버튼으로 직접 지정한 순서가 적용된다.
 */
export function useChannelReorder(channels: Channel[]) {
    const [order, setOrder] = useState<string[]>(readStoredOrder);
    const [sortMode, setSortModeState] = useState<ChannelSortMode>(readStoredSortMode);
    const [draggedKey, setDraggedKey] = useState<string | null>(null);
    const [dropTargetKey, setDropTargetKey] = useState<string | null>(null);
    const dragSourceRef = useRef<string | null>(null);
    const dropTargetRef = useRef<string | null>(null);

    const setSortMode = (mode: ChannelSortMode) => {
        setSortModeState(mode);
        writeStoredSortMode(mode);
    };

    useEffect(() => {
        // 초기 스트림 연결 전의 빈 배열로 저장된 사용자 순서를 지우지 않는다.
        if (channels.length === 0) return;
        const currentKeys = channels.map(getChannelKey);
        setOrder((previous) => {
            const next = [
                ...previous.filter((key) => currentKeys.includes(key)),
                ...currentKeys.filter((key) => !previous.includes(key)),
            ];
            if (next.length === previous.length && next.every((key, index) => key === previous[index])) return previous;
            writeStoredOrder(next);
            return next;
        });
    }, [channels]);

    const moveChannel = (sourceKey: string, targetKey: string) => {
        setOrder((previous) => {
            const sourceIndex = previous.indexOf(sourceKey);
            const targetIndex = previous.indexOf(targetKey);
            if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return previous;
            // 원래 대상 위치에 넣어야 아래쪽 이웃으로 드래그해도 실제 순서가 바뀐다.
            const next = previous.filter((key) => key !== sourceKey);
            next.splice(targetIndex, 0, sourceKey);
            writeStoredOrder(next);
            return next;
        });
    };

    const clearDragState = () => {
        dragSourceRef.current = null;
        dropTargetRef.current = null;
        setDraggedKey(null);
        setDropTargetKey(null);
    };

    // 드래그 중에는 렌더보다 이벤트가 훨씬 자주 온다. 최신 값은 ref로 읽고,
    // 실제로 대상이 바뀔 때만 state를 건드려 불필요한 렌더를 막는다.
    const updateDropTarget = (clientX: number, clientY: number) => {
        if (sortMode !== "manual") return;
        const sourceKey = dragSourceRef.current;
        if (!sourceKey) return;
        const hovered = document.elementFromPoint(clientX, clientY)?.closest<HTMLElement>("[data-channel-key]");
        const targetKey = hovered?.dataset.channelKey;
        const nextTarget = targetKey && targetKey !== sourceKey ? targetKey : null;
        if (dropTargetRef.current === nextTarget) return;
        dropTargetRef.current = nextTarget;
        setDropTargetKey(nextTarget);
    };

    const finishDrag = () => {
        if (sortMode === "manual") {
            const sourceKey = dragSourceRef.current;
            const targetKey = dropTargetRef.current;
            if (sourceKey && targetKey) moveChannel(sourceKey, targetKey);
        }
        clearDragState();
    };

    const handlePointerDown = (event: PointerEvent<HTMLElement>, channelKey: string) => {
        if (sortMode !== "manual") return;
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        dragSourceRef.current = channelKey;
        dropTargetRef.current = null;
        setDraggedKey(channelKey);
        setDropTargetKey(null);
    };

    const handlePointerMove = (event: PointerEvent<HTMLElement>) => {
        if (sortMode !== "manual" || !dragSourceRef.current) return;
        event.preventDefault();
        updateDropTarget(event.clientX, event.clientY);
    };

    const handlePointerUp = (event: PointerEvent<HTMLElement>) => {
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
            event.currentTarget.releasePointerCapture(event.pointerId);
        }
        finishDrag();
    };

    const handleMouseMove = (event: MouseEvent<HTMLElement>) => {
        if (sortMode !== "manual" || !dragSourceRef.current) return;
        event.preventDefault();
        updateDropTarget(event.clientX, event.clientY);
    };

    const moveBy = (channelKey: string, direction: number, visibleKeys?: string[]) => {
        if (sortMode !== "manual") return;
        setOrder((previous) => {
            const currentIndex = previous.indexOf(channelKey);
            // 숨긴 채널의 위치는 유지하고 현재 보이는 이웃끼리만 교환한다.
            const visible = visibleKeys ? previous.filter(key => visibleKeys.includes(key)) : previous;
            const visibleIndex = visible.indexOf(channelKey);
            const targetKey = visible[visibleIndex + direction];
            const targetIndex = targetKey ? previous.indexOf(targetKey) : currentIndex;
            if (currentIndex < 0 || currentIndex === targetIndex) return previous;
            const next = [...previous];
            [next[currentIndex], next[targetIndex]] = [next[targetIndex], next[currentIndex]];
            writeStoredOrder(next);
            return next;
        });
    };

    const handleKeyDown = (event: KeyboardEvent<HTMLElement>, channelKey: string, visibleKeys?: string[]) => {
        if (sortMode !== "manual") return;
        const direction = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1
            : event.key === "ArrowRight" || event.key === "ArrowDown" ? 1
            : 0;
        if (direction === 0) return;
        event.preventDefault();
        moveBy(channelKey, direction, visibleKeys);
    };

    const orderIndex = new Map(order.map((key, index) => [key, index]));
    const orderedChannels = sortChannels(channels, sortMode, orderIndex);

    const isManual = sortMode === "manual";
    const getReorderProps = (channelKey: string, visibleKeys = orderedChannels.map(getChannelKey)): ReorderProps => ({
        canMoveUp: isManual && visibleKeys.indexOf(channelKey) > 0,
        canMoveDown: isManual && visibleKeys.indexOf(channelKey) >= 0 && visibleKeys.indexOf(channelKey) < visibleKeys.length - 1,
        manualOrder: isManual,
        onMoveChannel: (direction) => moveBy(channelKey, direction, visibleKeys),
        isDragging: draggedKey === channelKey,
        isDropTarget: dropTargetKey === channelKey,
        onReorderPointerDown: (event) => handlePointerDown(event, channelKey),
        onReorderPointerMove: handlePointerMove,
        onReorderPointerUp: handlePointerUp,
        onReorderMouseMove: handleMouseMove,
        onReorderMouseUp: finishDrag,
        onReorderKeyDown: (event) => handleKeyDown(event, channelKey, visibleKeys),
    });

    return { orderedChannels, sortMode, setSortMode, getReorderProps };
}
