import { useEffect, useRef, useState, type KeyboardEvent, type MouseEvent, type PointerEvent } from "react";
import type { Channel } from "../api/client";
import { getChannelKey } from "../utils/channel";

const STORAGE_KEY = "dashboardChannelOrder";

/** 채널 카드·행에 그대로 펼쳐 넣는 재정렬 props. 훅과 컴포넌트가 이 타입 하나를 공유한다. */
export interface ReorderProps {
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

/**
 * 대시보드 채널의 표시 순서를 관리한다.
 *
 * 순서는 서버가 아니라 이 브라우저에만 남는다. 감시 목록은 여러 기기에서 공유되지만
 * "내가 먼저 보고 싶은 채널"은 보는 사람마다 다르기 때문이다.
 *
 * 포인터 이벤트와 마우스 이벤트를 둘 다 받는다. 포인터 캡처가 걸리지 않는 환경에서도
 * 드래그가 끝까지 따라오게 하려는 것이고, 그립에 방향키를 눌러도 옮길 수 있어
 * 마우스를 못 쓰는 경우에도 순서를 바꿀 수 있다.
 */
export function useChannelReorder(channels: Channel[]) {
    const [order, setOrder] = useState<string[]>(readStoredOrder);
    const [draggedKey, setDraggedKey] = useState<string | null>(null);
    const [dropTargetKey, setDropTargetKey] = useState<string | null>(null);
    const dragSourceRef = useRef<string | null>(null);
    const dropTargetRef = useRef<string | null>(null);

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
            const next = previous.filter((key) => key !== sourceKey);
            const targetIndex = next.indexOf(targetKey);
            next.splice(targetIndex < 0 ? next.length : targetIndex, 0, sourceKey);
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
        const sourceKey = dragSourceRef.current;
        const targetKey = dropTargetRef.current;
        if (sourceKey && targetKey) moveChannel(sourceKey, targetKey);
        clearDragState();
    };

    const handlePointerDown = (event: PointerEvent<HTMLElement>, channelKey: string) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.currentTarget.setPointerCapture(event.pointerId);
        dragSourceRef.current = channelKey;
        dropTargetRef.current = null;
        setDraggedKey(channelKey);
        setDropTargetKey(null);
    };

    const handlePointerMove = (event: PointerEvent<HTMLElement>) => {
        if (!dragSourceRef.current) return;
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
        if (!dragSourceRef.current) return;
        event.preventDefault();
        updateDropTarget(event.clientX, event.clientY);
    };

    const handleKeyDown = (event: KeyboardEvent<HTMLElement>, channelKey: string) => {
        const direction = event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1
            : event.key === "ArrowRight" || event.key === "ArrowDown" ? 1
            : 0;
        if (direction === 0) return;
        event.preventDefault();
        setOrder((previous) => {
            const currentIndex = previous.indexOf(channelKey);
            const targetIndex = Math.min(previous.length - 1, Math.max(0, currentIndex + direction));
            if (currentIndex < 0 || currentIndex === targetIndex) return previous;
            const next = [...previous];
            [next[currentIndex], next[targetIndex]] = [next[targetIndex], next[currentIndex]];
            writeStoredOrder(next);
            return next;
        });
    };

    // 저장된 순서에 없는 채널(방금 추가된 것)은 뒤로 보낸다.
    const orderIndex = new Map(order.map((key, index) => [key, index]));
    const orderedChannels = [...channels].sort((left, right) => (
        (orderIndex.get(getChannelKey(left)) ?? Number.MAX_SAFE_INTEGER)
        - (orderIndex.get(getChannelKey(right)) ?? Number.MAX_SAFE_INTEGER)
    ));

    const getReorderProps = (channelKey: string): ReorderProps => ({
        isDragging: draggedKey === channelKey,
        isDropTarget: dropTargetKey === channelKey,
        onReorderPointerDown: (event) => handlePointerDown(event, channelKey),
        onReorderPointerMove: handlePointerMove,
        onReorderPointerUp: handlePointerUp,
        onReorderMouseMove: handleMouseMove,
        onReorderMouseUp: finishDrag,
        onReorderKeyDown: (event) => handleKeyDown(event, channelKey),
    });

    return { orderedChannels, getReorderProps };
}
