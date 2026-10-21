import type { Channel } from '../api/client';
import { getBroadcastStatus, getChannelKey } from './channel';

export type ChannelSortMode = 'live-first-name' | 'name' | 'manual';

export function isChannelLive(channel: Channel): boolean {
    return channel.is_live || !!channel.recording?.is_recording || getBroadcastStatus(channel) === 'live';
}

export function compareChannelNames(a: Channel, b: Channel): number {
    const nameA = (a.channel_name || a.channel_id).trim();
    const nameB = (b.channel_name || b.channel_id).trim();
    const result = nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' });
    if (result !== 0) return result;
    return (a.channel_id || '').localeCompare(b.channel_id || '');
}

export function sortChannels(channels: Channel[], mode: ChannelSortMode, manualOrderIndex: Map<string, number>): Channel[] {
    if (mode === 'name') {
        return [...channels].sort(compareChannelNames);
    }
    if (mode === 'live-first-name') {
        return [...channels].sort((a, b) => {
            const liveA = isChannelLive(a);
            const liveB = isChannelLive(b);
            if (liveA !== liveB) {
                return liveA ? -1 : 1;
            }
            return compareChannelNames(a, b);
        });
    }
    // 'manual' 모드: 저장된 사용자 지정 순서
    return [...channels].sort((left, right) => (
        (manualOrderIndex.get(getChannelKey(left)) ?? Number.MAX_SAFE_INTEGER)
        - (manualOrderIndex.get(getChannelKey(right)) ?? Number.MAX_SAFE_INTEGER)
    ));
}
