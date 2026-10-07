import type { Channel } from "../api/client";

/**
 * 채널을 가리키는 단일 키.
 *
 * 플랫폼이 다르면 channel_id가 겹칠 수 있어 백엔드가 composite_key를 내려준다.
 * 치지직 단일 플랫폼 시절에 추가된 채널에는 아직 없어서 channel_id로 물러선다.
 */
export function getChannelKey(channel: Channel): string {
    return channel.composite_key || channel.channel_id;
}

/** Expanded cards end each compact run; its unpaired last card fills the row. */
export function getUnpairedCompactKeys(keys: string[], expandedKeys: ReadonlySet<string>): Set<string> {
    const unpaired = new Set<string>();
    let compactCount = 0;
    let lastCompactKey: string | undefined;
    for (const key of keys) {
        if (expandedKeys.has(key)) {
            if (compactCount % 2 && lastCompactKey !== undefined) unpaired.add(lastCompactKey);
            compactCount = 0;
            lastCompactKey = undefined;
        } else {
            compactCount++;
            lastCompactKey = key;
        }
    }
    if (compactCount % 2 && lastCompactKey !== undefined) unpaired.add(lastCompactKey);
    return unpaired;
}
