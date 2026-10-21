import assert from 'node:assert/strict';

// Simple unit tests for sorting logic
function isChannelLive(channel) {
    return channel.is_live || !!channel.recording?.is_recording || channel.broadcast_status === 'live';
}

function compareChannelNames(a, b) {
    const nameA = (a.channel_name || a.channel_id).trim();
    const nameB = (b.channel_name || b.channel_id).trim();
    const result = nameA.localeCompare(nameB, undefined, { numeric: true, sensitivity: 'base' });
    if (result !== 0) return result;
    return (a.channel_id || '').localeCompare(b.channel_id || '');
}

function sortChannels(channels, mode, manualOrderIndex) {
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
    return [...channels].sort((left, right) => (
        (manualOrderIndex.get(left.channel_id) ?? Number.MAX_SAFE_INTEGER)
        - (manualOrderIndex.get(right.channel_id) ?? Number.MAX_SAFE_INTEGER)
    ));
}

// Case 1: Live channel automatically moves to top, and live channels are sorted by name
const sampleChannels = [
    { channel_id: 'ch1', channel_name: '히츠', is_live: false },
    { channel_id: 'ch2', channel_name: '도이', is_live: false },
    { channel_id: 'ch3', channel_name: '진이', is_live: false },
    { channel_id: 'ch4', channel_name: '셀데아', is_live: false },
    { channel_id: 'ch5', channel_name: '츠키', is_live: false },
    { channel_id: 'ch6', channel_name: '아린', is_live: false },
    { channel_id: 'ch7', channel_name: '도화령', is_live: false },
    { channel_id: 'ch8', channel_name: '모몬 헤닐', is_live: true, recording: { is_recording: true } },
    { channel_id: 'ch9', channel_name: '에아', is_live: false },
    { channel_id: 'ch10', channel_name: '가람', is_live: true },
];

const sorted = sortChannels(sampleChannels, 'live-first-name', new Map());

// Both ch8 (모몬 헤닐) and ch10 (가람) are live. '가람' comes before '모몬 헤닐' alphabetically.
assert.equal(sorted[0].channel_name, '가람');
assert.equal(sorted[1].channel_name, '모몬 헤닐');

// The remaining offline channels should be sorted by name:
// 도이, 도화령, 셀데아, 아린, 에아, 츠키, 진이, 히츠
assert.equal(sorted[2].channel_name, '도이');
assert.equal(sorted[3].channel_name, '도화령');
assert.equal(sorted[sorted.length - 1].channel_name, '히츠');

console.log('PASS: Channel sorting with live-first-name logic works as expected');
