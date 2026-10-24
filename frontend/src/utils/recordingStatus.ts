import type { Channel } from '../api/client';

export function recordingPresentation(channel: Channel, pendingAction?: 'start' | 'stop' | 'remove') {
    const state = channel.recording?.state;
    const error = channel.last_error && !channel.last_error.startsWith('감시 오류:');
    const recovering = !channel.retry_blocked && (
        channel.retry_code === 'stream_closed' ||
        Boolean(channel.retry_at && ['stream_unavailable', 'connection'].includes(channel.retry_code || ''))
    );
    const [label, tone] = channel.skip_pending ? ['live.skippingRecording', 'neutral']
        : pendingAction === 'stop' || state === 'stopping' ? ['live.stoppingRecording', 'neutral']
        : pendingAction === 'start' ? ['live.preparingRecording', 'neutral']
        : state === 'connecting' ? ['live.connectingToStream', 'info']
        : state === 'reconnecting' ? ['live.reconnecting', 'warn']
        : channel.recording?.is_recording ? ['live.recording', 'ok']
        : recovering && channel.retry_code === 'stream_closed' ? ['live.streamClosedPending', 'neutral']
        : recovering && channel.retry_code === 'stream_unavailable' ? ['live.serverRecoveryWait', 'neutral']
        : recovering ? ['live.waitingToReconnect', 'neutral']
        : state === 'error' || error ? [channel.recording?.has_data === false || !channel.recording?.file_size_bytes ? 'live.recordingCouldNotStart' : 'live.recordingError', 'danger']
        : channel.download_hold_reason ? ['live.skippedRecording', 'neutral']
        : state === 'completed' ? ['live.recordingCompleted', 'ok']
        : ['live.waitingToRecord', 'neutral'];
    return { label, tone, recovering };
}

export function connectionEventLabel(event: { event: string; code?: string }) {
    if (event.event === 'receiving') return 'live.recordingStartedAt';
    if (event.code === 'stream_closed') return 'live.streamClosedPending';
    if (event.code === 'stream_unavailable') return 'live.serverRecoveryWait';
    return 'live.recordingError';
}
