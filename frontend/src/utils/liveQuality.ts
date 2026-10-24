import type { LiveQuality } from "../api/client";

type Resolution = { width?: number | null; height?: number | null; fps?: number | null };
const positive = (value: unknown): value is number =>
    typeof value === "number" && Number.isFinite(value) && value > 0;

/** Display only dimensions and frame rates actually supplied by the stream. */
export function formatLiveResolution(resolution?: Resolution | null): string {
    if (!resolution) return "";
    const parts: string[] = [];
    if (positive(resolution.width) && positive(resolution.height)) {
        parts.push(`${resolution.width}×${resolution.height}`);
    } else if (positive(resolution.height)) {
        parts.push(`${resolution.height}p`);
    }
    if (positive(resolution.fps)) parts.push(`${resolution.fps}fps`);
    return parts.join(" · ");
}

export function liveQualityLabel(quality: LiveQuality): string {
    const detail = formatLiveResolution(quality);
    return detail ? [...new Set([...quality.label.split(" · "), ...detail.split(" · ")])].join(" · ") : quality.label;
}
