declare namespace mpegts {
    interface Player {
        attachMediaElement(mediaElement: HTMLMediaElement): void;
        load(): void;
        play(): Promise<void>;
        pause(): void;
        unload(): void;
        detachMediaElement(): void;
        destroy(): void;
        on(event: string, listener: (...args: any[]) => void): void;
        off(event: string, listener: (...args: any[]) => void): void;
    }

    interface MediaDataSource {
        type: string;
        isLive?: boolean;
        url?: string;
        hasAudio?: boolean;
        hasVideo?: boolean;
    }

    interface Config {
        isLive?: boolean;
        enableWorker?: boolean;
        enableStashBuffer?: boolean;
        stashInitialSize?: number;
        liveBufferLatencyChasing?: boolean;
        liveBufferLatencyMaxLatency?: number;
        liveBufferLatencyMinRemain?: number;
        lazyLoad?: boolean;
        lazyLoadMaxDuration?: number;
        autoCleanupSourceBuffer?: boolean;
        autoCleanupMaxBackwardDuration?: number;
        autoCleanupMinBackwardDuration?: number;
    }

    const Events: {
        ERROR: string;
        LOADING_COMPLETE: string;
        RECOVERED_EARLY_EOF: string;
        MEDIA_INFO: string;
        METADATA_ARRIVED: string;
        SCRIPTDATA_ARRIVED: string;
        TIMED_ID3_METADATA_ARRIVED: string;
        SMPTE_2038_METADATA_ARRIVED: string;
        STATISTICS_INFO: string;
    };

    const ErrorTypes: {
        NETWORK_ERROR: string;
        MEDIA_ERROR: string;
        OTHER_ERROR: string;
    };

    const ErrorDetails: {
        NETWORK_EXCEPTION: string;
        NETWORK_STATUS_CODE_INVALID: string;
        NETWORK_TIMEOUT: string;
        NETWORK_UNRECOVERABLE_EARLY_EOF: string;
        MEDIA_MSE_ERROR: string;
        MEDIA_FORMAT_ERROR: string;
        MEDIA_FORMAT_UNSUPPORTED: string;
        MEDIA_CODEC_UNSUPPORTED: string;
    };

    function isSupported(): boolean;
    function createPlayer(mediaDataSource: MediaDataSource, config?: Config): Player;
}

declare const mpegtsInstance: typeof mpegts;
export default mpegtsInstance;
